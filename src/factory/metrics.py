"""The North Star ledger: an append-only event log plus aggregate views.

Headline metric: the share of shipped changes that required zero human
intervention. Plus where humans step in most (so the retro station knows where
to aim) and a cost-per-change proxy (Lloyd's "at what cost").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Metrics:
    def __init__(self, root: str | Path):
        self.path = Path(root) / ".factory" / "metrics" / "events.jsonl"

    def emit(self, **event: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(event) + "\n")

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def summary(self) -> dict:
        events = self.events()
        shipped = [e for e in events if e.get("kind") == "shipped"]
        gates = [e for e in events if e.get("kind") == "gate"]
        human_gates = [g for g in gates if g.get("required_human")]
        changed_gates = [g for g in gates if g.get("changed")]
        auto_shipped = [s for s in shipped if s.get("human_touches", 0) == 0]
        by_gate: dict[str, int] = {}
        for g in human_gates:
            key = g.get("gate", "?")
            by_gate[key] = by_gate.get(key, 0) + 1
        total = len(shipped)
        cost = sum(e.get("cost", 0.0) for e in events)
        return {
            "shipped": total,
            "auto_shipped": len(auto_shipped),
            "auto_ship_rate": (len(auto_shipped) / total) if total else 0.0,
            "human_gate_stops": len(human_gates),
            "human_changes": len(changed_gates),
            "interventions_by_gate": dict(sorted(by_gate.items(), key=lambda kv: -kv[1])),
            "total_cost": round(cost, 4),
            "cost_per_shipped": round(cost / total, 4) if total else 0.0,
        }
