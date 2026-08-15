import threading
from pathlib import Path

import pytest

from factory.dispatch import Dispatcher
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

def test_concurrent_saves_of_one_item_never_tear_it(factory_root: Path):
    """Two writers must not corrupt each other. A shared staging name (`<item>.tmp`)
    let one writer truncate the other's half-written file and rename the mixture
    over the real one — torn JSON installed as the source of truth."""
    store = Store(factory_root)
    store.save(WorkItem(id="WI-0001", title="seed"))
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        try:
            for _ in range(40):
                store.save(WorkItem(id="WI-0001", title=f"writer-{n}", body="x" * 4000))
                store.load("WI-0001")  # must always parse, mid-flight
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"concurrent saves raised: {errors[:3]}"
    assert store.load("WI-0001").title.startswith("writer-")


def test_concurrent_creations_never_reuse_an_id(factory_root: Path):
    """`next_id` only reads, so allocation has to hold a lock until the new file
    exists. Two `factory new` calls landing in that gap minted the same id, and
    the second save silently overwrote the first item."""
    d = Dispatcher(factory_root)
    made: list[str] = []
    lock = threading.Lock()

    def create(n: int) -> None:
        item = d.new_item(title=f"item {n}")
        with lock:
            made.append(item.id)

    threads = [threading.Thread(target=create, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(made)) == 8, f"duplicate ids minted: {sorted(made)}"
    assert len(store_ids := Store(factory_root).list_ids()) == 8, store_ids
