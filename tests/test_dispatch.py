from pathlib import Path

import pytest

from factory.dispatch import Dispatcher
from factory.line import LineError
from factory.model import GateDecision, StationReport, WorkItem


def _advance(d: Dispatcher, item: WorkItem, verdict: str, **kw) -> str:
    return d.advance(item, StationReport(station=item.state, verdict=verdict, **kw))


def test_full_happy_path_reaches_done_and_logs_one_ship(factory_root: Path):
    """A clean run triage→…→deploy→done should log exactly one 'shipped' event
    (anchored on the deploy state's `ships_on` verdict, not a hardcoded name) and
    attribute the two human gate stops it passed."""
    d = Dispatcher(factory_root)
    item = d.new_item("Add /health endpoint", risk="low")
    _advance(d, item, "needs_spec")
    assert item.state == "spec"
    _advance(d, item, "ready_for_review")
    assert item.state == "spec_review"
    d.gate(item, GateDecision(gate="spec_review", decision="approved"))
    assert item.state == "implement"
    _advance(d, item, "implemented", pr="#1")
    _advance(d, item, "pass")
    _advance(d, item, "verified")
    assert item.state == "ship_review"
    d.gate(item, GateDecision(gate="ship_review", decision="approved"))
    assert item.state == "deploy"
    _advance(d, item, "succeeded")  # deploy -> done (the ship point)
    assert item.state == "done"

    shipped = [e for e in d.metrics.events() if e["kind"] == "shipped"]
    assert len(shipped) == 1
    assert shipped[0]["human_touches"] == 2  # human attended both gates
    assert shipped[0]["steers"] == 0  # ...but both approvals were clean — a one-shot ship
    assert d.metrics.summary()["one_shot_ship_rate"] == 1.0


def test_gate_rework_and_block_both_count_as_steers_but_clean_approval_does_not(
    factory_root: Path,
):
    """A steer = human rework. A gate send-back and a station block (escape hatch)
    each increment the item's steer count; a clean approval must not. This is what
    keeps the one-shot metric measuring rework, not mere human presence."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature", risk="low")
    _advance(d, item, "needs_spec")
    _advance(d, item, "ready_for_review")
    d.gate(item, GateDecision(gate="spec_review", decision="needs_revision", notes="fix it"))
    assert item.steers == 1  # a send-back is rework
    _advance(d, item, "ready_for_review")
    d.gate(item, GateDecision(gate="spec_review", decision="approved"))
    assert item.steers == 1  # a clean approval adds nothing
    _advance(d, item, "implemented", human_required=True, human_reason="needs a prod secret")
    assert item.state == "blocked"
    assert item.steers == 2  # a block means autonomy broke — counts too


def test_routed_blocked_verdict_counts_as_a_steer_like_the_escape_hatch(factory_root: Path):
    """Regression: spec/implement can reach `blocked` via their routed `blocked`
    verdict, which skipped the steers increment the escape hatch applied — so an
    unblocked item could still ship as a 'one-shot', contradicting the North Star's
    own definition (no unblock). Both spellings must count identically."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature", risk="low")
    _advance(d, item, "needs_spec")
    _advance(d, item, "blocked", summary="need a product decision on scope")
    assert item.state == "blocked"
    assert item.steers == 1
    d.gate(item, GateDecision(gate="blocked", decision="unblocked"))
    assert item.steers == 1  # the steer was counted at block time, not doubled at the gate


def test_spawn_survives_the_escape_hatch(factory_root: Path):
    """Regression: the escape-hatch path returned early before spawn processing,
    silently dropping any child items a blocking report carried — input the system
    accepted must land somewhere durable."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature", risk="low")
    _advance(
        d,
        item,
        "blocked",
        human_required=True,
        human_reason="need access",
        spawn=[{"title": "Side issue found while triaging", "body": "details"}],
    )
    assert item.state == "blocked"
    children = [i for i in d.store.list_items() if i.parent == item.id]
    assert [c.title for c in children] == ["Side issue found while triaging"]


def test_gate_records_the_decider_identity(factory_root: Path):
    """Every gate decision carries a signature (by) into both the item history and
    the metrics ledger, so who approved what is attributable for later analysis."""
    d = Dispatcher(factory_root)
    item = d.new_item("x", risk="low")
    _advance(d, item, "needs_spec")
    _advance(d, item, "ready_for_review")
    d.gate(item, GateDecision(gate="spec_review", decision="approved", by="alice"))
    gate_events = [e for e in d.metrics.events() if e["kind"] == "gate"]
    assert gate_events[-1]["by"] == "alice"
    assert [e for e in item.history if e.kind == "gate"][-1].actor == "human:alice"


def test_needs_revision_records_intervention_and_loops_back(factory_root: Path):
    """Sending a spec back must (a) route to the spec station and (b) capture an
    intervention record — the raw material the retro station learns from."""
    d = Dispatcher(factory_root)
    item = d.new_item("Vague feature", risk="medium")
    _advance(d, item, "needs_spec")
    _advance(d, item, "ready_for_review")
    d.gate(
        item,
        GateDecision(
            gate="spec_review",
            decision="needs_revision",
            notes="missing rate-limit on the public endpoint",
            category="missing-edge-case",
        ),
    )
    assert item.state == "spec"
    assert len(d.interventions.list()) == 1


def test_station_report_spawns_child_at_triage(factory_root: Path):
    """A station report can spawn follow-up work: the child enters fresh at triage
    with a parent link back to its origin. This is the generic 'loop continues'
    mechanism the deferred monitor and triage's decomposition path ride on; we
    exercise it directly from a station here."""
    d = Dispatcher(factory_root)
    item = d.new_item("Parent feature", risk="low")
    item.state = "verify"
    d.store.save(item)
    d.advance(
        item,
        StationReport(
            station="verify",
            verdict="verified",
            spawn=[{"title": "Follow-up: add request metrics", "body": "spotted during verify"}],
        ),
    )
    assert item.state == "ship_review"
    ids = d.store.list_ids()
    assert len(ids) == 2
    child = next(d.store.load(i) for i in ids if i != item.id)
    assert child.parent == item.id
    assert child.state == "triage"


def test_advance_labels_are_additive_and_deduped(factory_root: Path):
    """A station classifies via labels the gate policies match on; the merge must be
    append-only (never wipe intake or earlier-station labels) and dedup, so a policy
    keyed on `labels_any` has a durable channel to be fed. Regression: triage's skill
    told it to 'add labels' when advance had no label channel at all."""
    d = Dispatcher(factory_root)
    item = d.new_item("Read-only endpoint", risk="low", labels=["intake"])
    _advance(d, item, "needs_spec", labels=["read-only", "intake"])
    assert item.labels == ["intake", "read-only"]  # existing kept, new added, no duplicate


def test_park_is_terminal_but_revivable(factory_root: Path):
    """Parking an item must not lose it: it lands in a terminal-but-revivable
    state, not a dead end."""
    d = Dispatcher(factory_root)
    item = d.new_item("Someday idea")
    d.advance(item, StationReport(station="triage", verdict="park"))
    assert item.state == "parked"
    assert d.line.is_terminal("parked")
    assert d.line.states["parked"].get("revivable") is True


def test_every_park_path_records_where_it_came_from(factory_root: Path):
    """All three routes into parked (station verdict, human gate, auto-gate
    policy) must record the pre-park state — otherwise revive --resume has
    nothing to resume to, depending on how the item happened to be shelved."""
    d = Dispatcher(factory_root)
    a = d.new_item("via station")
    d.advance(a, StationReport(station="triage", verdict="park"))
    assert a.metadata["parked_from"] == "triage"
    b = d.new_item("via gate")
    _advance(d, b, "needs_spec")
    _advance(d, b, "ready_for_review")
    d.gate(b, GateDecision(gate="spec_review", decision="park", notes="not now"))
    assert b.metadata["parked_from"] == "spec_review"
    c = d.new_item("via policy")
    _advance(d, c, "needs_spec")
    _advance(d, c, "ready_for_review")
    d.apply_auto_gate(c, "spec_review", {"id": "r1", "decision": "park"})
    assert c.metadata["parked_from"] == "spec_review"


def test_revive_defaults_to_the_top_of_the_line(factory_root: Path):
    """Reviving without --resume must follow the line's `revive` route (triage) —
    the safe default while the codebase may have moved — and log the move."""
    d = Dispatcher(factory_root)
    item = d.new_item("shelved")
    d.advance(item, StationReport(station="triage", verdict="park"))
    assert d.revive(item, by="alice") == "triage"
    ev = [e for e in item.history if e.kind == "revive"][-1]
    assert (ev.actor, ev.to_state) == ("alice", "triage")
    assert [e for e in d.metrics.events() if e["kind"] == "revive"][-1]["resumed"] is False


def test_revive_resume_reenters_at_the_pre_park_state(factory_root: Path):
    """--resume is the whole point of recording parked_from: an item shelved at
    ship_review must come back to ship_review, not re-run the entire line."""
    d = Dispatcher(factory_root)
    item = d.new_item("shelved late")
    item.state = "ship_review"
    d.store.save(item)
    d.gate(item, GateDecision(gate="ship_review", decision="park", notes="freeze week"))
    assert item.state == "parked"
    assert d.revive(item, by="alice", resume=True) == "ship_review"
    assert d.store.load(item.id).state == "ship_review"


def test_revive_resume_fails_loudly_without_a_recorded_state(factory_root: Path):
    """An item parked before parked_from existed (or whose recorded state left the
    line) must not silently fall back — the human asked to resume; tell them why
    that can't happen and leave the item parked."""
    d = Dispatcher(factory_root)
    item = d.new_item("old park")
    d.advance(item, StationReport(station="triage", verdict="park"))
    del item.metadata["parked_from"]
    d.store.save(item)
    with pytest.raises(ValueError, match="no recorded pre-park state"):
        d.revive(item, by="alice", resume=True)
    assert d.store.load(item.id).state == "parked"
    item.metadata["parked_from"] = "a_state_that_left_the_line"
    with pytest.raises(ValueError, match="no longer on the line"):
        d.revive(item, by="alice", resume=True)


def test_revive_rejects_non_revivable_states(factory_root: Path):
    """`done` is final and stations aren't shelved — revive must only work from a
    revivable terminal, never as a generic state mover (that's `correct`)."""
    d = Dispatcher(factory_root)
    item = d.new_item("x")
    with pytest.raises(ValueError, match="not a revivable"):
        d.revive(item, by="alice")
    item.state = "done"
    d.store.save(item)
    with pytest.raises(ValueError, match="not a revivable"):
        d.revive(item, by="alice")


def test_station_confidence_reaches_the_metrics_ledger(factory_root: Path):
    """Regression: --confidence was collected by the CLI but never persisted —
    the report object was discarded after routing. It must land in the station's
    metrics event, since that history is what a future confidence-weighted gate
    policy would mine."""
    d = Dispatcher(factory_root)
    item = d.new_item("x", risk="low")
    _advance(d, item, "needs_spec", confidence=0.85)
    ev = [e for e in d.metrics.events() if e["kind"] == "station"][-1]
    assert ev["confidence"] == 0.85


def test_station_notes_land_in_item_history(factory_root: Path):
    """Regression: StationReport.notes ('anything the next station should know')
    was write-only — skills instructed stations to pass it, then it evaporated.
    It must persist as a note event in the item's history."""
    d = Dispatcher(factory_root)
    item = d.new_item("x", risk="low")
    _advance(d, item, "needs_spec", notes="repro is flaky on CI only")
    notes = [e for e in item.history if e.kind == "note"]
    assert notes and notes[-1].note == "repro is flaky on CI only"
    assert notes[-1].actor == "triage"


def test_escalation_notes_and_confidence_survive_the_escape_hatch(factory_root: Path):
    """The blocked path builds its own event and metrics emit, so it could silently
    diverge from the normal path — notes and confidence must persist there too."""
    d = Dispatcher(factory_root)
    item = d.new_item("x", risk="low")
    _advance(
        d, item, "blocked", human_required=True, confidence=0.3, notes="need a prod secret"
    )
    assert item.state == "blocked"
    assert [e.note for e in item.history if e.kind == "note"] == ["need a prod secret"]
    assert [e for e in d.metrics.events() if e["kind"] == "station"][-1]["confidence"] == 0.3


def test_is_steer_is_the_single_definition_of_an_intervention():
    """The 'did the human steer?' predicate lives on GateDecision so the dispatcher
    (records the intervention) and the CLI (nudges for the why) can never drift:
    steering decisions steer on their own; --changed marks an edited approval;
    a clean approval is not a steer."""
    assert GateDecision(gate="g", decision="needs_revision").is_steer
    assert GateDecision(gate="g", decision="park").is_steer
    assert GateDecision(gate="g", decision="approved", changed=True).is_steer
    assert not GateDecision(gate="g", decision="approved").is_steer


def test_correct_moves_the_item_and_audits_the_move(factory_root: Path):
    """A mis-targeted advance has a one-command recovery: `correct` sets the state
    and logs a correction event under the operator's identity, in both the item
    history and the metrics ledger — visible, not an undo."""
    d = Dispatcher(factory_root)
    item = d.new_item("x")
    _advance(d, item, "needs_spec")  # oops — meant a different item
    assert d.correct(item, "triage", by="alice", reason="advanced the wrong item") == "triage"
    assert d.store.load(item.id).state == "triage"
    ev = [e for e in item.history if e.kind == "correction"][-1]
    assert (ev.actor, ev.note) == ("alice", "advanced the wrong item")
    assert [e for e in d.metrics.events() if e["kind"] == "correction"][-1]["by"] == "alice"


def test_correct_does_not_count_as_a_steer(factory_root: Path):
    """A correction fixes the operator's slip, not the station's work — it must
    not pollute the North Star's rework counters."""
    d = Dispatcher(factory_root)
    item = d.new_item("x")
    _advance(d, item, "needs_spec")
    d.correct(item, "triage", by="alice", reason="wrong item")
    assert item.steers == 0
    assert item.human_touches == 0


def test_correct_rejects_unknown_state_and_saves_nothing(factory_root: Path):
    """Garbage in must be rejected at the boundary: an unknown target state
    raises before anything persists, so a typo can't strand the item off-line."""
    d = Dispatcher(factory_root)
    item = d.new_item("x")
    with pytest.raises(ValueError, match="unknown state"):
        d.correct(item, "implment", by="alice", reason="typo demo")
    assert d.store.load(item.id).state == "triage"
    assert not [e for e in item.history if e.kind == "correction"]


def test_correct_rejects_a_noop_and_an_empty_reason(factory_root: Path):
    """A same-state correction or a blank reason would pollute the audit trail
    with noise — both are rejected loudly instead of recorded."""
    d = Dispatcher(factory_root)
    item = d.new_item("x")
    with pytest.raises(ValueError, match="already at"):
        d.correct(item, "triage", by="alice", reason="noop")
    with pytest.raises(ValueError, match="--reason"):
        d.correct(item, "spec", by="alice", reason="   ")


def test_cannot_advance_a_station_report_through_a_gate(factory_root: Path):
    """Guardrail: station verdicts and human decisions are different channels.
    Advancing a report while parked at a human gate must raise, not corrupt state."""
    d = Dispatcher(factory_root)
    item = d.new_item("x")
    _advance(d, item, "needs_spec")
    _advance(d, item, "ready_for_review")  # now at the spec_review gate
    with pytest.raises(LineError):
        _advance(d, item, "approved")


def test_next_action_carries_attempt_checking_and_what_sent_it_back(factory_root: Path):
    """The NEXT directive is the driver's whole world: a station run must know
    which attempt it is, whether it's a checking station (isolation rules key on
    this), and what routed the item here — without re-mining history."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature", risk="low")
    _advance(d, item, "automatable")
    a = d.next_action(item)
    assert (a.attempt, a.checking) == (1, False)
    _advance(d, item, "implemented")
    a = d.next_action(item)
    assert a.state == "code_review" and a.checking is True  # declared in line.yml
    _advance(d, item, "changes_requested", summary="tests missing")
    a = d.next_action(item)
    assert a.state == "implement" and a.attempt == 2
    assert "changes_requested" in a.last_return and "tests missing" in a.last_return


def test_station_ran_metadata_lands_on_the_history_event(factory_root: Path):
    """--ran is trace metadata: HOW a run executed (fresh subagent vs inline vs
    resumed) must survive into history, or the observability story has a hole."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature", risk="low")
    _advance(d, item, "automatable", ran="subagent")
    ev = [e for e in item.history if e.kind == "station"][-1]
    assert ev.ran == "subagent"


def _set_cap(factory_root: Path, cap: int) -> None:
    """Rewrite the copied line.yml's attempt cap for a tight-loop test."""
    path = factory_root / "line.yml"
    text = path.read_text()
    assert "max_attempts: 4" in text  # the shipped default this helper overrides
    path.write_text(text.replace("max_attempts: 4", f"max_attempts: {cap}"))


def test_attempt_cap_stops_an_automated_loop_at_blocked(factory_root: Path):
    """The live circuit-breaker: an automated route back into a station that
    already ran its per-epoch budget lands at `blocked` (counted as a steer)
    instead of looping again — churn stops burning tokens without a human."""
    _set_cap(factory_root, 2)
    d = Dispatcher(factory_root)
    item = d.new_item("Loopy change", risk="low")
    _advance(d, item, "automatable")
    _advance(d, item, "implemented")  # implement ran 1×
    _advance(d, item, "changes_requested")  # re-entry ok: 1 < 2
    _advance(d, item, "implemented")  # implement ran 2×
    _advance(d, item, "changes_requested")  # re-entry would be run 3 — capped
    assert item.state == "blocked"
    assert item.steers == 1
    assert any("attempt cap" in (e.note or "") for e in item.history)


def test_a_human_touch_opens_a_fresh_attempt_budget(factory_root: Path):
    """A human decision (here: unblock) starts a new epoch — new guidance
    deserves a fresh loop budget, so the cap must count only automated runs
    since the last human touch, never lifetime attempts."""
    _set_cap(factory_root, 1)
    d = Dispatcher(factory_root)
    item = d.new_item("Tight cap", risk="low")
    _advance(d, item, "automatable")
    _advance(d, item, "implemented")  # implement ran 1× this epoch
    _advance(d, item, "changes_requested")  # re-entry hits cap 1 → blocked
    assert item.state == "blocked"
    d.gate(item, GateDecision(gate="blocked", decision="unblocked", notes="try again"))
    assert item.state == "triage"
    _advance(d, item, "automatable")  # routes into implement again
    assert item.state == "implement"  # fresh epoch: the cap no longer bites
    assert item.attempts["implement"] == 1  # lifetime churn history is untouched


def _to_spec_review(d: Dispatcher, artifacts: list[str] | None = None) -> WorkItem:
    """Drive a fresh item to the spec_review gate, optionally with artifacts."""
    item = d.new_item("Feature")
    _advance(d, item, "needs_spec")
    _advance(d, item, "ready_for_review", artifacts=artifacts or [])
    return item


def test_open_gate_binds_and_a_clean_decision_consumes_the_binding(factory_root: Path):
    """The TOCTOU guard's happy path: open snapshots the reviewed content, an
    unchanged decision passes, and the binding is consumed (not left to haunt
    a later gate)."""
    spec = factory_root / "spec.md"
    spec.write_text("v1")
    d = Dispatcher(factory_root)
    item = _to_spec_review(d, artifacts=["spec.md"])
    d.open_gate(item, by="alice", packet=None)
    assert item.metadata["gate_open"]["gate"] == "spec_review"
    d.gate(item, GateDecision(gate="spec_review", decision="approved", by="alice"))
    assert item.state == "implement"
    assert "gate_open" not in item.metadata


def test_gate_refuses_a_decision_when_reviewed_content_moved(factory_root: Path):
    """What the human approves must be what the human saw: an artifact edited
    between --open and --decision refuses the decision, naming the file."""
    from factory.dispatch import GateDriftError

    spec = factory_root / "spec.md"
    spec.write_text("v1")
    d = Dispatcher(factory_root)
    item = _to_spec_review(d, artifacts=["spec.md"])
    d.open_gate(item, by="alice")
    spec.write_text("v2 — silently changed after review")
    with pytest.raises(GateDriftError, match="spec.md"):
        d.gate(item, GateDecision(gate="spec_review", decision="approved", by="alice"))
    assert item.state == "spec_review"  # nothing routed, nothing saved half-way


def test_accept_drift_records_the_decision_and_logs_what_moved(factory_root: Path):
    """The human can consciously approve past drift — but the drift lands in
    history, so the audit trail never shows a clean approval that wasn't."""
    spec = factory_root / "spec.md"
    spec.write_text("v1")
    d = Dispatcher(factory_root)
    item = _to_spec_review(d, artifacts=["spec.md"])
    d.open_gate(item, by="alice")
    spec.write_text("v2")
    d.gate(
        item,
        GateDecision(gate="spec_review", decision="approved", by="alice"),
        accept_drift=True,
    )
    assert item.state == "implement"
    assert any("despite drift" in (e.note or "") for e in item.history)


def test_history_growth_after_open_counts_as_drift(factory_root: Path):
    """Any event landing on the item after --open means the reviewed state moved
    — the binding covers the item's journey, not just its files."""
    from factory.dispatch import GateDriftError

    d = Dispatcher(factory_root)
    item = _to_spec_review(d)
    d.open_gate(item, by="alice")
    item.log(kind="note", actor="factory", note="something happened mid-review")
    with pytest.raises(GateDriftError, match="history advanced"):
        d.gate(item, GateDecision(gate="spec_review", decision="approved", by="alice"))


def test_an_unbound_gate_decision_still_works(factory_root: Path):
    """Compatibility pin: cloud flows and quick local decisions may skip --open;
    the decision must proceed (just without the drift check), not hard-require
    a binding."""
    d = Dispatcher(factory_root)
    item = _to_spec_review(d)
    d.gate(item, GateDecision(gate="spec_review", decision="approved", by="alice"))
    assert item.state == "implement"


def test_sensitive_text_floors_risk_at_intake(factory_root: Path):
    """The deterministic backstop: an item touching auth/payments/etc. enters at
    high risk unless a human explicitly said otherwise — an under-triaged
    sensitive change must not be able to skip a gate via a low risk rating."""
    d = Dispatcher(factory_root)
    item = d.new_item("Rotate the API token signing secret")
    assert item.risk == "high"
    assert item.metadata["risk_floor"] == "high"
    assert "token" in item.metadata["risk_floor_matches"]
    assert any("risk floored" in (e.note or "") for e in item.history)


def test_explicit_human_risk_bypasses_the_floor_but_is_recorded(factory_root: Path):
    """Human authority wins at creation: an explicit --risk low on floor-matching
    text is respected — but the bypass lands in history so the audit trail says
    why a sensitive-sounding item ran low-risk."""
    d = Dispatcher(factory_root)
    item = d.new_item("Fix typo in the auth README", risk="low")
    assert item.risk == "low"
    assert "risk_floor" not in item.metadata
    assert any("risk floor bypassed" in (e.note or "") for e in item.history)


def test_a_station_cannot_lower_risk_below_the_floor(factory_root: Path):
    """Stations may raise risk, never lower it past the intake floor — a model
    must not be able to quietly de-escalate a sensitive item back below the bar
    that keeps its gates human."""
    d = Dispatcher(factory_root)
    item = d.new_item("Handle password reset flow")
    assert item.risk == "high"
    _advance(d, item, "needs_spec", risk="low")  # triage tries to de-escalate
    assert item.risk == "high"
    assert any("risk floor: kept high" in (e.note or "") for e in item.history)


def test_risk_floor_matches_words_not_substrings(factory_root: Path):
    """`auth` must not fire on `author`, `token` not on `tokenizer` — substring
    matching would tax everyday items with gates they don't deserve."""
    d = Dispatcher(factory_root)
    item = d.new_item("Credit the author in the tokenizer docs")
    assert item.risk == "unknown"
    assert "risk_floor" not in item.metadata


def test_line_rejects_malformed_attempt_caps(factory_root: Path):
    """A cap that isn't a positive integer, or a cap on a non-station, is a
    config typo that must fail at load — not silently run uncapped."""
    from factory.line import Line

    base = (factory_root / "line.yml").read_text()
    (factory_root / "line.yml").write_text(base.replace("max_attempts: 4", "max_attempts: 0"))
    with pytest.raises(LineError):
        Line.load(factory_root / "line.yml")
    (factory_root / "line.yml").write_text(
        base.replace(
            "parked:       {kind: terminal,   revivable: true}",
            "parked:       {kind: terminal,   revivable: true, max_attempts: 3}",
        )
    )
    with pytest.raises(LineError):
        Line.load(factory_root / "line.yml")
