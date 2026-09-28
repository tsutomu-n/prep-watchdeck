import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.market_metrics import (
    build_market_metrics,
    candle_cutoff,
    read_market_metrics,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def row(now: datetime) -> dict[str, object]:
    cutoff = candle_cutoff(now)
    return {
        "venue_instrument_version_id": 7,
        "venue": "bitget",
        "source_symbol": "BTCUSDT",
        "quote_asset": "USDT",
        "settle_asset": "USDT",
        "price_tick": "0.1",
        "l_cycle_at": now.replace(second=0, microsecond=0),
        "l_oi_base": 120,
        "l_source_at": now - timedelta(seconds=3),
        "l_observed_at": now - timedelta(seconds=2),
        "oi_15m_base": 100,
        "oi_1h_base": 80,
        "oi_15m_source_at": now - timedelta(minutes=15),
        "oi_15m_observed_at": now - timedelta(minutes=15),
        "oi_1h_source_at": now - timedelta(hours=1),
        "oi_1h_observed_at": now - timedelta(hours=1),
        "c_end_close": 110,
        "c_end_finality": "confirmed",
        "c_end_source_at": cutoff,
        "c_end_observed_at": cutoff + timedelta(seconds=20),
        "c_15m_close": 100,
        "c_15m_finality": "confirmed",
        "c_15m_source_at": cutoff - timedelta(minutes=15),
        "c_15m_observed_at": cutoff - timedelta(minutes=15),
        "c_1h_close": 100,
        "c_1h_finality": "derived_final",
        "c_1h_source_at": cutoff - timedelta(hours=1),
        "c_1h_observed_at": cutoff - timedelta(hours=1),
        "c_24h_close": 100,
        "c_24h_finality": "confirmed",
        "c_24h_source_at": cutoff - timedelta(days=1),
        "c_24h_observed_at": cutoff - timedelta(days=1),
    }


def test_metrics_share_cutoff_and_keep_endpoint_quality_separate() -> None:
    now = datetime(2026, 9, 28, 12, 6, 30, tzinfo=UTC)
    result = build_market_metrics([row(now)], now=now)
    metric = result.rows[0]
    assert result.candle_cutoff == datetime(2026, 9, 28, 12, 3, tzinfo=UTC)
    assert metric.oi_change["15m"].value == pytest.approx(20)
    assert metric.oi_change["1h"].value == pytest.approx(50)
    assert metric.trade_change["15m"].value == pytest.approx(10)
    assert metric.trade_change["24h"].end_at == result.candle_cutoff
    assert metric.trade_change["1h"].end_finality == "confirmed"

    incomplete = row(now)
    incomplete["c_15m_close"] = None
    incomplete["l_oi_base"] = None
    changed = build_market_metrics([incomplete], now=now).rows[0]
    assert changed.trade_change["15m"].availability == "missing"
    assert changed.trade_change["1h"].availability == "available"
    assert changed.oi_change["15m"].availability == "missing"


def test_later_endpoint_correction_recomputes_without_cached_values() -> None:
    now = datetime(2026, 9, 28, 12, 6, 30, tzinfo=UTC)
    original = row(now)
    revised = dict(original, c_end_close=95, oi_15m_base=110)
    before = build_market_metrics([original], now=now).rows[0]
    after = build_market_metrics([revised], now=now).rows[0]
    assert before.trade_change["15m"].value == pytest.approx(10)
    assert after.trade_change["15m"].value == pytest.approx(-5)
    assert after.oi_change["15m"].value is not None
    assert after.oi_change["15m"].value < before.oi_change["15m"].value


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="isolated PostgreSQL required")
def test_metrics_query_uses_migrated_schema_without_writing() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"market_metrics_test_{uuid.uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            now = datetime(2026, 9, 28, 12, 6, 30, tzinfo=UTC)
            cutoff = candle_cutoff(now)
            run_id = uuid.uuid4()
            connection.execute(
                "INSERT INTO collector_runs (run_id, run_kind, started_at, status) "
                "VALUES (%s, 'catalog', %s, 'succeeded')",
                (run_id, now),
            )
            raw_id = connection.execute(
                "INSERT INTO raw_catalog_payloads "
                "(venue, endpoint, payload_hash, observed_at, last_observed_at, "
                "source_kind, payload) "
                "VALUES ('bitget', 'isolated-test', %s, %s, %s, 'native_rest', '{}') "
                "RETURNING raw_catalog_payload_id",
                ("a" * 64, now, now),
            ).fetchone()[0]
            version_id = connection.execute(
                "INSERT INTO venue_instrument_versions "
                "(venue, source_symbol, definition_hash, valid_from, active, asset_class, "
                "market_type, base_asset, quote_asset, settle_asset, raw_catalog_payload_id, "
                "quantity_unit, raw_definition) "
                "VALUES ('bitget', 'BTCUSDT', %s, %s, true, 'crypto', 'linear_perpetual', "
                "'BTC', 'USDT', 'USDT', %s, 'base', '{}') "
                "RETURNING venue_instrument_version_id",
                ("b" * 64, now - timedelta(days=2), raw_id),
            ).fetchone()[0]
            cycle = now.replace(second=0, microsecond=0)
            connection.execute(
                "INSERT INTO latest_market_state "
                "(venue_instrument_version_id, collector_run_id, cycle_at, observed_at, "
                "source_at, status, open_interest_base, quote_asset) "
                "VALUES (%s, %s, %s, %s, %s, 'partial', 1100, 'USDT')",
                (version_id, run_id, cycle, now, now),
            )
            for minutes, quantity in ((15, 1000), (60, 800)):
                connection.execute(
                    "INSERT INTO market_state_1m "
                    "(venue_instrument_version_id, bucket_at, status, first_observed_at, "
                    "last_observed_at, sample_count, open_interest_base) "
                    "VALUES (%s, %s, 'partial', %s, %s, 1, %s)",
                    (version_id, cycle - timedelta(minutes=minutes), now, now, quantity),
                )
            for minutes, close in ((0, 110), (15, 100), (60, 100), (1440, 100)):
                connection.execute(
                    "INSERT INTO candle_1m (venue_instrument_version_id, bucket_at, "
                    "open_price, high_price, low_price, close_price, finality, observed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'confirmed', %s)",
                    (
                        version_id,
                        cutoff - timedelta(minutes=minutes + 1),
                        close,
                        close,
                        close,
                        close,
                        cutoff - timedelta(seconds=20),
                    ),
                )
            artifact = read_market_metrics(connection, now=now)
            assert artifact.metric_version == "native-endpoints-v1"
            assert len(artifact.rows) == 1
            assert artifact.rows[0].oi_change["15m"].value == pytest.approx(10)
            assert artifact.rows[0].trade_change["15m"].value == pytest.approx(10)
            connection.execute(
                "UPDATE candle_1m SET open_price=95, high_price=95, low_price=95, "
                "close_price=95 WHERE venue_instrument_version_id=%s AND bucket_at=%s",
                (version_id, cutoff - timedelta(minutes=1)),
            )
            revised = read_market_metrics(connection, now=now)
            assert revised.rows[0].trade_change["15m"].value == pytest.approx(-5)
            connection.execute(
                "INSERT INTO venue_instrument_versions "
                "(venue, source_symbol, definition_hash, valid_from, active, asset_class, "
                "market_type, base_asset, quote_asset, settle_asset, raw_catalog_payload_id, "
                "quantity_unit, raw_definition) "
                "SELECT 'bitget', 'FIXTURE' || n || 'USDT', %s, %s, true, 'crypto', "
                "'linear_perpetual', 'FIXTURE' || n, 'USDT', 'USDT', %s, 'base', '{}' "
                "FROM generate_series(1, 1200) AS n",
                ("c" * 64, now - timedelta(days=2), raw_id),
            )
            started = time.perf_counter()
            full_universe = read_market_metrics(connection, now=now)
            elapsed = time.perf_counter() - started
            assert len(full_universe.rows) == 1201
            assert elapsed < 10
        finally:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
