from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from prep_watchdeck_market.market_state import MarketBatch, MarketObservation
from prep_watchdeck_market.models import canonical_json_sha256

RunStatus = Literal["succeeded", "partial", "failed"]
DATABASE_TIMEOUT_OPTIONS = "-c statement_timeout=20000 -c transaction_timeout=20000"


class MarketStoreError(RuntimeError):
    """A market cycle could not be committed without exposing database credentials."""


@dataclass(frozen=True, slots=True)
class MarketStoreResult:
    run_id: UUID
    status: RunStatus
    records_received: int
    records_written: int
    raw_payloads_written: int
    unknown_source_rows: int
    commit_seconds: float


def persist_market_cycle_url(
    database_url: str,
    cycle_at: datetime,
    started_at: datetime,
    batches: Sequence[MarketBatch],
) -> MarketStoreResult:
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=5,
            options=DATABASE_TIMEOUT_OPTIONS,
        ) as connection:
            return persist_market_cycle(connection, cycle_at, started_at, batches)
    except MarketStoreError:
        raise
    except (psycopg.Error, OSError):
        raise MarketStoreError("market cycle database connection failed") from None


def persist_market_cycle(
    connection: Connection[Any],
    cycle_at: datetime,
    started_at: datetime,
    batches: Sequence[MarketBatch],
) -> MarketStoreResult:
    _validate_cycle(cycle_at, started_at, batches)
    run_id = uuid4()
    transaction_started = perf_counter()
    received = sum(len(batch.observations) for batch in batches)

    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(
                """
                    INSERT INTO collector_runs (
                        run_id, run_kind, venue, cycle_at, started_at, status,
                        records_received, metrics
                    )
                    VALUES (%s, 'l1', NULL, %s, %s, 'running', %s, %s)
                """,
                (
                    run_id,
                    cycle_at,
                    started_at,
                    received,
                    Jsonb({}),
                ),
            )
            current_rows = cursor.execute(
                """
                    SELECT venue_instrument_version_id, venue, source_symbol,
                           quote_asset, collateral_asset
                    FROM venue_instrument_versions
                    WHERE valid_to IS NULL AND active = true
                      AND venue = ANY(%s)
                    ORDER BY venue, source_symbol
                    FOR SHARE
                """,
                ([batch.venue for batch in batches],),
            ).fetchall()
            current = {
                (str(row[1]), str(row[2])): (int(row[0]), str(row[3]), row[4])
                for row in current_rows
            }

            raw_written = 0
            observations: dict[tuple[str, str], MarketObservation] = {}
            unknown_source_rows = 0
            batch_by_venue: dict[str, MarketBatch] = {batch.venue: batch for batch in batches}
            state_statuses: dict[str, list[str]] = {venue: [] for venue in batch_by_venue}
            for batch in batches:
                source_at = _latest_source_at(batch.observations)
                cursor.execute(
                    """
                        INSERT INTO raw_market_observations (
                            observed_date, collector_run_id, venue, source_symbol,
                            dataset, observed_at, source_at, payload_hash, payload
                        )
                        VALUES (%s, %s, %s, NULL, 'l1_all_market', %s, %s, %s, %s)
                    """,
                    (
                        batch.observed_at.astimezone(UTC).date(),
                        run_id,
                        batch.venue,
                        batch.observed_at,
                        source_at,
                        batch.payload_hash,
                        Jsonb(batch.raw_payload),
                    ),
                )
                raw_written += 1
                for observation in batch.observations:
                    key = (batch.venue, observation.source_symbol)
                    if key in observations:
                        raise ValueError(
                            "duplicate market observation: "
                            f"{batch.venue}:{observation.source_symbol}"
                        )
                    if key not in current:
                        unknown_source_rows += 1
                        continue
                    expected_id = f"{batch.venue}:{observation.source_symbol}"
                    if observation.venue_instrument_id != expected_id:
                        raise ValueError(
                            "market observation identity does not match its Venue symbol"
                        )
                    observations[key] = observation

            written = 0
            for (
                venue,
                source_symbol,
            ), (version_id, quote_asset, collateral_asset) in current.items():
                batch = batch_by_venue[venue]
                observation = observations.get((venue, source_symbol))
                values = _state_values(
                    observation,
                    batch=batch,
                    quote_asset=quote_asset,
                    collateral_asset=collateral_asset,
                )
                state_statuses[venue].append(
                    "unavailable" if observation is None else observation.status
                )
                _upsert_latest(cursor, version_id, run_id, cycle_at, values)
                _upsert_minute(cursor, version_id, run_id, cycle_at, values)
                written += 1

            venue_statuses = {
                venue: _state_status(statuses) for venue, statuses in state_statuses.items()
            }
            run_status = _run_status(tuple(venue_statuses.values()))
            completed_at = max(datetime.now(UTC), started_at)
            cursor.execute(
                """
                    UPDATE collector_runs
                    SET completed_at = %s, status = %s, records_written = %s,
                        error_code = %s,
                        metrics = metrics || %s::jsonb
                    WHERE run_id = %s
                """,
                (
                    completed_at,
                    run_status,
                    written,
                    None if run_status == "succeeded" else "venue_partial_failure",
                    Jsonb(
                        {
                            "rawPayloadsWritten": raw_written,
                            "unknownSourceRows": unknown_source_rows,
                            "venueStatuses": venue_statuses,
                        }
                    ),
                    run_id,
                ),
            )
    except ValueError:
        raise
    except psycopg.Error:
        raise MarketStoreError("market cycle persistence failed") from None

    return MarketStoreResult(
        run_id=run_id,
        status=run_status,
        records_received=received,
        records_written=written,
        raw_payloads_written=raw_written,
        unknown_source_rows=unknown_source_rows,
        commit_seconds=perf_counter() - transaction_started,
    )


def _validate_cycle(
    cycle_at: datetime,
    started_at: datetime,
    batches: Sequence[MarketBatch],
) -> None:
    _require_aware(cycle_at, "cycle_at")
    _require_aware(started_at, "started_at")
    if cycle_at.second != 0 or cycle_at.microsecond != 0:
        raise ValueError("cycle_at must be aligned to a whole minute")
    if len(batches) != 3 or {batch.venue for batch in batches} != {
        "bitget",
        "hyperliquid",
        "aster",
    }:
        raise ValueError("market cycle requires exactly one batch for each supported Venue")
    for batch in batches:
        _require_aware(batch.observed_at, "batch observed_at")
        if batch.cycle_at != cycle_at:
            raise ValueError("market batch cycle_at does not match the persisted cycle")
        if canonical_json_sha256(batch.raw_payload) != batch.payload_hash:
            raise ValueError("market batch payload hash does not match its raw payload")
        for observation in batch.observations:
            _require_aware(observation.observed_at, "observation observed_at")
            if observation.source_at is not None:
                _require_aware(observation.source_at, "observation source_at")
            if observation.cycle_at != cycle_at:
                raise ValueError("market observation cycle_at does not match its batch")


def _state_status(statuses: Sequence[str]) -> str:
    if not statuses or all(status == "unavailable" for status in statuses):
        return "unavailable"
    if any(status != "ready" for status in statuses):
        return "partial"
    return "ready"


def _run_status(statuses: Sequence[str]) -> RunStatus:
    if all(status == "ready" for status in statuses):
        return "succeeded"
    if all(status == "unavailable" for status in statuses):
        return "failed"
    return "partial"


def _latest_source_at(observations: Sequence[MarketObservation]) -> datetime | None:
    values = [item.source_at for item in observations if item.source_at is not None]
    return max(values) if values else None


def _state_values(
    observation: MarketObservation | None,
    *,
    batch: MarketBatch,
    quote_asset: str,
    collateral_asset: str | None,
) -> tuple[object, ...]:
    if observation is None:
        raw_error = (
            batch.raw_payload.get("errorCode") if isinstance(batch.raw_payload, dict) else None
        )
        return (
            batch.observed_at,
            None,
            "unavailable",
            None,
            None,
            "none",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            quote_asset,
            collateral_asset,
            batch.payload_hash,
            str(raw_error) if raw_error else "missing_source_row",
        )
    return (
        observation.observed_at,
        observation.source_at,
        observation.status,
        observation.mark_price,
        observation.reference_price,
        observation.reference_price_kind,
        observation.best_bid,
        observation.best_ask,
        observation.funding_rate_raw,
        observation.funding_interval_seconds,
        observation.funding_rate_per_hour,
        observation.next_funding_at,
        observation.open_interest_raw,
        observation.open_interest_raw_unit,
        observation.open_interest_base,
        observation.open_interest_notional,
        observation.volume_24h_raw,
        observation.volume_24h_unit,
        observation.quote_asset,
        observation.collateral_asset,
        observation.source_payload_hash,
        observation.error_code,
    )


def _upsert_latest(
    cursor: Any,
    version_id: int,
    run_id: UUID,
    cycle_at: datetime,
    values: tuple[object, ...],
) -> None:
    cursor.execute(
        """
            INSERT INTO latest_market_state (
                venue_instrument_version_id, collector_run_id, cycle_at,
                observed_at, source_at, status, mark_price, reference_price,
                reference_price_kind, best_bid, best_ask, funding_rate_raw,
                funding_interval_seconds, funding_rate_per_hour, next_funding_at,
                open_interest_raw, open_interest_raw_unit, open_interest_base,
                open_interest_notional, volume_24h_raw, volume_24h_unit,
                quote_asset, collateral_asset, source_payload_hash, error_code
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (venue_instrument_version_id) DO UPDATE SET
                collector_run_id = EXCLUDED.collector_run_id,
                cycle_at = EXCLUDED.cycle_at,
                observed_at = EXCLUDED.observed_at,
                source_at = EXCLUDED.source_at,
                status = EXCLUDED.status,
                mark_price = EXCLUDED.mark_price,
                reference_price = EXCLUDED.reference_price,
                reference_price_kind = EXCLUDED.reference_price_kind,
                best_bid = EXCLUDED.best_bid,
                best_ask = EXCLUDED.best_ask,
                funding_rate_raw = EXCLUDED.funding_rate_raw,
                funding_interval_seconds = EXCLUDED.funding_interval_seconds,
                funding_rate_per_hour = EXCLUDED.funding_rate_per_hour,
                next_funding_at = EXCLUDED.next_funding_at,
                open_interest_raw = EXCLUDED.open_interest_raw,
                open_interest_raw_unit = EXCLUDED.open_interest_raw_unit,
                open_interest_base = EXCLUDED.open_interest_base,
                open_interest_notional = EXCLUDED.open_interest_notional,
                volume_24h_raw = EXCLUDED.volume_24h_raw,
                volume_24h_unit = EXCLUDED.volume_24h_unit,
                quote_asset = EXCLUDED.quote_asset,
                collateral_asset = EXCLUDED.collateral_asset,
                source_payload_hash = EXCLUDED.source_payload_hash,
                error_code = EXCLUDED.error_code,
                updated_at = clock_timestamp()
            WHERE latest_market_state.cycle_at <= EXCLUDED.cycle_at
        """,
        (version_id, run_id, cycle_at, *values),
    )


def _upsert_minute(
    cursor: Any,
    version_id: int,
    run_id: UUID,
    cycle_at: datetime,
    values: tuple[object, ...],
) -> None:
    (
        observed_at,
        source_at,
        status,
        mark_price,
        reference_price,
        reference_price_kind,
        best_bid,
        best_ask,
        funding_rate_raw,
        funding_interval_seconds,
        funding_rate_per_hour,
        _next_funding_at,
        open_interest_raw,
        open_interest_raw_unit,
        open_interest_base,
        open_interest_notional,
        volume_24h_raw,
        volume_24h_unit,
        _quote_asset,
        _collateral_asset,
        _source_payload_hash,
        _error_code,
    ) = values
    cursor.execute(
        """
            INSERT INTO market_state_1m (
                venue_instrument_version_id, bucket_at, collector_run_id, status,
                first_observed_at, last_observed_at, source_at, sample_count,
                mark_price, reference_price, reference_price_kind, best_bid, best_ask,
                funding_rate_raw, funding_interval_seconds, funding_rate_per_hour,
                open_interest_raw, open_interest_raw_unit, open_interest_base,
                open_interest_notional, volume_24h_raw, volume_24h_unit
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (venue_instrument_version_id, bucket_at) DO UPDATE SET
                collector_run_id = EXCLUDED.collector_run_id,
                status = EXCLUDED.status,
                first_observed_at = EXCLUDED.first_observed_at,
                last_observed_at = EXCLUDED.last_observed_at,
                source_at = EXCLUDED.source_at,
                sample_count = 1,
                mark_price = EXCLUDED.mark_price,
                reference_price = EXCLUDED.reference_price,
                reference_price_kind = EXCLUDED.reference_price_kind,
                best_bid = EXCLUDED.best_bid,
                best_ask = EXCLUDED.best_ask,
                funding_rate_raw = EXCLUDED.funding_rate_raw,
                funding_interval_seconds = EXCLUDED.funding_interval_seconds,
                funding_rate_per_hour = EXCLUDED.funding_rate_per_hour,
                open_interest_raw = EXCLUDED.open_interest_raw,
                open_interest_raw_unit = EXCLUDED.open_interest_raw_unit,
                open_interest_base = EXCLUDED.open_interest_base,
                open_interest_notional = EXCLUDED.open_interest_notional,
                volume_24h_raw = EXCLUDED.volume_24h_raw,
                volume_24h_unit = EXCLUDED.volume_24h_unit
        """,
        (
            version_id,
            cycle_at,
            run_id,
            status,
            observed_at,
            observed_at,
            source_at,
            mark_price,
            reference_price,
            reference_price_kind,
            best_bid,
            best_ask,
            funding_rate_raw,
            funding_interval_seconds,
            funding_rate_per_hour,
            open_interest_raw,
            open_interest_raw_unit,
            open_interest_base,
            open_interest_notional,
            volume_24h_raw,
            volume_24h_unit,
        ),
    )


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
