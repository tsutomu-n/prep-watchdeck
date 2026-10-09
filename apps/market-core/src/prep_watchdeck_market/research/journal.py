"""Append-only observations with a separate post-publication readback receipt.

The receipt bounds when this reader knew these serialized DB rows. It never claims
exchange first availability or capture of producer revisions between polls.
"""

from __future__ import annotations

import fcntl
import math
import os
import re
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

from pydantic import ValidationError

from prep_watchdeck_market.bundle_files import (
    BundleError,
    json_bytes,
    sha256,
    strict_json,
    write_bundle,
)
from prep_watchdeck_market.research.files import isolated_root, load_json, model_bytes, read_leaf
from prep_watchdeck_market.research.models import (
    CODE_PATTERN,
    ID_PATTERN,
    MAX_FILE_BYTES,
    MAX_OBSERVATIONS,
    MAX_SNAPSHOT_BYTES,
    ObservationReceipt,
    ResearchPayload,
    ResearchTarget,
    instant,
    payload_reasons,
)


class ObservationJournal:
    def __init__(
        self,
        root: Path,
        *,
        max_gap_seconds: int = 120,
        clock_error_seconds: float = 1.0,
        excluded_roots: tuple[Path, ...] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.root = isolated_root(root, excluded_roots)
        if (
            type(max_gap_seconds) is not int
            or not 5 <= max_gap_seconds <= 3600
            or not math.isfinite(clock_error_seconds)
            or not 0 <= clock_error_seconds <= 30
        ):
            raise BundleError("research_policy_invalid")
        self.max_gap_seconds = max_gap_seconds
        self.clock_error_seconds = clock_error_seconds
        self.clock = clock
        self._lock: int | None = None
        self.receipts: list[ObservationReceipt] = []
        self.receipt_bytes: list[bytes] = []
        self.payloads: dict[str, bytes] = {}
        self.target: ResearchTarget | None = None
        self.session: dict[str, Any] = {}

    def __enter__(self) -> Self:
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._lock = os.open(
                self.root / ".writer.lock",
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
            )
            if not stat.S_ISREG(os.fstat(self._lock).st_mode):
                raise BundleError("research_path_invalid")
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BundleError("research_writer_busy") from None
            self._open_session()
            self._load()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_args: object) -> None:
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None

    def _open_session(self) -> None:
        path = self.root / "journal.json"
        if path.exists() or path.is_symlink():
            session = load_json(path)
            if (
                not isinstance(session, dict)
                or set(session)
                != {"schema_version", "journal_id", "max_gap_seconds", "clock_error_seconds"}
                or session["schema_version"] != 1
                or re.fullmatch(ID_PATTERN, str(session["journal_id"])) is None
                or session["max_gap_seconds"] != self.max_gap_seconds
                or session["clock_error_seconds"] != self.clock_error_seconds
            ):
                raise BundleError("research_journal_policy_mismatch")
            self.session = {**session, "clock_error_seconds": self.clock_error_seconds}
        else:
            self.session = {
                "schema_version": 1,
                "journal_id": uuid4().hex,
                "max_gap_seconds": self.max_gap_seconds,
                "clock_error_seconds": self.clock_error_seconds,
            }
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(json_bytes(self.session))
                stream.flush()
                os.fsync(stream.fileno())
        for name in ("observations", "receipts"):
            directory = self.root / name
            isolated_root(directory)
            directory.mkdir(exist_ok=True, mode=0o700)

    def _load(self) -> None:
        self.receipts = []
        self.receipt_bytes = []
        self.payloads = {}
        rows: list[tuple[ObservationReceipt, bytes]] = []
        for count, path in enumerate((self.root / "receipts").iterdir(), 1):
            if count > MAX_OBSERVATIONS or re.fullmatch(ID_PATTERN, path.name) is None:
                raise BundleError("research_journal_incomplete")
            raw = read_leaf(path, "receipt.json")
            try:
                receipt = ObservationReceipt.model_validate(strict_json(raw))
            except (ValidationError, RecursionError):
                raise BundleError("research_schema_invalid") from None
            if receipt.observation_id != path.name:
                raise BundleError("research_receipt_identity_mismatch")
            rows.append((receipt, raw))
        for receipt, raw in sorted(rows, key=lambda row: row[0].sequence):
            if receipt.sequence != len(self.receipts) + 1 or receipt.previous_receipt_sha256 != (
                sha256(self.receipt_bytes[-1]) if self.receipt_bytes else None
            ):
                raise BundleError("research_receipt_chain_invalid")
            if receipt.kind == "observation":
                payload_bytes = read_leaf(
                    self.root / "observations" / receipt.observation_id, "payload.json"
                )
                if sha256(payload_bytes) != receipt.payload_sha256:
                    raise BundleError("research_hash_mismatch")
                try:
                    payload = ResearchPayload.model_validate(strict_json(payload_bytes))
                except (ValidationError, RecursionError):
                    raise BundleError("research_schema_invalid") from None
                self._check_target(payload)
                self.payloads[receipt.observation_id] = payload_bytes
            self.receipts.append(receipt)
            self.receipt_bytes.append(raw)
        payload_ids = {path.name for path in (self.root / "observations").iterdir()}
        if payload_ids != set(self.payloads):
            raise BundleError("research_publication_incomplete")

    def _check_target(self, payload: ResearchPayload) -> None:
        target = payload.target
        if self.target is not None and target != self.target:
            raise BundleError("research_target_changed")
        self.target = target

    def _require_open(self) -> None:
        if self._lock is None:
            raise BundleError("research_journal_closed")
        if len(self.receipts) >= MAX_OBSERVATIONS:
            raise BundleError("research_observation_limit")

    def record(
        self,
        payload: ResearchPayload,
        *,
        read_started_at: datetime,
        read_completed_at: datetime,
        elapsed_seconds: float,
    ) -> ObservationReceipt:
        self._require_open()
        started, completed = instant(read_started_at), instant(read_completed_at)
        reasons = set(payload_reasons(payload, completed))
        self._check_target(payload)
        if not math.isfinite(elapsed_seconds) or not 0 <= elapsed_seconds <= 3600:
            raise BundleError("research_elapsed_invalid")
        if (
            completed < started
            or abs((completed - started).total_seconds() - elapsed_seconds)
            > self.clock_error_seconds
        ):
            reasons.add("research_clock_invalid")
        margin = timedelta(seconds=self.clock_error_seconds)
        if not started - margin <= payload.snapshot_at <= completed + margin:
            reasons.add("research_database_clock_skew")
        raw = model_bytes(payload)
        if (
            len(raw) > MAX_FILE_BYTES
            or sum(map(len, self.payloads.values())) + len(raw) > MAX_SNAPSHOT_BYTES - 2_000_000
        ):
            raise BundleError("research_size_exceeded")
        observation_id = uuid4().hex
        path = write_bundle(self.root / "observations", observation_id, {"payload.json": raw})
        if read_leaf(path, "payload.json") != raw:
            raise BundleError("research_readback_failed")
        # Deliberately sampled AFTER durable publication and readback of the exact payload.
        published = instant(self.clock())
        if published < completed:
            reasons.add("research_clock_invalid")
        receipt = self._receipt(
            observation_id, started, completed, published, elapsed_seconds, reasons, sha256(raw)
        )
        self._append(receipt)
        self.payloads[observation_id] = raw
        return receipt

    def record_failure(self, code: str, *, started_at: datetime) -> ObservationReceipt:
        self._require_open()
        if re.fullmatch(CODE_PATTERN, code) is None:
            raise BundleError("research_error_code_invalid")
        completed = instant(self.clock())
        started = instant(started_at)
        reasons = {code}
        if completed < started:
            reasons.add("research_clock_invalid")
        receipt = self._receipt(uuid4().hex, started, completed, completed, 0.0, reasons, None)
        self._append(receipt)
        return receipt

    def _receipt(
        self,
        observation_id: str,
        started: datetime,
        completed: datetime,
        published: datetime,
        elapsed: float,
        reasons: set[str],
        digest: str | None,
    ) -> ObservationReceipt:
        if self.receipts:
            previous = self.receipts[-1]
            delta = (started - previous.read_started_at).total_seconds()
            if delta < 0 or published < previous.payload_readback_completed_at:
                reasons.add("research_clock_invalid")
            if delta > self.max_gap_seconds:
                reasons.add("research_poll_gap")
            if (published - self.receipts[0].read_started_at) > timedelta(hours=24):
                reasons.add("research_capture_window_exceeded")
        return ObservationReceipt(
            observation_id=observation_id,
            sequence=len(self.receipts) + 1,
            kind="gap" if digest is None else "observation",
            payload_sha256=digest,
            previous_receipt_sha256=sha256(self.receipt_bytes[-1]) if self.receipt_bytes else None,
            read_started_at=started,
            read_completed_at=completed,
            payload_readback_completed_at=published,
            available_at=max(completed, published) + timedelta(seconds=self.clock_error_seconds),
            elapsed_seconds=elapsed,
            clock_error_seconds=self.clock_error_seconds,
            reasons=tuple(sorted(reasons)),
        )

    def _append(self, receipt: ObservationReceipt) -> None:
        raw = model_bytes(receipt)
        write_bundle(self.root / "receipts", receipt.observation_id, {"receipt.json": raw})
        self.receipts.append(receipt)
        self.receipt_bytes.append(raw)


def export_snapshot(journal_root: Path, output_dir: Path) -> Path:
    root = isolated_root(journal_root)
    output = isolated_root(output_dir, (root,))
    session = load_json(root / "journal.json")
    if not isinstance(session, dict):
        raise BundleError("research_schema_invalid")
    try:
        with ObservationJournal(
            root,
            max_gap_seconds=session["max_gap_seconds"],
            clock_error_seconds=float(session["clock_error_seconds"]),
        ) as journal:
            if not journal.receipts:
                raise BundleError("research_journal_empty")
            files: dict[str, bytes] = {}
            for receipt, raw in zip(journal.receipts, journal.receipt_bytes, strict=True):
                files[f"receipts/{receipt.observation_id}.json"] = raw
                if receipt.kind == "observation":
                    files[f"observations/{receipt.observation_id}.json"] = journal.payloads[
                        receipt.observation_id
                    ]
            manifest = {
                "schema_version": 1,
                "kind": "reader_observed_snapshot",
                "journal": journal.session,
                "target": None
                if journal.target is None
                else journal.target.model_dump(mode="json"),
                "receipt_count": len(journal.receipts),
                "files": {name: sha256(raw) for name, raw in sorted(files.items())},
                "producer_revision_complete": False,
                "exchange_first_available_at": None,
                "funding_coverage": "observed_rows_only",
                "context_scope": "local_validity_and_reader_observation",
            }
            files["manifest.json"] = json_bytes(manifest)
            from prep_watchdeck_market.research.snapshot import verify_snapshot

            return write_bundle(output, uuid4().hex, files, validate=verify_snapshot)
    except (KeyError, TypeError, ValueError):
        raise BundleError("research_schema_invalid") from None
