"""Bounded optional publication for Bitget intraday activity."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from pydantic import ValidationError

from prep_watchdeck_market.artifacts import write_artifact_atomic
from prep_watchdeck_market.native_activity import NativeActivityArtifact, read_native_activity

METRIC_VERSION = "bitget-activity-v1"
READ_OPTIONS = "-c statement_timeout=5000 -c transaction_timeout=8000"
PROJECTION_TIMEOUT_SECONDS = 10


def _activity_snapshot(path: Path) -> tuple[bytes, tuple[int, ...]] | None:
    """Read only a stable regular file; permission errors are not corruption."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("activity target is not a regular file")
        content = handle.read()
        after = os.fstat(handle.fileno())

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    if identity(before) != identity(after) or identity(after) != identity(path.lstat()):
        raise ValueError("activity changed during read")
    return content, identity(after)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_native_activity(database_url: str, artifact_root: Path, *, now: datetime) -> int:
    artifact_root.mkdir(parents=True, exist_ok=True)
    path = artifact_root / "native-activity.json"
    # Keep the lock inode: unlinking it would allow two independent lock owners.
    descriptor = os.open(
        artifact_root / ".native-activity.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "rb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = _activity_snapshot(path)
        old = None
        corrupt = False
        if previous is not None:
            try:
                decoded = json.loads(previous[0])
            except (json.JSONDecodeError, UnicodeDecodeError):
                corrupt = True
            else:
                if (
                    not isinstance(decoded, dict)
                    or type(decoded.get("schemaVersion")) is not int
                    or decoded["schemaVersion"] != 1
                    or decoded.get("metricVersion", METRIC_VERSION) != METRIC_VERSION
                ):
                    raise ValueError("unknown activity schema")
                try:
                    old = NativeActivityArtifact.model_validate(decoded)
                except ValidationError:
                    corrupt = True
        with psycopg.connect(
            database_url, connect_timeout=2, options=READ_OPTIONS, autocommit=True
        ) as connection:
            artifact = read_native_activity(connection, now=now)
        if old is not None and old.candle_cutoff > artifact.candle_cutoff:
            return len(old.rows)
        staged = artifact_root / f".native-activity.{uuid4().hex}.pending"
        try:
            write_artifact_atomic(staged, artifact)
            if _activity_snapshot(path) != previous:
                raise ValueError("activity changed during projection")
            if corrupt and previous is not None:
                backup = artifact_root / f"native-activity.json.corrupt-{uuid4().hex}"
                with backup.open("xb") as handle:
                    handle.write(previous[0])
                    handle.flush()
                    os.fsync(handle.fileno())
                _sync_directory(artifact_root)
                if backup.read_bytes() != previous[0]:
                    raise ValueError("activity preservation failed")
            if _activity_snapshot(path) != previous:
                raise ValueError("activity changed before publication")
            os.replace(staged, path)
            _sync_directory(artifact_root)
        finally:
            staged.unlink(missing_ok=True)
        return len(artifact.rows)


def publish_native_activity_bounded(
    database_url: str, artifact_root: Path, *, now: datetime
) -> int:
    """Bound the entire optional projection, including filesystem work.

    A timed-out thread cannot release its connection/lock safely. The short-lived
    child owns both; subprocess.run kills and reaps it before another run starts.
    Credentials travel on stdin, never in command-line arguments or error output.
    """
    result = subprocess.run(
        [sys.executable, "-m", "prep_watchdeck_market.native_activity_publication"],
        input=json.dumps(
            {"database_url": database_url, "root": str(artifact_root), "now": now.isoformat()}
        ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=PROJECTION_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("activity projection failed")
    return int(result.stdout)


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        count = publish_native_activity(
            request["database_url"],
            Path(request["root"]),
            now=datetime.fromisoformat(request["now"]),
        )
        print(count)
    except Exception:
        sys.exit(1)
