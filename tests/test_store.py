from pathlib import Path

import pytest

from factory.model import WorkItem
from factory.store import Store


def test_a_failed_save_never_corrupts_the_existing_item(factory_root: Path, monkeypatch):
    """The store is the source of truth: a crash mid-write must leave the prior
    version intact (write-temp-then-rename), never a half-written JSON file."""
    store = Store(factory_root)
    item = WorkItem(id="WI-0001", title="original")
    store.save(item)

    def explode(self):
        raise RuntimeError("crash mid-serialization")

    monkeypatch.setattr(WorkItem, "to_dict", explode)
    item.title = "doomed update"
    with pytest.raises(RuntimeError):
        store.save(item)
    monkeypatch.undo()
    assert store.load("WI-0001").title == "original"


def test_save_leaves_no_temp_files_behind(factory_root: Path):
    """The atomic-write temp file is an implementation detail — it must never
    survive a save to be mistaken for a work item (or break list_ids globbing)."""
    store = Store(factory_root)
    store.save(WorkItem(id="WI-0001", title="t"))
    leftovers = [p.name for p in store.dir.iterdir() if p.suffix != ".json"]
    assert leftovers == []
    assert store.list_ids() == ["WI-0001"]
