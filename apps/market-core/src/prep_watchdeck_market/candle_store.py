from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection

from prep_watchdeck_market.candles import Candle1m


class CandleStoreError(RuntimeError):
    """Candle persistence failed without exposing connection credentials."""


class UnknownCandleInstrumentError(CandleStoreError):
    def __init__(self, venue_instrument_ids: Sequence[str]) -> None:
        self.venue_instrument_ids = tuple(sorted(set(venue_instrument_ids)))
        super().__init__(
            f"{len(self.venue_instrument_ids)} candle instrument(s) have no unambiguous "
            "catalog version covering the full minute"
        )

    @property
    def count(self) -> int:
        return len(self.venue_instrument_ids)


@dataclass(frozen=True, slots=True)
class CandleStoreResult:
    received: int
    stored: int
    ignored: int


def upsert_candles(
    connection: Connection[Any],
    candles: Sequence[Candle1m],
    *,
    collector_run_id: UUID | None = None,
) -> CandleStoreResult:
    """Atomically store normalized candles against their temporal catalog versions."""

    if not candles:
        return CandleStoreResult(received=0, stored=0, ignored=0)
    keys = [candle.storage_key for candle in candles]
    if len(keys) != len(set(keys)):
        raise ValueError("candle batch contains duplicate storage keys")

    try:
        with connection.transaction(), connection.cursor() as cursor:
            versions = _versions_covering_candles(cursor, candles)
            unknown = [
                candle.venue_instrument_id
                for candle in candles
                if candle.storage_key not in versions
            ]
            if unknown:
                raise UnknownCandleInstrumentError(unknown)

            stored = 0
            for candle in candles:
                version_id = versions[candle.storage_key]
                cursor.execute(
                    """
                        INSERT INTO candle_1m (
                            venue_instrument_version_id, bucket_at,
                            open_price, high_price, low_price, close_price,
                            volume_base, volume_notional, trade_count, finality,
                            source_at, observed_at, collector_run_id
                        )
                        VALUES (
                            %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s
                        )
                        ON CONFLICT (venue_instrument_version_id, bucket_at) DO UPDATE SET
                            open_price = EXCLUDED.open_price,
                            high_price = EXCLUDED.high_price,
                            low_price = EXCLUDED.low_price,
                            close_price = EXCLUDED.close_price,
                            volume_base = EXCLUDED.volume_base,
                            volume_notional = EXCLUDED.volume_notional,
                            trade_count = EXCLUDED.trade_count,
                            finality = EXCLUDED.finality,
                            source_at = EXCLUDED.source_at,
                            observed_at = EXCLUDED.observed_at,
                            collector_run_id = EXCLUDED.collector_run_id
                        WHERE
                            (
                                candle_1m.finality = 'derived_final'
                                AND EXCLUDED.finality = 'confirmed'
                            )
                            OR (
                                candle_1m.finality = EXCLUDED.finality
                                AND EXCLUDED.observed_at > candle_1m.observed_at
                            )
                    """,
                    (
                        version_id,
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
                        collector_run_id,
                    ),
                )
                stored += int(cursor.rowcount)
        return CandleStoreResult(
            received=len(candles),
            stored=stored,
            ignored=len(candles) - stored,
        )
    except (CandleStoreError, ValueError):
        raise
    except psycopg.Error:
        raise CandleStoreError("candle persistence failed") from None


def load_current_candle_version_starts(
    connection: Connection[Any],
) -> dict[str, datetime]:
    """Load the persisted start of every current catalog version."""

    try:
        with connection.transaction(), connection.cursor() as cursor:
            rows = cursor.execute(
                """
                    SELECT venue, source_symbol, valid_from
                    FROM venue_instrument_versions
                    WHERE valid_to IS NULL
                    FOR SHARE
                """
            ).fetchall()
        return {f"{row[0]}:{row[1]}": row[2] for row in rows}
    except psycopg.Error:
        raise CandleStoreError("current candle catalog versions could not be loaded") from None


def _versions_covering_candles(
    cursor: Any,
    candles: Sequence[Candle1m],
) -> dict[tuple[str, str, datetime], int]:
    requested = sorted({candle.storage_key for candle in candles})
    venues = [venue for venue, _, _ in requested]
    symbols = [source_symbol for _, source_symbol, _ in requested]
    buckets = [bucket_at for _, _, bucket_at in requested]
    rows = cursor.execute(
        """
            WITH requested (venue, source_symbol, bucket_at) AS (
                SELECT * FROM unnest(%s::text[], %s::text[], %s::timestamptz[])
            )
            SELECT requested.venue, requested.source_symbol, requested.bucket_at,
                   vi.venue_instrument_version_id
            FROM venue_instrument_versions AS vi
            JOIN requested AS requested
              ON requested.venue = vi.venue
             AND requested.source_symbol = vi.source_symbol
             AND vi.valid_from <= requested.bucket_at
             AND (
                 vi.valid_to IS NULL
                 OR requested.bucket_at + interval '1 minute' <= vi.valid_to
             )
            FOR SHARE OF vi
        """,
        (venues, symbols, buckets),
    ).fetchall()
    versions: dict[tuple[str, str, datetime], int] = {}
    ambiguous: set[tuple[str, str, datetime]] = set()
    for row in rows:
        key = (str(row[0]), str(row[1]), row[2])
        if key in versions:
            ambiguous.add(key)
        versions[key] = int(row[3])
    for key in ambiguous:
        del versions[key]
    return versions
