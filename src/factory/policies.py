"""Gate policies: decide whether a human gate can be cleared automatically.

The default posture is to require a human at every gate. The retro station
proposes new rules (written elsewhere for you to review); a rule only takes
effect once you set ``approved_by`` on it in ``policies.yml``. Each approved rule
permanently removes a class of work from your plate — this is the lever that
raises the "shipped without human intervention" metric over time.

Autonomy here is an asymmetric ratchet: **promotion is human** (``approved_by``
in policies.yml — config the operator owns), **demotion is automatic**. When an
item a rule auto-cleared later needs human rework (a steer, a block), the
dispatcher suspends that rule in the engine-owned overlay (``PolicyState``,
``.factory/policy-state.json``) — the gate returns to the human until someone
reviews and reinstates. The yaml stays the human's intent; the overlay is the
observed-outcome record the engine may write.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

from .classifiers import Classifiers
from .model import RISK_ORDER as _RISK_ORDER
from .model import WorkItem

_WHEN_KEYS = {"labels_any", "labels_all", "max_risk"}  # the ONLY valid condition keys


class PolicyError(Exception):
    """Raised on a malformed gate policy — caught at load time (e.g. ``factory init``)."""


class Policies:
    def __init__(
        self,
        data: dict[str, Any],
        path: Path | None = None,
        classifiers: Classifiers | None = None,
    ):
        self.path = path
        self.default = data.get("default", "require_human")
        self.rules: list[dict] = data.get("rules") or []
        # Label conditions match the *recognized* vocabulary only, so an
        # unrecognized label can't clear a gate (see classifiers.py).
        self.classifiers = classifiers or Classifiers.default()
        self._validate()

    @classmethod
    def load(cls, path: str | Path, classifiers: Classifiers | None = None) -> Policies:
        p = Path(path)
        # The vocabulary lives beside the rules that consume it; a caller with its
        # own loaded copy passes it in so a factory has exactly one.
        classifiers = classifiers or Classifiers.load(p.parent / "classifiers.yml")
        if not p.exists():
            return cls({"default": "require_human", "rules": []}, p, classifiers)
        with open(p) as f:
            return cls(yaml.safe_load(f) or {}, p, classifiers)

    def unrecognized_conditions(self) -> list[tuple[str, str]]:
        """(rule id, label) for every label a rule matches on that the vocabulary
        doesn't know — a rule that can therefore never fire. Silent by nature:
        the rule is well-formed, it just stopped matching. ``factory doctor``
        surfaces it."""
        out = []
        for rule in self.rules:
            when = rule.get("when")
            if not isinstance(when, dict):
                continue
            for key in ("labels_any", "labels_all"):
                for name in when.get(key, []):
                    if not self.classifiers.is_recognized(name):
                        out.append((rule.get("id", "?"), name))
        return out

    def auto_decision(
        self, gate: str, item: WorkItem, suspended: frozenset[str] | set[str] = frozenset()
    ) -> dict | None:
        """Return an *active* (approved, not suspended) rule that clears this
        gate for this item, or ``None`` if a human is still required. The caller
        (the dispatcher) supplies the suspended set from ``PolicyState`` — this
        module stays pure config evaluation."""
        for rule in self.rules:
            if rule.get("gate") != gate:
                continue
            if not rule.get("approved_by"):  # dormant until a human signs it
                continue
            if rule.get("id") in suspended:  # demoted by an observed failure
                continue
            if self._matches(rule.get("when", {}), item):
                return rule
        return None

    def _validate(self) -> None:
        """Reject malformed rules at load, before any of them can fire.

        The failure mode we most care about points the *unsafe* way: a typo in a
        ``when`` key (``lables_any``) is silently ignored by ``_matches``, which
        would widen an approved rule to match *every* item at its gate — the human
        signed a narrow rule and got a match-all. So an unrecognized key is a hard
        error here rather than a silent broadening. Runs on every rule, dormant or
        not, so a bad rule is caught before it's ever signed."""
        for i, rule in enumerate(self.rules):
            rid = rule.get("id") or f"#{i}"
            if not rule.get("id"):
                raise PolicyError(f"policy {rid!r}: missing required 'id'")
            if not rule.get("gate"):
                raise PolicyError(f"policy {rid!r}: missing required 'gate'")
            if not rule.get("decision"):
                raise PolicyError(f"policy {rid!r}: missing required 'decision'")
            when = rule.get("when")
            if when == "all":  # deliberate, explicit match-everything
                continue
            if not isinstance(when, dict) or not when:
                raise PolicyError(
                    f"policy {rid!r}: 'when' must list at least one condition "
                    f"({', '.join(sorted(_WHEN_KEYS))}). To match every item at the "
                    f"gate on purpose, set 'when: all' (or drop the gate in line.yml)."
                )
            unknown = set(when) - _WHEN_KEYS
            if unknown:
                raise PolicyError(
                    f"policy {rid!r}: unknown condition key(s) {sorted(unknown)}; "
                    f"valid keys are {sorted(_WHEN_KEYS)}"
                )
            if "max_risk" in when and when["max_risk"] not in _RISK_ORDER:
                raise PolicyError(
                    f"policy {rid!r}: max_risk {when['max_risk']!r} is not one of "
                    f"{sorted(_RISK_ORDER)}"
                )

    def _matches(self, when: dict | str, item: WorkItem) -> bool:
        if when == "all":  # validated match-everything sentinel
            return True
        # Only recognized labels count: an unrecognized one is recorded on the item
        # but must not clear a gate — nobody promoted it into the vocabulary, and a
        # gate that stays with the human is the safe way to be wrong.
        labels = set(self.classifiers.recognized(item.labels))
        if "labels_any" in when and not set(when["labels_any"]) & labels:
            return False
        if "labels_all" in when and not set(when["labels_all"]) <= labels:
            return False
        if "max_risk" in when:
            limit = _RISK_ORDER.get(when["max_risk"], 0)
            if _RISK_ORDER.get(item.risk, 3) > limit:
                return False
        return True


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class PolicyState:
    """The engine-owned overlay on ``policies.yml``: which signed rules are
    currently *suspended* by an observed failure, plus the suspend/reinstate
    audit trail. Kept apart from the yaml on purpose — the yaml is the human's
    intent and only humans edit it; this file is what the engine observed."""

    def __init__(self, root: str | Path):
        self.path = Path(root) / ".factory" / "policy-state.json"

    def _load(self) -> dict:
        if not self.path.exists():
            return {"suspended": {}, "history": []}
        data = json.loads(self.path.read_text())
        data.setdefault("suspended", {})
        data.setdefault("history", [])
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self.path)

    def suspended(self) -> dict[str, dict]:
        """rule id → {ts, item, why} for every currently-suspended rule."""
        return self._load()["suspended"]

    def suspend(self, rule_id: str, item_id: str, why: str) -> bool:
        """Suspend a rule (idempotent). Returns True if this call suspended it."""
        data = self._load()
        if rule_id in data["suspended"]:
            return False
        entry = {"ts": _now(), "item": item_id, "why": why}
        data["suspended"][rule_id] = entry
        data["history"].append({"event": "suspended", "rule": rule_id, **entry})
        self._save(data)
        return True

    def reinstate(self, rule_id: str, by: str, notes: str = "") -> None:
        """A human re-arms a suspended rule after review."""
        data = self._load()
        if rule_id not in data["suspended"]:
            known = ", ".join(sorted(data["suspended"])) or "(none)"
            raise PolicyError(f"{rule_id!r} is not suspended; suspended rules: {known}")
        del data["suspended"][rule_id]
        data["history"].append(
            {"event": "reinstated", "rule": rule_id, "ts": _now(), "by": by, "notes": notes}
        )
        self._save(data)
