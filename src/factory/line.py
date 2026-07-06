"""Loads ``line.yml`` and answers routing/topology questions about the line.

This is the only place that understands the *shape* of the factory. Everything
else asks it "what kind of state is this?" and "given this verdict, where next?"
so the line can be reshaped purely by editing line.yml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class LineError(Exception):
    """Raised on an invalid line definition or an impossible route."""


class Line:
    def __init__(self, data: dict[str, Any]):
        self.version = data.get("version", 1)
        self.north_star = (data.get("north_star") or "").strip()
        self.states: dict[str, dict] = data["states"]
        self.start: str = data["start"]
        self.routing: dict[str, dict[str, str]] = data["routing"]
        self._validate()

    @classmethod
    def load(cls, path: str | Path) -> Line:
        with open(path) as f:
            return cls(yaml.safe_load(f))

    def _validate(self) -> None:
        if self.start not in self.states:
            raise LineError(f"start state {self.start!r} is not a defined state")
        for state, table in self.routing.items():
            if state not in self.states:
                raise LineError(f"routing references unknown state {state!r}")
            for verdict, dest in table.items():
                if dest not in self.states:
                    raise LineError(f"routing {state}/{verdict} -> unknown state {dest!r}")

    # --- topology -----------------------------------------------------------
    def kind(self, state: str) -> str:
        return self.states[state]["kind"]

    def is_station(self, state: str) -> bool:
        return self.kind(state) == "station"

    def is_gate(self, state: str) -> bool:
        return self.kind(state) == "human_gate"

    def is_terminal(self, state: str) -> bool:
        return self.kind(state) == "terminal"

    def is_external(self, state: str) -> bool:
        return bool(self.states[state].get("external"))

    def skill_for(self, state: str) -> str | None:
        return self.states[state].get("skill")

    def agent_for(self, state: str) -> str | None:
        return self.states[state].get("agent")

    def gate_name(self, state: str) -> str | None:
        return self.states[state].get("gate")

    def prompt_for(self, state: str) -> str:
        return self.states[state].get("prompt", "")

    def valid_verdicts(self, state: str) -> list[str]:
        return list(self.routing.get(state, {}).keys())

    # --- routing ------------------------------------------------------------
    def route(self, state: str, verdict: str) -> str:
        table = self.routing.get(state, {})
        if verdict not in table:
            valid = ", ".join(self.valid_verdicts(state)) or "(none)"
            raise LineError(
                f"no route for verdict {verdict!r} from state {state!r}; valid: {valid}"
            )
        return table[verdict]
