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


def test_summary_counts_one_ship_per_item_keeping_the_last(factory_root: Path):
    """A phantom `shipped` from a mis-targeted advance can't be retracted from the
    append-only file — views must count one ship per item, last event wins."""
    m = Metrics(factory_root)
    m.emit(kind="shipped", item="WI-1", human_touches=0, steers=3, cost=1.0)  # phantom
    m.emit(kind="shipped", item="WI-1", human_touches=0, steers=0, cost=1.0)  # the real ship
    s = m.summary()
    assert s["shipped"] == 1
    assert s["one_shot_shipped"] == 1


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


def test_events_are_timestamped_at_emit(factory_root: Path):
    """Every event must carry a ts stamped at the source — timestamps can't be
    backfilled onto an append-only ledger, so emit() is the one place to add them."""
    m = Metrics(factory_root)
    m.emit(kind="created", item="WI-1")
    ev = m.events()[0]
    assert "ts" in ev
    assert ev["ts"].endswith("Z") and "T" in ev["ts"]


def test_caller_supplied_ts_is_preserved(factory_root: Path):
    """A caller that already knows the event's time (e.g. a backfill or replay)
    must win over the stamp — setdefault, not overwrite."""
    m = Metrics(factory_root)
    m.emit(kind="created", item="WI-1", ts="2020-01-01T00:00:00Z")
    assert m.events()[0]["ts"] == "2020-01-01T00:00:00Z"


def test_trend_compares_recent_ships_to_the_prior_window(factory_root: Path):
    """The North Star must be visible *moving*: with 7 ships (first 2 steered,
    last 5 clean) and window 5, recent reads 100% vs prior 0% — the improvement
    the lifetime cumulative rate (5/7) would forever understate."""
    m = Metrics(factory_root)
    for i in range(2):
        m.emit(kind="shipped", item=f"old-{i}", steers=1, cost=1.0)
    for i in range(5):
        m.emit(kind="shipped", item=f"new-{i}", steers=0, cost=1.0)
    t = m.summary(window=5)["trend"]
    assert (t["recent_ships"], t["recent_one_shot_rate"]) == (5, 1.0)
    assert (t["prior_ships"], t["prior_one_shot_rate"]) == (2, 0.0)


def test_trend_has_no_prior_window_until_enough_ships(factory_root: Path):
    """With fewer ships than the window there is nothing to compare against —
    the prior side must read empty/None, never a fabricated 0% rate."""
    m = Metrics(factory_root)
    for i in range(3):
        m.emit(kind="shipped", item=f"s{i}", steers=0, cost=1.0)
    t = m.summary(window=5)["trend"]
    assert t["recent_ships"] == 3
    assert t["prior_ships"] == 0
    assert t["prior_one_shot_rate"] is None


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
