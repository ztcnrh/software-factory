"""Assemble a briefing for the retro (learning) station.

The retro *station* — a Claude skill — does the reasoning: clustering
interventions, proposing edits to station skills, and proposing gate policies.
This module just gathers the raw material — intervention records, metrics, and
the automated-churn signal (items whose per-state ``attempts`` show an inner
loop thrashing with no human present) — into one compact, structured document
so the skill starts from signal, not noise.
"""

from __future__ import annotations

from pathlib import Path

from .interventions import Interventions
from .ledger import Ledger
from .metrics import Metrics
from .store import Store

# Station runs on one state before an item is flagged as internal thrash: 3 runs
# of e.g. implement = 2 automated send-backs that no human ever saw.
CHURN_THRESHOLD = 3


def briefing(root: str | Path, churn_threshold: int = CHURN_THRESHOLD) -> str:
    interventions = Interventions(root)
    summary = Metrics(root).summary()
    files = interventions.list()

    lines = ["# Retro briefing", ""]
    lines.append(f"- Interventions on record: **{len(files)}**")
    lines.append(
        f"- One-shot ship rate: **{summary['one_shot_ship_rate']:.0%}** "
        f"({summary['one_shot_shipped']}/{summary['shipped']} shipped with no human rework)"
    )
    if summary["steers_by_stage"]:
        lines.append("- Where humans had to step in (aim the learning here, worst first):")
        for stage, n in summary["steers_by_stage"].items():
            lines.append(f"    - `{stage}`: {n}")

    ledger = Ledger(root)
    open_rows = ledger.open_entries()
    if open_rows or ledger.warnings:
        lines += [
            "",
            "## Reconcile past proposals first",
            "",
            "Open ledger rows — adjudicate these against the record above *before* proposing "
            "anything new: has each row's signal shown up (record it: `factory ledger update "
            "<id> --outcome ...`)? Is a dormant policy's evidence bar now met, or has an "
            "accepted change stopped paying off (`--status activated|superseded`)? "
            "Full detail: `.factory/retro/LEDGER.md`.",
            "",
        ]
        for e in open_rows:
            lines.append(
                f"- **{e['id']}** [{e['status']}, {str(e['date'])[:10]}] {e['title']} — "
                f"watch for: {e['signal']}"
            )
        for w in ledger.warnings:
            lines.append(f"- ⚠ ledger: {w}")

    churn = []
    for item in Store(root).list_items():
        hot = {s: n for s, n in item.attempts.items() if n >= churn_threshold}
        if hot:
            churn.append((max(hot.values()), item, hot))
    if churn:
        lines += [
            "",
            "## Automated churn (no human saw these)",
            "",
            f"Items where a station ran {churn_threshold}+ times. The inner loops "
            "(e.g. code_review ↔ implement) are fully automated, so this thrash writes no "
            "intervention record — read it as \"this class of work churns internally\" and "
            "weigh sharpening the spec bar or the review bar even though no human stepped in.",
            "",
        ]
        for _, item, hot in sorted(churn, key=lambda c: -c[0]):
            counts = ", ".join(f"`{s}`×{n}" for s, n in sorted(hot.items()))
            lines.append(f"- **{item.id}** ({item.state}): {item.title} — {counts}")
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
