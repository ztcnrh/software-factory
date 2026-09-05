"""Intervention records — the fuel for the learning loop.

Every time a human steers the factory (sends a spec back, marks "not ready",
edits an artifact), we capture WHAT the station produced, WHAT the human wanted
instead, and WHY. The retro station reads these to improve the line so the same
class of problem stops reaching the human next time. The guiding line:
*every interactive agent use is a failure to learn from.*
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import yaml

from .model import GateDecision, WorkItem

# The record's machine surface. Writer and reader share this constant so the
# fence a record ships can never drift from the fence `records()` looks for.
_MACHINE_MARKER = "<!-- machine-readable: the retro station parses this block -->"
_MACHINE_BLOCK = re.compile(r"```yaml\n(.*?)\n```", re.S)
_FILENAME_TS = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})Z(?:-\d+)?\.md$")

_TEMPLATE = """\
# Intervention — {item_id} @ {gate}

- **When:** {ts}
- **Work item:** {item_id} — {title}
- **Gate:** {gate}
- **Decision:** {decision}
- **By:** {by}
- **Category:** {category}

## What the station produced
{produced}

## What the human wanted instead
{expected}

## Why — the steering signal
{notes}

---
{marker}
```yaml
item: {item_id}
gate: {gate}
decision: {decision}
category: "{category}"
changed: {changed}
state_before: {state_before}
```
"""


def _machine_fields(text: str) -> dict | None:
    """Parse a record's machine block, or None if it has none.

    Anchored on ``_MACHINE_MARKER`` rather than scanning the whole file: the
    sections above it embed a station's artifact and the human's free text, and
    either can contain its own yaml fence — including an unterminated one, which
    would otherwise swallow the real block's opening fence. A record without the
    marker (hand-written, or pre-dating it) falls back to the last fence, which
    is still the machine block in every shape the template has ever emitted.
    """
    _, marked, tail = text.rpartition(_MACHINE_MARKER)
    if marked:
        m = _MACHINE_BLOCK.search(tail)
        block = m.group(1) if m else None
    else:
        blocks = _MACHINE_BLOCK.findall(text)
        block = blocks[-1] if blocks else None
    if not block:
        return None
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _fence(text: str) -> str:
    """Wrap embedded artifact content in a code fence so its own markdown
    (H1 headings, code blocks) can't break the record's structure. The fence
    is sized to outrank any backtick run inside the content."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}markdown\n{text}\n{ticks}"


class Interventions:
    def __init__(self, root: str | Path):
        self.dir = Path(root) / ".factory" / "interventions"

    def record(
        self, item: WorkItem, decision: GateDecision, state_before: str, produced: str = ""
    ) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
        path = self.dir / f"{item.id}-{decision.gate}-{ts}.md"
        # Second resolution collides when one gate is steered twice inside a
        # second (a scripted driver, a tight loop) — and an overwrite would drop
        # a steer the retro can never recover. Suffix instead.
        n = 2
        while path.exists():
            path = self.dir / f"{item.id}-{decision.gate}-{ts}-{n}.md"
            n += 1
        path.write_text(
            _TEMPLATE.format(
                item_id=item.id,
                title=item.title,
                gate=decision.gate,
                decision=decision.decision,
                by=decision.by,
                category=decision.category or "uncategorized",
                produced=_fence(produced) if produced else "(see work item artifacts)",
                expected=decision.expected or "(not specified)",
                notes=decision.notes or "(none)",
                changed=str(decision.changed).lower(),
                state_before=state_before,
                ts=ts,
                marker=_MACHINE_MARKER,
            )
        )
        return path

    def list(self) -> list[Path]:
        if not self.dir.exists():
            return []
        return sorted(self.dir.glob("*.md"))

    def records(self) -> list[dict]:
        """Structured view of the records — every field of the machine block
        (item, gate, decision, category, changed, state_before) plus an ISO
        timestamp recovered from the filename, for mechanical joins like the
        ledger's recurrence check. Best-effort: a file that doesn't parse still
        contributes its path and timestamp, flagged ``malformed`` so
        ``factory doctor`` can report the loss."""
        out = []
        for path in self.list():
            rec: dict = {}
            data = _machine_fields(path.read_text())
            if data:
                rec.update(data)
            else:
                rec["malformed"] = True
            # After the block, so a malformed record can't shadow the two fields
            # every caller relies on.
            rec["path"] = path
            m = _FILENAME_TS.search(path.name)
            if m:
                # Filenames can't carry colons; the ledger's `status_since` is
                # colon-form ISO, and the recurrence join compares the two as
                # strings — so restore the colons or every comparison skews.
                rec["ts"] = f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}Z"
            out.append(rec)
        return out
