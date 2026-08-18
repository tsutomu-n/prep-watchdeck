from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from prep_watchdeck_market.market_store import DATABASE_TIMEOUT_OPTIONS
from prep_watchdeck_market.models import (
    CatalogInstrument,
    QuantityUnit,
    Venue,
    canonical_json_sha256,
)
from prep_watchdeck_market.sources.funding import FundingBatch, FundingEvent


class FundingStoreError(RuntimeError):
    """Settled funding events could not be persisted without exposing credentials."""


class FundingConflictError(FundingStoreError):
    """The same Venue event timestamp was observed with incompatible values."""


@dataclass(frozen=True, slots=True)
class FundingFailure:
    venue: Venue
    source_symbol: str
    error_code: str


@dataclass(frozen=True, slots=True)
class FundingCatalogSnapshot:
    instruments: tuple[CatalogInstrument, ...]
    version_starts: Mapping[str, datetime]


@dataclass(frozen=True, slots=True)
class FundingStoreResult:
    run_id: UUID
    status: str
    records_received: int
    records_written: int
    records_unchanged: int
    raw_payloads_written: int
    admission_rejected: int
    commit_seconds: float


@dataclass(frozen=True, slots=True)
class _InstrumentVersion:
    version_id: int
    venue: Venue
    source_symbol: str
    valid_from: datetime
    valid_to: datetime | None
    funding_interval_seconds: int | None


FailureSequence = Sequence[FundingFailure]


def load_funding_catalog_url(database_url: str) -> FundingCatalogSnapshot:
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=5,
            options=DATABASE_TIMEOUT_OPTIONS,
        ) as connection:
            return load_funding_catalog(connection)
    except FundingStoreError:
        raise
    except (psycopg.Error, OSError):
        raise FundingStoreError("funding catalog could not be loaded") from None


def load_funding_catalog(connection: Connection[Any]) -> FundingCatalogSnapshot:
    try:
        with connection.transaction(), connection.cursor() as cursor:
            rows = cursor.execute(
                """
                    SELECT venue_instrument_version_id, venue, source_symbol, valid_from,
                           active, source_status, asset_class, market_type, execution_model,
                           base_asset, quote_asset, settle_asset, collateral_asset,
                           quantity_unit, contract_multiplier, price_tick, amount_step,
                           funding_interval_seconds, raw_definition
                    FROM venue_instrument_versions
                    WHERE valid_to IS NULL AND active = true
                      AND market_type = 'linear_perpetual'
                    ORDER BY venue, source_symbol
                    FOR SHARE
                """
            ).fetchall()
    except psycopg.Error:
        raise FundingStoreError("funding catalog query failed") from None

    instruments: list[CatalogInstrument] = []
    version_starts: dict[str, datetime] = {}
    for row in rows:
        venue = _venue(str(row[1]))
        raw_definition = row[18] if isinstance(row[18], dict) else {}
        instrument = CatalogInstrument(
            venue=venue,
            source_symbol=str(row[2]),
            active=bool(row[4]),
            source_status=str(row[5] or "unknown"),
            asset_class=str(row[6]),
            market_type=str(row[7]),
            execution_model=str(row[8]),
            base_asset=str(row[9]),
            quote_asset=str(row[10]),
            settle_asset=str(row[11]),
            collateral_asset=None if row[12] is None else str(row[12]),
            quantity_unit=_quantity_unit(str(row[13])),
            contract_multiplier=row[14],
            price_tick=row[15],
            amount_step=row[16],
            funding_interval_seconds=None if row[17] is None else int(row[17]),
            raw_definition=dict(raw_definition),
        )
        instruments.append(instrument)
        version_starts[instrument.venue_instrument_id] = row[3]
    return FundingCatalogSnapshot(
        instruments=tuple(instruments),
        version_starts=version_starts,
    )


def load_latest_funding_times_url(database_url: str) -> dict[str, datetime]:
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=5,
            options=DATABASE_TIMEOUT_OPTIONS,
        ) as connection:
            return load_latest_funding_times(connection)
    except FundingStoreError:
        raise
    except (psycopg.Error, OSError):
        raise FundingStoreError("latest funding state could not be loaded") from None


def load_latest_funding_times(connection: Connection[Any]) -> dict[str, datetime]:
    try:
        with connection.transaction(), connection.cursor() as cursor:
            rows = cursor.execute(
                """
                    SELECT instrument.venue, instrument.source_symbol,
                           max(funding.funding_at)
                    FROM funding_events AS funding
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    GROUP BY instrument.venue, instrument.source_symbol
                """
            ).fetchall()
    except psycopg.Error:
        raise FundingStoreError("latest funding state query failed") from None
    return {
        f"{row[0]}:{row[1]}": row[2]
        for row in rows
        if isinstance(row[2], datetime)
    }


def persist_funding_sweep_url(
    database_url: str,
    started_at: datetime,
    batches: Sequence[FundingBatch],
    failures: FailureSequence = (),
) -> FundingStoreResult:
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=5,
            options=DATABASE_TIMEOUT_OPTIONS,
        ) as connection:
            return persist_funding_sweep(
                connection,
                started_at,
                batches,
                failures,
            )
    except (FundingStoreError, ValueError):
        raise
    except (psycopg.Error, OSError):
        raise FundingStoreError("funding sweep database connection failed") from None


def persist_funding_sweep(
    connection: Connection[Any],
    started_at: datetime,
    batches: Sequence[FundingBatch],
    failures: FailureSequence = (),
) -> FundingStoreResult:
    _require_aware(started_at, "started_at")
    _validate_batches(batches)
    run_id = uuid4()
    transaction_started = perf_counter()
    records_received = sum(len(batch.events) for batch in batches)
    status = "failed"
    raw_written = 0
    records_written = 0
    records_unchanged = 0
    admission_rejected = 0

    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(
                """
                    INSERT INTO collector_runs (
                        run_id, run_kind, venue, started_at, status,
                        records_received, metrics
                    )
                    VALUES (%s, 'funding', NULL, %s, 'running', %s, %s)
                """,
                (run_id, started_at, records_received, Jsonb({})),
            )
            versions = _load_versions(cursor, batches)
            current_versions = {
                (item.venue, item.source_symbol): item.version_id
                for values in versions.values()
                for item in values
                if item.valid_to is None
            }

            for batch in batches:
                current_version_id = current_versions.get((batch.venue, batch.source_symbol))
                source_at = max((item.funding_at for item in batch.events), default=None)
                cursor.execute(
                    """
                        INSERT INTO raw_market_observations (
                            observed_date, collector_run_id,
                            venue_instrument_version_id, venue, source_symbol,
                            dataset, observed_at, source_at, payload_hash, payload
                        )
                        VALUES (%s, %s, %s, %s, %s, 'funding_history',
                                %s, %s, %s, %s)
                    """,
                    (
                        batch.observed_at.astimezone(UTC).date(),
                        run_id,
                        current_version_id,
                        batch.venue,
                        batch.source_symbol,
                        batch.observed_at,
                        source_at,
                        batch.payload_hash,
                        Jsonb(batch.raw_payload),
                    ),
                )
                raw_written += 1

                version_candidates = versions.get((batch.venue, batch.source_symbol), ())
                for event in batch.events:
                    version = _version_covering(event, version_candidates)
                    if version is None:
                        admission_rejected += 1
                        continue
                    outcome = _upsert_event(cursor, run_id, version, event)
                    if outcome == "written":
                        records_written += 1
                    else:
                        records_unchanged += 1

            if not batches:
                status = "failed"
            elif failures or admission_rejected:
                status = "partial"
            else:
                status = "succeeded"
            completed_at = max(datetime.now(UTC), started_at)
            error_code = None
            if status == "failed":
                error_code = "funding_all_sources_failed"
            elif status == "partial":
                error_code = "funding_partial_failure"
            cursor.execute(
                """
                    UPDATE collector_runs
                    SET completed_at = %s, status = %s, records_written = %s,
                        error_code = %s, metrics = metrics || %s::jsonb
                    WHERE run_id = %s
                """,
                (
                    completed_at,
                    status,
                    records_written,
                    error_code,
                    Jsonb(
                        {
                            "admissionRejected": admission_rejected,
                            "rawPayloadsWritten": raw_written,
                            "recordsUnchanged": records_unchanged,
                            "sourceFailures": [
                                {
                                    "venue": item.venue,
                                    "sourceSymbol": item.source_symbol,
                                    "errorCode": item.error_code,
                                }
                                for item in failures
                            ],
                        }
                    ),
                    run_id,
                ),
            )
    except (FundingStoreError, ValueError):
        raise
    except psycopg.Error:
        raise FundingStoreError("funding sweep persistence failed") from None

    return FundingStoreResult(
        run_id=run_id,
        status=status,
        records_received=records_received,
        records_written=records_written,
        records_unchanged=records_unchanged,
        raw_payloads_written=raw_written,
        admission_rejected=admission_rejected,
        commit_seconds=perf_counter() - transaction_started,
    )


def _load_versions(
    cursor: Any,
    batches: Sequence[FundingBatch],
) -> dict[tuple[Venue, str], tuple[_InstrumentVersion, ...]]:
    requested = sorted({(batch.venue, batch.source_symbol) for batch in batches})
    if not requested:
        return {}
    venues = [item[0] for item in requested]
    symbols = [item[1] for item in requested]
    rows = cursor.execute(
        """
            WITH requested (venue, source_symbol) AS (
                SELECT * FROM unnest(%s::text[], %s::text[])
            )
            SELECT instrument.venue_instrument_version_id,
                   instrument.venue, instrument.source_symbol,
                   instrument.valid_from, instrument.valid_to,
                   instrument.funding_interval_seconds
            FROM venue_instrument_versions AS instrument
            JOIN requested
              ON requested.venue = instrument.venue
             AND requested.source_symbol = instrument.source_symbol
            ORDER BY instrument.venue, instrument.source_symbol, instrument.valid_from
            FOR SHARE OF instrument
        """,
        (venues, symbols),
    ).fetchall()
    grouped: dict[tuple[Venue, str], list[_InstrumentVersion]] = {}
    for row in rows:
        venue = _venue(str(row[1]))
        item = _InstrumentVersion(
            version_id=int(row[0]),
            venue=venue,
            source_symbol=str(row[2]),
            valid_from=row[3],
            valid_to=row[4],
            funding_interval_seconds=(None if row[5] is None else int(row[5])),
        )
        grouped.setdefault((venue, item.source_symbol), []).append(item)
    return {key: tuple(values) for key, values in grouped.items()}


def _version_covering(
    event: FundingEvent,
    versions: Sequence[_InstrumentVersion],
) -> _InstrumentVersion | None:
    candidates = tuple(
        item
        for item in versions
        if item.valid_from <= event.funding_at
        and (item.valid_to is None or event.funding_at < item.valid_to)
    )
    if len(candidates) > 1:
        raise FundingStoreError("funding event matches multiple instrument versions")
    return candidates[0] if candidates else None


def _upsert_event(
    cursor: Any,
    run_id: UUID,
    version: _InstrumentVersion,
    event: FundingEvent,
) -> str:
    existing = cursor.execute(
        """
            SELECT funding_rate_raw, funding_interval_seconds
            FROM funding_events
            WHERE venue_instrument_version_id = %s AND funding_at = %s
            FOR UPDATE
        """,
        (version.version_id, event.funding_at),
    ).fetchone()
    if existing is not None:
        if Decimal(existing[0]) != event.funding_rate_raw:
            raise FundingConflictError("settled funding rate changed for an existing event")
        existing_interval = None if existing[1] is None else int(existing[1])
        if (
            existing_interval is not None
            and version.funding_interval_seconds is not None
            and existing_interval != version.funding_interval_seconds
        ):
            raise FundingConflictError("funding interval changed for an existing event")
        return "unchanged"

    interval = version.funding_interval_seconds
    cursor.execute(
        """
            INSERT INTO funding_events (
                venue_instrument_version_id, funding_at, funding_rate_raw,
                funding_interval_seconds, funding_rate_per_hour,
                source_at, observed_at, collector_run_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            version.version_id,
            event.funding_at,
            event.funding_rate_raw,
            interval,
            _funding_per_hour(event.funding_rate_raw, interval),
            event.funding_at,
            event.observed_at,
            run_id,
        ),
    )
    return "written"


def _validate_batches(batches: Sequence[FundingBatch]) -> None:
    keys: set[tuple[Venue, str]] = set()
    for batch in batches:
        _require_aware(batch.observed_at, "batch observed_at")
        key = (batch.venue, batch.source_symbol)
        if key in keys:
            raise ValueError("funding sweep contains duplicate instrument batches")
        keys.add(key)
        if canonical_json_sha256(batch.raw_payload) != batch.payload_hash:
            raise ValueError("funding batch payload hash does not match its raw payload")
        for event in batch.events:
            _require_aware(event.funding_at, "funding_at")
            _require_aware(event.observed_at, "event observed_at")
            if event.venue != batch.venue or event.source_symbol != batch.source_symbol:
                raise ValueError("funding event identity does not match its batch")
            if event.observed_at != batch.observed_at:
                raise ValueError("funding event observation time does not match its batch")


def _funding_per_hour(rate: Decimal, interval_seconds: int | None) -> Decimal | None:
    if interval_seconds is None:
        return None
    return rate * Decimal(3_600) / Decimal(interval_seconds)


def _quantity_unit(value: str) -> QuantityUnit:
    if value == "base":
        return "base"
    if value == "contracts":
        return "contracts"
    return "unknown"


def _venue(value: str) -> Venue:
    if value == "bitget":
        return "bitget"
    if value == "hyperliquid":
        return "hyperliquid"
    if value == "aster":
        return "aster"
    raise FundingStoreError("database returned an unsupported Venue")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
