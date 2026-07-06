"""Intervention records — the fuel for the learning loop.

Every time a human steers the factory (sends a spec back, marks "not ready",
edits an artifact), we capture WHAT the station produced, WHAT the human wanted
instead, and WHY. The retro station reads these to improve the line so the same
class of problem stops reaching the human next time. This operationalizes the
article's line: *every interactive agent use is a failure to learn from.*
"""

from __future__ import annotations

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
                produced=produced or "(see work item artifacts)",
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
