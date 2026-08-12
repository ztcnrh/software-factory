"""The North Star ledger: a per-item event log plus aggregate views.

Headline metric: the **one-shot ship rate** — the share of shipped changes that
needed no human rework anywhere on the line (no send-back, no correction, no
unblock). The human still owns the ship decision and stays in the loop; this
measures how often the line was good enough that review was a rubber-stamp, not
how often the human was absent. Plus where humans had to step in (so the retro
station knows where to aim) and a cost-per-change proxy. ``summary`` also windows
a recent-vs-prior trend, so "is the factory improving?" has an answer.

Storage shards one file per item (``metrics/events/<item>.jsonl``): single-writer,
so parallel drivers never conflict. The views are set aggregations that don't need
a global write order; the one that does (the trend) sorts on each event's ts.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _now() -> str:
    # Microsecond precision so ts is a faithful sort key when shards are reassembled.
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int(t % 1 * 1_000_000):06d}Z"


class Metrics:
    def __init__(self, root: str | Path):
        self.events_dir = Path(root) / ".factory" / "metrics" / "events"
        self.warnings: list[str] = []  # malformed lines noticed on the last read

    def emit(self, **event: Any) -> None:
        # One shard per item (single-writer, conflict-free); ts stamped here since
        # it can't be backfilled, but a caller-supplied ts wins.
        event.setdefault("ts", _now())
        shard = self.events_dir / f"{event.get('item') or '_misc'}.jsonl"
        shard.parent.mkdir(parents=True, exist_ok=True)
        with open(shard, "a") as f:
            f.write(json.dumps(event) + "\n")

    def _read(self, path: Path) -> list[dict]:
        """Read one shard, tolerating a torn line (e.g. a crash mid-append).
        One bad line must not take down every view forever — it's skipped and
        reported via ``self.warnings``, mirroring the retro ledger's discipline.
        The shard is named in the warning: a line number alone no longer locates it."""
        out = []
        with open(path) as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    self.warnings.append(
                        f"{path.name} line {i}: unreadable (not JSON) — event skipped"
                    )
        return out

    def events(self) -> list[dict]:
        # Reassemble the global log from the shards, ordered by ts — cross-shard
        # write order carries no meaning.
        self.warnings = []
        rows: list[dict] = []
        if self.events_dir.exists():
            for shard in sorted(self.events_dir.glob("*.jsonl")):
                rows += self._read(shard)
        rows.sort(key=lambda e: e.get("ts", ""))
        return rows

    def summary(self, window: int = 5) -> dict:
        events = self.events()
        # One ship per item, last event wins: a mis-targeted advance can fire
        # ships_on for the wrong item, and the append-only file keeps that line.
        raw = [e for e in events if e.get("kind") == "shipped"]
        last = {e.get("item"): i for i, e in enumerate(raw)}
        shipped = [e for i, e in enumerate(raw) if last[e.get("item")] == i]
        gates = [e for e in events if e.get("kind") == "gate"]
        human_gates = [g for g in gates if g.get("required_human")]
        steered_gates = [g for g in gates if g.get("changed")]  # human reworked at a gate
        blocks = [e for e in events if e.get("kind") == "station" and e.get("verdict") == "blocked"]
        # A one-shot ship needed no human rework anywhere on its journey (steers == 0).
        # This is the North Star. `hands_off` (no human present at all) is a secondary,
        # expected-to-be-low signal — the human is meant to stay in the loop.
        one_shot = [s for s in shipped if s.get("steers", 0) == 0]
        hands_off = [s for s in shipped if s.get("human_touches", 0) == 0]
        # Where humans had to step in, ranked worst-first — the retro's to-do list. Gate
        # rework is keyed by gate; a station that blocked (routed verdict or escape hatch)
        # is keyed by that station (that's where autonomy actually broke), tagged so the
        # two don't blur.
        by_stage: dict[str, int] = {}
        for g in steered_gates:
            key = g.get("gate", "?")
            by_stage[key] = by_stage.get(key, 0) + 1
        for b in blocks:
            key = f"{b.get('station', '?')} (blocked)"
            by_stage[key] = by_stage.get(key, 0) + 1
        total = len(shipped)
        # Cost is counted once, at the station events that spent it. A `shipped`
        # event repeats the item's *cumulative* cost (useful per-ship context);
        # summing it here again would double-count every shipped item's spend.
        station_events = [e for e in events if e.get("kind") == "station"]
        cost = sum(e.get("cost", 0.0) for e in station_events)
        # The structural cost proxy: one station run is one agent doing one job.
        # Unlike `cost` it needs nothing from the stations — the engine already
        # records every run — so it always has data, and a change that removes a
        # rework loop shows up here whether or not anyone reported a number. It
        # counts runs, not tokens: an opus council inside one run reads the same
        # as a sonnet review (see docs/OPTIMIZATION-AREAS.md).
        station_runs = len(station_events)
        # Trend: the last `window` ships vs the `window` before them, in ledger
        # (append) order — so the North Star can be seen moving, not just its
        # lifetime average, which weights the factory's earliest runs forever.
        recent = shipped[-window:]
        prior = shipped[-2 * window : -window] if total > window else []

        def _rate(group: list[dict]) -> float | None:
            if not group:
                return None
            return len([s for s in group if s.get("steers", 0) == 0]) / len(group)

        return {
            "shipped": total,
            "one_shot_shipped": len(one_shot),
            "one_shot_ship_rate": (len(one_shot) / total) if total else 0.0,
            "hands_off_shipped": len(hands_off),  # secondary: shipped with no human present
            "human_gate_stops": len(human_gates),
            "human_steers": len(steered_gates) + len(blocks),
            "steers_by_stage": dict(sorted(by_stage.items(), key=lambda kv: -kv[1])),
            "total_cost": round(cost, 4),
            "cost_per_shipped": round(cost / total, 4) if total else 0.0,
            "station_runs": station_runs,
            "runs_per_shipped": round(station_runs / total, 2) if total else 0.0,
            "trend": {
                "window": window,
                "recent_ships": len(recent),
                "recent_one_shot_rate": _rate(recent),
                "prior_ships": len(prior),
                "prior_one_shot_rate": _rate(prior),
            },
        }
