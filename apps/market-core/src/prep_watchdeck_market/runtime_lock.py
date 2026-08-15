from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class RuntimeLockUnavailable(RuntimeError):
    """Another process owns the runtime state boundary."""


@contextmanager
def exclusive_runtime_lock(path: Path) -> Iterator[None]:
    """Hold a non-blocking process lock for one state-root runtime."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        import fcntl

        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeLockUnavailable("runtime lock is already held") from None
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
