from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, cast

import psycopg
from psycopg import Connection, sql

from prep_watchdeck_market.archive import ArchiveDataset, ArchiveResult, archive_partition
from prep_watchdeck_market.models import Venue
from prep_watchdeck_market.retention import (
    NORMALIZED_RETENTION,
    RawRetentionResult,
    RetentionResult,
    SelectedRetentionResult,
    prune_archived_partition,
    prune_raw_market_history,
    prune_selected_history,
)

ARCHIVE_DATASETS: tuple[ArchiveDataset, ...] = (
    "market_state_1m",
    "candle_1m",
    "funding_events",
)
ARCHIVE_VENUES: tuple[Venue, ...] = ("bitget", "hyperliquid", "aster")
MAX_RETENTION_PARTITIONS_PER_RUN = 30
MAX_NORMALIZED_DELETE_BATCHES_PER_RUN = 180
MAX_RAW_DELETE_BATCHES_PER_RUN = 10
MAX_SELECTED_DELETE_BATCHES_PER_RUN = 250
MAX_ARCHIVE_CATCHUP_DATES_PER_RUN = 3


class MaintenanceError(RuntimeError):
    """Hourly archive or bounded retention could not finish safely."""


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    partition_date: date
    archives: tuple[ArchiveResult, ...]
    retention: tuple[RetentionResult, ...]
    raw_retention: RawRetentionResult
    selected_retention: SelectedRetentionResult


def run_daily_maintenance(
    database_url: str,
    state_dir: Path,
    *,
    partition_date: date,
    now: datetime,
) -> MaintenanceResult:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("maintenance now must be timezone-aware")
    if partition_date >= now.date():
        raise ValueError("maintenance partition_date must be a completed UTC day")
    archive_root = state_dir / "archive"
    try:
        with psycopg.connect(database_url, connect_timeout=5, autocommit=True) as connection:
            archives: list[ArchiveResult] = []
            for archive_date in _archive_dates(
                connection,
                preferred_date=partition_date,
                today=now.date(),
            ):
                archives.extend(_archive_present_partitions(connection, archive_root, archive_date))
            retention = _drain_archived_retention(
                connection,
                archive_root,
                now,
                archives,
            )
            raw_retention = _drain_raw_market_retention(connection, now)
            selected_retention = _drain_selected_retention(connection, now)
    except (psycopg.Error, OSError, RuntimeError):
        raise MaintenanceError("market maintenance failed") from None
    return MaintenanceResult(
        partition_date=partition_date,
        archives=tuple(archives),
        retention=retention,
        raw_retention=raw_retention,
        selected_retention=selected_retention,
    )


def _archive_dates(
    connection: Connection[Any],
    *,
    preferred_date: date,
    today: date,
) -> tuple[date, ...]:
    before = datetime.combine(today, time.min, tzinfo=UTC)
    candidates: set[date] = set()
    for dataset in ARCHIVE_DATASETS:
        for venue in ARCHIVE_VENUES:
            missing = _oldest_unarchived_date(
                connection,
                dataset=dataset,
                venue=venue,
                before=before,
            )
            if missing is not None:
                candidates.add(missing)
    catchup = sorted(candidates)[:MAX_ARCHIVE_CATCHUP_DATES_PER_RUN]
    if preferred_date not in catchup:
        catchup.append(preferred_date)
    return tuple(catchup)


def _oldest_unarchived_date(
    connection: Connection[Any],
    *,
    dataset: ArchiveDataset,
    venue: Venue,
    before: datetime,
) -> date | None:
    if dataset == "market_state_1m":
        table = "market_state_1m"
        timestamp = "bucket_at"
    elif dataset == "candle_1m":
        table = "candle_1m"
        timestamp = "bucket_at"
    else:
        table = "funding_events"
        timestamp = "funding_at"
    query = sql.SQL(
        """
            SELECT (record.{timestamp} AT TIME ZONE 'UTC')::date
            FROM {table} AS record
            JOIN venue_instrument_versions AS instrument
              USING (venue_instrument_version_id)
            WHERE instrument.venue = %s
              AND record.{timestamp} < %s
              AND NOT EXISTS (
                SELECT 1
                FROM archive_manifests AS manifest
                WHERE manifest.dataset = %s
                  AND manifest.venue = %s
                  AND manifest.partition_date =
                      (record.{timestamp} AT TIME ZONE 'UTC')::date
                  AND manifest.status = 'confirmed'
                  AND manifest.superseded_at IS NULL
              )
            ORDER BY record.{timestamp}
            LIMIT 1
        """
    ).format(table=sql.Identifier(table), timestamp=sql.Identifier(timestamp))
    row = connection.execute(query, (venue, before, dataset, venue)).fetchone()
    if row is None:
        return None
    value = row[0]
    if not isinstance(value, date):
        raise MaintenanceError("archive source has an invalid partition date")
    return value


def _archive_present_partitions(
    connection: Connection[Any],
    archive_root: Path,
    partition_date: date,
) -> tuple[ArchiveResult, ...]:
    results: list[ArchiveResult] = []
    for dataset in ARCHIVE_DATASETS:
        for venue in ARCHIVE_VENUES:
            source_count, latest_observed_at = _partition_stats(
                connection, dataset, venue, partition_date
            )
            if source_count == 0:
                continue
            manifest = _active_manifest_state(connection, dataset, venue, partition_date)
            if manifest is not None:
                manifest_count, confirmed_at = manifest
                if latest_observed_at is None or latest_observed_at <= confirmed_at:
                    continue
                if source_count < manifest_count:
                    raise MaintenanceError(
                        "late correction arrived after archive retention had started"
                    )
            results.append(
                archive_partition(
                    connection,
                    archive_root,
                    dataset=dataset,
                    venue=venue,
                    partition_date=partition_date,
                )
            )
    return tuple(results)


def _partition_stats(
    connection: Connection[Any],
    dataset: ArchiveDataset,
    venue: Venue,
    partition_date: date,
) -> tuple[int, datetime | None]:
    if dataset == "market_state_1m":
        table = "market_state_1m"
        timestamp = "bucket_at"
        observed = "last_observed_at"
    elif dataset == "candle_1m":
        table = "candle_1m"
        timestamp = "bucket_at"
        observed = "observed_at"
    else:
        table = "funding_events"
        timestamp = "funding_at"
        observed = "observed_at"
    query = sql.SQL(
        """
            SELECT count(*), max(record.{observed})
            FROM {table} AS record
            JOIN venue_instrument_versions AS instrument
              USING (venue_instrument_version_id)
            WHERE instrument.venue = %s
              AND (record.{timestamp} AT TIME ZONE 'UTC')::date = %s
        """
    ).format(
        table=sql.Identifier(table),
        timestamp=sql.Identifier(timestamp),
        observed=sql.Identifier(observed),
    )
    row = connection.execute(query, (venue, partition_date)).fetchone()
    if row is None:
        raise MaintenanceError("archive source partition statistics are unavailable")
    latest = row[1]
    if latest is not None and (not isinstance(latest, datetime) or latest.tzinfo is None):
        raise MaintenanceError("archive source observation timestamp is invalid")
    return int(row[0]), latest


def _active_manifest_state(
    connection: Connection[Any],
    dataset: ArchiveDataset,
    venue: Venue,
    partition_date: date,
) -> tuple[int, datetime] | None:
    row = connection.execute(
        """
            SELECT row_count, confirmed_at
            FROM archive_manifests
            WHERE dataset = %s AND venue = %s AND partition_date = %s
              AND status = 'confirmed' AND superseded_at IS NULL
        """,
        (dataset, venue, partition_date),
    ).fetchone()
    if row is None:
        return None
    if not isinstance(row[1], datetime) or row[1].tzinfo is None:
        raise MaintenanceError("active archive manifest timestamp is invalid")
    return int(row[0]), row[1]


def _drain_archived_retention(
    connection: Connection[Any],
    archive_root: Path,
    now: datetime,
    archives: list[ArchiveResult],
) -> tuple[RetentionResult, ...]:
    results: list[RetentionResult] = []
    remaining_batches = MAX_NORMALIZED_DELETE_BATCHES_PER_RUN
    for dataset, venue, partition_date in _retention_targets(connection, now):
        total_deleted = 0
        manifest_id = None
        reason = None
        has_more = False
        rearchived = False
        while remaining_batches > 0:
            result = prune_archived_partition(
                connection,
                archive_root,
                dataset=dataset,
                venue=venue,
                partition_date=partition_date,
                now=now,
            )
            if result.reason == "archive_stale_late_correction":
                if rearchived:
                    raise MaintenanceError("archive remained stale after late-correction refresh")
                manifest = _active_manifest_state(connection, dataset, venue, partition_date)
                source_count, _latest = _partition_stats(connection, dataset, venue, partition_date)
                if manifest is None or source_count < manifest[0]:
                    raise MaintenanceError(
                        "late correction arrived after archive retention had started"
                    )
                archives.append(
                    archive_partition(
                        connection,
                        archive_root,
                        dataset=dataset,
                        venue=venue,
                        partition_date=partition_date,
                    )
                )
                rearchived = True
                continue
            manifest_id = result.manifest_id
            reason = result.reason
            total_deleted += result.normalized_deleted
            has_more = result.has_more
            remaining_batches -= 1
            if reason is not None or not has_more:
                break
        results.append(
            RetentionResult(
                manifest_id=manifest_id,
                normalized_deleted=total_deleted,
                raw_deleted=0,
                has_more=has_more,
                reason=reason,
            )
        )
        if remaining_batches == 0:
            break
    return tuple(results)


def _drain_raw_market_retention(
    connection: Connection[Any],
    now: datetime,
) -> RawRetentionResult:
    deleted = 0
    has_more = False
    for _ in range(MAX_RAW_DELETE_BATCHES_PER_RUN):
        result = prune_raw_market_history(connection, now=now)
        deleted += result.deleted
        has_more = result.has_more
        if not has_more:
            break
    return RawRetentionResult(deleted=deleted, has_more=has_more)


def _drain_selected_retention(
    connection: Connection[Any],
    now: datetime,
) -> SelectedRetentionResult:
    raw_deleted = 0
    depth_deleted = 0
    trades_deleted = 0
    leases_deleted = 0
    has_more = False
    for _ in range(MAX_SELECTED_DELETE_BATCHES_PER_RUN):
        result = prune_selected_history(connection, now=now)
        raw_deleted += result.raw_deleted
        depth_deleted += result.depth_deleted
        trades_deleted += result.trades_deleted
        leases_deleted += result.leases_deleted
        has_more = result.has_more
        if not has_more:
            break
    return SelectedRetentionResult(
        raw_deleted=raw_deleted,
        depth_deleted=depth_deleted,
        trades_deleted=trades_deleted,
        leases_deleted=leases_deleted,
        has_more=has_more,
    )


def _retention_targets(
    connection: Connection[Any],
    now: datetime,
) -> tuple[tuple[ArchiveDataset, Venue, date], ...]:
    normalized_cutoff = now - NORMALIZED_RETENTION
    rows = connection.execute(
        """
            SELECT manifest.dataset, manifest.venue, manifest.partition_date
            FROM archive_manifests AS manifest
            WHERE manifest.status = 'confirmed' AND manifest.superseded_at IS NULL
              AND (
                (
                  manifest.dataset = 'market_state_1m'
                  AND EXISTS (
                    SELECT 1
                    FROM market_state_1m AS state
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = manifest.venue
                      AND (state.bucket_at AT TIME ZONE 'UTC')::date =
                          manifest.partition_date
                      AND state.bucket_at < %s
                  )
                )
                OR (
                  manifest.dataset = 'candle_1m'
                  AND EXISTS (
                    SELECT 1
                    FROM candle_1m AS candle
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = manifest.venue
                      AND (candle.bucket_at AT TIME ZONE 'UTC')::date =
                          manifest.partition_date
                      AND candle.bucket_at < %s
                  )
                )
                OR (
                  manifest.dataset = 'funding_events'
                  AND EXISTS (
                    SELECT 1
                    FROM funding_events AS funding
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = manifest.venue
                      AND (funding.funding_at AT TIME ZONE 'UTC')::date =
                          manifest.partition_date
                      AND funding.funding_at < %s
                  )
                )
              )
            ORDER BY manifest.partition_date, manifest.dataset, manifest.venue
            LIMIT %s
        """,
        (
            normalized_cutoff,
            normalized_cutoff,
            normalized_cutoff,
            MAX_RETENTION_PARTITIONS_PER_RUN,
        ),
    ).fetchall()
    targets: list[tuple[ArchiveDataset, Venue, date]] = []
    for dataset_value, venue_value, date_value in rows:
        dataset = str(dataset_value)
        venue = str(venue_value)
        if dataset not in ARCHIVE_DATASETS or venue not in ARCHIVE_VENUES:
            raise MaintenanceError("archive manifest has an unsupported retention target")
        if not isinstance(date_value, date):
            raise MaintenanceError("archive manifest has an invalid partition date")
        targets.append((cast(ArchiveDataset, dataset), cast(Venue, venue), date_value))
    return tuple(targets)
