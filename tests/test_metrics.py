from pathlib import Path

from factory.metrics import Metrics


def test_auto_ship_rate_counts_only_zero_touch_ships(factory_root: Path):
    """The North Star number = changes shipped with zero human touches / all
    changes shipped. One clean ship and one human-touched ship must read 50%."""
    m = Metrics(factory_root)
    m.emit(kind="shipped", item="WI-1", human_touches=0, cost=1.0)
    m.emit(kind="shipped", item="WI-2", human_touches=2, cost=3.0)
    s = m.summary()
    assert s["shipped"] == 2
    assert s["auto_shipped"] == 1
    assert s["auto_ship_rate"] == 0.5


def test_interventions_by_gate_ranks_worst_first(factory_root: Path):
    """The ledger must surface which gate stops humans most, so the retro station
    knows where to aim — highest count first."""
    m = Metrics(factory_root)
    m.emit(kind="gate", item="a", gate="spec_review", required_human=True, changed=True)
    m.emit(kind="gate", item="b", gate="ship_review", required_human=True, changed=True)
    m.emit(kind="gate", item="c", gate="ship_review", required_human=True, changed=False)
    ranked = list(m.summary()["interventions_by_gate"].items())
    assert ranked[0][0] == "ship_review"
    assert ranked[0][1] == 2
