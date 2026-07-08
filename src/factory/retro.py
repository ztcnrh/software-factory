"""Assemble a briefing for the retro (learning) station.

The retro *station* — a Claude skill — does the reasoning: clustering
interventions, proposing edits to station skills, and proposing gate policies.
This module just gathers the raw material (intervention records + metrics) into
one compact, structured document so the skill starts from signal, not noise.
"""

from __future__ import annotations

from pathlib import Path

from .interventions import Interventions
from .metrics import Metrics


def briefing(root: str | Path) -> str:
    interventions = Interventions(root)
    summary = Metrics(root).summary()
    files = interventions.list()

    lines = ["# Retro briefing", ""]
    lines.append(f"- Interventions on record: **{len(files)}**")
    lines.append(
        f"- Auto-ship rate: **{summary['auto_ship_rate']:.0%}** "
        f"({summary['auto_shipped']}/{summary['shipped']} shipped with no human touch)"
    )
    if summary["interventions_by_gate"]:
        lines.append("- Human stops by gate (aim the learning here, worst first):")
        for gate, n in summary["interventions_by_gate"].items():
            lines.append(f"    - `{gate}`: {n}")
    lines += ["", "## Raw intervention records", ""]
    if not files:
        lines.append("_No interventions recorded yet — nothing to learn from._")
    for f in files:
        lines += [f"### {f.name}", "", f.read_text(), ""]

    signals = interventions.signals()
    if signals:
        lines += [
            "",
            "## Chat steering signals",
            "",
            "Captured mid-session by the UserPromptSubmit hook while an item sat at a gate.",
            "Rawer than the records above — weigh them as corroborating context.",
            "",
        ]
        for s in signals:
            if s.get("malformed"):
                lines.append("- ⚠ (an unreadable signal line was skipped — a steer was lost here)")
                continue
            items = ", ".join(s.get("waiting_items", [])) or "?"
            lines.append(f"- {s.get('ts', '?')} [{items}] {s.get('steering', '')}")
    return "\n".join(lines)
