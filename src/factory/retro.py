"""Assemble a briefing for the retro (learning) station.

The retro *station* — a Claude skill — does the reasoning: clustering
interventions, proposing edits to station skills, and proposing gate policies.
This module just gathers the raw material — intervention records, metrics, and
a churn signal (items whose per-state ``attempts`` show a station re-running
well past once; the *why* lives in each item's history) — into one compact,
structured document so the skill starts from signal, not noise.
"""

from __future__ import annotations

from pathlib import Path

from .interventions import Interventions
from .ledger import Ledger
from .metrics import Metrics
from .policies import PolicyState
from .store import Store

# Times a station may run on one state before the item is flagged for a look:
# 3 runs = re-entered twice. The count flags; the item's history explains.
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
            "Open ledger rows — adjudicate each against the record above and its PR's real "
            "state *before* proposing anything new: did its signal show up (record it: "
            "`factory ledger update <id> --outcome ...`)? Did a dormant policy earn its "
            "signature (→ `--status applied`), or an accepted change stop paying off "
            "(`--status superseded`)? Full detail: `.factory/retro/LEDGER.md`.",
            "",
        ]
        for e in open_rows:
            lines.append(
                f"- **{e['id']}** [{e['status']}, {str(e['date'])[:10]}] {e['title']} — "
                f"watch for: {e['signal']}"
            )
        for w in ledger.warnings:
            lines.append(f"- ⚠ ledger: {w}")

    # Mechanical recurrence check: an APPLIED proposal with a category is a
    # falsifiable claim — "this class of steer stops". Interventions of that
    # category recorded after it took effect say the claim is failing; compute
    # that join here so no retro has to remember to do it.
    recurrences = []
    records = interventions.records()
    for e in ledger.entries():
        if e.get("status") != "applied" or not e.get("category"):
            continue
        since = e.get("status_since", "")
        hits = [
            r
            for r in records
            if r.get("category") == e["category"] and r.get("ts", "") > since
        ]
        if hits:
            recurrences.append((e, hits))
    if recurrences:
        lines += [
            "",
            "## Recurrence check — applied proposals whose steer came back",
            "",
            "These proposals shipped, and interventions of the very category they were meant "
            "to end have been recorded since. The fix didn't hold (or didn't cover the class): "
            "adjudicate — tighten/supersede the proposal, or record the honest outcome.",
            "",
        ]
        for e, hits in recurrences:
            hit_names = ", ".join(f"`{h['path'].name}`" for h in hits)
            lines.append(
                f"- ⚠ **{e['id']}** (category `{e['category']}`, applied "
                f"{str(e.get('status_since', ''))[:10]}): {len(hits)} matching intervention(s) "
                f"since — {hit_names}"
            )

    suspended = PolicyState(root).suspended()
    if suspended:
        lines += [
            "",
            "## Suspended gate policies",
            "",
            "These signed rules auto-cleared an item that later needed human rework, so the "
            "engine suspended them (their gates are back to human). Adjudicate each: if the "
            "rule was at fault, propose a tighter replacement (and supersede its ledger row); "
            "if the failure was unrelated, recommend reinstating "
            "(`factory policy reinstate <id>`). Don't leave them in limbo.",
            "",
        ]
        for rid, s in sorted(suspended.items()):
            lines.append(f"- **{rid}** — suspended {s['ts']} after {s['item']}: {s['why']}")

    churn = []
    for item in Store(root).list_items():
        hot = {s: n for s, n in item.attempts.items() if n >= churn_threshold}
        if hot:
            churn.append((max(hot.values()), item, hot))
    if churn:
        lines += [
            "",
            "## Items with repeated station runs (churn signal)",
            "",
            f"A station re-ran {churn_threshold}+ times on these items — real rework "
            "(tokens, cycle time), often with no intervention record. The count flags "
            "the item; it doesn't explain it. A state gets re-entered by an automated "
            "`code_review ↔ implement` loop, a human `not_ready` at ship_review, a "
            "deploy failure back into the code loop, or an unblock — indistinguishable "
            "by count alone. Read each item's history (the `history` list in its "
            "work-item JSON): the transitions (`from_state → to_state`, `verdict`, "
            "`actor`) show which. Diagnose from that before you reach for a lever.",
            "",
        ]
        for _, item, hot in sorted(churn, key=lambda c: -c[0]):
            counts = ", ".join(f"`{s}`×{n}" for s, n in sorted(hot.items()))
            lines.append(
                f"- **{item.id}** (Item current state: {item.state}): {item.title}\n"
                f"    Attempts by station: {counts}"
            )

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
