"""The artifact lifecycle: one brief per state, promoted decisions, and the sweep
that tells memory from scratch."""

from pathlib import Path

import pytest

from factory import brief as brief_mod
from factory import sweep as sweep_mod
from factory.cli import main
from factory.dispatch import Dispatcher
from factory.model import GateDecision, StationReport, WorkItem


def _home(root: Path, item_id: str) -> Path:
    return root / ".factory" / "work-items" / item_id


def _scratch(root: Path, item: WorkItem) -> None:
    """The scratch a real run leaves behind: a brief, a scratchpad file, a render."""
    home = _home(root, item.id)
    (home / "runs" / "scratchpad").mkdir(parents=True, exist_ok=True)
    (home / "runs" / "verify-brief.md").write_text("# brief")
    (home / "runs" / "scratchpad" / "partial.md").write_text("halfway through")
    (home / "review-packets").mkdir(parents=True, exist_ok=True)
    (home / "review-packets" / "ship_review-1.md").write_text("# packet")


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


def test_the_latest_review_conversation_wins(factory_root: Path):
    """A retry must start from the newest worklist, not whichever file globs first —
    picking an older round would have it fixing points already addressed."""
    home = _home(factory_root, "WI-0001")
    home.mkdir(parents=True, exist_ok=True)
    (home / "code-review-1.md").write_text("round one")
    (home / "code-review-2.md").write_text("round two")
    assert brief_mod.latest_review(factory_root, "WI-0001").name == "code-review-2.md"


# --- promotion and sweeping -------------------------------------------------


def test_a_decision_promotes_the_render_it_was_bound_to(factory_root: Path):
    """A packet is a render — rebuildable, so not worth keeping — right up until a
    human decides against it. Then it's the record of what they were looking at."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    item.state = "ship_review"
    d.store.save(item)
    home = _home(factory_root, item.id)
    (home / "review-packets").mkdir(parents=True, exist_ok=True)
    rel = f".factory/work-items/{item.id}/review-packets/ship_review-1.md"
    (factory_root / rel).write_text("# what the human read")
    d.bind_gate(item, by="tianchi", packet=rel)
    d.gate(item, GateDecision(gate="ship_review", decision="approved", by="tianchi"))
    promoted = home / "decisions" / "ship_review-1.md"
    assert promoted.read_text() == "# what the human read"
    assert str(promoted.relative_to(factory_root)) in item.metadata["decisions"]


def test_binding_a_packet_resolves_it_against_the_factory_root(factory_root: Path, monkeypatch):
    """Regression: `--bind --packet` checked the path against the process's CWD
    while the engine hashes and promotes it relative to --root, so binding failed
    on a valid path whenever the two differed. Caught driving the real CLI."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    item.state = "ship_review"
    d.store.save(item)
    rel = f".factory/work-items/{item.id}/review-packets/ship_review-1.md"
    (factory_root / rel).parent.mkdir(parents=True, exist_ok=True)
    (factory_root / rel).write_text("# packet")
    monkeypatch.chdir(factory_root.parent)  # drive from anywhere but the root
    assert main(["--root", str(factory_root), "gate", item.id, "--bind", "--packet", rel]) == 0


def test_an_undecided_render_is_swept_and_a_promoted_one_is_kept(factory_root: Path):
    """The rule that makes the whole split work: only what a decision bound to is
    durable, so an abandoned render costs nothing and a real one survives."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    item.state = "ship_review"
    d.store.save(item)
    home = _home(factory_root, item.id)
    (home / "review-packets").mkdir(parents=True, exist_ok=True)
    (home / "review-packets" / "ship_review-1.md").write_text("# superseded, never decided")
    rel = f".factory/work-items/{item.id}/review-packets/ship_review-2.md"
    (factory_root / rel).write_text("# the one they read")
    d.bind_gate(item, by="t", packet=rel)
    d.gate(item, GateDecision(gate="ship_review", decision="park", by="t", notes="later"))
    assert item.state == "parked"  # terminal → swept automatically
    assert not (home / "review-packets").exists()
    assert (home / "decisions" / "ship_review-2.md").read_text() == "# the one they read"


def test_a_binding_from_another_gate_promotes_nothing(factory_root: Path):
    """A leftover binding was already treated as stale for drift; it must be stale
    for promotion too, or the record of "what the human approved at the ship gate"
    would be a render they read at the spec gate."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    item.state = "spec_review"
    d.store.save(item)
    rel = f".factory/work-items/{item.id}/review-packets/spec_review-1.md"
    (factory_root / rel).parent.mkdir(parents=True, exist_ok=True)
    (factory_root / rel).write_text("# the spec packet")
    d.bind_gate(item, by="t", packet=rel)
    item.state = "ship_review"  # the binding is now from a gate we've moved past
    d.gate(item, GateDecision(gate="ship_review", decision="approved", by="t"))
    assert not (_home(factory_root, item.id) / "decisions").exists()
    assert "decisions" not in item.metadata


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
    assert len(removed) == 3 and all(line.startswith("removed: ") for line in removed)
    assert sweep_mod.run(factory_root, item) == []


def test_the_sweep_dry_run_removes_nothing(factory_root: Path):
    """The plan and the act come from one code path, so what --dry-run prints is
    exactly what a real run would take."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    _scratch(factory_root, item)
    lines = sweep_mod.run(factory_root, item, dry_run=True)
    assert len(lines) == 3 and all(line.startswith("would remove: ") for line in lines)
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
