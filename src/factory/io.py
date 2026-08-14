"""Disk primitives for the files the line treats as source of truth.

Every durable write goes through here, so the two hazards are handled in one
place: a crash mid-write must leave the previous version intact, and two writers
must not corrupt each other.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# A lock older than this is assumed to belong to a dead process. Every critical
# section here is a few milliseconds, so anything near this age is a corpse.
_LOCK_STALE_SECONDS = 30.0


def atomic_write_text(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` in one step, or not at all.

    The staging file gets a **unique** name rather than ``path + ".tmp"``. A
    shared name is what turns two concurrent writers into a torn file: the second
    one truncates the first one's staging file, their bytes interleave, and
    whichever renames first installs the mixture as the real thing. With unique
    names the worst case is an ordinary lost update, which is survivable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2))


@contextmanager
def file_lock(path: Path, *, timeout: float = 10.0, wait: float = 0.01) -> Iterator[None]:
    """Hold an exclusive lock for the duration of the block.

    Create-exclusive rather than ``fcntl`` so it behaves the same everywhere,
    including the network filesystems people keep repos on. A lock left behind by
    a killed process is stolen once it goes stale — wedging the store forever is
    a worse failure than the race this prevents.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            pass
        try:
            stale = (time.time() - path.stat().st_mtime) > _LOCK_STALE_SECONDS
        except OSError:
            stale = False  # it vanished under us — just retry the open
        if stale:
            path.unlink(missing_ok=True)
        elif time.monotonic() >= deadline:
            raise TimeoutError(f"could not acquire lock {path} within {timeout}s")
        else:
            time.sleep(wait)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)
