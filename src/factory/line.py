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


_KINDS = {"station", "human_gate", "terminal"}


class Line:
    def __init__(self, data: dict[str, Any]):
        self.version = data.get("version", 1)
        self.north_star = (data.get("north_star") or "").strip()
        self.states: dict[str, dict] = data["states"]
        self.start: str = data["start"]
        self.routing: dict[str, dict[str, str]] = data["routing"]
        self.max_attempts_default = data.get("max_attempts")
        self._validate()

    @classmethod
    def load(cls, path: str | Path) -> Line:
        with open(path) as f:
            return cls(yaml.safe_load(f))

    def _validate(self) -> None:
        if self.start not in self.states:
            raise LineError(f"start state {self.start!r} is not a defined state")
        self._check_cap(self.max_attempts_default, "line-level max_attempts")
        for name, spec in self.states.items():
            # A typo'd kind would otherwise fall through the dispatcher's checks
            # and be treated as a station — reject it at the boundary instead.
            if spec.get("kind") not in _KINDS:
                raise LineError(
                    f"state {name!r} has unknown kind {spec.get('kind')!r}; "
                    f"valid: {', '.join(sorted(_KINDS))}"
                )
            if "max_attempts" in spec:
                if spec["kind"] != "station":
                    raise LineError(
                        f"state {name!r}: max_attempts only applies to stations — "
                        "a cap on a gate or terminal would never be consulted"
                    )
                self._check_cap(spec["max_attempts"], f"state {name!r} max_attempts")
            if spec.get("checking") and spec["kind"] != "station":
                raise LineError(
                    f"state {name!r}: checking only applies to stations — "
                    "only a station can be a checker of other stations' work"
                )
        for state, table in self.routing.items():
            if state not in self.states:
                raise LineError(f"routing references unknown state {state!r}")
            for verdict, dest in table.items():
                if dest not in self.states:
                    raise LineError(f"routing {state}/{verdict} -> unknown state {dest!r}")

    @staticmethod
    def _check_cap(value: Any, where: str) -> None:
        # bool is an int subclass — `max_attempts: true` must not sneak through.
        bad = isinstance(value, bool) or not isinstance(value, int) or value < 1
        if value is not None and bad:
            raise LineError(f"{where}: must be a positive integer, got {value!r}")

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

    def is_checking(self, state: str) -> bool:
        """A checker of other stations' work (line.yml `checking: true`) — the
        driver keys isolation on this: fresh context, no chat steering."""
        return bool(self.states[state].get("checking"))

    def ships_on(self, state: str) -> str | None:
        """The verdict from ``state`` that means "the change shipped" — the point
        the North Star ``shipped`` metric is recorded. Declarative (set in
        line.yml) so the engine isn't hardcoded to specific tail-state names."""
        return self.states.get(state, {}).get("ships_on")

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

    def max_attempts(self, state: str) -> int | None:
        """Cap on completed runs of a station within one human epoch (``None`` =
        uncapped). Per-state ``max_attempts`` overrides the line-level default;
        only stations are ever capped."""
        spec = self.states.get(state, {})
        if spec.get("kind") != "station":
            return None
        return spec.get("max_attempts", self.max_attempts_default)

    # --- routing ------------------------------------------------------------
    def route(self, state: str, verdict: str) -> str:
        table = self.routing.get(state, {})
        if verdict not in table:
            valid = ", ".join(self.valid_verdicts(state)) or "(none)"
            raise LineError(
                f"no route for verdict {verdict!r} from state {state!r}; valid: {valid}"
            )
        return table[verdict]
