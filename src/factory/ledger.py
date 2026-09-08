"""The retro ledger: durable memory for the learning loop's own proposals.

Every retro proposal (``RP-####`` — Retro Proposal) gets one row — what it
changed, the steer(s) it answered, the "how you'll know it worked"
signal, and a status tracking what became of it (``proposed`` → ``applied``, via
``dormant`` for a policy awaiting its signature; ``rejected``/``superseded``
closes it) plus the later observed outcome. The retro station opens every run by
reconciling the open rows; the human audits from one file.

Storage follows the factory's history discipline: ``.factory/retro/ledger.jsonl``
is append-only events (``add`` / ``update`` rows — a status change is a new
event, never an edit), materialized on read. ``LEDGER.md`` beside it is a
regenerated human-readable view, never the source of truth.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATUSES = {"proposed", "applied", "dormant", "rejected", "superseded"}
# Closed rows have had their final adjudication; everything else is open until an
# observed outcome is recorded — that's what "reconcile past proposals" means.
CLOSED = {"rejected", "superseded"}

_FIELDS = ("title", "lever", "files", "answers", "signal", "pr", "status", "category")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class LedgerError(Exception):
    """Raised on malformed ledger input — caught at the CLI boundary."""


class Ledger:
    def __init__(self, root: str | Path):
        self.dir = Path(root) / ".factory" / "retro"
        self.path = self.dir / "ledger.jsonl"
        self.view = self.dir / "LEDGER.md"
        self.warnings: list[str] = []  # malformed/orphan lines noticed on the last read

    # --- reads ---------------------------------------------------------------
    def entries(self) -> list[dict]:
        """Materialize the append-only event log into current entry state, in id
        order. Bad lines never vanish silently: they land in ``self.warnings``."""
        self.warnings = []
        if not self.path.exists():
            return []
        by_id: dict[str, dict] = {}
        for i, line in enumerate(self.path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                self.warnings.append(f"line {i}: unreadable (not JSON) — a ledger event is lost")
                continue
            rid = row.get("id")
            if row.get("op") == "add" and rid:
                entry = {k: row.get(k) for k in _FIELDS}
                entry.update(id=rid, date=row.get("ts", ""), outcome=row.get("outcome", ""))
                entry["status_since"] = row.get("ts", "")
                by_id[rid] = entry
            elif row.get("op") == "update" and rid in by_id:
                for k in ("status", "outcome", "pr"):
                    if row.get(k) is not None:
                        by_id[rid][k] = row[k]
                if row.get("status") is not None:
                    # When the status last changed — the recurrence check scopes
                    # "did the steer come back?" to steers recorded after this.
                    by_id[rid]["status_since"] = row.get("ts", "")
            else:
                self.warnings.append(f"line {i}: update for unknown id {rid!r} — skipped")
        return sorted(by_id.values(), key=lambda e: e["id"])

    def open_entries(self) -> list[dict]:
        """Rows still awaiting adjudication: not closed, and no observed outcome
        recorded yet. This is the retro's read-first reconciliation list."""
        return [e for e in self.entries() if e["status"] not in CLOSED and not e.get("outcome")]

    # --- writes --------------------------------------------------------------
    def add(
        self,
        title: str,
        lever: str,
        signal: str,
        files: list[str] | None = None,
        answers: list[str] | None = None,
        pr: str = "",
        status: str = "proposed",
        category: str = "",
    ) -> dict:
        if not title.strip() or not lever.strip():
            raise LedgerError("a ledger row needs a --title and a --lever")
        if not signal.strip():
            raise LedgerError(
                "a ledger row needs a --signal (how you'll know it worked) — "
                "a proposal you can't falsify isn't ready to record"
            )
        self._check_status(status)
        nums = [int(e["id"].split("-")[-1]) for e in self.entries()]
        rid = f"RP-{(max(nums) + 1) if nums else 1:04d}"
        self._append(
            {
                "op": "add",
                "ts": _now(),
                "id": rid,
                "title": title.strip(),
                "lever": lever.strip(),
                "files": files or [],
                "answers": answers or [],
                "signal": signal.strip(),
                "pr": pr,
                "status": status,
                "category": category.strip(),
            }
        )
        self.render()
        return next(e for e in self.entries() if e["id"] == rid)

    def update(
        self,
        entry_id: str,
        status: str | None = None,
        outcome: str | None = None,
        pr: str | None = None,
    ) -> dict:
        if status is None and outcome is None and pr is None:
            raise LedgerError("nothing to update — pass --status, --outcome, and/or --pr")
        if status is not None:
            self._check_status(status)
        if not any(e["id"] == entry_id for e in self.entries()):
            known = ", ".join(e["id"] for e in self.entries()) or "(none)"
            raise LedgerError(f"unknown ledger id {entry_id!r}; known: {known}")
        row: dict[str, Any] = {"op": "update", "ts": _now(), "id": entry_id}
        for k, v in (("status", status), ("outcome", outcome), ("pr", pr)):
            if v is not None:
                row[k] = v
        self._append(row)
        self.render()
        return next(e for e in self.entries() if e["id"] == entry_id)

    # --- the rendered view ---------------------------------------------------
    def render(self) -> str:
        """Regenerate LEDGER.md from the event log. A view, not a second store —
        hand-edits would be overwritten on the next mutation."""
        lines = [
            "# Retro ledger",
            "",
            "One row per retro proposal: what changed, the evidence it answered, the signal that",
            "would show it worked, and what actually happened to it. Generated from",
            "`ledger.jsonl` (append-only) — update with `factory ledger update`, don't hand-edit.",
            "",
        ]
        entries = self.entries()
        if not entries:
            lines.append("_No proposals recorded yet._")
        for e in entries:
            closed = e["status"] in CLOSED or e.get("outcome")
            marker = "" if closed else " · **open**"
            lines += [
                f"## {e['id']} — {e['title']}",
                "",
                f"- **Status:** {e['status']}{marker}   ·   **Date:** {e['date']}",
                f"- **Lever:** {e['lever']}",
            ]
            if e.get("files"):
                lines.append(f"- **Files:** {', '.join(e['files'])}")
            if e.get("answers"):
                lines.append(f"- **Answers:** {', '.join(e['answers'])}")
            if e.get("category"):
                lines.append(f"- **Category:** {e['category']}")
            lines.append(f"- **How we'll know it worked:** {e['signal']}")
            if e.get("pr"):
                lines.append(f"- **PR:** {e['pr']}")
            if e.get("outcome"):
                lines.append(f"- **Observed outcome:** {e['outcome']}")
            lines.append("")
        text = "\n".join(lines).rstrip() + "\n"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.view.write_text(text)
        return text

    # --- plumbing ------------------------------------------------------------
    @staticmethod
    def _check_status(status: str) -> None:
        if status not in STATUSES:
            raise LedgerError(f"unknown status {status!r}; valid: {', '.join(sorted(STATUSES))}")

    def _append(self, row: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(row) + "\n")
