"""Assemble the deterministic half of a station run's context packet.

``factory brief`` writes one file per station *state* (``runs/<state>-brief.md``)
carrying what the engine knows the station needs: identity, risk, lineage, the
request, artifact pointers, what routed the item here, and where to read next. A
retry appends its own section rather than minting a second file. The driver appends
session-only context under the marked section and passes the file verbatim, so "what
was this worker actually fed?" is a file on disk rather than a memory of chat. How to
do the job stays in the station's skill — the brief points at it, never paraphrases
it, so the two can't drift.
"""

from __future__ import annotations

import re
from pathlib import Path

from .checklist import Checklist
from .classifiers import Classifiers
from .dispatch import Action
from .line import Line
from .model import WorkItem

SESSION_HEADER = "## Session context (driver-added)"

_CHECKING_SESSION = (
    "_(deliberately empty — this is a checking station: it converges on the spec and the\n"
    "persisted artifacts alone, never on chat steering. Steering that should change the\n"
    "acceptance bar goes through the spec, not through a checker's ear.)_"
)
_OPEN_SESSION = (
    "_(empty — the driver may append session-only context below before dispatch: spec-interview\n"
    "answers, gate feedback being acted on, session constraints. Everything above this section\n"
    "comes from durable state and regenerates; only this section is the driver's voice.)_"
)


def item_dir(root: str | Path, item_id: str) -> Path:
    return Path(root) / ".factory" / "work-items" / item_id


def runs_dir(root: str | Path, item_id: str) -> Path:
    return item_dir(root, item_id) / "runs"


def scratchpad_dir(root: str | Path, item_id: str) -> Path:
    """Where a station may checkpoint mid-run. Swept when the item finishes, so a
    station can write freely without first deciding whether the result is durable."""
    return runs_dir(root, item_id) / "scratchpad"


def brief_path(root: str | Path, item_id: str, state: str) -> Path:
    """One brief per station *state*, not per attempt — a retry appends a section,
    so the state's whole run history reads as one document."""
    return runs_dir(root, item_id) / f"{state}-brief.md"


def run_marker(attempt: int) -> str:
    """Marks one attempt's section inside the state's brief. Explicit rather than
    the rendered heading, which ``--force`` would stop matching if its wording moved."""
    return f"<!-- factory:run {attempt} -->"


_REVIEW_NAME = re.compile(r"code-review-(\d+)\.md")


def latest_review(root: str | Path, item_id: str) -> Path | None:
    """The highest-numbered review conversation file — the send-back worklist an
    implement retry (or a re-review) reads first."""
    best: tuple[int, Path] | None = None
    for p in item_dir(root, item_id).glob("code-review-*.md"):
        m = _REVIEW_NAME.fullmatch(p.name)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), p)
    return best[1] if best else None


def compose(
    root: str | Path,
    line: Line,
    item: WorkItem,
    action: Action,
    classifiers: Classifiers | None = None,
) -> str:
    """Render the deterministic brief for this station run. Pure templating of
    state the engine already owns — no interpretation, nothing the item's files
    don't already say."""
    root = Path(root)
    classifiers = classifiers or Classifiers.default()
    cap = line.max_attempts(action.state)
    cap_part = f" of max {cap} this epoch" if cap else ""
    lines = [
        run_marker(action.attempt or 1),
        f"# Station brief — {item.id} @ {action.state} (attempt {action.attempt}{cap_part})",
        "",
        "Deterministic context assembled by `factory brief` from durable state. The driver may",
        "append session-only context under the last section; everything else regenerates.",
        "",
        f"- **Item:** {item.id} — {item.title}",
        f"- **Risk:** {item.risk}"
        + (
            f"  ·  **Classifiers:** {classifiers.mark(item.classifiers)}"
            if item.classifiers
            else ""
        ),
        # Shown at the moment a station picks a label — what stops `docs-update`
        # and `doc-update` becoming two terms for one idea.
        f"- **Classifiers in use:** {', '.join(classifiers.names)} "
        "(anything else is recorded and flagged, and matches no gate policy until a human "
        "promotes it — coin a new one when it names a kind of work this list is missing, "
        "never a synonym for a term already on it)",
    ]
    if item.parent:
        lines.append(f"- **Parent:** {item.parent}")
    if item.source_ref:
        lines.append(f"- **Source:** {item.source} {item.source_ref}")
    if item.branch:
        lines.append(
            f"- **Feature branch:** `{item.branch}`"
            + (f" — PR {item.pr} into the integration branch" if item.pr else "")
            + " · the item's unit of delivery; everything it produces lands here"
        )
    if item.change_branch:
        lines.append(
            f"- **Change branch:** `{item.change_branch}`"
            + (f" — PR {item.change_pr} into the feature branch" if item.change_pr else "")
            + " · the implementation pass in flight"
        )
    if action.last_return:
        lines.append(f"- **Routed here by:** {action.last_return}")
    body = item.body.strip() or "_(no body — the title is the whole request)_"
    lines += ["", "## Request", "", body]
    lines += ["", "## Artifacts on record", ""]
    if item.artifacts:
        for a in item.artifacts:
            exists = "" if (root / a).exists() else "  (missing on disk)"
            lines.append(f"- `{a}`{exists}")
    else:
        lines.append("_(none yet)_")
    review = latest_review(root, item.id)
    if review:
        lines.append(f"- Latest review conversation: `{review.relative_to(root)}`")
    # Both checkers get structurally identical briefs; naming the checklist is what
    # differentiates their inputs, rather than the prose in their skills alone.
    if action.checking:
        chk = Checklist.find(root, item.artifacts)
        lines += ["", "## Your grading surface", ""]
        if chk:
            lines += [
                f"`{chk.relative_to(root)}` — one row per in-scope behavior invariant, "
                "already scoped by the spec.",
                "Fill **your** column and leave the other alone: code review records whether "
                "each invariant is implemented (judged by reading), verify records whether it "
                "holds (judged by running).",
                "Every row needs an answer in your column — a clean verdict is refused while "
                "any is blank, and both columns have honest answers for a row you can't "
                "settle, so only silence is blocked.",
                "Rows are durable — work finished before your context ends survives, and a "
                "station replacing you does not repeat it.",
            ]
        else:
            lines.append(
                "_(no checklist registered on this item — grade against the spec's numbered "
                "Behavior invariants directly)_"
            )
    lines += [
        "",
        "## Scratchpad",
        "",
        f"`{scratchpad_dir(root, item.id).relative_to(root)}` — yours to checkpoint into mid-run",
        "(partial findings, a long command's output) so a context that ends early doesn't lose",
        "them. Swept when the item finishes; anything worth keeping goes in a real file and is",
        "registered with `--artifact`.",
        "",
        "## Read next",
        "",
        f"1. `factory status {item.id}` — the full history and the notes earlier stations left.",
        f"2. Your station skill (`{action.skill}`) — the contract for this state; its own",
        "   read-first list governs what to open beyond this brief.",
        "",
        SESSION_HEADER,
        "",
        _CHECKING_SESSION if action.checking else _OPEN_SESSION,
        "",
    ]
    return "\n".join(lines)
