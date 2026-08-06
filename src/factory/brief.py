"""Assemble the deterministic half of a station run's context packet.

``factory brief`` writes one file per station run — ``runs/<state>-<attempt>-brief.md``
under the item's directory — carrying everything the *engine* knows the station
needs: identity, risk, lineage, the request, artifact pointers, what routed the
item here, and where to read next. The driver appends session-only context under
the marked section and passes the file's content to the station verbatim. That
makes "what was this worker actually fed?" a file on disk instead of a memory of
chat — the trace layer for the driver→station handoff. The NL half (how to do
the job) stays in the station's skill: the brief points at it, never paraphrases
it, so the two can't drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

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


def brief_path(root: str | Path, item_id: str, state: str, attempt: int) -> Path:
    return runs_dir(root, item_id) / f"{state}-{attempt}-brief.md"


def latest_review(root: str | Path, item_id: str) -> Path | None:
    """The highest-numbered review conversation file, if any — the send-back
    worklist an implement retry (or a re-review) reads first."""
    best: tuple[int, Path] | None = None
    for p in item_dir(root, item_id).glob("review-*.md"):
        m = re.fullmatch(r"review-(\d+)\.md", p.name)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), p)
    return best[1] if best else None


def compose(root: str | Path, line: Line, item: WorkItem, action: Action) -> str:
    """Render the deterministic brief for this station run. Pure templating of
    state the engine already owns — no interpretation, nothing the item's files
    don't already say."""
    root = Path(root)
    cap = line.max_attempts(action.state)
    cap_part = f" of max {cap} this epoch" if cap else ""
    lines = [
        f"# Station brief — {item.id} @ {action.state} (attempt {action.attempt}{cap_part})",
        "",
        "Deterministic context assembled by `factory brief` from durable state. The driver may",
        "append session-only context under the last section; everything else regenerates.",
        "",
        f"- **Item:** {item.id} — {item.title}",
        f"- **Risk:** {item.risk}"
        + (f"  ·  **Labels:** {', '.join(item.labels)}" if item.labels else ""),
    ]
    if item.parent:
        lines.append(f"- **Parent:** {item.parent}")
    if item.source_ref:
        lines.append(f"- **Source:** {item.source} {item.source_ref}")
    if item.pr:
        lines.append(f"- **PR:** {item.pr}")
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
    lines += [
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
