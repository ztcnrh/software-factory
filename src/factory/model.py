"""Core data model. Three records flow through the factory:

- ``WorkItem``    — a unit of work moving down the line (mirrors a GitHub issue).
- ``StationReport`` — what a station emits when it finishes; its ``verdict``
  routes the item to the next state.
- ``GateDecision`` — a human's decision at a gate (or an auto-decision applied
  from an approved policy).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Event:
    """One entry in a work item's history. Every transition is recorded so the
    item's whole journey down the line is auditable and replayable."""

    ts: str
    kind: str  # created | station | gate | auto_gate | spawn | note | correction | revive
    from_state: str | None = None
    to_state: str | None = None
    verdict: str | None = None
    actor: str | None = None  # "triage" | "human:johndoe" | "policy:<rule-id>" ...
    note: str | None = None
    cost: float = 0.0


@dataclass
class WorkItem:
    """A unit of work. The local JSON of this object is the source of truth;
    GitHub issues (if used) are a mirror."""

    id: str
    title: str
    body: str = ""
    state: str = "triage"
    risk: str = "unknown"  # low | medium | high | unknown (triage assigns this)
    labels: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)  # files produced (specs, etc.)
    pr: str | None = None
    source: str = "local"  # local | github
    source_ref: str | None = None  # e.g. github issue number
    attempts: dict[str, int] = field(default_factory=dict)  # per-state run counts
    human_touches: int = 0  # times a human was present at a gate (attention proxy)
    steers: int = 0  # times a human had to rework the line: gate send-back/correction, or unblock
    cost: float = 0.0  # accumulated cost proxy (tokens or $)
    parent: str | None = None  # the item that spawned this one (e.g. a follow-up bug)
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)
    history: list[Event] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def log(self, **kwargs: Any) -> Event:
        ev = Event(ts=_now(), **kwargs)
        self.history.append(ev)
        self.updated = ev.ts
        return ev

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkItem:
        d = dict(d)
        d["history"] = [Event(**e) for e in d.get("history", [])]
        return cls(**d)


@dataclass
class StationReport:
    """What a station emits when done. ``verdict`` drives routing via line.yml.

    A station can also escalate (``human_required``), update the item's risk,
    attach artifacts, or spawn new work items (a follow-up item, e.g. from a
    deferred monitor or an issues-watcher, enters fresh at triage)."""

    station: str
    verdict: str
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    confidence: float = 0.0
    cost: float = 0.0
    human_required: bool = False
    human_reason: str = ""
    notes: str = ""
    risk: str | None = None
    pr: str | None = None
    labels: list[str] = field(default_factory=list)  # classifying labels to add (append-only)
    spawn: list[dict[str, Any]] = field(default_factory=list)  # new items → triage


# Gate decisions that are themselves a steer (rework), regardless of --changed.
STEERING_VERDICTS = {"needs_revision", "not_ready", "park"}


@dataclass
class GateDecision:
    """A human's decision at a gate. The ``expected``/``category`` fields are the
    structured learning signal the retro station mines."""

    gate: str
    decision: str  # the verdict chosen, e.g. "approved" | "needs_revision"
    by: str = "unknown"  # who decided — the CLI resolves this to a real identity
    changed: bool = False  # human changed the work at the gate, by hand or via their agent
    notes: str = ""
    expected: str = ""  # what the human wanted the station to have produced
    category: str = ""  # e.g. "missing-edge-case" | "wrong-scope" | "style"

    @property
    def is_steer(self) -> bool:
        """Did the human steer? True for a send-back/park (the decision itself is
        rework) or an approval where they edited the work (``changed``). This single
        definition decides what counts as an intervention everywhere — the dispatcher
        records one, and the CLI nudges for the missing why."""
        return self.changed or self.decision in STEERING_VERDICTS
