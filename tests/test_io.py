import threading
import time
from pathlib import Path

import pytest

from factory import io


def test_a_write_that_raises_leaves_the_previous_version_and_no_staging_file(
    tmp_path: Path, monkeypatch
):
    """Atomicity is the whole point of routing writes through here: a write that
    dies between staging and rename must leave the old content readable, and
    nothing half-written lying around to be mistaken for real state."""
    target = tmp_path / "state.json"
    target.write_text('{"v": 1}')

    def boom(_fd):
        raise RuntimeError("disk went away")

    monkeypatch.setattr(io.os, "fsync", boom)
    with pytest.raises(RuntimeError):
        io.atomic_write_text(target, '{"v": 2}')

    assert target.read_text() == '{"v": 1}'
    assert list(tmp_path.glob(".*.tmp")) == []


def test_two_writers_never_share_a_staging_path(tmp_path: Path, monkeypatch):
    """The bug this module exists for: a staging name derived only from the target
    means the second writer truncates the first one's half-written file."""
    target = tmp_path / "state.json"
    seen: list[str] = []
    real = io.tempfile.mkstemp

    def spy(*a, **kw):
        fd, name = real(*a, **kw)
        seen.append(name)
        return fd, name

    monkeypatch.setattr(io.tempfile, "mkstemp", spy)
    io.atomic_write_text(target, "a")
    io.atomic_write_text(target, "b")

    assert len(set(seen)) == 2, f"staging paths collided: {seen}"


def test_file_lock_serializes_its_holders(tmp_path: Path):
    """Allocation correctness rests on this: if two holders can be inside at once,
    they both read the same highest id."""
    lock_path = tmp_path / ".id.lock"
    inside = 0
    overlaps: list[int] = []

    def hold() -> None:
        nonlocal inside
        for _ in range(20):
            with io.file_lock(lock_path):
                inside += 1
                if inside != 1:
                    overlaps.append(inside)
                time.sleep(0.001)
                inside -= 1

    threads = [threading.Thread(target=hold) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert overlaps == [], f"lock admitted {max(overlaps)} holders at once"


def test_a_stale_lock_is_stolen_rather_than_wedging_the_store(tmp_path: Path, monkeypatch):
    """A process killed mid-write must not block every later write forever —
    wedging the store is a worse failure than the race the lock prevents."""
    lock_path = tmp_path / ".id.lock"
    lock_path.write_text("99999")  # a corpse from a dead pid
    monkeypatch.setattr(io, "_LOCK_STALE_SECONDS", -1.0)  # treat it as long dead

    with io.file_lock(lock_path, timeout=1.0):
        pass

    assert not lock_path.exists()


def test_a_live_lock_times_out_instead_of_being_stolen(tmp_path: Path):
    """The flip side: stealing must be gated on age, or the lock guarantees nothing."""
    lock_path = tmp_path / ".id.lock"
    with io.file_lock(lock_path):
        with pytest.raises(TimeoutError):
            with io.file_lock(lock_path, timeout=0.05, wait=0.01):
                pass
