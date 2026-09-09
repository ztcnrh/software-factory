"""The steer record: a human's gate rework lands structured in the metrics ledger."""

from pathlib import Path

from factory.dispatch import Dispatcher
from factory.model import GateDecision, WorkItem
from factory.retro import briefing
from factory.store import Store


def _gated(factory_root: Path, state: str = "spec_review"):
    d = Dispatcher(factory_root)
    item = d.new_item("test item")
    item.state = state
    d.store.save(item)
    return d, item


def test_a_steer_lands_structured_in_the_metrics_ledger(factory_root: Path):
    """The metrics gate event carries only the steer's structured half — changed
    and the category the recurrence check joins on. The prose why lives once, in
    the gate history event; the shared ts is the join key, so duplicating notes
    into the ledger (or losing the linkage) would both be regressions."""
    d, item = _gated(factory_root)
    d.gate(
        item,
        GateDecision(
            gate="spec_review",
            decision="needs_revision",
            by="tz",
            notes="rate limiting is missing",
            category="missing-edge-case",
        ),
    )
    ev = [e for e in d.metrics.events() if e.get("kind") == "gate"][-1]
    assert ev["changed"] is True
    assert ev["category"] == "missing-edge-case"
    assert "notes" not in ev and "expected" not in ev  # prose stays out of the ledger
    hist = [e for e in d.store.load(item.id).history if e.kind == "gate"][-1]
    assert hist.note == "rate limiting is missing"
    assert ev["ts"] == hist.ts  # the join key the steer log relies on


def test_an_unsteered_approval_still_carries_its_fields_quietly(factory_root: Path):
    """A category on a plain approval must neither vanish nor warn: the event
    records whatever the human said, and 'changed' is what separates steers from
    approvals for every downstream join."""
    d, item = _gated(factory_root)
    d.gate(
        item,
        GateDecision(gate="spec_review", decision="approved", by="tz", category="wrong-scope"),
    )
    ev = [e for e in d.metrics.events() if e.get("kind") == "gate"][-1]
    assert ev["changed"] is False and ev["category"] == "wrong-scope"


def test_briefing_renders_the_steer_log_from_the_ledger(factory_root: Path):
    """The retro runs in fresh context, so the briefing's steer log is its only
    structured view of what humans reworked — item, gate, decision, category must
    surface, the why joined in from the item's gate history via the shared ts,
    plus the pointer to the PR threads that hold the conversation itself."""
    d, item = _gated(factory_root)
    d.gate(
        item,
        GateDecision(
            gate="spec_review",
            decision="needs_revision",
            by="tz",
            notes="spec misses the empty-input case",
            category="missing-edge-case",
        ),
    )
    text = briefing(factory_root)
    assert "## Steer log" in text
    assert item.id in text and "spec_review" in text and "needs_revision" in text
    assert "`missing-edge-case`" in text
    assert "spec misses the empty-input case" in text  # joined from item history
    assert "PR review threads" in text


def test_steer_log_says_so_when_the_item_was_pruned(factory_root: Path):
    """Work-item JSONs get pruned in practice; the ledger event survives. The
    steer log must say the why went with the history rather than render a steer
    that looks like it never had one."""
    d, item = _gated(factory_root)
    d.gate(
        item,
        GateDecision(gate="spec_review", decision="needs_revision", by="tz", notes="w",
                     category="wrong-scope"),
    )
    (factory_root / ".factory" / "work-items" / f"{item.id}.json").unlink()
    text = briefing(factory_root)
    assert "wrong-scope" in text  # the structured half survives the prune
    assert "item pruned" in text


def test_briefing_flags_repeated_station_runs(tmp_path):
    """A station re-running past the threshold records no steer, so the briefing
    must surface it by attempt count — labeled enough to orient a stateless agent,
    which then diagnoses the cause from the item's history."""
    store = Store(tmp_path)
    hot = WorkItem(id="WI-0001", title="churny feature", state="ship_review")
    hot.attempts = {"implement": 4, "code_review": 3, "triage": 1}
    store.save(hot)
    text = briefing(tmp_path)
    assert "## Items with repeated station runs" in text
    assert "WI-0001" in text and "`implement`×4" in text and "`code_review`×3" in text
    assert "Item current state: ship_review" in text  # labeled, not a bare dump
    assert "`triage`×1" not in text  # below threshold — noise stays out


def test_briefing_omits_churn_section_when_all_quiet(tmp_path):
    """Items that moved through cleanly must not manufacture a churn section —
    an empty warning dilutes the briefing's signal."""
    calm = WorkItem(id="WI-0001", title="clean feature", state="done")
    calm.attempts = {"implement": 1, "code_review": 1}
    Store(tmp_path).save(calm)
    assert "## Items with repeated station runs" not in briefing(tmp_path)
