#!/usr/bin/env python3
"""SessionStart hook: make every session factory-aware by injecting the board.

Reads ``.factory/work-items/*.json`` directly (no dependency on the factory
package or its venv) and returns the in-flight items as additional context. Fails
open — any error just means no context is injected, never a blocked session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GATES = {"spec_review", "ship_review", "needs_human", "blocked"}


def find_root(start: str) -> Path | None:
    p = Path(start).resolve()
    for d in [p, *p.parents]:
        if (d / "line.yml").exists() and (d / ".factory").exists():
            return d
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    root = find_root(data.get("cwd") or ".")
    if not root:
        return
    items = []
    for f in sorted((root / ".factory" / "work-items").glob("*.json")):
        try:
            items.append(json.loads(f.read_text()))
        except Exception:
            pass
    live = [i for i in items if i.get("state") not in ("done", "parked")]
    # Speak even when the floor is empty: a cold session must still learn the factory
    # exists and where its driver protocol lives, or governance (station isolation,
    # gate etiquette) never reaches a session started without /factory.
    if live:
        waiting = [i for i in live if i.get("state") in GATES]
        moving = [i for i in live if i.get("state") not in GATES]
        lines = [f"🏭 Software factory: {len(live)} work item(s) in flight."]
        if waiting:
            lines.append("Waiting on you (human gate):")
            for i in waiting:
                lines.append(f"  - {i['id']} @ {i['state']}: {i['title']}")
        if moving:
            lines.append("Moving down the line:")
            for i in moving:
                lines.append(f"  - {i['id']} @ {i['state']}: {i['title']}")
    else:
        lines = ["🏭 This repo runs a software factory — idle, no work items in flight."]
    lines.append(
        "Drive it with /factory, or see all with /factory-status. If asked to run the "
        "factory without the /factory command, read .claude/commands/factory.md first — "
        "it is the driver protocol (station dispatch rules, gate etiquette)."
    )
    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }
    print(json.dumps(out))


if __name__ == "__main__":
    main()
