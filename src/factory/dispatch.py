"""The dispatcher: the conveyor motor.

A deterministic state machine over work items. It decides the next action
(``next_action``), records a station's output and routes the item (``advance``),
and records a human's decision at a gate (``gate``) — consulting policies first
so a proven-safe item can clear a gate untouched.

The intelligence (actually running a station) lives in Claude Code skills; this
module only decides WHAT should happen next and records WHAT happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .interventions import Interventions
from .line import Line, LineError
from .metrics import Metrics
from .model import GateDecision, StationReport, WorkItem
from .policies import Policies
from .store import Store

# Gate decisions that mean the human steered (rework), not just approved.
# Public: the CLI also consults this to nudge for a --notes learning signal.
STEERING_VERDICTS = {"needs_revision", "not_ready", "park"}


@dataclass
class Action:
    """What the driver (the /factory command) should do next for an item."""

    type: str  # run_station | run_external | human_gate | auto_gate | done | parked
    item_id: str
    state: str
    skill: str | None = None
    agent: str | None = None
    gate: str | None = None
    prompt: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


class Dispatcher:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.line = Line.load(self.root / "line.yml")
        self.policies = Policies.load(self.root / "policies.yml")
        self.store = Store(self.root)
        self.metrics = Metrics(self.root)
        self.interventions = Interventions(self.root)

    # --- creation -----------------------------------------------------------
    def new_item(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        risk: str = "unknown",
        parent: str | None = None,
    ) -> WorkItem:
        item = WorkItem(
            id=self.store.next_id(),
            title=title,
            body=body,
            labels=labels or [],
            risk=risk,
            state=self.line.start,
            parent=parent,
        )
        item.log(kind="created", to_state=item.state, actor="factory")
        self.store.save(item)
        self.metrics.emit(kind="created", item=item.id)
        return item

    # --- decide (pure) ------------------------------------------------------
    def next_action(self, item: WorkItem) -> Action:
        """Pure: what should happen for the item in its CURRENT state. Gates that
        an approved policy can clear are reported as ``auto_gate`` (the caller
        applies them), so this never mutates."""
        state = item.state
        if self.line.is_terminal(state):
            kind = "parked" if state == "parked" else "done"
            return Action(type=kind, item_id=item.id, state=state, message=f"{item.id} is {state}.")
        if self.line.is_gate(state):
            gate = self.line.gate_name(state) or state
            rule = self.policies.auto_decision(gate, item)
            if rule:
                return Action(
                    type="auto_gate",
                    item_id=item.id,
                    state=state,
                    gate=gate,
                    message=f"Policy {rule['id']!r} auto-clears the {gate} gate.",
                )
            return Action(
                type="human_gate",
                item_id=item.id,
                state=state,
                gate=gate,
                prompt=self.line.prompt_for(state),
                message=f"Human gate: {gate}. {self.line.prompt_for(state)}",
            )
        if self.line.is_external(state):
            return Action(
                type="run_external",
                item_id=item.id,
                state=state,
                message=f"External station {state!r} (run the CI/CD deploy step, then advance).",
            )
        return Action(
            type="run_station",
            item_id=item.id,
            state=state,
            skill=self.line.skill_for(state),
            agent=self.line.agent_for(state),
            message=f"Run the {state!r} station.",
        )

    # --- act (mutating) -----------------------------------------------------
    def advance(self, item: WorkItem, report: StationReport) -> str:
        """Record a station's report and route the item to its next state."""
        state = item.state
        if not self.line.is_station(state):
            raise LineError(f"{item.id} at {state!r} is not a station; cannot advance")
        item.attempts[state] = item.attempts.get(state, 0) + 1
        item.cost += report.cost
        self._absorb(item, report)

        if report.human_required:
            item.log(
                kind="station",
                from_state=state,
                to_state="blocked",
                verdict="blocked",
                actor=report.station,
                note=report.human_reason or "station requested a human",
                cost=report.cost,
            )
            item.state = "blocked"
            item.steers += 1  # a block means autonomy broke here — counts as a human step-in
            self.store.save(item)
            self.metrics.emit(
                kind="station",
                item=item.id,
                station=report.station,
                verdict="blocked",
                cost=report.cost,
            )
            return item.state

        nxt = self.line.route(state, report.verdict)
        item.log(
            kind="station",
            from_state=state,
            to_state=nxt,
            verdict=report.verdict,
            actor=report.station,
            note=report.summary,
            cost=report.cost,
        )
        item.state = nxt
        for spec in report.spawn:
            child = self.new_item(
                spec.get("title", "Untitled"),
                spec.get("body", ""),
                labels=spec.get("labels", []),
                parent=item.id,
            )
            item.log(kind="spawn", actor=report.station, note=f"spawned {child.id}: {child.title}")
        if report.verdict == self.line.ships_on(state):  # a change just shipped
            self.metrics.emit(
                kind="shipped",
                item=item.id,
                human_touches=item.human_touches,
                steers=item.steers,
                cost=item.cost,
            )
        self.store.save(item)
        self.metrics.emit(
            kind="station",
            item=item.id,
            station=report.station,
            verdict=report.verdict,
            cost=report.cost,
        )
        return item.state

    def gate(self, item: WorkItem, decision: GateDecision, produced: str = "") -> str:
        """Record a human's decision at a gate; capture an intervention if the
        human steered (revision / not-ready / park / explicit change)."""
        state = item.state
        if not self.line.is_gate(state):
            raise LineError(f"{item.id} is at {state!r}, not a human gate")
        gate_name = self.line.gate_name(state) or state
        nxt = self.line.route(state, decision.decision)
        item.human_touches += 1
        item.log(
            kind="gate",
            from_state=state,
            to_state=nxt,
            verdict=decision.decision,
            actor=f"human:{decision.by}",
            note=decision.notes,
        )
        item.state = nxt
        is_intervention = decision.changed or decision.decision in STEERING_VERDICTS
        if is_intervention:
            item.steers += 1  # a send-back / correction / park is human rework
            path = self.interventions.record(item, decision, state, produced)
            item.log(
                kind="note",
                actor="factory",
                note=f"intervention recorded at {path.relative_to(self.root)}",
            )
        self.store.save(item)
        self.metrics.emit(
            kind="gate",
            item=item.id,
            gate=gate_name,
            decision=decision.decision,
            by=decision.by,
            required_human=True,
            changed=is_intervention,
        )
        return item.state

    def apply_auto_gate(self, item: WorkItem, gate: str, rule: dict) -> str:
        """Clear a gate via an approved policy — no human, no intervention."""
        state = item.state
        decision = rule["decision"]
        nxt = self.line.route(state, decision)
        rationale = rule.get("rationale", "")
        item.log(
            kind="auto_gate",
            from_state=state,
            to_state=nxt,
            verdict=decision,
            actor=f"policy:{rule['id']}",
            note=f"rationale: {rationale}" if rationale else "cleared by approved policy",
        )
        item.state = nxt
        self.store.save(item)
        self.metrics.emit(
            kind="gate",
            item=item.id,
            gate=gate,
            decision=decision,
            required_human=False,
            changed=False,
            rule=rule["id"],
        )
        return nxt

    @staticmethod
    def _absorb(item: WorkItem, report: StationReport) -> None:
        for a in report.artifacts:
            if a not in item.artifacts:
                item.artifacts.append(a)
        if report.risk:
            item.risk = report.risk
        if report.pr:
            item.pr = report.pr
