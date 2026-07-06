#!/usr/bin/env python3
"""UserPromptSubmit hook: capture human steering as learning fuel.

Most steering is captured at the gates by ``factory gate --changed``. But humans
also steer mid-session, in chat. This hook captures that — but *only* when the
factory is explicitly waiting on the human (an item parked at a gate), so it stays
silent during ordinary work. It appends the message to
``.factory/interventions/_signals.jsonl`` for the retro station to mine. Fails
open and never blocks the prompt.
"""

from __future__ import annotations

import json
import sys
import time
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
    prompt = (data.get("prompt") or "").strip()
    root = find_root(data.get("cwd") or ".")
    if not root or not prompt:
        return
    waiting = []
    for f in (root / ".factory" / "work-items").glob("*.json"):
        try:
            item = json.loads(f.read_text())
            if item.get("state") in GATES:
                waiting.append(item["id"])
        except Exception:
            pass
    if not waiting:
        return  # nothing waiting on the human → not steering → stay quiet
    sig = root / ".factory" / "interventions" / "_signals.jsonl"
    sig.parent.mkdir(parents=True, exist_ok=True)
    with open(sig, "a") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "waiting_items": waiting,
                    "steering": prompt,
                }
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
