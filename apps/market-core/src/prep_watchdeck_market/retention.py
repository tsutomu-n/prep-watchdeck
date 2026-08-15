from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection

from prep_watchdeck_market.archive import ArchiveDataset, sha256_file
from prep_watchdeck_market.models import Venue

RAW_RETENTION = timedelta(days=7, hours=2)
NORMALIZED_RETENTION = timedelta(days=8)
DEFAULT_DELETE_BATCH_SIZE = 10_000


class RetentionError(RuntimeError):
    """Expired data could not be pruned safely."""


@dataclass(frozen=True, slots=True)
class RetentionResult:
    manifest_id: UUID | None
    normalized_deleted: int
    raw_deleted: int
    has_more: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class SelectedRetentionResult:
    raw_deleted: int
    depth_deleted: int
    trades_deleted: int
    leases_deleted: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class RawRetentionResult:
    deleted: int
    has_more: bool


def prune_archived_partition(
    connection: Connection[Any],
    archive_root: Path,
    *,
    dataset: ArchiveDataset,
    venue: Venue,
    partition_date: date,
    now: datetime,
    batch_size: int = DEFAULT_DELETE_BATCH_SIZE,
) -> RetentionResult:
    """Delete at most one bounded batch only while an intact manifest stays confirmed."""

    _require_aware(now)
    if not 0 < batch_size <= DEFAULT_DELETE_BATCH_SIZE:
        raise ValueError("retention batch_size must be between 1 and 10000")
    manifest = _confirmed_manifest(connection, dataset, venue, partition_date)
    if manifest is None:
        return RetentionResult(None, 0, 0, False, "confirmed_manifest_missing")
    manifest_id, relative_path, expected_sha256, confirmed_at = manifest
    archive_path = _safe_manifest_path(archive_root, relative_path)
    if not archive_path.is_file():
        return RetentionResult(manifest_id, 0, 0, False, "archive_file_missing")
    if sha256_file(archive_path) != expected_sha256:
        return RetentionResult(manifest_id, 0, 0, False, "archive_checksum_mismatch")

    try:
        with connection.transaction(), connection.cursor() as cursor:
            locked = cursor.execute(
                """
                    SELECT manifest_id
                    FROM archive_manifests
                    WHERE manifest_id = %s AND status = 'confirmed'
                      AND superseded_at IS NULL
                    FOR SHARE
                """,
                (manifest_id,),
            ).fetchone()
            if locked is None:
                return RetentionResult(manifest_id, 0, 0, False, "manifest_changed")
            if _has_late_correction(
                cursor,
                dataset=dataset,
                venue=venue,
                partition_date=partition_date,
                confirmed_at=confirmed_at,
            ):
                return RetentionResult(
                    manifest_id,
                    0,
                    0,
                    False,
                    "archive_stale_late_correction",
                )
            normalized_deleted = _delete_normalized(
                cursor,
                dataset=dataset,
                venue=venue,
                partition_date=partition_date,
                cutoff=now - NORMALIZED_RETENTION,
                archive_confirmed_at=confirmed_at,
                batch_size=batch_size,
            )
            raw_deleted = 0
    except psycopg.Error:
        raise RetentionError("archive-backed retention failed") from None

    return RetentionResult(
        manifest_id=manifest_id,
        normalized_deleted=normalized_deleted,
        raw_deleted=raw_deleted,
        has_more=normalized_deleted == batch_size or raw_deleted == batch_size,
        reason=None,
    )


def prune_raw_market_history(
    connection: Connection[Any],
    *,
    now: datetime,
    batch_size: int = DEFAULT_DELETE_BATCH_SIZE,
) -> RawRetentionResult:
    """Delete one bounded batch of intentionally ephemeral raw market observations."""

    _require_aware(now)
    if not 0 < batch_size <= DEFAULT_DELETE_BATCH_SIZE:
        raise ValueError("retention batch_size must be between 1 and 10000")
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(
                """
                    WITH doomed AS (
                        SELECT raw.tableoid, raw.ctid
                        FROM raw_market_observations AS raw
                        WHERE raw.observed_at < %s
                        ORDER BY raw.observed_at
                        LIMIT %s
                        FOR UPDATE OF raw SKIP LOCKED
                    )
                    DELETE FROM raw_market_observations AS raw
                    USING doomed
                    WHERE raw.tableoid = doomed.tableoid AND raw.ctid = doomed.ctid
                """,
                (now - RAW_RETENTION, batch_size),
            )
            deleted = int(cursor.rowcount)
    except psycopg.Error:
        raise RetentionError("raw market retention failed") from None
    return RawRetentionResult(deleted=deleted, has_more=deleted == batch_size)


def prune_selected_history(
    connection: Connection[Any],
    *,
    now: datetime,
    batch_size: int = DEFAULT_DELETE_BATCH_SIZE,
) -> SelectedRetentionResult:
    """Bound selected raw and inactive read-model history without touching an active lease."""

    _require_aware(now)
    if not 0 < batch_size <= DEFAULT_DELETE_BATCH_SIZE:
        raise ValueError("retention batch_size must be between 1 and 10000")
    raw_cutoff = now - RAW_RETENTION
    normalized_cutoff = now - NORMALIZED_RETENTION
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(
                """
                    WITH doomed AS (
                        SELECT raw.tableoid, raw.ctid
                        FROM selected_raw_observations AS raw
                        WHERE raw.observed_at < %s
                        ORDER BY raw.observed_at
                        LIMIT %s
                        FOR UPDATE OF raw SKIP LOCKED
                    )
                    DELETE FROM selected_raw_observations AS raw
                    USING doomed
                    WHERE raw.tableoid = doomed.tableoid AND raw.ctid = doomed.ctid
                """,
                (raw_cutoff, batch_size),
            )
            raw_deleted = int(cursor.rowcount)
            depth_deleted = _delete_selected_rows(
                cursor,
                table="selected_depth_levels",
                cutoff=normalized_cutoff,
                batch_size=batch_size,
            )
            trades_deleted = _delete_selected_rows(
                cursor,
                table="selected_trades",
                cutoff=normalized_cutoff,
                batch_size=batch_size,
            )
            cursor.execute(
                """
                    WITH doomed AS (
                        SELECT lease.ctid
                        FROM selected_group_leases AS lease
                        WHERE lease.superseded_at IS NOT NULL
                          AND COALESCE(lease.cleaned_at, lease.superseded_at) < %s
                          AND NOT EXISTS (
                              SELECT 1 FROM selected_raw_observations AS raw
                              WHERE raw.selection_id = lease.selection_id
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM selected_depth_levels AS depth
                              WHERE depth.selection_id = lease.selection_id
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM selected_trades AS trade
                              WHERE trade.selection_id = lease.selection_id
                          )
                        ORDER BY lease.superseded_at
                        LIMIT %s
                        FOR UPDATE OF lease SKIP LOCKED
                    )
                    DELETE FROM selected_group_leases AS lease
                    USING doomed
                    WHERE lease.ctid = doomed.ctid
                """,
                (normalized_cutoff, batch_size),
            )
            leases_deleted = int(cursor.rowcount)
    except psycopg.Error:
        raise RetentionError("selected history retention failed") from None
    return SelectedRetentionResult(
        raw_deleted=raw_deleted,
        depth_deleted=depth_deleted,
        trades_deleted=trades_deleted,
        leases_deleted=leases_deleted,
        has_more=any(
            count == batch_size
            for count in (raw_deleted, depth_deleted, trades_deleted, leases_deleted)
        ),
    )


def _delete_selected_rows(
    cursor: Any,
    *,
    table: str,
    cutoff: datetime,
    batch_size: int,
) -> int:
    if table == "selected_depth_levels":
        cursor.execute(
            """
                WITH doomed AS (
                    SELECT selected.ctid
                    FROM selected_depth_levels AS selected
                    JOIN selected_group_leases AS lease USING (selection_id)
                    WHERE lease.superseded_at IS NOT NULL
                      AND COALESCE(lease.cleaned_at, lease.superseded_at) < %s
                    ORDER BY lease.superseded_at
                    LIMIT %s
                    FOR UPDATE OF selected SKIP LOCKED
                )
                DELETE FROM selected_depth_levels AS selected
                USING doomed
                WHERE selected.ctid = doomed.ctid
            """,
            (cutoff, batch_size),
        )
    elif table == "selected_trades":
        cursor.execute(
            """
                WITH doomed AS (
                    SELECT selected.ctid
                    FROM selected_trades AS selected
                    JOIN selected_group_leases AS lease USING (selection_id)
                    WHERE lease.superseded_at IS NOT NULL
                      AND COALESCE(lease.cleaned_at, lease.superseded_at) < %s
                    ORDER BY lease.superseded_at
                    LIMIT %s
                    FOR UPDATE OF selected SKIP LOCKED
                )
                DELETE FROM selected_trades AS selected
                USING doomed
                WHERE selected.ctid = doomed.ctid
            """,
            (cutoff, batch_size),
        )
    else:
        raise ValueError("unsupported selected retention table")
    return int(cursor.rowcount)


def _confirmed_manifest(
    connection: Connection[Any],
    dataset: ArchiveDataset,
    venue: Venue,
    partition_date: date,
) -> tuple[UUID, str, str, datetime] | None:
    try:
        with connection.transaction():
            row = connection.execute(
                """
                    SELECT manifest_id, relative_path, sha256, confirmed_at
                    FROM archive_manifests
                    WHERE dataset = %s AND venue = %s AND partition_date = %s
                      AND status = 'confirmed' AND superseded_at IS NULL
                """,
                (dataset, venue, partition_date),
            ).fetchone()
    except psycopg.Error:
        raise RetentionError("confirmed archive manifest could not be read") from None
    if row is None:
        return None
    if not isinstance(row[3], datetime) or row[3].tzinfo is None:
        raise RetentionError("confirmed archive manifest has no valid timestamp")
    return UUID(str(row[0])), str(row[1]), str(row[2]).strip(), row[3]


def _has_late_correction(
    cursor: Any,
    *,
    dataset: ArchiveDataset,
    venue: Venue,
    partition_date: date,
    confirmed_at: datetime,
) -> bool:
    if dataset == "market_state_1m":
        row = cursor.execute(
            """
                SELECT 1
                FROM market_state_1m AS state
                JOIN venue_instrument_versions AS instrument
                  USING (venue_instrument_version_id)
                WHERE instrument.venue = %s
                  AND (state.bucket_at AT TIME ZONE 'UTC')::date = %s
                  AND state.last_observed_at > %s
                LIMIT 1
            """,
            (venue, partition_date, confirmed_at),
        ).fetchone()
    elif dataset == "candle_1m":
        row = cursor.execute(
            """
                SELECT 1
                FROM candle_1m AS candle
                JOIN venue_instrument_versions AS instrument
                  USING (venue_instrument_version_id)
                WHERE instrument.venue = %s
                  AND (candle.bucket_at AT TIME ZONE 'UTC')::date = %s
                  AND candle.observed_at > %s
                LIMIT 1
            """,
            (venue, partition_date, confirmed_at),
        ).fetchone()
    else:
        row = cursor.execute(
            """
                SELECT 1
                FROM funding_events AS funding
                JOIN venue_instrument_versions AS instrument
                  USING (venue_instrument_version_id)
                WHERE instrument.venue = %s
                  AND (funding.funding_at AT TIME ZONE 'UTC')::date = %s
                  AND funding.observed_at > %s
                LIMIT 1
            """,
            (venue, partition_date, confirmed_at),
        ).fetchone()
    return row is not None


def _delete_normalized(
    cursor: Any,
    *,
    dataset: ArchiveDataset,
    venue: Venue,
    partition_date: date,
    cutoff: datetime,
    archive_confirmed_at: datetime,
    batch_size: int,
) -> int:
    if dataset == "market_state_1m":
        cursor.execute(
            """
                WITH doomed AS (
                    SELECT state.ctid
                    FROM market_state_1m AS state
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = %s
                      AND (state.bucket_at AT TIME ZONE 'UTC')::date = %s
                      AND state.bucket_at < %s
                      AND state.last_observed_at <= %s
                    ORDER BY state.bucket_at
                    LIMIT %s
                    FOR UPDATE OF state SKIP LOCKED
                )
                DELETE FROM market_state_1m AS state
                USING doomed
                WHERE state.ctid = doomed.ctid
            """,
            (venue, partition_date, cutoff, archive_confirmed_at, batch_size),
        )
    elif dataset == "candle_1m":
        cursor.execute(
            """
                WITH doomed AS (
                    SELECT candle.ctid
                    FROM candle_1m AS candle
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = %s
                      AND (candle.bucket_at AT TIME ZONE 'UTC')::date = %s
                      AND candle.bucket_at < %s
                      AND candle.observed_at <= %s
                    ORDER BY candle.bucket_at
                    LIMIT %s
                    FOR UPDATE OF candle SKIP LOCKED
                )
                DELETE FROM candle_1m AS candle
                USING doomed
                WHERE candle.ctid = doomed.ctid
            """,
            (venue, partition_date, cutoff, archive_confirmed_at, batch_size),
        )
    else:
        cursor.execute(
            """
                WITH doomed AS (
                    SELECT funding.ctid
                    FROM funding_events AS funding
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = %s
                      AND (funding.funding_at AT TIME ZONE 'UTC')::date = %s
                      AND funding.funding_at < %s
                      AND funding.observed_at <= %s
                    ORDER BY funding.funding_at
                    LIMIT %s
                    FOR UPDATE OF funding SKIP LOCKED
                )
                DELETE FROM funding_events AS funding
                USING doomed
                WHERE funding.ctid = doomed.ctid
            """,
            (venue, partition_date, cutoff, archive_confirmed_at, batch_size),
        )
    return int(cursor.rowcount)


def _safe_manifest_path(archive_root: Path, relative_path: str) -> Path:
    root = archive_root.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise RetentionError("archive manifest path escapes its root")
    return candidate


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("retention now must be timezone-aware")
