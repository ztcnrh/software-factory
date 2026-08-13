"""The dispatcher: the conveyor motor.

A deterministic state machine over work items. It decides the next action
(``next_action``), records a station's output and routes the item (``advance``),
and records a human's decision at a gate (``gate``) — consulting policies first
so a proven-safe item can clear a gate untouched.

The intelligence (actually running a station) lives in Claude Code skills; this
module only decides WHAT should happen next and records WHAT happened.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import sweep
from .checklist import DISPOSITIONS, Checklist, ChecklistError, row_label
from .classifiers import Classifiers
from .interventions import Interventions
from .line import Line, LineError
from .metrics import Metrics
from .model import (
    RISK_FLOOR,
    RISK_ORDER,
    GateDecision,
    StationReport,
    WorkItem,
    risk_floor_matches,
)
from .policies import Policies, PolicyState
from .store import Store

# Bounds on the git reads a gate binding makes. The local ones are instant; the
# remote one is a single network round trip, generous enough for a slow link and
# short enough that a human is never left waiting on a dead host.
_GIT_TIMEOUT = 10.0
_LS_REMOTE_TIMEOUT = 20.0


def _short_sha(sha: str) -> str:
    """A commit for a human to eyeball, or a word for the two non-commit cases."""
    return sha[:9] if sha else "(absent)"


def unreadable_tips(snap: dict) -> list[str]:
    """Which branch tips a binding could not read.

    The binding still holds for everything else; this is the part of its promise
    that didn't, and a caller is expected to say so out loud rather than let the
    human assume the whole review is pinned."""
    out = []
    for label, tips in (snap.get("tips") or {}).items():
        for where in ("local", "remote"):
            if tips and tips.get(where) is None:
                out.append(f"{label} `{tips.get('ref')}` ({where})")
    return out


class GateDriftError(Exception):
    """A gate decision arrived after the reviewed content moved — the approval
    would bind to something the human never saw. Caught at the CLI boundary."""


class ClassifierError(Exception):
    """A retraction the engine refuses: the item doesn't carry the classifier,
    it carries no reason, or a station tried to overrule a human's classification.
    Raised before anything is written, so the call it arrived on applies nothing."""


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
    # run_station context: which run this is (1-based), whether the station is a
    # checker (drives the driver's isolation rules), and the event that routed
    # the item here (a retry knows what sent it back without digging).
    attempt: int | None = None
    checking: bool = False
    last_return: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", False)}


class Dispatcher:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.line = Line.load(self.root / "line.yml")
        # One vocabulary per factory, shared by everything that consults it —
        # policy matching, the station brief, status rendering.
        self.classifiers = Classifiers.load(self.root / "classifiers.yml")
        self.policies = Policies.load(self.root / "policies.yml", classifiers=self.classifiers)
        self.policy_state = PolicyState(self.root)
        self.store = Store(self.root)
        self.metrics = Metrics(self.root)
        self.interventions = Interventions(self.root)

    def active_auto_rule(self, gate: str, item: WorkItem) -> dict | None:
        """The one lookup every auto-clear goes through: policies.yml rules
        filtered by the suspension overlay, so a demoted rule can't fire."""
        suspended = frozenset(self.policy_state.suspended())
        return self.policies.auto_decision(gate, item, suspended=suspended)

    # --- creation -----------------------------------------------------------
    def new_item(
        self,
        title: str,
        body: str = "",
        classifiers: list[str] | None = None,
        risk: str = "unknown",
        parent: str | None = None,
        source: str = "local",
        source_ref: str | None = None,
        classifiers_by: str = "unknown",
    ) -> WorkItem:
        item = WorkItem(
            id=self.store.next_id(),
            title=title,
            body=body,
            risk=risk,
            state=self.line.start,
            parent=parent,
            source=source,
            source_ref=source_ref,
        )
        for name in classifiers or []:
            item.add_classifier(name, by=classifiers_by)
        item.log(kind="created", to_state=item.state, actor="factory")
        # Deterministic risk floor: sensitive-sounding work enters at RISK_FLOOR
        # unless a human explicitly set a risk at creation (their call wins —
        # recorded either way, so the audit trail says why).
        matches = risk_floor_matches(f"{title}\n{body}")
        if matches:
            if risk == "unknown":
                item.risk = RISK_FLOOR
                item.metadata["risk_floor"] = RISK_FLOOR
                item.metadata["risk_floor_matches"] = matches
                item.log(
                    kind="note",
                    actor="factory",
                    note=f"risk floored to {RISK_FLOOR}: touches {', '.join(matches)} "
                    "(stations may raise it, never lower it; an explicit risk at "
                    "creation overrides)",
                )
            elif RISK_ORDER.get(risk, 3) < RISK_ORDER[RISK_FLOOR]:
                item.log(
                    kind="note",
                    actor="factory",
                    note=f"risk floor bypassed by explicit risk={risk} "
                    f"(matched: {', '.join(matches)})",
                )
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
            rule = self.active_auto_rule(gate, item)
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
            attempt=item.attempts.get(state, 0) + 1,
            checking=self.line.is_checking(state),
            last_return=self._last_return(item, state),
        )

    @staticmethod
    def _last_return(item: WorkItem, state: str) -> str | None:
        """The event that routed the item into ``state`` — so a retry's brief can
        say what sent it back (e.g. the review's headline) without the station
        re-mining history."""
        for ev in reversed(item.history):
            if ev.to_state == state and ev.kind != "created":
                who = ev.actor or ev.kind
                verdict = f" ({ev.verdict})" if ev.verdict else ""
                note = f": {ev.note}" if ev.note else ""
                return f"{who}{verdict}{note}"
        return None

    # --- classifiers --------------------------------------------------------
    def _is_station_actor(self, by: str) -> bool:
        """Is this actor a station on the line? The one thing that decides whether
        a retraction is authorized — a station name is a state; a human signs
        ``human:<who>``, and an unattributed one carries ``unknown``. Neither is a state,
        so neither is retractable by a station."""
        return by in self.line.states and self.line.is_station(by)

    def check_retraction(self, item: WorkItem, name: str, by: str, reason: str) -> None:
        """Everything that must hold before a classifier comes off — raised, never
        applied. Split from ``retract`` so a whole report's retractions can be
        vetted before any of them (or the verdict carrying them) takes effect."""
        if not (reason or "").strip():
            raise ClassifierError(
                f"retracting {name!r} needs a reason — the log's value is that the "
                "correction says why the classification was wrong"
            )
        if name not in item.classifiers:
            carried = ", ".join(item.classifiers) or "(none)"
            raise ClassifierError(
                f"{item.id} does not carry the classifier {name!r}; it has: {carried}"
            )
        if self._is_station_actor(by):
            owner = item.provenance(name)
            if not self._is_station_actor(owner or ""):
                raise ClassifierError(
                    f"{by!r} may not retract {name!r}: it was applied by {owner!r}, not by a "
                    "station. A station may correct another station's classification, never a "
                    f"human's — a human can, at the gate: factory gate {item.id} "
                    f"--retract {name} --retract-reason '<why>'"
                )

    def retract(self, item: WorkItem, name: str, by: str, reason: str) -> None:
        """Retract a classifier, validating first. ``by`` is both the recorded actor and
        the authority: a station may retract only what a station applied; anyone
        else may retract anything. The caller saves."""
        self.check_retraction(item, name, by, reason)
        item.retract_classifier(name, by=by, reason=reason)

    # --- the invariant checklist --------------------------------------------
    def _check_checklist(self, item: WorkItem, report: StationReport) -> None:
        """Refuse a ``verified`` verdict that leaves invariants undisposed.

        `blocked`/`accepted`/`out-of-scope` make an honest "didn't run it" cheap to
        record, so the only thing this blocks is silence. Registering the checklist
        is what arms the guard — the report's artifacts are absorbed first so a
        station can register it and dispose its rows in one call."""
        if report.verdict != "verified" or report.human_required:
            return
        path = Checklist.find(self.root, list(item.artifacts) + list(report.artifacts))
        if not path:
            return
        pending = Checklist.load(path).undisposed()
        if pending:
            named = "\n  - ".join(row_label(r) for r in pending)
            raise ChecklistError(
                f"{item.id}: cannot report `verified` — {len(pending)} invariant(s) in "
                f"{path.name} have no disposition:\n  - {named}\n"
                f"Record one of {', '.join(DISPOSITIONS)} for each. `blocked` (out of reach), "
                "`accepted` (low risk, didn't run it), and `out-of-scope` are all honest "
                "answers; a blank row is the only one that isn't."
            )

    # --- act (mutating) -----------------------------------------------------
    def advance(self, item: WorkItem, report: StationReport) -> str:
        """Record a station's report and route the item to its next state."""
        state = item.state
        if not self.line.is_station(state):
            raise LineError(f"{item.id} at {state!r} is not a station; cannot advance")
        # Validate every retraction before touching the item: a refused retraction must
        # take the whole report with it, or the verdict routes while the correction
        # it depended on silently didn't apply.
        for name, reason in report.retractions:
            self.check_retraction(item, name, report.station, reason)
        self._check_checklist(item, report)
        item.attempts[state] = item.attempts.get(state, 0) + 1
        item.cost += report.cost
        self._absorb(item, report)
        # The floor set at intake holds against stations: risk may be raised by
        # a report, never lowered back below the floor (a model can only make a
        # sensitive item MORE guarded, not quietly de-escalate it past a gate).
        floor = item.metadata.get("risk_floor")
        if floor and report.risk and RISK_ORDER.get(report.risk, 3) < RISK_ORDER.get(floor, 0):
            item.risk = floor
            item.log(
                kind="note",
                actor="factory",
                note=f"risk floor: kept {floor} (station proposed {report.risk}; floored at "
                f"intake on: {', '.join(item.metadata.get('risk_floor_matches', []))})",
            )

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
        # Attempt cap: an automated route into a station that already ran its
        # budget this epoch lands at `blocked` instead of looping again — the
        # live circuit-breaker for implement↔code_review-style ping-pong. Human
        # decisions are never capped (gate/correct/revive open a fresh epoch).
        cap_note = None
        if nxt != "blocked" and self.line.is_station(nxt):
            cap = self.line.max_attempts(nxt)
            if cap is not None:
                runs = self._runs_this_epoch(item, nxt)
                if runs >= cap:
                    cap_note = (
                        f"attempt cap: {nxt} already ran {runs}× since the last human "
                        f"touch (max_attempts {cap}) — loop stopped instead of re-entering; "
                        "a human unblock opens a fresh budget"
                    )
                    nxt = "blocked"
        item.log(
            kind="station",
            from_state=state,
            to_state=nxt,
            verdict=verdict,
            actor=report.station,
            note=note,
            cost=report.cost,
            ran=report.ran or None,
        )
        item.state = nxt
        self._note_park(item, state, nxt)
        if nxt == "blocked":
            # However it arrived — the routed `blocked` verdict, the escape hatch,
            # or the attempt cap — landing at the blocked gate means autonomy broke
            # at this station. Count it as a human step-in, or the one-shot ship
            # rate would lie.
            item.steers += 1
            self._suspend_clearing_rules(item, f"blocked at {state} ({note})")
        if cap_note:
            item.log(kind="note", actor="factory", note=cap_note)
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
                classifiers=spec.get("classifiers", []),
                classifiers_by=report.station,
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
        self._sweep_if_terminal(item)
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

    def bind_gate(self, item: WorkItem, by: str) -> dict:
        """Bind the upcoming human decision to what is being reviewed right now.

        Snapshots three things: the item's artifact files (content-hashed), its
        two PR pointers, and where its branches point — locally and on the remote
        the human is reading the PR on. The branches are the reason this reaches
        for the network at all: a pointer is only a name, so without the tips a
        pass re-pushed under an open review would clear a gate the human gave to
        different code. ``gate`` then refuses a decision if any of it moved.

        Binding says nothing about the outcome — the gate still waits on the
        human."""
        state = item.state
        if not self.line.is_gate(state):
            raise LineError(f"{item.id} is at {state!r}, not a human gate — nothing to bind")
        gate_name = self.line.gate_name(state) or state
        snap = self._gate_snapshot(item)
        item.log(
            kind="gate_bound",
            from_state=state,
            actor=by,
            note=f"decision bound to {len(snap['artifacts'])} artifact(s), the item's PRs, "
            "and its branch tips",
        )
        snap["gate"] = gate_name
        # Recorded after the bind event: ANY later history growth is drift.
        snap["history_len"] = len(item.history)
        item.metadata["gate_binding"] = snap
        self.store.save(item)
        return snap

    def gate(
        self,
        item: WorkItem,
        decision: GateDecision,
        produced: str = "",
        accept_drift: bool = False,
        retractions: list[tuple[str, str]] | None = None,
        notices: list[str] | None = None,
    ) -> str:
        """Record a human's decision at a gate; capture an intervention if the
        human steered (revision / not-ready / park / explicit change). If the
        gate was bound (``bind_gate``), the decision is checked against the
        bound snapshot and refused on drift unless ``accept_drift``.

        ``retractions`` ride along with the decision the human is already making —
        the human's retraction path, unrestricted by provenance.

        ``notices`` is an out-parameter: pass a list and this appends anything the
        caller should show but that must not block the decision (today, checks the
        binding couldn't complete). It stays out of the return value because every
        other caller only wants the state it routed to."""
        state = item.state
        if not self.line.is_gate(state):
            raise LineError(f"{item.id} is at {state!r}, not a human gate")
        gate_name = self.line.gate_name(state) or state
        # Vet before anything applies, same discipline as advance: a bad retraction
        # name must not leave the decision recorded and the correction dropped.
        actor = f"human:{decision.by}"
        for name, reason in retractions or []:
            self.check_retraction(item, name, actor, reason)
        bound = item.metadata.get("gate_binding")
        # Only a binding made *at this gate* speaks for this decision — a leftover
        # from an earlier one describes a different review.
        if bound and bound.get("gate") != gate_name:
            bound = None
        if bound:
            drift, unverifiable = self._gate_drift(item, bound)
            if drift and not accept_drift:
                raise GateDriftError(
                    f"{item.id}: the content reviewed at {gate_name} moved since it was "
                    "bound:\n  - " + "\n  - ".join(drift)
                )
            if drift:
                item.log(
                    kind="note",
                    actor="factory",
                    note="gate decision recorded despite drift: " + "; ".join(drift),
                )
            if unverifiable:
                # On the record as well as on screen: a decision taken with part of
                # its binding unchecked should still say so a year later.
                item.log(
                    kind="note",
                    actor="factory",
                    note="gate binding partly unverified: " + "; ".join(unverifiable),
                )
                if notices is not None:
                    notices.extend(unverifiable)
        item.metadata.pop("gate_binding", None)  # used, or stale — either way it's spent
        nxt = self.line.route(state, decision.decision)
        item.human_touches += 1
        for name, reason in retractions or []:
            item.retract_classifier(name, by=actor, reason=reason)
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
        # A human decision opens a fresh attempt epoch: new guidance deserves a
        # fresh loop budget, and the lifetime `attempts` map keeps the full churn
        # history for the retro regardless.
        item.metadata["epoch_len"] = len(item.history)
        if decision.is_steer:
            item.steers += 1  # a send-back / correction / park is human rework
            path = self.interventions.record(item, decision, state, produced)
            item.log(
                kind="note",
                actor="factory",
                note=f"intervention recorded at {path.relative_to(self.root)}",
            )
            self._suspend_clearing_rules(
                item, f"human steer at {gate_name} ({decision.decision})"
            )
        self._sweep_if_terminal(item)
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
        item.metadata["epoch_len"] = len(item.history)  # human act: fresh attempt epoch
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
        item.metadata["epoch_len"] = len(item.history)  # human act: fresh attempt epoch
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
        # Remember who vouched for this item: if it later needs human rework,
        # every rule that auto-cleared it gets suspended (the demotion half of
        # the autonomy ratchet — promotion stays human, in policies.yml).
        cleared_by = item.metadata.setdefault("auto_cleared_by", [])
        if rule["id"] not in cleared_by:
            cleared_by.append(rule["id"])
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
    def _suspend_clearing_rules(self, item: WorkItem, why: str) -> None:
        """The demotion half of the autonomy ratchet: an item needing human
        rework suspends every policy rule that auto-cleared it. Conservative on
        purpose — the gate returns to the human, who reviews and reinstates
        (``factory policy reinstate``) if the rule wasn't at fault."""
        for rule_id in item.metadata.get("auto_cleared_by", []):
            if self.policy_state.suspend(rule_id, item.id, why):
                item.log(
                    kind="note",
                    actor="factory",
                    note=f"policy {rule_id!r} suspended: it auto-cleared this item, which "
                    f"then needed a human ({why}). Reinstate after review: "
                    f"factory policy reinstate {rule_id}",
                )
                self.metrics.emit(
                    kind="policy_suspended", rule=rule_id, item=item.id, why=why
                )

    def _hash_file(self, rel: str) -> str:
        """Content hash of a root-relative file, or "missing" — so an artifact
        that vanishes between open and decide reads as drift, not an error."""
        p = self.root / rel
        if not p.is_file():
            return "missing"
        return hashlib.sha256(p.read_bytes()).hexdigest()

    def _git(self, *args: str, timeout: float = _GIT_TIMEOUT) -> str | None:
        """Run a read-only git command in the factory root, or ``None`` if it
        couldn't run (no git, no repo, no network, a timeout, a non-zero exit).

        ``GIT_TERMINAL_PROMPT=0`` is the load-bearing part: without it a remote
        that wants credentials blocks on a password prompt, and the one command
        that must never hang is the one a human is waiting at."""
        try:
            p = subprocess.run(
                ["git", *args],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""},
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return p.stdout.strip() if p.returncode == 0 else None

    def _branch_tips(self, branch: str | None) -> dict[str, Any]:
        """Where ``branch`` points, locally and on the remote it tracks.

        Three-valued on purpose: a SHA, ``""`` for "the branch isn't there", or
        ``None`` for "couldn't read it". Collapsing the last two would let an
        unreachable remote read as agreement, which is the one answer a binding
        must never invent. The remote is asked with ``ls-remote`` — one round
        trip, no objects fetched, nothing in the repo mutated."""
        if not branch:
            return {}
        if self._git("rev-parse", "--git-dir") is None:
            return {"ref": branch, "local": None, "remote": None, "via": None}
        local = self._git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        via = self._git("config", "--get", f"branch.{branch}.remote") or "origin"
        ls = self._git("ls-remote", "--heads", via, branch, timeout=_LS_REMOTE_TIMEOUT)
        return {
            "ref": branch,
            "local": local if local is not None else "",
            "remote": None if ls is None else (ls.split()[0] if ls else ""),
            "via": via,
        }

    def _gate_snapshot(self, item: WorkItem) -> dict:
        return {
            "pr": item.pr,
            "change_pr": item.change_pr,
            # What the human is actually reading is the branch behind the PR, so
            # the pointer alone is not the review — the tips are.
            "tips": {
                "feature branch": self._branch_tips(item.branch),
                "change branch": self._branch_tips(item.change_branch),
            },
            "artifacts": {a: self._hash_file(a) for a in sorted(item.artifacts)},
        }

    def _gate_drift(self, item: WorkItem, bound: dict) -> tuple[list[str], list[str]]:
        """What moved since ``bind_gate``, and what couldn't be checked.

        Two lists, because they deserve different answers: **drift** refuses the
        decision (something the human reviewed is not what they're about to
        approve), while **unverifiable** only warns (a remote we couldn't reach
        proves nothing either way, and a gate that fails closed on a flaky network
        is a gate nobody can use)."""
        drift: list[str] = []
        unverifiable: list[str] = []
        grew = len(item.history) - int(bound.get("history_len", 0))
        if grew:
            drift.append(f"item history advanced by {grew} event(s) since the gate was bound")
        if item.pr != bound.get("pr"):
            drift.append(f"pr changed: {bound.get('pr')!r} → {item.pr!r}")
        if item.change_pr != bound.get("change_pr"):
            drift.append(f"change pr changed: {bound.get('change_pr')!r} → {item.change_pr!r}")
        for label, was in (bound.get("tips") or {}).items():
            if not was:
                continue
            now = self._branch_tips(was.get("ref"))
            for where in ("local", "remote"):
                before, after = was.get(where), now.get(where)
                if before is None or after is None:
                    unverifiable.append(
                        f"{label} `{was.get('ref')}` ({where}) could not be read, so whether it "
                        "moved since the gate was bound is unknown"
                    )
                elif before != after:
                    drift.append(
                        f"{label} `{was.get('ref')}` moved ({where}): "
                        f"{_short_sha(before)} → {_short_sha(after)} — re-review the diff"
                    )
        old = bound.get("artifacts", {})
        now = {a: self._hash_file(a) for a in sorted(item.artifacts)}
        for a, h in now.items():
            if a not in old:
                drift.append(f"artifact added since bind: {a}")
            elif h != old[a]:
                drift.append(f"artifact changed since bind: {a}")
        drift += [f"artifact removed since bind: {a}" for a in old if a not in now]
        return drift, unverifiable

    @staticmethod
    def _runs_this_epoch(item: WorkItem, state: str) -> int:
        """Completed runs of ``state`` since the last human touch (gate, correct,
        or revive stamps ``metadata.epoch_len``). The lifetime ``attempts`` map is
        deliberately untouched history — the retro's churn signal — while the cap
        judges only the current fully-automated stretch."""
        epoch = item.metadata.get("epoch_len", 0)
        return sum(
            1 for ev in item.history[epoch:] if ev.kind == "station" and ev.from_state == state
        )

    def _sweep_if_terminal(self, item: WorkItem) -> None:
        """Reclaim the item's scratch once it comes off the line. Never fatal — a
        failed cleanup must not take down the transition that finished the work."""
        if not self.line.is_terminal(item.state):
            return
        try:
            removed = sweep.run(self.root, item)
        except (OSError, sweep.SweepError) as e:
            item.log(kind="note", actor="factory", note=f"sweep skipped: {e}")
            return
        if removed:
            item.log(
                kind="note",
                actor="factory",
                note=f"swept {len(removed)} scratch file(s) on reaching {item.state} "
                "(briefs regenerate; registered artifacts kept)",
            )

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
        # Append-only: adds, then the retractions `advance` already validated.
        for name in report.classifiers:
            item.add_classifier(name, by=report.station)
        for name, reason in report.retractions:
            item.retract_classifier(name, by=report.station, reason=reason)
        if report.risk:
            item.risk = report.risk
        if report.branch:
            item.branch = report.branch
        if report.pr:
            item.pr = report.pr
        item.open_change_pass(report.change_branch, report.change_pr)
