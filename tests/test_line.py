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
    assert line.route("ship_review", "approved") == "deploy"
    assert line.route("deploy", "succeeded") == "done"


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


def test_deploy_is_the_ship_point_and_fails_back_to_review(factory_root: Path):
    """The collapsed external tail: a green deploy ships (and is the declarative
    metric anchor via `ships_on`); a failed deploy re-enters the code loop instead
    of dead-ending. Guards against the tail silently losing its ship semantics."""
    line = Line.load(factory_root / "line.yml")
    assert line.route("deploy", "failed") == "code_review"
    assert line.ships_on("deploy") == "succeeded"
    assert line.ships_on("verify") is None  # only the deploy state carries the marker


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
    assert line.is_external("deploy")
    assert not line.is_external("implement")
