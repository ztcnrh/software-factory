"""Local JSON state store for work items, at ``<root>/.factory/work-items/``.

The local store is the source of truth. IDs are simple, sortable, and human
friendly (``WI-0001``)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .io import atomic_write_json, file_lock
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
        self.ensure()
        atomic_write_json(self._path(item.id), item.to_dict())

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
        """The next free id. Call this inside :meth:`allocating` — on its own it
        only reads, so two callers get the same answer."""
        nums = [int(i.split("-")[-1]) for i in self.list_ids() if i.split("-")[-1].isdigit()]
        return f"WI-{(max(nums) + 1) if nums else 1:04d}"

    @contextmanager
    def allocating(self) -> Iterator[None]:
        """Hold the id lock across allocate-*and*-save.

        Locking `next_id` alone would fix nothing: the race is the gap between
        reading the highest id on disk and the new file existing, so both have to
        happen inside one critical section. Two `factory new` calls that land in
        that gap mint the same id, and the second save silently overwrites the
        first item.
        """
        self.ensure()
        with file_lock(self.dir / ".id.lock"):
            yield
