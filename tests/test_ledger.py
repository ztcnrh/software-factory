"""The retro ledger: append-only storage, materialized state, and the rendered view."""

import json

import pytest

from factory.ledger import Ledger, LedgerError


def _add(led: Ledger, title: str = "sharpen spec skill", **kw) -> dict:
    defaults = dict(lever="skill-edit", signal="missing-validation send-backs stop")
    defaults.update(kw)
    return led.add(title=title, **defaults)


def test_add_materializes_a_proposed_row_with_an_id(tmp_path):
    """A recorded proposal must come back as a full row — sequential RP id,
    proposed status, and the signal it will be reconciled against."""
    led = Ledger(tmp_path)
    e = _add(led, files=["a.md"], answers=["WI-0001-spec_review.md"])
    assert e["id"] == "RP-0001"
    assert e["status"] == "proposed"
    assert e["signal"] == "missing-validation send-backs stop"
    assert _add(led, title="second")["id"] == "RP-0002"


def test_add_requires_a_falsifiable_signal(tmp_path):
    """The skill's own bar — 'a proposal you can't falsify isn't ready' — is
    enforced at the boundary: no signal, no ledger row."""
    with pytest.raises(LedgerError, match="--signal"):
        Ledger(tmp_path).add(title="t", lever="skill-edit", signal="   ")


def test_update_mutates_state_but_the_file_stays_append_only(tmp_path):
    """Status is mutable *state*, not a mutable *record*: an update must append a
    new event line (history discipline), while the materialized row reflects it."""
    led = Ledger(tmp_path)
    e = _add(led)
    led.update(e["id"], status="applied", pr="https://pr/7")
    lines = [json.loads(x) for x in led.path.read_text().splitlines()]
    assert [x["op"] for x in lines] == ["add", "update"]
    row = led.entries()[0]
    assert (row["status"], row["pr"]) == ("applied", "https://pr/7")


def test_update_rejects_unknown_ids_statuses_and_noops(tmp_path):
    """Garbage in is rejected at the boundary: a typo'd id, an invented status,
    or an update carrying nothing must all fail loudly, appending no event."""
    led = Ledger(tmp_path)
    e = _add(led)
    with pytest.raises(LedgerError, match="unknown ledger id"):
        led.update("RP-9999", status="applied")
    with pytest.raises(LedgerError, match="unknown status"):
        led.update(e["id"], status="shipped-it")
    with pytest.raises(LedgerError, match="nothing to update"):
        led.update(e["id"])
    assert len(led.path.read_text().splitlines()) == 1


def test_open_entries_is_the_reconciliation_worklist(tmp_path):
    """Open = not closed and no outcome recorded. A rejected row and an
    adjudicated row must drop out; a merely-applied row stays until its signal
    is observed — that's the read-first list the retro reconciles."""
    led = Ledger(tmp_path)
    a = _add(led, title="applied, unadjudicated")
    b = _add(led, title="rejected")
    c = _add(led, title="observed")
    led.update(a["id"], status="applied")
    led.update(b["id"], status="rejected")
    led.update(c["id"], status="applied", outcome="send-backs stopped over 5 items")
    assert [e["title"] for e in led.open_entries()] == ["applied, unadjudicated"]


def test_every_mutation_rerenders_the_human_view(tmp_path):
    """LEDGER.md is a regenerated view of the jsonl — after add and update it
    must exist and reflect current state, or the human audits a stale file."""
    led = Ledger(tmp_path)
    e = _add(led)
    assert led.view.exists()
    led.update(e["id"], status="activated", outcome="gate cleared 4 items untouched")
    text = led.view.read_text()
    assert "RP-0001" in text
    assert "activated" in text
    assert "gate cleared 4 items untouched" in text


def test_malformed_lines_surface_as_warnings_not_silence(tmp_path):
    """A corrupt jsonl line (or an update for an id that never existed) must not
    vanish — entries() skips it but records a warning the briefing can show."""
    led = Ledger(tmp_path)
    _add(led)
    with open(led.path, "a") as f:
        f.write("not json\n")
        orphan = {"op": "update", "ts": "t", "id": "RP-0404", "status": "applied"}
        f.write(json.dumps(orphan) + "\n")
    entries = led.entries()
    assert len(entries) == 1
    assert len(led.warnings) == 2
    assert any("not JSON" in w for w in led.warnings)
    assert any("RP-0404" in w for w in led.warnings)


def test_briefing_opens_with_open_ledger_rows(tmp_path):
    """The retro's read-first reconciliation: open rows (and only open rows)
    must appear in the briefing before the raw records, with their signals."""
    from factory.retro import briefing

    led = Ledger(tmp_path)
    open_row = _add(led, title="watch this one")
    done_row = _add(led, title="already adjudicated")
    led.update(done_row["id"], outcome="observed")
    text = briefing(tmp_path)
    assert "## Reconcile past proposals first" in text
    assert open_row["id"] in text and "watch this one" in text
    assert "already adjudicated" not in text
    assert text.index("Reconcile past proposals") < text.index("## Raw intervention records")


def test_briefing_stays_quiet_with_no_open_rows(tmp_path):
    """No ledger (or nothing open) must not manufacture a reconciliation section —
    the briefing's sections earn their place."""
    from factory.retro import briefing

    assert "Reconcile past proposals" not in briefing(tmp_path)
