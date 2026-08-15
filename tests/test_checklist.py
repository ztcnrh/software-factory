"""The invariant checklist: the shared grading surface, and the guard that keeps
`verified` honest."""

from pathlib import Path

import pytest

from factory.checklist import Checklist, ChecklistError
from factory.dispatch import Dispatcher
from factory.model import GateDecision, StationReport, WorkItem


def _checklist(rows: str) -> str:
    return (
        "# Invariant checklist — WI-0001\n\n"
        "| # | Invariant | Implemented | Holds |\n| - | - | - | - |\n\n"
        "<!-- machine-readable: the factory engine parses this block -->\n"
        f"```yaml\nitem: WI-0001\nrows:\n{rows}```\n"
    )


ROW_DONE = (
    '  - n: 1\n    invariant: "Over the limit returns 429"\n'
    "    implemented: yes\n    holds: verified\n"
)
ROW_OPEN = '  - n: 2\n    invariant: "The limit is per-key"\n    implemented: yes\n    holds: ""\n'
ROW_BLOCKED = (
    '  - n: 2\n    invariant: "The limit is per-key"\n    implemented: yes\n'
    '    holds: blocked\n    note: "needs a second API key"\n'
)


def _write(root: Path, item: WorkItem, text: str) -> str:
    rel = f"specs/{item.id}-x/CHECKLIST.md"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return rel


def _at_verify(d: Dispatcher, checklist: str | None) -> tuple[WorkItem, list[str]]:
    """An item walked to the verify station, optionally carrying a checklist."""
    item = d.new_item("Rate limiting")
    arts = []
    if checklist is not None:
        arts = [_write(d.root, item, checklist)]
    d.advance(item, StationReport(station="triage", verdict="needs_spec"))
    d.advance(item, StationReport(station="spec", verdict="ready_for_review", artifacts=arts))
    d.gate(item, GateDecision(gate="spec_review", decision="approved", by="t"))
    d.advance(item, StationReport(station="implement", verdict="implemented"))
    d.advance(item, StationReport(station="code_review", verdict="pass"))
    return item, arts


def test_verified_is_refused_while_any_invariant_is_undisposed(factory_root: Path):
    """`verified` has to mean the whole spec was accounted for, or the word buys the
    ship gate nothing. A blank row blocks the verdict and the refusal names it."""
    d = Dispatcher(factory_root)
    item, _ = _at_verify(d, _checklist(ROW_DONE + ROW_OPEN))
    with pytest.raises(ChecklistError, match="2 \\(The limit is per-key\\)"):
        d.advance(item, StationReport(station="verify", verdict="verified"))
    assert d.store.load(item.id).state == "verify"  # nothing routed


def test_a_categorized_row_is_disposed_and_lets_verified_through(factory_root: Path):
    """The categories are what keep the guard from being bureaucracy: an honest
    "couldn't reach it" is a one-word answer, and only silence is blocked."""
    d = Dispatcher(factory_root)
    item, _ = _at_verify(d, _checklist(ROW_DONE + ROW_BLOCKED))
    assert d.advance(item, StationReport(station="verify", verdict="verified")) == "ship_review"


def test_the_guard_only_binds_a_registered_checklist(factory_root: Path):
    """Registration is what makes an artifact load-bearing — so an item from before
    checklists existed still advances, and a stray file on disk guards nothing."""
    d = Dispatcher(factory_root)
    item, _ = _at_verify(d, None)
    _write(d.root, item, _checklist(ROW_OPEN))  # on disk, never registered
    assert d.advance(item, StationReport(station="verify", verdict="verified")) == "ship_review"


def test_a_checklist_registered_by_the_same_report_still_guards(factory_root: Path):
    """Verify registers the checklist and disposes its rows in one call; the guard
    has to see the artifact arriving with the report, or it never fires at all."""
    d = Dispatcher(factory_root)
    item, _ = _at_verify(d, None)
    rel = _write(d.root, item, _checklist(ROW_OPEN))
    with pytest.raises(ChecklistError):
        d.advance(item, StationReport(station="verify", verdict="verified", artifacts=[rel]))


def test_failed_is_never_blocked_by_an_open_row(factory_root: Path):
    """A station reporting the change is broken must always be able to say so —
    the guard exists to stop overclaiming, never to trap a failure report."""
    d = Dispatcher(factory_root)
    item, _ = _at_verify(d, _checklist(ROW_DONE + ROW_OPEN))
    assert d.advance(item, StationReport(station="verify", verdict="failed")) == "ship_review"


def test_the_escape_hatch_is_never_blocked_by_an_open_row(factory_root: Path):
    """"I couldn't verify at all" is exactly the case with undisposed rows; the
    guard must not stand between a station and the blocked gate."""
    d = Dispatcher(factory_root)
    item, _ = _at_verify(d, _checklist(ROW_OPEN))
    d.advance(
        item,
        StationReport(
            station="verify", verdict="verified", human_required=True, human_reason="no staging"
        ),
    )
    assert item.state == "blocked"


def test_an_unreadable_checklist_fails_loudly_rather_than_stopping_guarding(factory_root: Path):
    """A checklist the engine can't parse must raise, not silently wave the verdict
    through — a guard that fails open is worse than none. `pass` reads it first."""
    d = Dispatcher(factory_root)
    item = d.new_item("Rate limiting")
    arts = [_write(d.root, item, "# Checklist\n\nno machine block here\n")]
    d.advance(item, StationReport(station="triage", verdict="needs_spec"))
    d.advance(item, StationReport(station="spec", verdict="ready_for_review", artifacts=arts))
    d.gate(item, GateDecision(gate="spec_review", decision="approved", by="t"))
    d.advance(item, StationReport(station="implement", verdict="implemented"))
    with pytest.raises(ChecklistError, match="no machine-readable block"):
        d.advance(item, StationReport(station="code_review", verdict="pass"))
    assert d.store.load(item.id).state == "code_review"  # nothing routed


def test_the_machine_block_is_read_past_fences_in_the_prose(factory_root: Path):
    """Rows quote invariants and evidence, and evidence contains code fences. The
    marker anchors the parse so an earlier fence can't be mistaken for the block."""
    text = (
        "# Checklist\n\n```yaml\nrows:\n  - n: 99\n    holds: verified\n```\n\n"
        "<!-- machine-readable: the factory engine parses this block -->\n"
        "```yaml\nrows:\n  - n: 1\n    holds: blocked\n```\n"
    )
    c = Checklist.parse(text)
    assert [r["n"] for r in c.rows] == [1]


def _at_code_review(d: Dispatcher, checklist: str) -> WorkItem:
    """An item walked to the code-review station, carrying a checklist."""
    item = d.new_item("Rate limiting")
    arts = [_write(d.root, item, checklist)]
    d.advance(item, StationReport(station="triage", verdict="needs_spec"))
    d.advance(item, StationReport(station="spec", verdict="ready_for_review", artifacts=arts))
    d.gate(item, GateDecision(gate="spec_review", decision="approved", by="t"))
    d.advance(item, StationReport(station="implement", verdict="implemented"))
    return item


ROW_UNGRADED = (
    '  - n: 2\n    invariant: "The limit is per-key"\n    implemented: ""\n    holds: ""\n'
)
ROW_MISSED = (
    '  - n: 2\n    invariant: "The limit is per-key"\n    implemented: no\n    holds: ""\n'
)


def test_pass_is_refused_while_any_invariant_is_ungraded(factory_root: Path):
    """Code review's column used to be advisory: `pass` never read the checklist, so a
    run could grade nothing and route on. Both checkers now owe an answer per row."""
    d = Dispatcher(factory_root)
    item = _at_code_review(d, _checklist(ROW_DONE + ROW_UNGRADED))
    with pytest.raises(ChecklistError, match="2 \\(The limit is per-key\\)"):
        d.advance(item, StationReport(station="code_review", verdict="pass"))
    assert d.store.load(item.id).state == "code_review"  # nothing routed


def test_an_explicit_no_is_an_answer_and_lets_pass_through(factory_root: Path):
    """`no` has to be sayable, or the guard forces a reviewer to either lie with `yes`
    or stall. Only silence is blocked — an invariant the diff misses is a finding."""
    d = Dispatcher(factory_root)
    item = _at_code_review(d, _checklist(ROW_DONE + ROW_MISSED))
    assert d.advance(item, StationReport(station="code_review", verdict="pass")) == "verify"


def test_changes_requested_does_not_demand_a_complete_column(factory_root: Path):
    """A send-back is already routing the item back for rework; demanding a full column
    there would tax the loop the guard exists to keep honest, not shorten it."""
    d = Dispatcher(factory_root)
    item = _at_code_review(d, _checklist(ROW_DONE + ROW_UNGRADED))
    assert (
        d.advance(item, StationReport(station="code_review", verdict="changes_requested"))
        == "implement"
    )


def test_the_headline_names_invariants_the_diff_misses(factory_root: Path):
    """A row code review marked `no` is a gap the ship gate is being asked to accept, and
    it reads differently from one nobody graded — the headline has to distinguish them."""
    c = Checklist.parse(_checklist(ROW_DONE + ROW_MISSED))
    assert c.unimplemented() and not c.ungraded()
    assert "1 not implemented (2)" in c.headline()


def test_only_yes_and_no_grade_a_row(factory_root: Path):
    """`yes`/`no` are the only two the skill teaches, so a typo and a once-accepted
    synonym both read as ungraded — a third spelling is drift to surface, not absorb."""
    c = Checklist.parse(
        _checklist(
            '  - n: 1\n    implemented: probably\n'
            '  - n: 2\n    implemented: done\n'
            '  - n: 3\n    implemented: "✅"\n'
        )
    )
    assert len(c.ungraded()) == 3
    assert not c.unimplemented()  # unanswered is not the same as answered "no"


def test_a_bare_yes_grades_the_same_as_a_quoted_one(factory_root: Path):
    """YAML 1.1 resolves an unquoted `yes`/`no` to a bool before the engine sees it.
    Without the bool branch, `implemented: yes` — the obvious form — reads as ungraded."""
    bare = _checklist('  - n: 1\n    implemented: yes\n  - n: 2\n    implemented: no\n')
    quoted = _checklist('  - n: 1\n    implemented: "yes"\n  - n: 2\n    implemented: "no"\n')
    for text in (bare, quoted):
        c = Checklist.parse(text)
        assert not c.ungraded()
        assert [r["n"] for r in c.unimplemented()] == [2]


def test_an_unknown_disposition_counts_as_undisposed(factory_root: Path):
    """A typo'd category must not pass as settled: only the named vocabulary
    disposes a row, so `holds: probably` blocks the verdict like a blank would."""
    c = Checklist.parse(_checklist('  - n: 1\n    holds: probably\n'))
    assert len(c.undisposed()) == 1


def test_the_headline_counts_what_was_demonstrated_and_what_was_accepted(factory_root: Path):
    """The ship gate's ten seconds: the human must see how much was actually run
    and which invariants they are being asked to take on trust, without reading
    the evidence body."""
    c = Checklist.parse(_checklist(ROW_DONE + ROW_BLOCKED))
    head = c.headline()
    assert "1/2 invariants verified by running" in head
    assert "1 blocked (2)" in head


def test_recheck_routes_back_to_verify_and_counts_as_a_steer(factory_root: Path):
    """When the only gap is a blocker the human has since resolved, the fix is to
    re-verify, not to re-review code that was never wrong. It still counts as a
    steer: the line couldn't finish without a human, and the North Star says so."""
    d = Dispatcher(factory_root)
    item, _ = _at_verify(d, _checklist(ROW_DONE + ROW_BLOCKED))
    d.advance(item, StationReport(station="verify", verdict="verified"))
    before = item.steers
    d.gate(
        item,
        GateDecision(gate="ship_review", decision="recheck", by="t", notes="second key issued"),
    )
    assert item.state == "verify"
    assert item.steers == before + 1
