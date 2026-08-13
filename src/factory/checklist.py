"""The invariant checklist — one shared grading surface for both checking stations.

It makes the spec's scoping decision once and each invariant's disposition
structural: **code review fills a row by reading, verify fills it by running**, and
a row nobody could settle carries a category saying why. Without it each checker
re-derives what matters and reports in prose, so a partial verification reaches the
human gate as a paragraph rather than a count.

Markdown a human reviews in the pull request, with a fenced yaml block the engine
parses; writer and reader share `MACHINE_MARKER` so the fence can't drift.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

CHECKLIST_NAME = "CHECKLIST.md"

# Shared with the skills that write the file (see factory-spec's SKILL.md).
MACHINE_MARKER = "<!-- machine-readable: the factory engine parses this block -->"
_MACHINE_BLOCK = re.compile(r"```yaml\n(.*?)\n```", re.S)

# What verify may record in a row's `holds`. Anything else — blank included —
# leaves the row undisposed, which is what blocks a `verified` verdict.
#   verified      ran it, it behaves as specified
#   failed        ran it, it does not
#   blocked       needs access, credentials, or an environment out of reach
#   accepted      verifiable in principle; low risk, and the station is confident
#   out-of-scope  the spec assigned this invariant to another work item
DISPOSITIONS = ("verified", "failed", "blocked", "accepted", "out-of-scope")

# What code review may record in a row's `implemented`. Anything else reads as
# "not yet" — there is no third state, so a doubt belongs in `evidence`, which is
# prose for the human and is never parsed.
IMPLEMENTED_VALUES = ("yes", "y", "true", "done", "✅")

# Dispositions that mean "settled without being demonstrated" — the gap the ship
# gate's headline has to show, because they are what the human is accepting.
UNDEMONSTRATED = ("blocked", "accepted", "out-of-scope")


class ChecklistError(Exception):
    """A checklist that exists but can't be read. Loud rather than silent: one the
    engine can't parse would otherwise quietly stop guarding anything."""


class Checklist:
    def __init__(self, rows: list[dict[str, Any]], path: Path | None = None):
        self.path = path
        self.rows = rows

    # --- reading ------------------------------------------------------------
    @classmethod
    def parse(cls, text: str, path: Path | None = None) -> Checklist:
        _, marked, tail = text.rpartition(MACHINE_MARKER)
        # Anchor on the marker: the prose above it quotes invariants and evidence,
        # either of which can contain its own fence.
        source = tail if marked else text
        blocks = _MACHINE_BLOCK.findall(source)
        if not blocks:
            raise ChecklistError(
                f"{path or 'checklist'}: no machine-readable block found "
                f"(expected a ```yaml fence after {MACHINE_MARKER!r})"
            )
        try:
            data = yaml.safe_load(blocks[-1])
        except yaml.YAMLError as e:
            raise ChecklistError(
                f"{path or 'checklist'}: machine block is not valid yaml: {e}"
            ) from e
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            raise ChecklistError(
                f"{path or 'checklist'}: machine block must be a mapping with a 'rows' list"
            )
        return cls([r for r in data["rows"] if isinstance(r, dict)], path)

    @classmethod
    def load(cls, path: str | Path) -> Checklist:
        p = Path(path)
        return cls.parse(p.read_text(), p)

    @staticmethod
    def find(root: str | Path, artifacts: Iterable[str]) -> Path | None:
        """The checklist among these registered artifacts, or None — registration is
        what makes it load-bearing. Takes paths rather than the item so a caller can
        include a report's artifacts before they've been absorbed."""
        for art in artifacts:
            if Path(art).name == CHECKLIST_NAME:
                p = Path(root) / art
                if p.is_file():
                    return p
        return None

    # --- views --------------------------------------------------------------
    def disposition(self, row: dict) -> str | None:
        value = str(row.get("holds") or "").strip().lower()
        return value if value in DISPOSITIONS else None

    def undisposed(self) -> list[dict]:
        return [r for r in self.rows if self.disposition(r) is None]

    def by_disposition(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for r in self.rows:
            d = self.disposition(r)
            if d:
                out.setdefault(d, []).append(r)
        return out

    def unimplemented(self) -> list[dict]:
        """Rows code review read and did not mark implemented."""
        return [r for r in self.rows if not _truthy(r.get("implemented"))]

    def headline(self) -> str:
        """The one line the ship-gate packet leads with: how much of the spec was
        actually demonstrated, and what the human is being asked to accept."""
        groups = self.by_disposition()
        total = len(self.rows)
        verified = len(groups.get("verified", []))
        parts = [f"{verified}/{total} invariants verified by running"]
        for name in ("failed", *UNDEMONSTRATED):
            if groups.get(name):
                ns = ", ".join(str(r.get("n", "?")) for r in groups[name])
                parts.append(f"{len(groups[name])} {name} ({ns})")
        if self.undisposed():
            ns = ", ".join(str(r.get("n", "?")) for r in self.undisposed())
            parts.append(f"{len(self.undisposed())} undisposed ({ns})")
        return "; ".join(parts)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in set(IMPLEMENTED_VALUES)


def row_label(row: dict) -> str:
    """Number plus enough text to recognize the invariant without opening the file."""
    text = str(row.get("invariant") or "").strip()
    if len(text) > 60:
        text = text[:57] + "…"
    return f"{row.get('n', '?')}" + (f" ({text})" if text else "")
