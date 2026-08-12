"""The label log: labels are correctable, audited, and safe from silent erasure.

Labels are gate-policy inputs (`labels_any` / `labels_all`), so a wrong label is a
live input to auto-approval — and *how* a label got onto an item decides who may
take it off.
"""

import json
from pathlib import Path

import pytest

from factory.classifiers import Classifiers
from factory.dispatch import Dispatcher, LabelError
from factory.model import LabelEvent, StationReport, WorkItem
from factory.store import Store


def test_a_persisted_item_round_trips_its_label_log(factory_root: Path):
    """`labels` is derived, so it must never reach disk — a stored copy is exactly
    the drift this design exists to prevent, and it would decide gate policy."""
    store = Store(factory_root)
    store.ensure()
    item = WorkItem(id="WI-0001", title="Session state leaks between users")
    item.add_label("bug", by="triage")
    item.add_label("security", by="spec")
    store.save(item)

    on_disk = json.loads((store.dir / "WI-0001.json").read_text())
    assert "labels" not in on_disk
    assert [e["name"] for e in on_disk["label_log"]] == ["bug", "security"]
    assert store.load("WI-0001").labels == ["bug", "security"]


def test_an_item_with_no_label_log_loads_as_unlabelled(factory_root: Path):
    """A hand-written or minimal item record must load, not raise — the log is
    optional state, and an absent one means "no labels", not a broken item."""
    item = WorkItem.from_dict({"id": "WI-0002", "title": "no labels here"})
    assert item.labels == []
    assert item.label_log == []


# --- the log itself ---------------------------------------------------------


def _advance(d: Dispatcher, item: WorkItem, verdict: str, **kw) -> str:
    return d.advance(item, StationReport(station=item.state, verdict=verdict, **kw))


def test_a_retracted_label_disappears_from_labels_but_not_from_the_log(factory_root: Path):
    """Correction without erasure: `labels` reflects only what is currently applied,
    while the log keeps every application and retraction — append-only, so a
    correction is a new entry rather than an edit of the one it corrects."""
    d = Dispatcher(factory_root)
    item = d.new_item("Session leak", labels=["bug"], labels_by="human:tianchi")
    _advance(d, item, "needs_spec", labels=["docs"])
    d.unlabel(item, "docs", by="human:tianchi", reason="mis-classified")
    assert item.labels == ["bug"]
    assert [(e.name, e.action) for e in item.label_log] == [
        ("bug", "add"),
        ("docs", "add"),
        ("docs", "retract"),
    ]


def test_re_adding_a_retracted_label_makes_it_active_again(factory_root: Path):
    """add → retract → add must end active, with all three entries retained: the
    log is the audit trail, and a re-classification is as legitimate as the first."""
    d = Dispatcher(factory_root)
    item = d.new_item("Item", labels=["bug"], labels_by="human:t")
    d.unlabel(item, "bug", by="human:t", reason="wrong")
    _advance(d, item, "needs_spec", labels=["bug"])
    assert item.labels == ["bug"]
    assert len(item.label_log) == 3
    assert item.provenance("bug") == "triage"  # the most recent add owns it now


def test_re_applying_an_active_label_records_nothing_new(factory_root: Path):
    """Idempotence: a station re-asserting a label the item already carries must
    succeed and add no entry, or every re-run would pad the log with noise."""
    d = Dispatcher(factory_root)
    item = d.new_item("Item", labels=["bug"], labels_by="human:t")
    _advance(d, item, "needs_spec", labels=["bug", "bug"])
    assert item.labels == ["bug"]
    assert len(item.label_log) == 1


def test_a_station_cannot_retract_a_human_applied_label(factory_root: Path):
    """The provenance rule: a station may correct another station's classification
    but never overrule the human's — and the refusal must take the whole advance
    with it, so the verdict cannot half-apply."""
    d = Dispatcher(factory_root)
    item = d.new_item("Item", labels=["bug"], labels_by="human:tianchi")
    before = (d.store.dir / f"{item.id}.json").read_bytes()
    with pytest.raises(LabelError, match="human:tianchi"):
        _advance(d, item, "needs_spec", unlabels=[("bug", "I disagree")])
    assert (d.store.dir / f"{item.id}.json").read_bytes() == before
    assert d.store.load(item.id).state == "triage"  # the verdict did not route either


def test_a_station_can_retract_a_label_another_station_applied(factory_root: Path):
    """The case that started this work: the spec station reproduced the bug, dis-
    proved triage's classification, and must be able to take that label back off."""
    d = Dispatcher(factory_root)
    item = d.new_item("Session leak")
    _advance(d, item, "needs_spec", labels=["data-isolation"])
    _advance(
        d,
        item,
        "ready_for_review",
        labels=["observability"],
        unlabels=[("data-isolation", "reproduced it: state is shared, not leaked across users")],
    )
    assert item.labels == ["observability"]
    assert item.label_log[-1].reason.startswith("reproduced it")


def test_retracting_an_absent_label_is_refused_at_the_boundary(factory_root: Path):
    """A retraction naming a label the item never carried is a caller mistake, not
    a no-op — silently succeeding would hide a typo'd label name forever."""
    d = Dispatcher(factory_root)
    item = d.new_item("Item", labels=["bug"], labels_by="human:t")
    with pytest.raises(LabelError, match="does not carry"):
        _advance(d, item, "needs_spec", unlabels=[("bugg", "typo")])
    with pytest.raises(LabelError, match="does not carry"):
        d.unlabel(item, "bugg", by="human:t", reason="typo")


def test_a_retraction_requires_a_reason(factory_root: Path):
    """A retraction with no reason teaches nobody why the classification was wrong —
    and the log's whole value is that the correction carries its rationale."""
    d = Dispatcher(factory_root)
    item = d.new_item("Item", labels=["bug"], labels_by="human:t")
    with pytest.raises(LabelError, match="reason"):
        d.unlabel(item, "bug", by="human:t", reason="  ")


def test_a_human_can_retract_a_label_of_any_provenance(factory_root: Path):
    """The human is the backstop: whatever applied a label — a station, another
    human, or an item that predates the log — they can take it off at the gate."""
    d = Dispatcher(factory_root)
    item = d.new_item("Item", labels=["bug"], labels_by="human:someone-else")
    _advance(d, item, "needs_spec", labels=["docs"])
    for name in ("bug", "docs"):
        d.unlabel(item, name, by="human:tianchi", reason="cleaning up at the gate")
    assert item.labels == []


# --- the vocabulary --------------------------------------------------------


def test_an_unrecognized_label_is_recorded_and_marked_never_dropped(factory_root: Path):
    """Never lose input: a label outside the vocabulary still lands on the item
    (the classification may be right and the vocabulary behind), but it is flagged
    so nobody mistakes near-duplicate drift for a real term."""
    d = Dispatcher(factory_root)
    item = d.new_item("Item", labels=["data-isolation"], labels_by="human:t")
    assert item.labels == ["data-isolation"]
    assert d.classifiers.unrecognized(item.labels) == ["data-isolation"]
    assert d.classifiers.recognized(item.labels) == []


def test_an_unrecognized_label_never_satisfies_a_gate_policy(factory_root: Path):
    """The reason recognition matters: an approved rule keyed on `labels_any` must
    not fire on a label nobody promoted into the vocabulary. Failing closed sends
    the gate back to the human, which is the safe direction."""
    (factory_root / "policies.yml").write_text(
        "version: 1\ndefault: require_human\nrules:\n"
        "  - id: docsy\n    gate: spec_review\n    decision: approved\n"
        "    when: {labels_any: [docs, doc-update]}\n    approved_by: tianchi\n"
    )
    (factory_root / "classifiers.yml").write_text("version: 1\nclassifiers:\n  - docs\n")
    d = Dispatcher(factory_root)
    typo = d.new_item("Item", labels=["doc-update"], labels_by="human:t")
    assert d.policies.auto_decision("spec_review", typo) is None
    real = d.new_item("Item", labels=["docs"], labels_by="human:t")
    assert d.policies.auto_decision("spec_review", real) is not None


def test_the_vocabulary_falls_back_to_the_seed_when_the_file_is_absent(factory_root: Path):
    """An adopter mid-upgrade has no classifiers.yml yet; the seed keeps recognition
    working rather than marking every label on every item as unrecognized."""
    assert not (factory_root / "classifiers.yml").exists()
    c = Classifiers.load(factory_root / "classifiers.yml")
    assert c.is_recognized("bug") and c.is_recognized("docs")
    assert not c.is_recognized("data-isolation")


def test_a_label_event_carries_its_own_timestamp(factory_root: Path):
    """Every entry is dated at the moment it happens; a log without times can't
    reconstruct which classification came first."""
    ev = LabelEvent(name="bug", action="add", by="triage")
    assert ev.at.endswith("Z") and "T" in ev.at
