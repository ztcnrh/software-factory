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
    mechanism a future monitor or issues-watcher uses; no v1 mainline state
    triggers it, so we exercise it directly from a station."""
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


def test_park_is_terminal_but_revivable(factory_root: Path):
    """Parking an item must not lose it: it lands in a terminal-but-revivable
    state, not a dead end."""
    d = Dispatcher(factory_root)
    item = d.new_item("Someday idea")
    d.advance(item, StationReport(station="triage", verdict="park"))
    assert item.state == "parked"
    assert d.line.is_terminal("parked")
    assert d.line.states["parked"].get("revivable") is True


def test_cannot_advance_a_station_report_through_a_gate(factory_root: Path):
    """Guardrail: station verdicts and human decisions are different channels.
    Advancing a report while parked at a human gate must raise, not corrupt state."""
    d = Dispatcher(factory_root)
    item = d.new_item("x")
    _advance(d, item, "needs_spec")
    _advance(d, item, "ready_for_review")  # now at the spec_review gate
    with pytest.raises(LineError):
        _advance(d, item, "approved")
