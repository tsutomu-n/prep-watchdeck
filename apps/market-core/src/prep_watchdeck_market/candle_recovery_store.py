from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from prep_watchdeck_market.candles import Candle1m, require_utc_datetime
from prep_watchdeck_market.models import Venue


class RecoveryStoreError(RuntimeError):
    """A bounded recovery database operation failed."""


class RecoveryVersionChanged(RecoveryStoreError):
    """The current catalog definition changed after the recovery scan."""


@dataclass(frozen=True, slots=True)
class RecoveryTarget:
    version_id: int
    venue: Venue
    source_symbol: str
    definition_hash: str
    valid_from: datetime
    base_asset: str
    quote_asset: str
    settle_asset: str

    @property
    def instrument_id(self) -> str:
        return f"{self.venue}:{self.source_symbol}"


def load_recovery_targets(
    connection: Connection[Any],
    *,
    venue: Venue | None = None,
    instrument_id: str | None = None,
) -> tuple[RecoveryTarget, ...]:
    """Read only current active crypto linear perpetual definitions."""
    try:
        rows = connection.execute(
            """
                SELECT venue_instrument_version_id, venue, source_symbol,
                       definition_hash, valid_from, base_asset, quote_asset, settle_asset
                FROM venue_instrument_versions
                WHERE valid_to IS NULL AND active
                  AND asset_class = 'crypto' AND market_type = 'linear_perpetual'
                  AND venue IN ('bitget', 'hyperliquid', 'aster')
                  AND (%s::text IS NULL OR venue = %s)
                  AND (%s::text IS NULL OR venue || ':' || source_symbol = %s)
                ORDER BY venue, source_symbol, venue_instrument_version_id
            """,
            (venue, venue, instrument_id, instrument_id),
        ).fetchall()
    except psycopg.Error:
        raise RecoveryStoreError("recovery targets unavailable") from None
    return tuple(
        RecoveryTarget(
            version_id=int(row[0]),
            venue=row[1],
            source_symbol=row[2],
            definition_hash=row[3],
            valid_from=row[4],
            base_asset=row[5],
            quote_asset=row[6],
            settle_asset=row[7],
        )
        for row in rows
    )


def target_window_start(target: RecoveryTarget, start: datetime) -> datetime:
    """Exclude minutes that begin before the exact current definition starts."""
    require_utc_datetime(start, field_name="recovery window start")
    valid_from = target.valid_from.astimezone(UTC)
    if valid_from.second or valid_from.microsecond:
        valid_from = valid_from.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return max(start, valid_from)


def scan_missing_candles(
    connection: Connection[Any],
    target: RecoveryTarget,
    *,
    start: datetime,
    end: datetime,
) -> tuple[datetime, ...]:
    """Compare every expected minute with DB rows for one exact version."""
    require_utc_datetime(end, field_name="recovery window end")
    first = target_window_start(target, start)
    if first >= end:
        return ()
    minutes = int((end - first).total_seconds() // 60)
    if minutes > 1440 or end != first + timedelta(minutes=minutes):
        raise ValueError("recovery scan window must be aligned and at most 24 hours")
    try:
        rows = connection.execute(
            """
                SELECT bucket_at FROM candle_1m
                WHERE venue_instrument_version_id = %s
                  AND bucket_at >= %s AND bucket_at < %s
                ORDER BY bucket_at
            """,
            (target.version_id, first, end),
        ).fetchall()
    except psycopg.Error:
        raise RecoveryStoreError("recovery scan unavailable") from None
    present = {row[0] for row in rows}
    return tuple(
        bucket
        for index in range(minutes)
        if (bucket := first + timedelta(minutes=index)) not in present
    )


def insert_missing_candles(
    connection: Connection[Any],
    target: RecoveryTarget,
    candles: Sequence[Candle1m],
    *,
    run_id: UUID,
) -> int:
    """Lock the exact version, then insert only absent rows in one short transaction."""
    if not candles:
        return 0
    buckets = [candle.bucket_start for candle in candles]
    if len(buckets) != len(set(buckets)):
        raise ValueError("recovery batch contains duplicate buckets")
    if any(
        candle.venue != target.venue
        or candle.source_symbol != target.source_symbol
        or candle.bucket_start < target_window_start(target, candle.bucket_start)
        or (target.venue == "bitget" and candle.finality != "confirmed")
        or (target.venue != "bitget" and candle.finality != "derived_final")
        for candle in candles
    ):
        raise ValueError("recovery batch does not match its target")
    try:
        with connection.transaction(), connection.cursor() as cursor:
            row = cursor.execute(
                """
                    SELECT definition_hash, valid_from, active, valid_to,
                           asset_class, market_type, venue, source_symbol,
                           base_asset, quote_asset, settle_asset
                    FROM venue_instrument_versions
                    WHERE venue_instrument_version_id = %s
                    FOR SHARE
                """,
                (target.version_id,),
            ).fetchone()
            if row != (
                target.definition_hash,
                target.valid_from,
                True,
                None,
                "crypto",
                "linear_perpetual",
                target.venue,
                target.source_symbol,
                target.base_asset,
                target.quote_asset,
                target.settle_asset,
            ):
                raise RecoveryVersionChanged("recovery target definition changed")
            for day in {candle.bucket_start.date() for candle in candles}:
                manifest = cursor.execute(
                    """
                        SELECT row_count FROM archive_manifests
                        WHERE dataset = 'candle_1m' AND venue = %s
                          AND partition_date = %s AND status = 'confirmed'
                          AND superseded_at IS NULL
                        FOR SHARE
                    """,
                    (target.venue, day),
                ).fetchone()
                if manifest is None:
                    continue
                day_start = datetime.combine(day, time.min, tzinfo=UTC)
                current = cursor.execute(
                    """
                        SELECT count(*) FROM candle_1m AS candle
                        JOIN venue_instrument_versions AS instrument
                          USING (venue_instrument_version_id)
                        WHERE instrument.venue = %s
                          AND candle.bucket_at >= %s
                          AND candle.bucket_at < %s
                    """,
                    (target.venue, day_start, day_start + timedelta(days=1)),
                ).fetchone()
                if current is None or int(current[0]) < int(manifest[0]):
                    raise RecoveryStoreError("archive retention has started for this day")
            inserted = 0
            for candle in candles:
                inserted += cursor.execute(
                    """
                        INSERT INTO candle_1m (
                            venue_instrument_version_id, bucket_at,
                            open_price, high_price, low_price, close_price,
                            volume_base, volume_notional, trade_count, finality,
                            source_at, observed_at, finalized_at, collector_run_id
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (venue_instrument_version_id, bucket_at) DO NOTHING
                    """,
                    (
                        target.version_id,
                        candle.bucket_start,
                        candle.open_price,
                        candle.high_price,
                        candle.low_price,
                        candle.close_price,
                        candle.volume_base,
                        candle.volume_notional,
                        candle.trade_count,
                        candle.finality,
                        candle.source_at,
                        candle.observed_at,
                        candle.finalized_at,
                        run_id,
                    ),
                ).rowcount
        return inserted
    except RecoveryVersionChanged:
        raise
    except psycopg.Error:
        raise RecoveryStoreError("recovery insert failed") from None


def start_recovery_run(
    connection: Connection[Any],
    run_id: UUID,
    started_at: datetime,
    *,
    metrics: dict[str, object],
) -> None:
    try:
        connection.execute(
            """
                INSERT INTO collector_runs (
                    run_id, run_kind, started_at, status, metrics
                ) VALUES (%s, 'candle_recovery', %s, 'running', %s)
            """,
            (run_id, started_at, Jsonb(metrics)),
        )
    except psycopg.Error:
        raise RecoveryStoreError("recovery run could not start") from None


def finish_recovery_run(
    connection: Connection[Any],
    run_id: UUID,
    finished_at: datetime,
    *,
    status: str,
    received: int,
    inserted: int,
    error_code: str | None,
    metrics: dict[str, object],
) -> None:
    if status not in {"succeeded", "partial", "failed"}:
        raise ValueError("invalid recovery run status")
    try:
        connection.execute(
            """
                UPDATE collector_runs
                SET completed_at = %s, status = %s, records_received = %s,
                    records_written = %s, error_code = %s, metrics = %s
                WHERE run_id = %s AND status = 'running'
            """,
            (finished_at, status, received, inserted, error_code, Jsonb(metrics), run_id),
        )
    except psycopg.Error:
        raise RecoveryStoreError("recovery run could not finish") from None
