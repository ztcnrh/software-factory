"""Local JSON state store for work items, at ``<root>/.factory/work-items/``.

The local store is the source of truth. IDs are simple, sortable, and human
friendly (``WI-0001``)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .model import WorkItem


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.dir = self.root / ".factory" / "work-items"

    def _path(self, item_id: str) -> Path:
        return self.dir / f"{item_id}.json"

    def ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, item: WorkItem) -> None:
        # Atomic: write a sibling temp file, fsync, then rename over the real one.
        # A crash mid-write must never leave a half-written (corrupt) item — the
        # store is the source of truth, so the old version stays intact until the
        # new one is fully on disk.
        self.ensure()
        path = self._path(item.id)
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(item.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def load(self, item_id: str) -> WorkItem:
        with open(self._path(item_id)) as f:
            return WorkItem.from_dict(json.load(f))

    def exists(self, item_id: str) -> bool:
        return self._path(item_id).exists()

    def list_ids(self) -> list[str]:
        if not self.dir.exists():
            return []
        return sorted(p.stem for p in self.dir.glob("*.json"))

    def list_items(self) -> list[WorkItem]:
        return [self.load(i) for i in self.list_ids()]

    def next_id(self) -> str:
        nums = [int(i.split("-")[-1]) for i in self.list_ids() if i.split("-")[-1].isdigit()]
        return f"WI-{(max(nums) + 1) if nums else 1:04d}"
