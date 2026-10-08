"""Bounded no-follow reads of stable regular input files."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path


class StableFileError(ValueError):
    """Input is missing, nonregular, oversized or changed during a read."""


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "FileIdentity":
        return cls(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def read_stable_regular_file(path: Path, *, max_bytes: int) -> bytes:
    if max_bytes < 1:
        raise StableFileError("invalid_size_limit")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise StableFileError("non_regular_file")
            if before.st_size > max_bytes:
                raise StableFileError("input_too_large")
            content = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
            final = path.lstat()
        if len(content) > max_bytes:
            raise StableFileError("input_too_large")
        if (
            not stat.S_ISREG(final.st_mode)
            or FileIdentity.from_stat(before) != FileIdentity.from_stat(after)
            or FileIdentity.from_stat(after) != FileIdentity.from_stat(final)
            or len(content) != after.st_size
        ):
            raise StableFileError("input_changed_during_read")
        return content
    except OSError as error:
        raise StableFileError(f"input_read_failed:{error.errno}") from error
