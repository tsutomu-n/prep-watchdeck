"""Bounded, read-only candle coverage evidence across historical contract versions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Self

import psycopg
from psycopg import Connection
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from prep_watchdeck_market.config import Settings, require_production_database_target

MINUTE = timedelta(minutes=1)
MAX_INSTRUMENTS = 2048
MAX_VERSIONS = 20_000
MAX_BUCKETS = 3_000_000
MAX_GAPS = 100_000
MAX_BYTES = 64 * 1024 * 1024


class EvidenceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, alias_generator=to_camel, populate_by_name=True
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps require an explicit timezone")
    return value.astimezone(UTC)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


class AuditScope(EvidenceModel):
    instrument_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_INSTRUMENTS)
    since: datetime
    until: datetime

    @field_validator("since", "until")
    @classmethod
    def minute_time(cls, value: datetime) -> datetime:
        value = _utc(value)
        if value.second or value.microsecond:
            raise ValueError("scope timestamps must be minute aligned")
        return value

    @field_validator("instrument_ids")
    @classmethod
    def identifiers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("scope contains duplicate instruments")
        for identity in value:
            venue, separator, symbol = identity.partition(":")
            if (
                venue not in {"aster", "bitget", "hyperliquid", "mexc"}
                or not separator
                or not symbol
                or len(symbol) > 100
                or any(ord(c) < 33 for c in symbol)
            ):
                raise ValueError("invalid scope instrument ID")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def bounded(self) -> Self:
        minutes = int((self.until - self.since).total_seconds() // 60)
        if not 0 < minutes <= 1440 or minutes * len(self.instrument_ids) > MAX_BUCKETS:
            raise ValueError("scope must contain at most 24 hours and bounded instruments")
        return self


class ContractRange(EvidenceModel):
    instrument_id: str
    version_id: int = Field(gt=0, strict=True)
    definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    valid_from: datetime
    valid_to: datetime | None

    @field_validator("valid_from", "valid_to")
    @classmethod
    def valid_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("invalid contract validity range")
        return self


class CandleKey(EvidenceModel):
    instrument_id: str
    version_id: int = Field(gt=0, strict=True)
    definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bucket: datetime

    @field_validator("bucket")
    @classmethod
    def minute_time(cls, value: datetime) -> datetime:
        return AuditScope.minute_time(value)


class Boundary(EvidenceModel):
    instrument_id: str
    bucket: datetime
    status: Literal["boundary_unresolved"] = "boundary_unresolved"
    contracts: tuple[ContractRange, ...] = Field(min_length=1)

    @field_validator("bucket")
    @classmethod
    def minute_time(cls, value: datetime) -> datetime:
        return AuditScope.minute_time(value)


class UnavailableRange(EvidenceModel):
    instrument_id: str
    since: datetime
    until: datetime
    status: Literal["catalog_unavailable"] = "catalog_unavailable"

    @field_validator("since", "until")
    @classmethod
    def minute_time(cls, value: datetime) -> datetime:
        return AuditScope.minute_time(value)


class TrackedGap(EvidenceModel):
    key: CandleKey
    status: Literal[
        "missing", "recovered", "definition_changed", "version_unavailable", "boundary_unresolved"
    ]


class HistoryAudit(EvidenceModel):
    schema_version: Literal["candle-gap-audit-v2"] = "candle-gap-audit-v2"
    scope: AuditScope
    scope_hash: str
    observed_at: datetime
    snapshot: str
    database_identity: str
    session_read_only: Literal[True] = True
    database_mutations: Literal[0] = 0
    provider_requests: Literal[0] = 0
    provider_status: Literal["not_queried"] = "not_queried"
    contract_ranges: tuple[ContractRange, ...]
    expected_minutes: int = Field(ge=0, le=MAX_BUCKETS, strict=True)
    present_minutes: int = Field(ge=0, le=MAX_BUCKETS, strict=True)
    missing: tuple[CandleKey, ...]
    boundaries: tuple[Boundary, ...]
    catalog_unavailable: tuple[UnavailableRange, ...]
    tracked_gaps: tuple[TrackedGap, ...]
    previous_evidence_hash: str | None
    evidence_hash: str

    @field_validator("observed_at")
    @classmethod
    def observation_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.observed_at < self.scope.until:
            raise ValueError("observation precedes the scope window")
        total = len(self.scope.instrument_ids) * int(
            (self.scope.until - self.scope.since).total_seconds() // 60
        )
        if (
            self.expected_minutes > total
            or self.present_minutes > self.expected_minutes
            or self.expected_minutes - self.present_minutes != len(self.missing)
            or (
                not self.boundaries
                and not self.catalog_unavailable
                and self.expected_minutes != total
            )
        ):
            raise ValueError("inconsistent coverage counts")
        versions = {item.version_id: item for item in self.contract_ranges}
        if len(versions) != len(self.contract_ranges) or len(versions) > MAX_VERSIONS:
            raise ValueError("duplicate or excessive contract versions")
        if any(item.instrument_id not in self.scope.instrument_ids for item in versions.values()):
            raise ValueError("contract outside requested scope")
        if not self.boundaries and not self.catalog_unavailable:
            by_instrument: dict[str, list[ContractRange]] = defaultdict(list)
            for contract in versions.values():
                by_instrument[contract.instrument_id].append(contract)
            for identity in self.scope.instrument_ids:
                covered_until = self.scope.since
                for contract in sorted(by_instrument[identity], key=lambda item: item.valid_from):
                    start = max(self.scope.since, contract.valid_from)
                    end = min(self.scope.until, contract.valid_to or self.scope.until)
                    if start >= end:
                        continue
                    if start != covered_until or end.second or end.microsecond:
                        raise ValueError(
                            "contract coverage requires a boundary or catalog interval"
                        )
                    covered_until = end
                if covered_until != self.scope.until:
                    raise ValueError("contract coverage does not span the scope")
        missing_keys = {_key(item) for item in self.missing}
        tracked = {_key(item.key): item.status for item in self.tracked_gaps}
        if len(missing_keys) != len(self.missing) or len(tracked) != len(self.tracked_gaps):
            raise ValueError("duplicate gap keys")
        if any(tracked.get(key) != "missing" for key in missing_keys):
            raise ValueError("missing gap has no matching unresolved tracking entry")
        for item in (*self.missing, *(entry.key for entry in self.tracked_gaps)):
            if item.instrument_id not in self.scope.instrument_ids or not (
                self.scope.since <= item.bucket < self.scope.until
            ):
                raise ValueError("gap outside requested scope")
        for item in (
            *self.missing,
            *(entry.key for entry in self.tracked_gaps if entry.status == "recovered"),
        ):
            version = versions.get(item.version_id)
            if (
                version is None
                or version.instrument_id != item.instrument_id
                or version.definition_hash != item.definition_hash
                or version.valid_from > item.bucket
                or (version.valid_to is not None and version.valid_to < item.bucket + MINUTE)
            ):
                raise ValueError("missing or recovered gap has no matching contract")
        if len({_boundary_key(item) for item in self.boundaries}) != len(self.boundaries):
            raise ValueError("duplicate boundary keys")
        for item in self.boundaries:
            if (
                item.instrument_id not in self.scope.instrument_ids
                or not self.scope.since <= item.bucket < self.scope.until
                or any(contract.instrument_id != item.instrument_id for contract in item.contracts)
            ):
                raise ValueError("boundary outside requested scope")
        for item in self.catalog_unavailable:
            if item.instrument_id not in self.scope.instrument_ids or not (
                self.scope.since <= item.since < item.until <= self.scope.until
            ):
                raise ValueError("catalog interval outside requested scope")
        if len(self.tracked_gaps) + len(self.boundaries) + len(self.catalog_unavailable) > MAX_GAPS:
            raise ValueError("gap evidence exceeds budget")
        return self

    @property
    def complete(self) -> bool:
        return not (
            self.missing
            or self.boundaries
            or self.catalog_unavailable
            or any(item.status != "recovered" for item in self.tracked_gaps)
        )


def _key(value: CandleKey) -> tuple[str, int, str, datetime]:
    return value.instrument_id, value.version_id, value.definition_hash, value.bucket


def _boundary_key(value: Boundary) -> tuple[str, datetime]:
    return value.instrument_id, value.bucket


def _content_hash(report: HistoryAudit) -> str:
    return _hash(report.model_dump(mode="json", by_alias=True, exclude={"evidence_hash"}))


def _check_previous(previous: HistoryAudit, scope: AuditScope, database_identity: str) -> None:
    if previous.scope != scope or previous.scope_hash != _hash(
        scope.model_dump(mode="json", by_alias=True)
    ):
        raise ValueError("previous evidence scope differs from requested scope")
    if previous.database_identity != database_identity:
        raise ValueError("previous evidence database differs")
    if previous.evidence_hash != _content_hash(previous):
        raise ValueError("previous evidence hash differs")


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise ValueError("audit exceeds time budget")


def build_audit(
    scope: AuditScope,
    ranges: tuple[ContractRange, ...],
    present: dict[int, set[datetime]],
    *,
    observed_at: datetime,
    snapshot: str,
    database_identity: str,
    previous: HistoryAudit | None = None,
    deadline: float | None = None,
) -> HistoryAudit:
    deadline = time.monotonic() + 60 if deadline is None else deadline
    _check_deadline(deadline)
    observed_at = _utc(observed_at)
    if scope.until > observed_at:
        raise ValueError("scope must end before the observation")
    if len(ranges) > MAX_VERSIONS or len({item.version_id for item in ranges}) != len(ranges):
        raise ValueError("duplicate or excessive contract versions")
    if any(item.instrument_id not in scope.instrument_ids for item in ranges):
        raise ValueError("contract outside requested scope")
    if previous is not None:
        _check_previous(previous, scope, database_identity)
        if observed_at < previous.observed_at:
            raise ValueError("observation precedes previous evidence")
    by_instrument: dict[str, list[ContractRange]] = defaultdict(list)
    for item in ranges:
        by_instrument[item.instrument_id].append(item)
    for values in by_instrument.values():
        values.sort(key=lambda item: (item.valid_from, item.version_id))
    missing: list[CandleKey] = []
    boundaries: dict[tuple[str, datetime], Boundary] = {}
    unavailable: list[UnavailableRange] = []
    expected = found = 0
    minutes = int((scope.until - scope.since).total_seconds() // 60)
    for identity in scope.instrument_ids:
        uncovered_start: datetime | None = None
        for index in range(minutes):
            if index % 256 == 0:
                _check_deadline(deadline)
            bucket = scope.since + index * MINUTE
            overlaps = tuple(
                item
                for item in by_instrument[identity]
                if item.valid_from < bucket + MINUTE
                and (item.valid_to is None or bucket < item.valid_to)
            )
            if not overlaps:
                if uncovered_start is None:
                    uncovered_start = bucket
                continue
            if uncovered_start is not None:
                unavailable.append(
                    UnavailableRange(instrument_id=identity, since=uncovered_start, until=bucket)
                )
                uncovered_start = None
            covering = tuple(
                item
                for item in overlaps
                if item.valid_from <= bucket
                and (item.valid_to is None or bucket + MINUTE <= item.valid_to)
            )
            if len(overlaps) != 1 or len(covering) != 1:
                boundary = Boundary(instrument_id=identity, bucket=bucket, contracts=overlaps)
                boundaries[_boundary_key(boundary)] = boundary
            else:
                contract = covering[0]
                expected += 1
                if bucket in present.get(contract.version_id, set()):
                    found += 1
                else:
                    missing.append(
                        CandleKey(
                            instrument_id=identity,
                            version_id=contract.version_id,
                            definition_hash=contract.definition_hash,
                            bucket=bucket,
                        )
                    )
            if len(missing) + len(boundaries) > MAX_GAPS:
                raise ValueError("gap evidence exceeds budget; narrow the explicit scope")
        if uncovered_start is not None:
            unavailable.append(
                UnavailableRange(instrument_id=identity, since=uncovered_start, until=scope.until)
            )

    tracking = {_key(item): item for item in missing}
    if previous is not None:
        tracking.update({_key(item): item for item in previous.missing})
        tracking.update({_key(item.key): item.key for item in previous.tracked_gaps})
        # A new catalog must never erase an earlier unresolved boundary/coverage interval.
        for item in previous.boundaries:
            key = _boundary_key(item)
            current = boundaries.get(key)
            if current is None:
                boundaries[key] = item
            else:
                versions = {
                    value.model_dump_json(): value
                    for value in (*item.contracts, *current.contracts)
                }
                boundaries[key] = item.model_copy(update={"contracts": tuple(versions.values())})
        intervals = {
            item.model_dump_json(): item for item in (*previous.catalog_unavailable, *unavailable)
        }
        unavailable = list(intervals.values())
    if len(tracking) + len(boundaries) + len(unavailable) > MAX_GAPS:
        raise ValueError("gap evidence exceeds budget; narrow the explicit scope")
    versions = {item.version_id: item for item in ranges}
    tracked = []
    for key in sorted(tracking):
        item = tracking[key]
        version = versions.get(item.version_id)
        if version is None or version.instrument_id != item.instrument_id:
            status = "version_unavailable"
        elif version.definition_hash != item.definition_hash:
            status = "definition_changed"
        elif version.valid_from > item.bucket or (
            version.valid_to is not None and version.valid_to < item.bucket + MINUTE
        ):
            status = "boundary_unresolved"
        elif item.bucket in present.get(item.version_id, set()):
            status = "recovered"
        else:
            status = "missing"
        tracked.append(TrackedGap(key=item, status=status))
    report = HistoryAudit(
        scope=scope,
        scope_hash=_hash(scope.model_dump(mode="json", by_alias=True)),
        observed_at=observed_at,
        snapshot=snapshot,
        database_identity=database_identity,
        contract_ranges=tuple(
            sorted(ranges, key=lambda item: (item.instrument_id, item.valid_from, item.version_id))
        ),
        expected_minutes=expected,
        present_minutes=found,
        missing=tuple(missing),
        boundaries=tuple(boundaries[key] for key in sorted(boundaries)),
        catalog_unavailable=tuple(unavailable),
        tracked_gaps=tuple(tracked),
        previous_evidence_hash=None if previous is None else previous.evidence_hash,
        evidence_hash="",
    )
    report = report.model_copy(update={"evidence_hash": _content_hash(report)})
    _check_deadline(deadline)
    return report


def audit_connection(
    connection: Connection[Any],
    scope: AuditScope,
    *,
    previous: HistoryAudit | None = None,
) -> HistoryAudit:
    """Use one read-only repeatable-read snapshot; never migrate or repair anything."""
    if not connection.autocommit:
        raise ValueError("audit requires a fresh autocommit connection")
    deadline = time.monotonic() + 60
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '15s'")
        connection.execute("SET LOCAL lock_timeout = '2s'")
        connection.execute("SET LOCAL idle_in_transaction_session_timeout = '30s'")
        meta = connection.execute(
            "SELECT statement_timestamp(), pg_current_snapshot()::text, "
            "current_setting('transaction_read_only'), current_database(), "
            "inet_server_addr()::text, inet_server_port(), "
            "(SELECT oid FROM pg_database WHERE datname=current_database()), "
            "'venue_instrument_versions'::regclass::oid, 'candle_1m'::regclass::oid"
        ).fetchone()
        if meta is None or meta[2] != "on":
            raise ValueError("read-only snapshot could not be established")
        database_identity = _hash(list(meta[3:]))
        if scope.until > meta[0]:
            raise ValueError("scope must end before the database snapshot")
        if previous is not None:
            _check_previous(previous, scope, database_identity)
        previous_ids = (
            []
            if previous is None
            else sorted(
                {item.key.version_id for item in previous.tracked_gaps}
                | {item.version_id for item in previous.missing}
            )
        )
        rows = connection.execute(
            "SELECT venue || ':' || source_symbol, venue_instrument_version_id, "
            "definition_hash, valid_from, valid_to FROM venue_instrument_versions "
            "WHERE venue || ':' || source_symbol = ANY(%s) AND "
            "((valid_from < %s AND (valid_to IS NULL OR valid_to > %s)) "
            "OR venue_instrument_version_id = ANY(%s)) "
            "ORDER BY venue, source_symbol, valid_from LIMIT %s",
            (list(scope.instrument_ids), scope.until, scope.since, previous_ids, MAX_VERSIONS + 1),
        ).fetchall()
        if len(rows) > MAX_VERSIONS:
            raise ValueError("contract scan exceeds budget")
        ranges = tuple(
            ContractRange(
                instrument_id=row[0],
                version_id=row[1],
                definition_hash=row[2].strip(),
                valid_from=row[3],
                valid_to=row[4],
            )
            for row in rows
        )
        present: dict[int, set[datetime]] = defaultdict(set)
        # A server cursor bounds client transfer batches; SQL has an independent total bound.
        with connection.cursor(name="candle_gap_audit") as cursor:
            cursor.execute(
                "SELECT venue_instrument_version_id, bucket_at FROM candle_1m "
                "WHERE venue_instrument_version_id = ANY(%s) AND bucket_at >= %s "
                "AND bucket_at < %s LIMIT %s",
                ([item.version_id for item in ranges], scope.since, scope.until, MAX_BUCKETS + 1),
            )
            for count, (version_id, bucket) in enumerate(cursor, 1):
                if count > MAX_BUCKETS:
                    raise ValueError("candle scan exceeds budget")
                if count % 2000 == 0 and time.monotonic() > deadline:
                    raise ValueError("candle scan exceeds time budget")
                present[version_id].add(bucket)
        if time.monotonic() > deadline:
            raise ValueError("audit exceeds time budget")
        return build_audit(
            scope,
            ranges,
            present,
            observed_at=meta[0],
            snapshot=meta[1],
            database_identity=database_identity,
            previous=previous,
            deadline=deadline,
        )


def load_evidence(path: Path) -> HistoryAudit:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("previous evidence must be a regular file")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("previous evidence exceeds size budget")
    report = HistoryAudit.model_validate_json(raw)
    _check_previous(report, report.scope, report.database_identity)
    return report


def write_evidence(path: Path, report: HistoryAudit) -> None:
    payload = (report.model_dump_json(by_alias=True, indent=2) + "\n").encode()
    if len(payload) > MAX_BYTES:
        raise ValueError("output exceeds size budget")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="inclusive ISO-8601 minute with timezone")
    parser.add_argument(
        "--until", required=True, help="exclusive ISO-8601 minute, at most 24h later"
    )
    parser.add_argument(
        "--instrument-id", action="append", default=[], help="explicit venue:symbol; repeatable"
    )
    parser.add_argument("--roster", type=Path, help="JSON array of explicit venue:symbol IDs")
    parser.add_argument(
        "--previous", type=Path, help="previous immutable ledger for the identical scope"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="new evidence path; overwrite refused"
    )
    args = parser.parse_args(argv)
    try:
        identifiers = list(args.instrument_id)
        if args.roster is not None:
            descriptor = os.open(args.roster, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("roster must be a regular file")
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("roster exceeds size budget")
            roster = json.loads(raw)
            if not isinstance(roster, list) or not all(isinstance(item, str) for item in roster):
                raise ValueError("roster must be an array of instrument IDs")
            identifiers.extend(roster)
        scope = AuditScope(instrument_ids=tuple(identifiers), since=args.since, until=args.until)
        previous = None if args.previous is None else load_evidence(args.previous)
        if previous is not None and previous.scope != scope:
            raise ValueError("previous evidence scope differs")
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError("output already exists")
        settings = Settings()
        # No allow_nonstandard_database_target bypass for this operator-facing audit.
        require_production_database_target(settings.database_url)
        with psycopg.connect(
            settings.database_url,
            autocommit=True,
            connect_timeout=5,
            options=(
                "-c default_transaction_read_only=on "
                "-c statement_timeout=15000 -c lock_timeout=2000"
            ),
        ) as connection:
            report = audit_connection(connection, scope, previous=previous)
        write_evidence(args.output, report)
        print(
            json.dumps(
                {
                    "output": str(args.output.absolute()),
                    "complete": report.complete,
                    "expectedMinutes": report.expected_minutes,
                    "missing": len(report.missing),
                    "boundaries": len(report.boundaries),
                    "catalogUnavailableRanges": len(report.catalog_unavailable),
                    "unresolvedTracked": sum(
                        item.status != "recovered" for item in report.tracked_gaps
                    ),
                    "evidenceHash": report.evidence_hash,
                }
            )
        )
        return 0 if report.complete else 1
    except (OSError, ValueError, psycopg.Error):
        # Configuration validation and driver errors can contain credential-bearing URLs.
        print(
            "candle history audit failed: invalid input, database, or output; no success evidence",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
