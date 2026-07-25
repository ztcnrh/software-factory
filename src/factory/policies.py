"""Gate policies: decide whether a human gate can be cleared automatically.

The default posture is to require a human at every gate. The retro station
proposes new rules (written elsewhere for you to review); a rule only takes
effect once you set ``approved_by`` on it in ``policies.yml``. Each approved rule
permanently removes a class of work from your plate — this is the lever that
raises the "shipped without human intervention" metric over time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .model import RISK_ORDER as _RISK_ORDER
from .model import WorkItem

_WHEN_KEYS = {"labels_any", "labels_all", "max_risk"}  # the ONLY valid condition keys


class PolicyError(Exception):
    """Raised on a malformed gate policy — caught at load time (e.g. ``factory init``)."""


class Policies:
    def __init__(self, data: dict[str, Any], path: Path | None = None):
        self.path = path
        self.default = data.get("default", "require_human")
        self.rules: list[dict] = data.get("rules") or []
        self._validate()

    @classmethod
    def load(cls, path: str | Path) -> Policies:
        p = Path(path)
        if not p.exists():
            return cls({"default": "require_human", "rules": []}, p)
        with open(p) as f:
            return cls(yaml.safe_load(f) or {}, p)

    def auto_decision(self, gate: str, item: WorkItem) -> dict | None:
        """Return an *active* (approved) rule that clears this gate for this item,
        or ``None`` if a human is still required."""
        for rule in self.rules:
            if rule.get("gate") != gate:
                continue
            if not rule.get("approved_by"):  # dormant until a human signs it
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

    @staticmethod
    def _matches(when: dict | str, item: WorkItem) -> bool:
        if when == "all":  # validated match-everything sentinel
            return True
        if "labels_any" in when and not set(when["labels_any"]) & set(item.labels):
            return False
        if "labels_all" in when and not set(when["labels_all"]) <= set(item.labels):
            return False
        if "max_risk" in when:
            limit = _RISK_ORDER.get(when["max_risk"], 0)
            if _RISK_ORDER.get(item.risk, 3) > limit:
                return False
        return True
