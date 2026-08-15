from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.market_state import MarketBatch, MarketObservation
from prep_watchdeck_market.market_store import persist_market_cycle
from prep_watchdeck_market.models import Venue, canonical_json_sha256

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)
def test_cycle_commit_replaces_missing_source_row_with_unavailable() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"market_cycle_test_{uuid.uuid4().hex}"
    first_cycle = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            _insert_instruments(connection, first_cycle - timedelta(minutes=1))

            first = persist_market_cycle(
                connection,
                first_cycle,
                first_cycle,
                tuple(_ready_batch(venue, first_cycle) for venue in _venues()),
            )
            second_cycle = first_cycle + timedelta(minutes=1)
            second = persist_market_cycle(
                connection,
                second_cycle,
                second_cycle,
                (
                    _failed_batch("bitget", second_cycle),
                    _ready_batch("hyperliquid", second_cycle),
                    _ready_batch("aster", second_cycle),
                ),
            )

            assert first.status == "succeeded"
            assert second.status == "partial"
            assert second.records_written == 3
            assert connection.execute(
                """
                    SELECT state.status, state.mark_price, state.error_code
                    FROM latest_market_state state
                    JOIN venue_instrument_versions instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = 'bitget'
                """
            ).fetchone() == ("unavailable", None, "source_unavailable")
            assert connection.execute(
                "SELECT count(*) FROM raw_market_observations"
            ).fetchone() == (6,)
            assert connection.execute("SELECT count(*) FROM market_state_1m").fetchone() == (6,)
            assert connection.execute("SELECT count(*) FROM collector_runs").fetchone() == (2,)
        finally:
            connection.execute("RESET search_path")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)
def test_cycle_status_includes_omitted_current_instrument() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"market_cycle_status_test_{uuid.uuid4().hex}"
    cycle_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            _insert_instruments(
                connection,
                cycle_at - timedelta(minutes=1),
                bitget_symbols=("BTCUSDT", "ETHUSDT"),
            )

            result = persist_market_cycle(
                connection,
                cycle_at,
                cycle_at,
                tuple(_ready_batch(venue, cycle_at) for venue in _venues()),
            )

            assert result.status == "partial"
            assert result.records_written == 4
            assert connection.execute(
                """
                    SELECT run.status, run.metrics -> 'venueStatuses'
                    FROM collector_runs run
                    WHERE run.run_kind = 'l1'
                """
            ).fetchone() == (
                "partial",
                {"aster": "ready", "bitget": "partial", "hyperliquid": "ready"},
            )
            assert connection.execute(
                """
                    SELECT instrument.source_symbol, state.status, state.error_code
                    FROM latest_market_state state
                    JOIN venue_instrument_versions instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = 'bitget'
                    ORDER BY instrument.source_symbol
                """
            ).fetchall() == [
                ("BTCUSDT", "ready", None),
                ("ETHUSDT", "unavailable", "missing_source_row"),
            ]
        finally:
            connection.execute("RESET search_path")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def _insert_instruments(
    connection: psycopg.Connection[Any],
    observed_at: datetime,
    *,
    bitget_symbols: tuple[str, ...] = ("BTCUSDT",),
) -> None:
    for venue in _venues():
        symbols = bitget_symbols if venue == "bitget" else (_symbol(venue),)
        for symbol in symbols:
            _insert_instrument(connection, observed_at, venue, symbol)


def _insert_instrument(
    connection: psycopg.Connection[Any],
    observed_at: datetime,
    venue: Venue,
    symbol: str,
) -> None:
    raw_payload = {"symbol": symbol}
    payload_hash = canonical_json_sha256(raw_payload)
    raw_id = connection.execute(
        """
            INSERT INTO raw_catalog_payloads (
                venue, endpoint, source_kind, documentation_url, payload_hash,
                observed_at, last_observed_at, payload
            )
            VALUES (%s, '/catalog', 'native_rest', 'https://example.invalid',
                    %s, %s, %s, %s)
            RETURNING raw_catalog_payload_id
        """,
        (venue, payload_hash, observed_at, observed_at, Jsonb(raw_payload)),
    ).fetchone()
    assert raw_id is not None
    connection.execute(
        """
            INSERT INTO venue_instrument_versions (
                venue, source_symbol, definition_hash, valid_from, active,
                asset_class, market_type, execution_model, base_asset,
                quote_asset, settle_asset, collateral_asset, quantity_unit,
                contract_multiplier, source_status, raw_definition,
                raw_catalog_payload_id
            )
            VALUES (%s, %s, %s, %s, true, 'crypto', 'linear_perpetual',
                    'clob', 'BTC', 'USDT', 'USDT', 'USDT', 'base', 1,
                    'normal', %s, %s)
        """,
        (venue, symbol, "0" * 64, observed_at, Jsonb(raw_payload), int(raw_id[0])),
    )


def _ready_batch(venue: Venue, cycle_at: datetime) -> MarketBatch:
    raw_payload: dict[str, object] = {"venue": venue, "markPrice": "100"}
    payload_hash = canonical_json_sha256(raw_payload)
    symbol = _symbol(venue)
    observation = MarketObservation(
        venue_instrument_id=f"{venue}:{symbol}",
        source_symbol=symbol,
        cycle_at=cycle_at,
        observed_at=cycle_at,
        source_at=None,
        status="ready",
        mark_price=Decimal("100"),
        reference_price=None,
        reference_price_kind="none",
        best_bid=Decimal("99"),
        best_ask=Decimal("101"),
        funding_rate_raw=Decimal("0.0001"),
        funding_interval_seconds=3_600,
        funding_rate_per_hour=Decimal("0.0001"),
        next_funding_at=None,
        open_interest_raw=Decimal("10"),
        open_interest_raw_unit="base",
        open_interest_base=Decimal("10"),
        open_interest_notional=Decimal("1000"),
        volume_24h_raw=Decimal("5000"),
        volume_24h_unit="quote",
        quote_asset="USDT",
        collateral_asset="USDT",
        source_payload_hash=payload_hash,
        error_code=None,
        raw_payload=raw_payload,
    )
    return MarketBatch(
        venue=venue,
        cycle_at=cycle_at,
        observed_at=cycle_at,
        endpoint="/l1",
        payload_hash=payload_hash,
        observations=(observation,),
        raw_payload=raw_payload,
    )


def _failed_batch(venue: Venue, cycle_at: datetime) -> MarketBatch:
    raw_payload: dict[str, object] = {"venue": venue, "errorCode": "source_unavailable"}
    return MarketBatch(
        venue=venue,
        cycle_at=cycle_at,
        observed_at=cycle_at,
        endpoint="/l1",
        payload_hash=canonical_json_sha256(raw_payload),
        observations=(),
        raw_payload=raw_payload,
    )


def _venues() -> tuple[Venue, Venue, Venue]:
    return "bitget", "hyperliquid", "aster"


def _symbol(venue: Venue) -> str:
    return "BTC" if venue == "hyperliquid" else "BTCUSDT"
