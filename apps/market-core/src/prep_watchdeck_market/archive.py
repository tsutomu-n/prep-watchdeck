from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import polars as pl
import psycopg
from psycopg import Connection

from prep_watchdeck_market.models import Venue

ArchiveDataset = Literal["market_state_1m", "candle_1m", "funding_events"]
ArchiveStatus = Literal["confirmed"]
_SUPPORTED_DATASETS = {"market_state_1m", "candle_1m", "funding_events"}
_SUPPORTED_VENUES = {"bitget", "hyperliquid", "aster"}
_SCHEMA_VERSION = 1
_PART_FILE_NAME = "part-0000.parquet"


class ArchiveError(RuntimeError):
    """A partition could not be archived and confirmed safely."""


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    manifest_id: UUID
    dataset: ArchiveDataset
    venue: Venue
    partition_date: date
    generation: int
    status: ArchiveStatus
    relative_path: str
    schema_version: int
    row_count: int
    unique_key_columns: tuple[str, ...]
    min_timestamp: datetime
    max_timestamp: datetime
    sha256: str


@dataclass(frozen=True, slots=True)
class _PartitionRows:
    columns: tuple[str, ...]
    unique_key_columns: tuple[str, ...]
    timestamp_column: str
    rows: tuple[tuple[Any, ...], ...]


def archive_partition(
    connection: Connection[Any],
    archive_root: Path,
    *,
    dataset: ArchiveDataset,
    venue: Venue,
    partition_date: date,
) -> ArchiveResult:
    """Write and verify one immutable Parquet file, then atomically switch its manifest."""

    _validate_partition(dataset, venue)
    root = archive_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    partition = _fetch_partition(connection, dataset, venue, partition_date)
    if not partition.rows:
        raise ArchiveError("archive partition has no source rows")
    min_timestamp, max_timestamp = _source_bounds(partition)
    source_digest = _rows_digest(partition.columns, partition.rows)

    staging_directory = root / ".staging" / uuid4().hex
    staging_directory.mkdir(parents=True, exist_ok=False)
    staging_path = staging_directory / _PART_FILE_NAME
    manifest_id: UUID | None = None
    final_path: Path | None = None
    confirmed = False
    try:
        frame = pl.DataFrame(
            partition.rows,
            schema=list(partition.columns),
            orient="row",
            strict=False,
        )
        frame.write_parquet(staging_path, compression="zstd", statistics=True)
        _verify_readback(
            staging_path,
            partition,
            expected_min=min_timestamp,
            expected_max=max_timestamp,
            expected_rows_digest=source_digest,
        )
        file_digest = sha256_file(staging_path)

        manifest_id, generation, relative_path = _stage_manifest(
            connection,
            dataset=dataset,
            venue=venue,
            partition_date=partition_date,
            row_count=len(partition.rows),
            unique_key_columns=partition.unique_key_columns,
            min_timestamp=min_timestamp,
            max_timestamp=max_timestamp,
            file_digest=file_digest,
        )
        final_path = _safe_archive_path(root, relative_path)
        final_path.parent.mkdir(parents=True, exist_ok=False)
        staging_path.replace(final_path)
        superseded_paths = _confirm_manifest(
            connection,
            manifest_id=manifest_id,
            dataset=dataset,
            venue=venue,
            partition_date=partition_date,
        )
        confirmed = True
        _prune_superseded_files(root, superseded_paths)
        return ArchiveResult(
            manifest_id=manifest_id,
            dataset=dataset,
            venue=venue,
            partition_date=partition_date,
            generation=generation,
            status="confirmed",
            relative_path=relative_path,
            schema_version=_SCHEMA_VERSION,
            row_count=len(partition.rows),
            unique_key_columns=partition.unique_key_columns,
            min_timestamp=min_timestamp,
            max_timestamp=max_timestamp,
            sha256=file_digest,
        )
    except ArchiveError:
        if manifest_id is not None and not confirmed:
            failed = _mark_manifest_failed(connection, manifest_id)
            if failed:
                _remove_unconfirmed_file(final_path)
        raise
    except (OSError, psycopg.Error, pl.exceptions.PolarsError):
        if manifest_id is not None and not confirmed:
            failed = _mark_manifest_failed(connection, manifest_id)
            if failed:
                _remove_unconfirmed_file(final_path)
        raise ArchiveError("archive partition could not be confirmed") from None
    finally:
        staging_path.unlink(missing_ok=True)
        try:
            staging_directory.rmdir()
            staging_directory.parent.rmdir()
        except OSError:
            pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch_partition(
    connection: Connection[Any],
    dataset: ArchiveDataset,
    venue: Venue,
    partition_date: date,
) -> _PartitionRows:
    start = datetime.combine(partition_date, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    with connection.transaction(), connection.cursor() as cursor:
        if dataset == "market_state_1m":
            columns = (
                "venue_instrument_version_id",
                "venue",
                "source_symbol",
                "bucket_at",
                "status",
                "first_observed_at",
                "last_observed_at",
                "source_at",
                "sample_count",
                "mark_price",
                "reference_price",
                "reference_price_kind",
                "best_bid",
                "best_ask",
                "funding_rate_raw",
                "funding_interval_seconds",
                "funding_rate_per_hour",
                "open_interest_raw",
                "open_interest_raw_unit",
                "open_interest_base",
                "open_interest_notional",
                "volume_24h_raw",
                "volume_24h_unit",
            )
            cursor.execute(
                """
                    SELECT state.venue_instrument_version_id, instrument.venue,
                           instrument.source_symbol, state.bucket_at, state.status,
                           state.first_observed_at, state.last_observed_at, state.source_at,
                           state.sample_count, state.mark_price, state.reference_price,
                           state.reference_price_kind, state.best_bid, state.best_ask,
                           state.funding_rate_raw, state.funding_interval_seconds,
                           state.funding_rate_per_hour, state.open_interest_raw,
                           state.open_interest_raw_unit, state.open_interest_base,
                           state.open_interest_notional, state.volume_24h_raw,
                           state.volume_24h_unit
                    FROM market_state_1m AS state
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = %s
                      AND state.bucket_at >= %s AND state.bucket_at < %s
                    ORDER BY state.venue_instrument_version_id, state.bucket_at
                """,
                (venue, start, end),
            )
            keys = ("venue_instrument_version_id", "bucket_at")
            timestamp_column = "bucket_at"
        elif dataset == "candle_1m":
            columns = (
                "venue_instrument_version_id",
                "venue",
                "source_symbol",
                "bucket_at",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "volume_base",
                "volume_notional",
                "trade_count",
                "finality",
                "source_at",
                "observed_at",
            )
            cursor.execute(
                """
                    SELECT candle.venue_instrument_version_id, instrument.venue,
                           instrument.source_symbol, candle.bucket_at, candle.open_price,
                           candle.high_price, candle.low_price, candle.close_price,
                           candle.volume_base, candle.volume_notional, candle.trade_count,
                           candle.finality, candle.source_at, candle.observed_at
                    FROM candle_1m AS candle
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = %s
                      AND candle.bucket_at >= %s AND candle.bucket_at < %s
                    ORDER BY candle.venue_instrument_version_id, candle.bucket_at
                """,
                (venue, start, end),
            )
            keys = ("venue_instrument_version_id", "bucket_at")
            timestamp_column = "bucket_at"
        else:
            columns = (
                "venue_instrument_version_id",
                "venue",
                "source_symbol",
                "funding_at",
                "funding_rate_raw",
                "funding_interval_seconds",
                "funding_rate_per_hour",
                "source_at",
                "observed_at",
            )
            cursor.execute(
                """
                    SELECT funding.venue_instrument_version_id, instrument.venue,
                           instrument.source_symbol, funding.funding_at,
                           funding.funding_rate_raw, funding.funding_interval_seconds,
                           funding.funding_rate_per_hour, funding.source_at,
                           funding.observed_at
                    FROM funding_events AS funding
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = %s
                      AND funding.funding_at >= %s AND funding.funding_at < %s
                    ORDER BY funding.venue_instrument_version_id, funding.funding_at
                """,
                (venue, start, end),
            )
            keys = ("venue_instrument_version_id", "funding_at")
            timestamp_column = "funding_at"
        rows = tuple(tuple(row) for row in cursor.fetchall())
    return _PartitionRows(columns, keys, timestamp_column, rows)


def _source_bounds(partition: _PartitionRows) -> tuple[datetime, datetime]:
    timestamp_index = partition.columns.index(partition.timestamp_column)
    timestamps = tuple(_as_utc(row[timestamp_index]) for row in partition.rows)
    return min(timestamps), max(timestamps)


def _verify_readback(
    path: Path,
    source: _PartitionRows,
    *,
    expected_min: datetime,
    expected_max: datetime,
    expected_rows_digest: str,
) -> None:
    frame = pl.read_parquet(path)
    if frame.columns != list(source.columns) or frame.height != len(source.rows):
        raise ArchiveError("Parquet readback schema or row count mismatch")
    key_rows = frame.select(list(source.unique_key_columns)).rows()
    canonical_keys = {tuple(_canonical_scalar(value) for value in row) for row in key_rows}
    if len(canonical_keys) != frame.height:
        raise ArchiveError("Parquet readback contains duplicate unique keys")
    readback_rows = tuple(tuple(row) for row in frame.select(list(source.columns)).rows())
    if _rows_digest(source.columns, readback_rows) != expected_rows_digest:
        raise ArchiveError("Parquet readback row checksum mismatch")
    timestamps = tuple(
        _as_utc(value) for value in frame.get_column(source.timestamp_column).to_list()
    )
    if min(timestamps) != expected_min or max(timestamps) != expected_max:
        raise ArchiveError("Parquet readback timestamp bounds mismatch")


def _stage_manifest(
    connection: Connection[Any],
    *,
    dataset: ArchiveDataset,
    venue: Venue,
    partition_date: date,
    row_count: int,
    unique_key_columns: tuple[str, ...],
    min_timestamp: datetime,
    max_timestamp: datetime,
    file_digest: str,
) -> tuple[UUID, int, str]:
    manifest_id = uuid4()
    lock_key = f"archive:{dataset}:{venue}:{partition_date.isoformat()}"
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
        row = cursor.execute(
            """
                SELECT COALESCE(max(generation), 0) + 1
                FROM archive_manifests
                WHERE dataset = %s AND venue = %s AND partition_date = %s
            """,
            (dataset, venue, partition_date),
        ).fetchone()
        if row is None:
            raise ArchiveError("archive generation could not be allocated")
        generation = int(row[0])
        relative_path = (
            f"dataset={dataset}/venue={venue}/date={partition_date.isoformat()}/"
            f"generation={generation:06d}/{_PART_FILE_NAME}"
        )
        cursor.execute(
            """
                INSERT INTO archive_manifests (
                    manifest_id, dataset, venue, partition_date, generation, status,
                    relative_path, schema_version, row_count, unique_key_columns,
                    min_timestamp, max_timestamp, sha256, created_at
                )
                VALUES (%s, %s, %s, %s, %s, 'staged', %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                manifest_id,
                dataset,
                venue,
                partition_date,
                generation,
                relative_path,
                _SCHEMA_VERSION,
                row_count,
                list(unique_key_columns),
                min_timestamp,
                max_timestamp,
                file_digest,
                datetime.now(UTC),
            ),
        )
    return manifest_id, generation, relative_path


def _confirm_manifest(
    connection: Connection[Any],
    *,
    manifest_id: UUID,
    dataset: ArchiveDataset,
    venue: Venue,
    partition_date: date,
) -> tuple[str, ...]:
    lock_key = f"archive:{dataset}:{venue}:{partition_date.isoformat()}"
    confirmed_at = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
        staged = cursor.execute(
            """
                SELECT generation
                FROM archive_manifests
                WHERE manifest_id = %s AND status = 'staged'
                FOR UPDATE
            """,
            (manifest_id,),
        ).fetchone()
        if staged is None:
            raise ArchiveError("staged archive manifest could not be confirmed")
        generation = int(staged[0])
        newer_confirmed = cursor.execute(
            """
                SELECT 1
                FROM archive_manifests
                WHERE dataset = %s AND venue = %s AND partition_date = %s
                  AND status = 'confirmed' AND superseded_at IS NULL
                  AND generation > %s
            """,
            (dataset, venue, partition_date, generation),
        ).fetchone()
        if newer_confirmed is not None:
            raise ArchiveError("a newer archive generation is already confirmed")
        cursor.execute(
            """
                UPDATE archive_manifests
                SET status = 'superseded', superseded_at = %s
                WHERE dataset = %s AND venue = %s AND partition_date = %s
                  AND status = 'confirmed' AND superseded_at IS NULL
                  AND generation < %s
            """,
            (confirmed_at, dataset, venue, partition_date, generation),
        )
        cursor.execute(
            """
                UPDATE archive_manifests
                SET status = 'confirmed', confirmed_at = %s
                WHERE manifest_id = %s AND status = 'staged'
            """,
            (confirmed_at, manifest_id),
        )
        if cursor.rowcount != 1:
            raise ArchiveError("staged archive manifest could not be confirmed")
        superseded_paths = tuple(
            str(row[0])
            for row in cursor.execute(
                """
                    SELECT relative_path
                    FROM archive_manifests
                    WHERE dataset = %s AND venue = %s AND partition_date = %s
                      AND status = 'superseded'
                    ORDER BY generation DESC
                    OFFSET 3
                """,
                (dataset, venue, partition_date),
            ).fetchall()
        )
    return superseded_paths


def _mark_manifest_failed(connection: Connection[Any], manifest_id: UUID) -> bool:
    try:
        with connection.transaction():
            result = connection.execute(
                """
                    UPDATE archive_manifests
                    SET status = 'failed', error_code = 'archive_confirmation_failed'
                    WHERE manifest_id = %s AND status = 'staged'
                """,
                (manifest_id,),
            )
        return result.rowcount == 1
    except psycopg.Error:
        return False


def _remove_unconfirmed_file(path: Path | None) -> None:
    if path is None:
        return
    path.unlink(missing_ok=True)
    with suppress(OSError):
        path.parent.rmdir()


def _prune_superseded_files(root: Path, relative_paths: Sequence[str]) -> None:
    for relative_path in relative_paths:
        path = _safe_archive_path(root, relative_path)
        path.unlink(missing_ok=True)
        with suppress(OSError):
            path.parent.rmdir()


def _rows_digest(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    canonical_rows = [
        {column: _canonical_scalar(value) for column, value in zip(columns, row, strict=True)}
        for row in rows
    ]
    payload = json.dumps(canonical_rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _canonical_scalar(value: Any) -> object:
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, UUID):
        return str(value)
    return value


def _as_utc(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ArchiveError("archive timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _safe_archive_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise ArchiveError("archive path escapes its root")
    return candidate


def _validate_partition(dataset: str, venue: str) -> None:
    if dataset not in _SUPPORTED_DATASETS:
        raise ValueError("unsupported archive dataset")
    if venue not in _SUPPORTED_VENUES:
        raise ValueError("unsupported archive Venue")
