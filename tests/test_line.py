from pathlib import Path

import pytest

from factory.line import Line, LineError


def test_happy_path_routes_match_diagram(factory_root: Path):
    """The forward routes are the factory diagram; pin every critical hop so a
    careless edit to line.yml can't silently re-wire the conveyor."""
    line = Line.load(factory_root / "line.yml")
    assert line.route("triage", "needs_spec") == "spec"
    assert line.route("triage", "automatable") == "implement"
    assert line.route("spec", "ready_for_review") == "spec_review"
    assert line.route("spec_review", "approved") == "implement"
    assert line.route("implement", "implemented") == "code_review"
    assert line.route("code_review", "pass") == "verify"
    assert line.route("verify", "verified") == "ship_review"
    assert line.route("ship_review", "approved") == "ci_cd"
    assert line.route("ci_cd", "passed") == "ship"
    assert line.route("ship", "shipped") == "monitor"


def test_loop_backs_send_work_backward(factory_root: Path):
    """Steering verdicts must route backward, not forward — that backward motion
    is exactly what the learning loop later tries to eliminate."""
    line = Line.load(factory_root / "line.yml")
    assert line.route("spec_review", "needs_revision") == "spec"
    assert line.route("code_review", "changes_requested") == "implement"
    assert line.route("ship_review", "not_ready") == "code_review"


def test_every_human_gate_can_park(factory_root: Path):
    """A human at any gate must be able to shelve an item, not just steer or
    approve — otherwise the only way to halt the line is to walk away and leave
    it lingering silently. `park` is the recorded, revivable 'stop the engine'."""
    line = Line.load(factory_root / "line.yml")
    for gate in ("spec_review", "ship_review", "needs_human", "blocked"):
        assert line.route(gate, "park") == "parked"


def test_unknown_verdict_raises(factory_root: Path):
    """An unroutable verdict must fail loudly rather than silently stall an item
    in limbo with no next state."""
    line = Line.load(factory_root / "line.yml")
    with pytest.raises(LineError):
        line.route("triage", "ship_it_yolo")


def test_state_classification(factory_root: Path):
    """Gates, stations, terminals, and external stations must be distinguishable,
    since the dispatcher branches on exactly these kinds."""
    line = Line.load(factory_root / "line.yml")
    assert line.is_gate("spec_review")
    assert line.is_station("implement")
    assert line.is_terminal("done")
    assert line.is_external("ci_cd")
    assert not line.is_external("implement")
