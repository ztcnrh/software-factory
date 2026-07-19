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
        source: str = "local",
        source_ref: str | None = None,
    ) -> WorkItem:
        item = WorkItem(
            id=self.store.next_id(),
            title=title,
            body=body,
            labels=labels or [],
            risk=risk,
            state=self.line.start,
            parent=parent,
            source=source,
            source_ref=source_ref,
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
            # Revivable terminals surface as "parked" (with the way back), any
            # other terminal as "done" — keyed off line.yml, not a state name.
            if self.line.states[state].get("revivable"):
                return Action(
                    type="parked",
                    item_id=item.id,
                    state=state,
                    message=f"{item.id} is {state}. Revive it: factory revive {item.id}"
                    " (add --resume to re-enter where it left off).",
                )
            return Action(
                type="done", item_id=item.id, state=state, message=f"{item.id} is {state}."
            )
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
            # The escape hatch: any station can bypass the routing table and land
            # the item at the blocked gate, whether or not a `blocked` route exists
            # from its state.
            nxt = "blocked"
            verdict = "blocked"
            note = report.human_reason or "station requested a human"
        else:
            nxt = self.line.route(state, report.verdict)
            verdict = report.verdict
            note = report.summary
        item.log(
            kind="station",
            from_state=state,
            to_state=nxt,
            verdict=verdict,
            actor=report.station,
            note=note,
            cost=report.cost,
        )
        item.state = nxt
        self._note_park(item, state, nxt)
        if nxt == "blocked":
            # However it arrived — the routed `blocked` verdict or the escape hatch —
            # landing at the blocked gate means autonomy broke at this station. Count
            # it as a human step-in, or the one-shot ship rate would lie.
            item.steers += 1
        if report.notes:
            # Station notes are context for whoever reads the item next — the human
            # at the gate (via status / the review packet) and the next station.
            # Persist them; the report object itself is discarded. (The retro
            # briefing reads interventions + metrics, not these, so notes don't
            # auto-fuel it — a retro would have to dig into work-item history.)
            item.log(kind="note", actor=report.station, note=report.notes)
        for spec in report.spawn:
            child = self.new_item(
                spec.get("title", "Untitled"),
                spec.get("body", ""),
                labels=spec.get("labels", []),
                parent=item.id,
            )
            item.log(kind="spawn", actor=report.station, note=f"spawned {child.id}: {child.title}")
        if verdict == self.line.ships_on(state):  # a change just shipped
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
            verdict=verdict,
            # Confidence lands in the ledger so a future confidence-weighted gate
            # policy has history to mine (e.g. auto-clear only above a threshold).
            confidence=report.confidence,
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
        self._note_park(item, state, nxt)
        if decision.is_steer:
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
            changed=decision.is_steer,
        )
        return item.state

    def revive(self, item: WorkItem, by: str, resume: bool = False, notes: str = "") -> str:
        """Bring a revivable (parked) item back onto the line.

        Default re-entry is the line's ``revive`` route (triage) — the safe path,
        since the codebase and priorities may have moved while it sat. With
        ``resume``, re-enter at the recorded pre-park state instead — for when
        the human signals the shelved context is still fresh."""
        state = item.state
        if not (self.line.is_terminal(state) and self.line.states[state].get("revivable")):
            raise ValueError(f"{item.id} at {state!r} is not a revivable state")
        nxt = self.line.route(state, "revive")
        if resume:
            prev = item.metadata.get("parked_from")
            if not prev:
                raise ValueError(
                    f"{item.id} has no recorded pre-park state (parked before this factory "
                    "tracked it) — revive without --resume to re-enter at the top"
                )
            if prev not in self.line.states:
                raise ValueError(
                    f"{item.id} was parked from {prev!r}, which is no longer on the line — "
                    "revive without --resume to re-enter at the top"
                )
            nxt = prev
        item.log(
            kind="revive",
            from_state=state,
            to_state=nxt,
            verdict="revive",
            actor=by,
            note=notes or ("resumed where it left off" if resume else ""),
        )
        item.state = nxt
        self.store.save(item)
        self.metrics.emit(kind="revive", item=item.id, to_state=nxt, resumed=resume, by=by)
        return item.state

    def correct(self, item: WorkItem, state: str, by: str, reason: str) -> str:
        """Admin correction: set the item's state directly, with an audited event.

        For the unlucky mis-target — an `advance`/`gate` that hit the wrong item
        whose state happened to accept the verdict. This is not an undo: the
        mistaken event stays in history (append-only is the audit trail); this
        puts the item back on track in one recorded move. Not a steer — it fixes
        the operator's slip, not the work."""
        if not reason.strip():
            raise ValueError("a correction must carry a --reason (it's the audit trail)")
        if state not in self.line.states:
            valid = ", ".join(self.line.states)
            raise ValueError(f"unknown state {state!r}; valid: {valid}")
        if state == item.state:
            raise ValueError(f"{item.id} is already at {state!r} — nothing to correct")
        old = item.state
        item.log(
            kind="correction",
            from_state=old,
            to_state=state,
            actor=by,
            note=reason,
        )
        item.state = state
        self.store.save(item)
        self.metrics.emit(
            kind="correction", item=item.id, from_state=old, to_state=state, by=by
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
        self._note_park(item, state, nxt)
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

    # --- internals ----------------------------------------------------------
    def _note_park(self, item: WorkItem, from_state: str, nxt: str) -> None:
        """Remember where a park came from (any route into a revivable terminal),
        so ``revive --resume`` can re-enter there instead of the top of the line."""
        if self.line.is_terminal(nxt) and self.line.states[nxt].get("revivable"):
            item.metadata["parked_from"] = from_state

    @staticmethod
    def _absorb(item: WorkItem, report: StationReport) -> None:
        for a in report.artifacts:
            if a not in item.artifacts:
                item.artifacts.append(a)
        # Labels are additive: a station classifies an item, it never wipes labels
        # set at intake or by an earlier station (policies match on the union).
        for lab in report.labels:
            if lab not in item.labels:
                item.labels.append(lab)
        if report.risk:
            item.risk = report.risk
        if report.pr:
            item.pr = report.pr
