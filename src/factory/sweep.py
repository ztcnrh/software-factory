"""Reclaiming a finished item's scratch.

**Memory** is anything nothing else holds — the specs, the checklist, the review
conversation, the decisions a human made. **Scratch** is anything the engine can
rebuild or that has no reader left: per-run briefs and station scratchpads (working
notes, council memos, verification transcripts). Only memory is committed, and only
memory survives an item finishing.

Two rules make the sweep safe to run unattended: a file is kept because the item
**registered it as an artifact** (never because of its name), and any path
resolving outside the item's own directory is refused.
"""

from __future__ import annotations

from pathlib import Path

from .model import WorkItem

SCRATCH_DIRS = ("runs",)


class SweepError(Exception):
    """A sweep that would have left the item's directory — refused."""


def item_dir(root: str | Path, item_id: str) -> Path:
    return Path(root) / ".factory" / "work-items" / item_id


def plan(root: str | Path, item: WorkItem) -> list[Path]:
    """Every file this sweep would remove, in a stable order. Pure: callers use it
    for the dry run and for the real thing, so what's printed is what happens."""
    root = Path(root)
    home = item_dir(root, item.id).resolve()
    if not home.is_dir():
        return []
    keep = {(root / a).resolve() for a in item.artifacts}
    doomed: list[Path] = []
    for name in SCRATCH_DIRS:
        base = home / name
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            resolved = p.resolve()
            if not resolved.is_relative_to(home):
                raise SweepError(
                    f"{item.id}: refusing to sweep {p} — it resolves outside the item's "
                    f"directory ({home})"
                )
            if resolved in keep:
                continue  # registered as an artifact; that's what makes it durable
            doomed.append(p)
    return doomed


def run(root: str | Path, item: WorkItem, dry_run: bool = False) -> list[str]:
    """Sweep the item, returning one human-readable line per removal. Idempotent —
    a second sweep of the same item finds nothing and says so by returning []."""
    root = Path(root)
    doomed = plan(root, item)
    lines: list[str] = []
    for p in doomed:
        rel = p.relative_to(root)
        if dry_run:
            lines.append(f"would remove: {rel}")
            continue
        p.unlink()
        lines.append(f"removed: {rel}")
    if not dry_run:
        _prune_empty_dirs(item_dir(root, item.id))
    return lines


def _prune_empty_dirs(home: Path) -> None:
    """Drop the scratch directories once they're empty — but only those, and only
    when empty, so a registered artifact that kept one alive keeps its parent too."""
    for name in SCRATCH_DIRS:
        base = home / name
        if not base.is_dir():
            continue
        for d in sorted(base.rglob("*"), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        if not any(base.iterdir()):
            base.rmdir()
