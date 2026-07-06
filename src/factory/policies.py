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

from .model import WorkItem

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "unknown": 3}


class Policies:
    def __init__(self, data: dict[str, Any], path: Path | None = None):
        self.path = path
        self.default = data.get("default", "require_human")
        self.rules: list[dict] = data.get("rules") or []

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

    @staticmethod
    def _matches(when: dict, item: WorkItem) -> bool:
        if "labels_any" in when and not set(when["labels_any"]) & set(item.labels):
            return False
        if "labels_all" in when and not set(when["labels_all"]) <= set(item.labels):
            return False
        if "max_risk" in when:
            limit = _RISK_ORDER.get(when["max_risk"], 0)
            if _RISK_ORDER.get(item.risk, 3) > limit:
                return False
        return True
