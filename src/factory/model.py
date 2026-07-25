"""Core data model. Three records flow through the factory:

- ``WorkItem``    — a unit of work moving down the line (mirrors a GitHub issue).
- ``StationReport`` — what a station emits when it finishes; its ``verdict``
  routes the item to the next state.
- ``GateDecision`` — a human's decision at a gate (or an auto-decision applied
  from an approved policy).
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# One shared ordering for risk comparisons ("unknown" ranks riskiest — it hasn't
# been judged yet, so nothing may treat it as safe). Policies and the risk floor
# both consume this; one home so the two can never disagree.
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "unknown": 3}

# Deterministic risk floor: work whose text touches these concerns cannot enter
# the line below `high` unless a human explicitly says so, and a station may
# raise its risk but never lower it back past the floor. A dumb, word-bounded
# backstop against an under-triaged auth/payments/migration change skipping a
# gate — the model's judgment can only make such an item *more* guarded.
# Word-bounded alternation, not substrings: `auth` must not fire on `author`,
# `token` must not fire on `tokenizer`.
RISK_FLOOR = "high"
_RISK_FLOOR_TERMS = (
    "auth", "authn", "authz", "authentication", "authorization",
    "authenticate", "authenticates", "authenticated", "authorize", "authorized",
    "login", "password", "passwords", "token", "tokens", "secret", "secrets",
    "credential", "credentials", "payment", "payments", "billing",
    "migration", "migrations", "encrypt", "encrypts", "encrypted", "encryption",
    "permission", "permissions",
)
_RISK_FLOOR_RE = re.compile(r"\b(" + "|".join(_RISK_FLOOR_TERMS) + r")\b", re.IGNORECASE)


def risk_floor_matches(text: str) -> list[str]:
    """Distinct floor-triggering terms found in ``text``, lowercased, first-seen
    order — recorded on the item so every later clamp can say *why*."""
    seen: list[str] = []
    for m in _RISK_FLOOR_RE.findall(text or ""):
        w = m.lower()
        if w not in seen:
            seen.append(w)
    return seen


@dataclass
class Event:
    """One entry in a work item's history. Every transition is recorded so the
    item's whole journey down the line is auditable and replayable."""

    ts: str
    kind: str  # created | station | gate | auto_gate | spawn | note | correction | revive
    from_state: str | None = None
    to_state: str | None = None
    verdict: str | None = None
    actor: str | None = None  # "triage" | "human:johndoe" | "driver:claude" | "policy:<id>" ...
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
    attach artifacts, or spawn new work items (a follow-up or leaf item — e.g.
    from the deferred monitor, or triage decomposing an oversized item — enters
    fresh at triage, linked to its parent)."""

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
