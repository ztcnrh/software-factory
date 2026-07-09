from pathlib import Path

from factory.metrics import Metrics


def test_one_shot_ship_rate_counts_only_zero_steer_ships(factory_root: Path):
    """The North Star = changes shipped with zero human rework (steers) / all
    changes shipped. A ship that needed a steer must not count, regardless of how
    many times a human was merely present at a gate."""
    m = Metrics(factory_root)
    m.emit(kind="shipped", item="WI-1", human_touches=0, steers=0, cost=1.0)
    m.emit(kind="shipped", item="WI-2", human_touches=3, steers=1, cost=3.0)
    s = m.summary()
    assert s["shipped"] == 2
    assert s["one_shot_shipped"] == 1
    assert s["one_shot_ship_rate"] == 0.5


def test_a_human_present_but_not_steering_still_counts_as_one_shot(factory_root: Path):
    """The whole point of the redesign: a change the human attended at gates but
    never had to rework (steers == 0) IS a one-shot ship. Human presence is
    expected and must not be penalized — only rework is."""
    m = Metrics(factory_root)
    m.emit(kind="shipped", item="WI-1", human_touches=2, steers=0, cost=2.0)
    s = m.summary()
    assert s["one_shot_ship_rate"] == 1.0
    assert s["hands_off_shipped"] == 0  # a human WAS present — just didn't steer


def test_steers_by_stage_ranks_worst_first_and_includes_blocks(factory_root: Path):
    """The retro's to-do list must rank where humans had to step in — both gate
    rework (keyed by gate) and station blocks (keyed by the station that broke),
    highest first — so the learning aims at the real autonomy gap."""
    m = Metrics(factory_root)
    m.emit(kind="gate", item="a", gate="spec_review", required_human=True, changed=True)
    m.emit(kind="gate", item="b", gate="spec_review", required_human=True, changed=True)
    m.emit(kind="gate", item="c", gate="ship_review", required_human=True, changed=True)
    m.emit(kind="station", item="d", station="implement", verdict="blocked")
    s = m.summary()
    ranked = list(s["steers_by_stage"].items())
    assert ranked[0] == ("spec_review", 2)
    assert "implement (blocked)" in s["steers_by_stage"]
    assert s["human_steers"] == 4  # 3 gate reworks + 1 block


def test_clean_approvals_do_not_register_as_steers(factory_root: Path):
    """A gate stop that required the human's presence but no change (changed=False)
    is not rework — it must not inflate human_steers or block a one-shot ship."""
    m = Metrics(factory_root)
    m.emit(kind="gate", item="a", gate="ship_review", required_human=True, changed=False)
    m.emit(kind="shipped", item="a", human_touches=1, steers=0, cost=1.0)
    s = m.summary()
    assert s["human_steers"] == 0
    assert s["one_shot_ship_rate"] == 1.0
    assert s["human_gate_stops"] == 1  # presence is still tracked, just not as rework
