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
# the line below `medium` unless a human explicitly says so, and a station may
# raise its risk but never lower it back past the floor. A keyword hit is a dumb
# signal, so it makes the weak claim ("not trivial — don't auto-clear its gates")
# and leaves `high` to judgment: triage, or code-review's own auth/payments
# council trigger, which reads the text rather than a rating.
# Word-bounded alternation, not substrings: `auth` must not fire on `author`,
# `token` must not fire on `tokenizer`. Families are prefix patterns
# (`authoriz\w*`) so a new inflection can't slip the net the way an enumerated
# list of conjugations does.
RISK_FLOOR = "medium"
_RISK_FLOOR_TERMS = (
    # identity & access
    r"auth", r"authn", r"authz", r"authenticat\w*", r"authoriz\w*",
    r"oauth", r"sso", r"jwt", r"login", r"password\w*", r"token", r"tokens",
    r"cookie", r"cookies", r"permission\w*", r"privilege\w*", r"rbac", r"acl",
    # secrets & crypto
    r"secret", r"secrets", r"credential\w*", r"encrypt\w*", r"decrypt\w*",
    r"csrf", r"xss",
    # money
    r"payment\w*", r"billing", r"refund\w*",
    # data at risk
    r"migrat\w*", r"backfill\w*", r"pii", r"gdpr",
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
    kind: str  # created | station | gate | auto_gate | gate_bound | spawn | note | correction | ...
    from_state: str | None = None
    to_state: str | None = None
    verdict: str | None = None
    actor: str | None = None  # "triage" | "human:johndoe" | "driver:claude" | "policy:<id>" ...
    note: str | None = None
    cost: float = 0.0
    ran: str | None = None  # how a station ran: inline | subagent | resumed | cloud


@dataclass
class ClassifierEvent:
    """One application or retraction of a classifier.

    Classifiers are gate-policy inputs, so a classification has to be correctable —
    and *who* applied one decides who may take it off (a station may correct
    another station, never the human). The log is append-only: a retraction is a
    new entry, never an edit of the entry that applied it."""

    name: str
    action: str  # add | retract
    by: str  # a station name ("triage"), "human:<who>", or "unknown"
    at: str = field(default_factory=_now)
    reason: str | None = None  # required on a retraction: why the classification was wrong


@dataclass
class ChangePass:
    """One implementation pass: a change branch off the item's feature branch,
    and the pull request carrying it back into that branch.

    Passes accumulate rather than replace. A send-back after the human has merged
    the pass in flight opens a new numbered branch, and the one before it is still
    what a prior gate decision was bound to."""

    branch: str | None = None
    pr: str | None = None


@dataclass
class WorkItem:
    """A unit of work. The local JSON of this object is the source of truth;
    GitHub issues (if used) are a mirror."""

    id: str
    title: str
    body: str = ""
    state: str = "triage"
    risk: str = "unknown"  # low | medium | high | unknown (triage assigns this)
    # `classifiers` is derived from this log
    classifier_log: list[ClassifierEvent] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)  # files produced (specs, etc.)
    # The item's own branch and its pull request into the integration branch. The
    # spec station opens both; everything the item produces ends up here.
    branch: str | None = None
    pr: str | None = None
    # Every implementation pass, oldest first; `change_branch`/`change_pr` derive
    # from the last one.
    change_passes: list[ChangePass] = field(default_factory=list)
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

    @property
    def classifiers(self) -> list[str]:
        """The classifiers currently applied, derived from the log — a name is
        active if its most recent entry is an ``add``. Never stored (``to_dict``
        emits only ``classifier_log``), so the two can't drift apart."""
        active: list[str] = []
        for ev in self.classifier_log:
            if ev.action == "add":
                if ev.name not in active:
                    active.append(ev.name)
            elif ev.name in active:
                active.remove(ev.name)
        return active

    @property
    def change_branch(self) -> str | None:
        """The pass in flight — the most recently opened one. Derived, never
        stored, so it can't drift from the log the way an overwritten field would."""
        return self.change_passes[-1].branch if self.change_passes else None

    @property
    def change_pr(self) -> str | None:
        return self.change_passes[-1].pr if self.change_passes else None

    def open_change_pass(self, branch: str | None = None, pr: str | None = None) -> None:
        """Record what a station reported about its implementation pass.

        A report naming the branch already in flight (or naming none at all) fills
        in that pass; a different branch opens a new one. That single rule is what
        keeps a re-push from forking the log and a new numbered branch from
        overwriting the pass before it."""
        tip = self.change_passes[-1] if self.change_passes else None
        if tip is not None and (branch is None or tip.branch in (None, branch)):
            tip.branch = branch or tip.branch
            tip.pr = pr or tip.pr
        elif branch or pr:
            self.change_passes.append(ChangePass(branch=branch, pr=pr))

    def provenance(self, name: str) -> str | None:
        """Who applied ``name`` most recently — the fact that decides who may
        retract it. ``None`` if the item has never carried it."""
        for ev in reversed(self.classifier_log):
            if ev.name == name and ev.action == "add":
                return ev.by
        return None

    def add_classifier(self, name: str, by: str) -> ClassifierEvent | None:
        """Apply a classifier. Idempotent: re-asserting an active one records nothing."""
        if name in self.classifiers:
            return None
        ev = ClassifierEvent(name=name, action="add", by=by)
        self.classifier_log.append(ev)
        return ev

    def retract_classifier(self, name: str, by: str, reason: str) -> ClassifierEvent:
        """Take a classifier back off. Callers validate first (see
        ``Dispatcher.retract``, which owns the authority rule) — this only records."""
        ev = ClassifierEvent(name=name, action="retract", by=by, reason=reason)
        self.classifier_log.append(ev)
        return ev

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
        d["classifier_log"] = [ClassifierEvent(**e) for e in d.get("classifier_log", [])]
        d["change_passes"] = [ChangePass(**c) for c in d.get("change_passes", [])]
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
    branch: str | None = None
    pr: str | None = None
    change_branch: str | None = None
    change_pr: str | None = None
    ran: str = ""  # how the station ran (inline | subagent | resumed | cloud) — trace metadata
    classifiers: list[str] = field(default_factory=list)  # classifiers to add
    # Classifications this station disproved: (name, why). A station may retract
    # only what a station applied — the dispatcher enforces that and refuses the
    # whole report otherwise, so a bad retraction can't half-apply a verdict.
    retractions: list[tuple[str, str]] = field(default_factory=list)
    spawn: list[dict[str, Any]] = field(default_factory=list)  # new items → triage


# Gate decisions that are themselves a steer (rework), regardless of --changed.
# `recheck` belongs here even though the code is fine: the human had to resolve a
# blocker the line couldn't get past, which is an unblock — and the North Star
# counts those. It also writes an intervention record, which is the point: "verify
# couldn't reach staging" is exactly the recurring gap a retro should aim at.
STEERING_VERDICTS = {"needs_revision", "not_ready", "recheck", "park"}


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
