"""The artifact lifecycle: one brief per state, gate bindings, and the sweep that
tells memory from scratch."""

from pathlib import Path

import pytest

from factory import brief as brief_mod
from factory import sweep as sweep_mod
from factory.cli import main
from factory.dispatch import Dispatcher, GateDriftError
from factory.model import GateDecision, StationReport, WorkItem


def _home(root: Path, item_id: str) -> Path:
    return root / ".factory" / "work-items" / item_id


def _scratch(root: Path, item: WorkItem) -> None:
    """The scratch a real run leaves behind: a brief and a scratchpad file."""
    home = _home(root, item.id)
    (home / "runs" / "scratchpad").mkdir(parents=True, exist_ok=True)
    (home / "runs" / "verify-brief.md").write_text("# brief")
    (home / "runs" / "scratchpad" / "partial.md").write_text("halfway through")


# --- one brief per state ----------------------------------------------------


def test_a_retry_appends_to_the_state_brief_instead_of_minting_a_new_file(
    factory_root: Path, capsys
):
    """A state that ran three times should leave one readable document, not three
    files — and the retry sees what its predecessor was told, which is context an
    attempt-numbered file throws away."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    item.state = "implement"
    d.store.save(item)
    main(["--root", str(factory_root), "brief", item.id])
    capsys.readouterr()
    item = d.store.load(item.id)
    d.advance(item, StationReport(station="implement", verdict="implemented"))
    d.advance(item, StationReport(station="code_review", verdict="changes_requested"))
    main(["--root", str(factory_root), "brief", item.id])
    err = capsys.readouterr().err

    briefs = sorted(p.name for p in (_home(factory_root, item.id) / "runs").glob("*-brief.md"))
    assert briefs == ["implement-brief.md"]
    text = (_home(factory_root, item.id) / "runs" / "implement-brief.md").read_text()
    assert brief_mod.run_marker(1) in text and brief_mod.run_marker(2) in text
    assert "appended (attempt 2)" in err


def test_force_regenerates_only_this_runs_section(factory_root: Path, capsys):
    """Earlier attempts are the trace of what those workers were actually fed —
    --force refreshes the current section without erasing that history."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    item.state = "implement"
    d.store.save(item)
    main(["--root", str(factory_root), "brief", item.id])
    item = d.store.load(item.id)
    d.advance(item, StationReport(station="implement", verdict="implemented"))
    d.advance(item, StationReport(station="code_review", verdict="changes_requested"))
    main(["--root", str(factory_root), "brief", item.id])
    path = _home(factory_root, item.id) / "runs" / "implement-brief.md"
    with open(path, "a") as f:
        f.write("\nDriver note on attempt 2.\n")
    main(["--root", str(factory_root), "brief", item.id, "--force"])
    capsys.readouterr()
    text = path.read_text()
    assert brief_mod.run_marker(1) in text  # attempt 1's section survives
    assert "Driver note on attempt 2." not in text  # this run's section was rebuilt


def test_the_brief_creates_and_names_the_scratchpad(factory_root: Path, capsys):
    """A station can only checkpoint into a place it knows exists and has been
    told about — that's what makes work survive a context that dies mid-run."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    item.state = "implement"
    d.store.save(item)
    main(["--root", str(factory_root), "brief", item.id])
    assert "runs/scratchpad" in capsys.readouterr().out
    assert (_home(factory_root, item.id) / "runs" / "scratchpad").is_dir()


# --- promotion and sweeping -------------------------------------------------


def test_a_binding_covers_both_of_the_items_prs(factory_root: Path):
    """The ship gate reviews the item's PR and the pass's PR together, so a change
    to either after the human reviewed has to be caught — binding only the first
    would let a re-pushed implementation pass slip under an approval."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    item.state = "ship_review"
    item.pr = "#41"
    item.open_change_pass("change/x-1", "#42")
    d.store.save(item)
    d.bind_gate(item, by="tianchi")
    item.open_change_pass("change/x-2", "#43")  # a new pass opened under the review
    with pytest.raises(GateDriftError, match="change pr"):
        d.gate(item, GateDecision(gate="ship_review", decision="approved", by="tianchi"))


def test_a_binding_from_another_gate_is_ignored(factory_root: Path):
    """A leftover binding describes a different review, so it must not drift-check
    this one — otherwise a spec-gate binding could refuse a valid ship decision."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    item.state = "spec_review"
    item.pr = "#41"
    d.store.save(item)
    d.bind_gate(item, by="t")
    item.state = "ship_review"  # the binding is now from a gate we've moved past
    item.pr = "#99"  # would be drift, if the stale binding still counted
    assert d.gate(item, GateDecision(gate="ship_review", decision="approved", by="t")) == "deploy"


def test_the_sweep_keeps_every_registered_artifact(factory_root: Path):
    """Registration is what makes a station's output durable — a screenshot saved
    into the scratchpad and registered must survive, or stations learn to hoard."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    _scratch(factory_root, item)
    keeper = f".factory/work-items/{item.id}/runs/scratchpad/evidence.png"
    (factory_root / keeper).write_text("screenshot bytes")
    item.artifacts.append(keeper)
    removed = sweep_mod.run(factory_root, item)
    assert (factory_root / keeper).exists()
    assert not (_home(factory_root, item.id) / "runs" / "verify-brief.md").exists()
    assert all("evidence.png" not in line for line in removed)


def test_the_sweep_reports_what_it_removed_and_is_idempotent(factory_root: Path):
    """A cleanup nobody can audit is a cleanup nobody trusts; and a second sweep
    must find nothing rather than error on the files the first one took."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    _scratch(factory_root, item)
    removed = sweep_mod.run(factory_root, item)
    assert len(removed) == 2 and all(line.startswith("removed: ") for line in removed)
    assert sweep_mod.run(factory_root, item) == []


def test_the_sweep_dry_run_removes_nothing(factory_root: Path):
    """The plan and the act come from one code path, so what --dry-run prints is
    exactly what a real run would take."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    _scratch(factory_root, item)
    lines = sweep_mod.run(factory_root, item, dry_run=True)
    assert len(lines) == 2 and all(line.startswith("would remove: ") for line in lines)
    assert (_home(factory_root, item.id) / "runs" / "verify-brief.md").exists()


def test_the_sweep_never_leaves_the_items_directory(factory_root: Path):
    """A `..` in a registered path (or a symlink) must not turn a cleanup into a
    delete somewhere else in the repo — the containment check is the whole safety
    argument for running this automatically."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    outside = factory_root / "src" / "precious.py"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("do not delete me")
    home = _home(factory_root, item.id)
    (home / "runs").mkdir(parents=True, exist_ok=True)
    (home / "runs" / "escape.md").symlink_to(outside)
    with pytest.raises(sweep_mod.SweepError, match="outside the item's directory"):
        sweep_mod.run(factory_root, item)
    assert outside.exists()


def test_sweeping_a_live_item_is_refused(factory_root: Path, capsys):
    """An item still on the line is using its scratch: its brief is what the next
    station reads, so reclaiming it early would delete live context."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    _scratch(factory_root, item)
    rc = main(["--root", str(factory_root), "sweep", item.id])
    assert rc == 1
    assert "still in use" in capsys.readouterr().err
    assert (_home(factory_root, item.id) / "runs" / "verify-brief.md").exists()


def test_sweep_all_skips_live_items_and_reclaims_terminal_ones(factory_root: Path, capsys):
    """The batch pass for items that predate the automatic sweep — it has to be
    safe to run against a whole board without reading it first."""
    d = Dispatcher(factory_root)
    live = d.new_item("Still going")
    finished = d.new_item("Shipped")
    for item in (live, finished):
        _scratch(factory_root, item)
    finished.state = "done"
    d.store.save(finished)
    rc = main(["--root", str(factory_root), "sweep", "--all"])
    assert rc == 0
    assert not (_home(factory_root, finished.id) / "runs").exists()
    assert (_home(factory_root, live.id) / "runs" / "verify-brief.md").exists()
    assert "reclaimed scratch from 1 item(s)" in capsys.readouterr().out


def test_sweep_needs_exactly_one_of_id_or_all(factory_root: Path, capsys):
    """Neither form is a safe default: a bare `sweep` could mean the whole board,
    so the caller says which rather than the CLI guessing."""
    assert main(["--root", str(factory_root), "sweep"]) == 1
    assert main(["--root", str(factory_root), "sweep", "WI-0001", "--all"]) == 1
    assert "name one work item" in capsys.readouterr().err
