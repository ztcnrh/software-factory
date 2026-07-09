import argparse
import subprocess
from pathlib import Path

from factory.cli import _print_action, _resolve_actor
from factory.dispatch import Action
from factory.line import Line


def _gate_action(gate: str, state: str) -> Action:
    return Action(type="human_gate", item_id="WI-0001", state=state, gate=gate, message="Gate")


def test_blocked_gate_renders_a_distinct_glyph(capsys, factory_root: Path):
    """The blocked gate prints ⛔ (a station hit the human_required escape hatch),
    visually distinct from a routine checkpoint. Guards the gate-name special case
    in _print_action against a future 'collapse back to one icon lookup' regression."""
    _print_action(_gate_action("blocked", "blocked"), Line.load(factory_root / "line.yml"))
    assert "⛔" in capsys.readouterr().out


def test_routine_gate_keeps_the_plain_gate_glyph(capsys, factory_root: Path):
    """A normal human gate (ship_review) keeps ✋ and is never dressed as blocked —
    the ⛔ special case must stay scoped to the blocked gate alone."""
    _print_action(_gate_action("ship_review", "ship_review"), Line.load(factory_root / "line.yml"))
    out = capsys.readouterr().out
    assert "✋" in out
    assert "⛔" not in out


def test_resolve_actor_prefers_explicit_by_then_env(monkeypatch, tmp_path):
    """A gate signature must be a real identity. Explicit --by wins over everything;
    absent that, $FACTORY_USER — so decisions are attributable, never a bare 'human'."""
    monkeypatch.setenv("FACTORY_USER", "env-user")
    assert _resolve_actor(argparse.Namespace(by="alice", root=str(tmp_path))) == "alice"
    assert _resolve_actor(argparse.Namespace(by=None, root=str(tmp_path))) == "env-user"


def test_resolve_actor_falls_back_to_git_identity(monkeypatch, tmp_path):
    """With no --by and no env var, the repo's git identity signs the decision — the
    common local case, so signatures happen with zero extra effort from the human."""
    monkeypatch.delenv("FACTORY_USER", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Repo Owner"], cwd=tmp_path, check=True, capture_output=True
    )
    assert _resolve_actor(argparse.Namespace(by=None, root=str(tmp_path))) == "Repo Owner"
