from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg import sql

from prep_watchdeck_market.candle_store import (
    UnknownCandleInstrumentError,
    upsert_candles,
)
from prep_watchdeck_market.candles import Candle1m, CandleFinality
from prep_watchdeck_market.database import apply_migrations

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)
def test_candle_upsert_preserves_finality_and_fails_closed_for_unknown_instrument() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"market_candle_test_{uuid.uuid4().hex}"
    bucket_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            _insert_current_instrument(connection, observed_at=bucket_at)
            derived = _candle(bucket_at, finality="derived_final", close_price="101")
            confirmed = replace(
                derived,
                finality="confirmed",
                close_price=Decimal("102"),
                observed_at=derived.observed_at - timedelta(seconds=1),
            )
            downgrade = replace(
                derived,
                close_price=Decimal("103"),
                observed_at=derived.observed_at + timedelta(seconds=1),
            )
            newer_confirmed = replace(
                confirmed,
                close_price=Decimal("104"),
                observed_at=derived.observed_at + timedelta(seconds=2),
            )

            assert upsert_candles(connection, (derived,)).stored == 1
            assert upsert_candles(connection, (confirmed,)).stored == 1
            assert upsert_candles(connection, (downgrade,)).ignored == 1
            assert upsert_candles(connection, (newer_confirmed,)).stored == 1
            assert connection.execute(
                "SELECT finality, close_price, observed_at FROM candle_1m"
            ).fetchone() == ("confirmed", Decimal("104"), newer_confirmed.observed_at)

            unknown = replace(newer_confirmed, source_symbol="UNKNOWNUSDT")
            with pytest.raises(UnknownCandleInstrumentError) as caught:
                upsert_candles(
                    connection,
                    (replace(newer_confirmed, close_price=Decimal("105")), unknown),
                )
            assert caught.value.count == 1
            assert caught.value.venue_instrument_ids == ("bitget:UNKNOWNUSDT",)
            assert connection.execute("SELECT close_price FROM candle_1m").fetchone() == (
                Decimal("104"),
            )
        finally:
            connection.execute("RESET search_path")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)
def test_candle_maps_to_version_covering_full_minute_and_rejects_boundary_crossing() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"market_candle_temporal_test_{uuid.uuid4().hex}"
    first_bucket = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    changed_at = first_bucket + timedelta(minutes=1, seconds=30)

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            old_version_id = _insert_instrument_version(
                connection,
                valid_from=first_bucket - timedelta(minutes=1),
                valid_to=changed_at,
                payload_hash="c" * 64,
                definition_hash="d" * 64,
            )
            new_version_id = _insert_instrument_version(
                connection,
                valid_from=changed_at,
                valid_to=None,
                payload_hash="e" * 64,
                definition_hash="f" * 64,
            )
            old_bar = _candle(first_bucket, finality="confirmed", close_price="101")
            crossing_bar = _candle(
                first_bucket + timedelta(minutes=1),
                finality="confirmed",
                close_price="102",
            )
            new_bar = _candle(
                first_bucket + timedelta(minutes=2),
                finality="confirmed",
                close_price="103",
            )

            assert upsert_candles(connection, (old_bar,)).stored == 1
            assert connection.execute(
                "SELECT venue_instrument_version_id FROM candle_1m WHERE bucket_at = %s",
                (first_bucket,),
            ).fetchone() == (old_version_id,)

            with pytest.raises(UnknownCandleInstrumentError):
                upsert_candles(connection, (new_bar, crossing_bar))
            assert connection.execute("SELECT count(*) FROM candle_1m").fetchone() == (1,)

            assert upsert_candles(connection, (new_bar,)).stored == 1
            assert connection.execute(
                "SELECT venue_instrument_version_id FROM candle_1m WHERE bucket_at = %s",
                (new_bar.bucket_start,),
            ).fetchone() == (new_version_id,)
        finally:
            connection.execute("RESET search_path")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def _insert_current_instrument(
    connection: psycopg.Connection[Any], *, observed_at: datetime
) -> None:
    _insert_instrument_version(
        connection,
        valid_from=observed_at,
        valid_to=None,
        payload_hash="a" * 64,
        definition_hash="b" * 64,
    )


def _insert_instrument_version(
    connection: psycopg.Connection[Any],
    *,
    valid_from: datetime,
    valid_to: datetime | None,
    payload_hash: str,
    definition_hash: str,
) -> int:
    payload_id = connection.execute(
        """
            INSERT INTO raw_catalog_payloads (
                venue, endpoint, source_kind, documentation_url,
                payload_hash, observed_at, last_observed_at, payload
            )
            VALUES ('bitget', '/catalog', 'native_rest', 'https://example.invalid',
                    %s, %s, %s, '{}'::jsonb)
            RETURNING raw_catalog_payload_id
        """,
        (payload_hash, valid_from, valid_from),
    ).fetchone()
    assert payload_id is not None
    version_row = connection.execute(
        """
            INSERT INTO venue_instrument_versions (
                venue, source_symbol, definition_hash, valid_from, valid_to, active,
                asset_class, market_type, base_asset, quote_asset, settle_asset,
                quantity_unit, contract_multiplier, raw_definition, raw_catalog_payload_id
            )
            VALUES (
                'bitget', 'BTCUSDT', %s, %s, %s, true, 'crypto', 'linear_perpetual',
                'BTC', 'USDT', 'USDT', 'base', 1, '{}'::jsonb, %s
            )
            RETURNING venue_instrument_version_id
        """,
        (definition_hash, valid_from, valid_to, payload_id[0]),
    ).fetchone()
    assert version_row is not None
    return int(version_row[0])


def _candle(bucket_at: datetime, *, finality: CandleFinality, close_price: str) -> Candle1m:
    return Candle1m(
        venue="bitget",
        source_symbol="BTCUSDT",
        bucket_start=bucket_at,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal(close_price),
        volume_base=Decimal("5"),
        volume_notional=Decimal("500"),
        trade_count=10,
        finality=finality,
        source_at=bucket_at + timedelta(minutes=1),
        observed_at=bucket_at + timedelta(minutes=1, seconds=5),
    )
