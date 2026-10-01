"""Publish an immutable saved-candle audit report and its optional read index."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import stat
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from prep_watchdeck_market.artifacts import write_artifact_atomic
from prep_watchdeck_market.candle_audit import MAX_INPUT_BYTES, audit_snapshots
from prep_watchdeck_market.candle_audit_artifacts import (
    AuditIndex,
    AuditReport,
    AuditRequest,
    build_audit_report,
    build_failed_report,
    index_entry_from_report,
)
from prep_watchdeck_market.runtime_lock import RuntimeLockUnavailable, exclusive_runtime_lock

MAX_REQUEST_BYTES = 64 * 1024
MAX_INDEX_BYTES = 1024 * 1024
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_AUDIT_AREA_BYTES = 2 * 1024 * 1024 * 1024


class AuditPublicationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> object:
    raise ValueError("non-finite JSON number")


def _read_regular(path: Path, limit: int) -> bytes:
    current = Path(path.anchor)
    for part in path.absolute().parts[1:-1]:
        current /= part
        if current.is_symlink():
            raise ValueError("input path contains a symlink")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError("input path contains a symlink") from None
        raise
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("input is not a bounded regular file")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("input exceeds size limit")
        return data
    finally:
        os.close(descriptor)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def _safe_label(value: str) -> bool:
    lowered = value.lower()
    return not any(token in lowered for token in ("://", "\\", "/", "bearer ", "key=", "token="))


def load_audit_request(path: Path) -> AuditRequest:
    """Validate the bounded operator request; paths remain CLI-only."""
    try:
        raw = _read_regular(path, MAX_REQUEST_BYTES)
        data = json.loads(
            raw, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite
        )
        request = AuditRequest.model_validate(data)
    except (OSError, ValueError, ValidationError):
        raise AuditPublicationError("audit_request_invalid") from None
    if not (_safe_label(request.left_source.label) and _safe_label(request.right_source.label)):
        raise AuditPublicationError("audit_request_invalid")
    if request.window_start.second or request.window_start.microsecond:
        raise AuditPublicationError("audit_request_invalid")
    if request.window_end.second or request.window_end.microsecond:
        raise AuditPublicationError("audit_request_invalid")
    if not (
        timedelta(minutes=5) < request.window_end - request.window_start <= timedelta(days=7)
        and request.window_end <= request.data_as_of
    ):
        raise AuditPublicationError("audit_request_invalid")
    return request


def _validate_execution_time(request: AuditRequest, started_at: datetime) -> None:
    if started_at.tzinfo is None or request.data_as_of > started_at:
        raise AuditPublicationError("audit_request_invalid")
    for source in (request.left_source, request.right_source):
        if source.snapshot_created_at and source.snapshot_created_at > started_at:
            raise AuditPublicationError("audit_request_invalid")


def _read_index(path: Path) -> AuditIndex | None:
    try:
        raw = _read_regular(path, MAX_INDEX_BYTES)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise AuditPublicationError("audit_index_invalid") from None
    try:
        index = AuditIndex.model_validate_json(raw)
        keys = [
            (entry.target.venue_instrument_id, entry.target.venue_instrument_version_id)
            for entry in index.entries
        ]
        if keys != sorted(set(keys)):
            raise ValueError("index target order invalid")
        if any(entry.checked_at < entry.started_at for entry in index.entries):
            raise ValueError("index time order invalid")
        return index
    except (ValueError, ValidationError):
        raise AuditPublicationError("audit_index_invalid") from None


def _area_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise AuditPublicationError("audit_capacity_exceeded")
        if path.is_file():
            total += path.stat().st_size
            if total > MAX_AUDIT_AREA_BYTES:
                raise AuditPublicationError("audit_capacity_exceeded")
    return total


def _write_new(path: Path, data: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600
    )
    try:
        with os.fdopen(os.dup(descriptor), "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    if _read_regular(path, len(data)) != data:
        raise AuditPublicationError("audit_publish_failed")


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_index(
    path: Path,
    previous: AuditIndex | None,
    report: AuditReport,
) -> AuditIndex:
    entries = [] if previous is None else list(previous.entries)
    key = (report.target.venue_instrument_id, report.target.venue_instrument_version_id)
    prior = next(
        (
            entry
            for entry in entries
            if (entry.target.venue_instrument_id, entry.target.venue_instrument_version_id) == key
        ),
        None,
    )
    if prior is None or (report.started_at, report.run_id) >= (prior.started_at, prior.run_id):
        entries = [
            entry
            for entry in entries
            if (entry.target.venue_instrument_id, entry.target.venue_instrument_version_id) != key
        ]
        last_completed = None if prior is None else prior.last_completed_run_id
        entries.append(index_entry_from_report(report, last_completed_run_id=last_completed))
    entries.sort(
        key=lambda item: (item.target.venue_instrument_id, item.target.venue_instrument_version_id)
    )
    if len(entries) > 256:
        raise AuditPublicationError("audit_capacity_exceeded")
    index = AuditIndex(schema_version=1, generated_at=datetime.now(UTC), entries=tuple(entries))
    if len(_json_bytes(index.model_dump(mode="json", by_alias=True))) > MAX_INDEX_BYTES:
        raise AuditPublicationError("audit_capacity_exceeded")
    write_artifact_atomic(path, index)
    return index


def execute_and_publish(
    request: AuditRequest,
    *,
    request_path: Path,
    state_dir: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AuditReport:
    """Copy fixed inputs, evaluate copies, publish run, then advance the index."""
    started_at = clock().astimezone(UTC)
    _validate_execution_time(request, started_at)
    state_dir = state_dir.expanduser().resolve()
    area = state_dir / "candle-audits"
    if area.is_symlink() or (area / "runs").is_symlink():
        raise AuditPublicationError("audit_publish_failed")
    area.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_root = area / "runs"
    run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    index_path = state_dir / "artifacts" / "candle-audit-index.json"
    lock_path = area / "publish.lock"
    deadline = time.monotonic() + 5
    while True:
        try:
            with exclusive_runtime_lock(lock_path):
                return _execute_locked(
                    request,
                    request_path=request_path,
                    index_path=index_path,
                    area=area,
                    run_root=run_root,
                    started_at=started_at,
                    clock=clock,
                )
        except RuntimeLockUnavailable:
            if time.monotonic() >= deadline:
                raise AuditPublicationError("audit_lock_unavailable") from None
            time.sleep(0.1)


def _execute_locked(
    request: AuditRequest,
    *,
    request_path: Path,
    index_path: Path,
    area: Path,
    run_root: Path,
    started_at: datetime,
    clock: Callable[[], datetime],
) -> AuditReport:
    previous = _read_index(index_path)
    existing_bytes = _area_bytes(area)
    run_id = uuid4().hex
    staging = area / f".staging-{run_id}"
    staging.mkdir(mode=0o700)
    left_hash: str | None = None
    right_hash: str | None = None
    left_path = request_path.parent / request.left_path
    right_path = request_path.parent / request.right_path
    try:
        try:
            left_bytes = _read_regular(left_path, MAX_INPUT_BYTES)
            left_hash = hashlib.sha256(left_bytes).hexdigest()
            _write_new(staging / "left.snapshot.json", left_bytes)
            right_bytes = _read_regular(right_path, MAX_INPUT_BYTES)
            right_hash = hashlib.sha256(right_bytes).hexdigest()
            _write_new(staging / "right.snapshot.json", right_bytes)
            diagnostic = audit_snapshots(
                staging / "left.snapshot.json",
                staging / "right.snapshot.json",
                start=request.window_start,
                end=request.window_end,
                as_of=request.data_as_of,
                price_abs_tol=Decimal(request.tolerances.price_abs_tol),
                price_rel_tol=Decimal(request.tolerances.price_rel_tol),
                compare_volume_base=request.compare_volume_base,
                volume_abs_tol=Decimal(request.tolerances.volume_abs_tol),
                volume_rel_tol=Decimal(request.tolerances.volume_rel_tol),
                return_minutes=5,
                return_tol_bps=Decimal(request.tolerances.return_tol_bps),
            )
            report = build_audit_report(
                request,
                diagnostic,
                run_id=run_id,
                started_at=started_at,
                checked_at=max(clock().astimezone(UTC), started_at),
            )
        except OSError:
            diagnostic = {"errorCode": "audit_input_io_error"}
            report = build_failed_report(
                request,
                run_id=run_id,
                started_at=started_at,
                checked_at=max(clock().astimezone(UTC), started_at),
                execution="failed",
                error_code="audit_input_io_error",
                left_hash=left_hash,
                right_hash=right_hash,
            )
        except (ValueError, ValidationError) as error:
            code = (
                "audit_target_mismatch"
                if "target mismatch" in str(error)
                else "audit_series_mismatch"
                if "series_mismatch" in str(error)
                else "audit_input_invalid"
            )
            diagnostic = {"errorCode": code}
            report = build_failed_report(
                request,
                run_id=run_id,
                started_at=started_at,
                checked_at=max(clock().astimezone(UTC), started_at),
                execution="invalid_input",
                error_code=code,
                left_hash=left_hash,
                right_hash=right_hash,
            )

        public_request = request.model_dump(mode="json", by_alias=True)
        public_request.pop("leftPath")
        public_request.pop("rightPath")
        report_bytes = _json_bytes(report.model_dump(mode="json", by_alias=True))
        if len(report_bytes) > MAX_REPORT_BYTES:
            raise AuditPublicationError("audit_capacity_exceeded")
        output = {
            "request.public.json": _json_bytes(public_request),
            "diagnostic.json": _json_bytes(diagnostic),
            "report.json": report_bytes,
        }
        new_bytes = sum(len(data) for data in output.values())
        new_bytes += sum(path.stat().st_size for path in staging.iterdir())
        if existing_bytes + new_bytes > MAX_AUDIT_AREA_BYTES:
            raise AuditPublicationError("audit_capacity_exceeded")
        for name, data in output.items():
            _write_new(staging / name, data)
        _fsync_dir(staging)
        destination = run_root / run_id
        if destination.exists():
            raise AuditPublicationError("audit_publish_failed")
        os.rename(staging, destination)
        _fsync_dir(run_root)
        _publish_index(index_path, previous, report)
        return report
    except AuditPublicationError:
        raise
    except (OSError, ValueError, ValidationError):
        raise AuditPublicationError("audit_publish_failed") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="保存1分足の照合結果を不変ファイルとして公開する")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = load_audit_request(args.request)
        report = execute_and_publish(request, request_path=args.request, state_dir=args.state_dir)
    except AuditPublicationError as error:
        print(error.code, file=sys.stderr)
        return 2 if error.code == "audit_request_invalid" else 4
    except Exception:
        print("audit_publish_failed", file=sys.stderr)
        return 4
    print(
        json.dumps(
            {
                "runId": report.run_id,
                "execution": report.execution,
                "outcome": report.outcome,
                "errorCode": report.error_code,
            }
        )
    )
    if report.execution == "failed":
        return 4
    if report.execution == "invalid_input":
        return 2
    if report.outcome is None:
        return 4
    return {"match": 0, "differences": 1, "incomplete": 1, "unverified": 3}[report.outcome]


if __name__ == "__main__":
    raise SystemExit(main())
