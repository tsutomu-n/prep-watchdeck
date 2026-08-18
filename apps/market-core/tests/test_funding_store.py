from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.types.json import Jsonb

from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.funding_store import (
    FundingConflictError,
    load_funding_catalog,
    load_latest_funding_times,
    persist_funding_sweep,
)
from prep_watchdeck_market.models import canonical_json_sha256
from prep_watchdeck_market.sources.funding import FundingBatch, FundingEvent

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
VALID_FROM = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
OBSERVED = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
FUNDING_AT = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)
def test_funding_store_is_idempotent_conflict_safe_and_catalog_backed() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"funding_store_test_{uuid.uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            _install_instrument(connection, "bitget", "BTCUSDT", 28_800)
            _install_instrument(connection, "hyperliquid", "BTC", 3_600)
            _install_instrument(connection, "aster", "BTCUSDT", None)

            snapshot = load_funding_catalog(connection)
            assert [item.venue_instrument_id for item in snapshot.instruments] == [
                "aster:BTCUSDT",
                "bitget:BTCUSDT",
                "hyperliquid:BTC",
            ]
            assert set(snapshot.version_starts.values()) == {VALID_FROM}

            batches = (
                _batch("bitget", "BTCUSDT", "0.0008"),
                _batch("hyperliquid", "BTC", "0.0002"),
                _batch("aster", "BTCUSDT", "-0.0003"),
            )
            first = persist_funding_sweep(connection, OBSERVED, batches)
            assert first.status == "succeeded"
            assert first.records_received == 3
            assert first.records_written == 3
            assert first.records_unchanged == 0
            assert first.admission_rejected == 0

            second = persist_funding_sweep(connection, OBSERVED, batches)
            assert second.status == "succeeded"
            assert second.records_written == 0
            assert second.records_unchanged == 3

            latest = load_latest_funding_times(connection)
            assert latest == {
                "aster:BTCUSDT": FUNDING_AT,
                "bitget:BTCUSDT": FUNDING_AT,
                "hyperliquid:BTC": FUNDING_AT,
            }
            rows = connection.execute(
                """
                    SELECT instrument.venue, funding.funding_rate_raw,
                           funding.funding_interval_seconds,
                           funding.funding_rate_per_hour
                    FROM funding_events AS funding
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    ORDER BY instrument.venue
                """
            ).fetchall()
            assert rows == [
                ("aster", Decimal("-0.0003"), None, None),
                ("bitget", Decimal("0.0008"), 28_800, Decimal("0.00010000000000000000")),
                ("hyperliquid", Decimal("0.0002"), 3_600, Decimal("0.00020000000000000000")),
            ]

            with pytest.raises(FundingConflictError, match="settled funding rate changed"):
                persist_funding_sweep(
                    connection,
                    OBSERVED,
                    (_batch("bitget", "BTCUSDT", "0.0009"),),
                )
            assert connection.execute("SELECT count(*) FROM funding_events").fetchone() == (3,)
            assert connection.execute(
                "SELECT count(*) FROM raw_market_observations"
            ).fetchone() == (6,)
        finally:
            connection.execute("RESET search_path")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def _install_instrument(
    connection: Connection[Any],
    venue: str,
    symbol: str,
    interval_seconds: int | None,
) -> None:
    payload_hash = hashlib.sha256(f"payload:{venue}:{symbol}".encode()).hexdigest()
    definition_hash = hashlib.sha256(f"definition:{venue}:{symbol}".encode()).hexdigest()
    payload_id = connection.execute(
        """
            INSERT INTO raw_catalog_payloads (
                venue, endpoint, source_kind, documentation_url,
                payload_hash, observed_at, last_observed_at, payload
            )
            VALUES (%s, '/catalog', 'native_rest', 'https://example.invalid/catalog',
                    %s, %s, %s, %s)
            RETURNING raw_catalog_payload_id
        """,
        (venue, payload_hash, VALID_FROM, VALID_FROM, Jsonb({"symbol": symbol})),
    ).fetchone()
    assert payload_id is not None
    connection.execute(
        """
            INSERT INTO venue_instrument_versions (
                venue, source_symbol, definition_hash, valid_from,
                active, asset_class, market_type, execution_model,
                base_asset, quote_asset, settle_asset, collateral_asset,
                quantity_unit, contract_multiplier, price_tick, amount_step,
                funding_interval_seconds, source_status, raw_definition,
                raw_catalog_payload_id
            )
            VALUES (
                %s, %s, %s, %s,
                true, 'crypto', 'linear_perpetual', 'clob',
                'BTC', 'USDT', 'USDT', 'USDT',
                'base', 1, 0.01, 0.001,
                %s, 'normal', %s, %s
            )
        """,
        (
            venue,
            symbol,
            definition_hash,
            VALID_FROM,
            interval_seconds,
            Jsonb({"symbol": symbol}),
            payload_id[0],
        ),
    )


def _batch(venue: str, symbol: str, rate: str) -> FundingBatch:
    raw = [{"symbol": symbol, "fundingRate": rate, "fundingTime": FUNDING_AT.isoformat()}]
    event = FundingEvent(
        venue=venue,  # type: ignore[arg-type]
        source_symbol=symbol,
        funding_at=FUNDING_AT,
        funding_rate_raw=Decimal(rate),
        observed_at=OBSERVED,
        raw_payload=dict(raw[0]),
    )
    return FundingBatch(
        venue=venue,  # type: ignore[arg-type]
        source_symbol=symbol,
        endpoint="/funding",
        observed_at=OBSERVED,
        payload_hash=canonical_json_sha256(raw),
        events=(event,),
        raw_payload=raw,
    )
