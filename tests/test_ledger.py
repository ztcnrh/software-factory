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
    led.update(e["id"], status="applied", outcome="gate cleared 4 items untouched")
    text = led.view.read_text()
    assert "RP-0001" in text
    assert "applied" in text
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


def _intervention_file(root, ts_name: str, category: str) -> None:
    d = root / ".factory" / "interventions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"WI-0001-spec_review-{ts_name}.md").write_text(
        "# Intervention — WI-0001 @ spec_review\n\n---\n"
        f'```yaml\nitem: WI-0001\ngate: spec_review\ncategory: "{category}"\n```\n'
    )


def test_recurrence_check_flags_an_applied_row_whose_category_came_back(tmp_path):
    """The falsifiability join: an applied proposal claims its intervention
    category stops recurring — a later matching intervention must be flagged
    mechanically, not left to a future retro's memory."""
    from factory.retro import briefing

    led = Ledger(tmp_path)
    row = _add(led, category="missing-edge-case")
    led.update(row["id"], status="applied")
    # An intervention BEFORE the apply date is the evidence the proposal answered,
    # not a recurrence — the check must scope to interventions since.
    _intervention_file(tmp_path, "1999-01-01T00-00-00Z", "missing-edge-case")
    assert "Recurrence check" not in briefing(tmp_path)
    _intervention_file(tmp_path, "2999-01-01T00-00-00Z", "missing-edge-case")
    text = briefing(tmp_path)
    assert "Recurrence check" in text
    assert row["id"] in text and "missing-edge-case" in text


def test_recurrence_check_ignores_other_categories_and_unapplied_rows(tmp_path):
    """Only an APPLIED row's own category counts: a proposed row, or a
    different category recurring, must not manufacture a false alarm."""
    from factory.retro import briefing

    led = Ledger(tmp_path)
    _add(led, category="missing-edge-case")  # proposed, never applied
    _intervention_file(tmp_path, "2999-01-01T00-00-00Z", "wrong-scope")
    assert "Recurrence check" not in briefing(tmp_path)


def test_category_lands_on_the_row_and_renders(tmp_path):
    """--category is the recurrence check's key — it must persist through the
    append-only log and show in LEDGER.md, or the join silently dies."""
    led = Ledger(tmp_path)
    e = _add(led, category="missing-edge-case")
    assert e["category"] == "missing-edge-case"
    assert "**Category:** missing-edge-case" in led.render()
