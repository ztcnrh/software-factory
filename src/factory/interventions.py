"""Intervention records — the fuel for the learning loop.

Every time a human steers the factory (sends a spec back, marks "not ready",
edits an artifact), we capture WHAT the station produced, WHAT the human wanted
instead, and WHY. The retro station reads these to improve the line so the same
class of problem stops reaching the human next time. The guiding line:
*every interactive agent use is a failure to learn from.*
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .model import GateDecision, WorkItem

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
<!-- machine-readable: the retro station parses this block -->
```yaml
item: {item_id}
gate: {gate}
decision: {decision}
category: "{category}"
changed: {changed}
state_before: {state_before}
```
"""


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
            )
        )
        return path

    def list(self) -> list[Path]:
        if not self.dir.exists():
            return []
        return sorted(self.dir.glob("*.md"))

    def signals(self) -> list[dict]:
        """Chat steering captured by the UserPromptSubmit hook (_signals.jsonl).
        Best-effort by design: the hook appends blindly, so an unparseable line
        becomes a ``{"malformed": True}`` marker in place (order preserved) rather
        than vanishing — the reader should know a signal existed even if its
        content is lost."""
        path = self.dir / "_signals.jsonl"
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"malformed": True})
        return out
