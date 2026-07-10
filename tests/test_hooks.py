"""The SessionStart board hook, exercised as a real subprocess (it's a
stdlib-only script with no dependency on the factory package)."""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / ".claude" / "hooks" / "factory_board.py"


def _run_hook(cwd: Path) -> str:
    """Run the hook the way Claude Code does: JSON on stdin, context on stdout."""
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0
    return r.stdout


def _context(stdout: str) -> str:
    return json.loads(stdout)["hookSpecificOutput"]["additionalContext"]


def _factory_floor(factory_root: Path) -> Path:
    items_dir = factory_root / ".factory" / "work-items"
    items_dir.mkdir(parents=True)
    return items_dir


def test_idle_factory_still_announces_itself(factory_root: Path):
    """Regression: with no work items in flight the hook used to inject nothing,
    so a cold session (first item ever) had zero factory context unless the human
    typed /factory. An idle factory must still say it exists and point at the
    driver protocol."""
    _factory_floor(factory_root)
    ctx = _context(_run_hook(factory_root))
    assert "idle" in ctx
    assert ".claude/commands/factory.md" in ctx


def test_busy_board_lists_items_and_the_protocol_pointer(factory_root: Path):
    """With items in flight, the board must show them grouped by gate-vs-moving and
    still carry the protocol pointer for sessions started without /factory."""
    items_dir = _factory_floor(factory_root)
    (items_dir / "WI-0001.json").write_text(
        json.dumps({"id": "WI-0001", "state": "spec_review", "title": "Rate limiting"})
    )
    (items_dir / "WI-0002.json").write_text(
        json.dumps({"id": "WI-0002", "state": "implement", "title": "Health endpoint"})
    )
    ctx = _context(_run_hook(factory_root))
    assert "Waiting on you" in ctx and "WI-0001" in ctx
    assert "Moving down the line" in ctx and "WI-0002" in ctx
    assert ".claude/commands/factory.md" in ctx


def test_non_factory_directory_stays_silent(tmp_path: Path):
    """Outside a factory root (no line.yml + .factory), the hook must inject
    nothing — it fails open and never pollutes unrelated sessions."""
    assert _run_hook(tmp_path).strip() == ""
