from __future__ import annotations

import json

from prep_watchdeck.adapters.duckdb.service_store import DuckDbServiceStore
from prep_watchdeck.adapters.local_snapshot import AtomicServiceStateWriter
from prep_watchdeck.application.service_plan import build_subscription_plan
from prep_watchdeck.application.service_publisher import (
    build_service_state_snapshot,
    publish_service_state_once,
)
from prep_watchdeck.domain.service_models import (
    BackfillProgress,
    Candle1mRecord,
)


def test_build_service_state_snapshot_uses_store_diagnostics(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    store.upsert_candles_1m(
        [
            Candle1mRecord(
                symbol="BTCUSDT",
                ts_ms=1_781_000_040_000,
                open=100.0,
                high=102.0,
                low=99.0,
                close=101.0,
                is_closed=False,
                source="ws-candle1m",
                updated_at_ms=1_781_000_040_500,
            )
        ]
    )
    subscription = build_subscription_plan(
        ["BTCUSDT", "ETHUSDT"],
        product_type="USDT-FUTURES",
    )

    snapshot = build_service_state_snapshot(
        store,
        product_type="USDT-FUTURES",
        subscription=subscription,
        generated_at_ms=1_781_000_050_000,
    )

    assert snapshot.schema_version == 1
    assert snapshot.generated_at_ms == 1_781_000_050_000
    assert snapshot.data_as_of_ms == 1_781_000_040_000
    assert snapshot.product_type == "USDT-FUTURES"
    assert snapshot.stream_symbols == 2
    assert snapshot.stream_channels == 4
    assert snapshot.stream_shards == 1
    assert snapshot.diagnostics.candle_1m_count == 1


def test_build_service_state_snapshot_includes_optional_backfill_progress(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    subscription = build_subscription_plan(["BTCUSDT"], product_type="USDT-FUTURES")
    backfill = BackfillProgress(
        status="running",
        requested_symbols=1,
        completed_symbols=0,
        saved_count=0,
        error_count=0,
        limit=200,
        concurrency=12,
        started_at_ms=1_781_000_000_000,
        updated_at_ms=1_781_000_000_000,
    )

    snapshot = build_service_state_snapshot(
        store,
        product_type="USDT-FUTURES",
        subscription=subscription,
        backfill=backfill,
        generated_at_ms=1_781_000_050_000,
    )

    assert snapshot.backfill == backfill


def test_publish_service_state_once_writes_atomic_json(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    subscription = build_subscription_plan(["BTCUSDT"], product_type="USDT-FUTURES")
    writer = AtomicServiceStateWriter(tmp_path / "snapshots" / "service-state.json")

    snapshot = publish_service_state_once(
        store,
        writer,
        product_type="USDT-FUTURES",
        subscription=subscription,
        backfill=BackfillProgress(
            status="completed",
            requested_symbols=1,
            completed_symbols=1,
            saved_count=200,
            error_count=0,
            limit=200,
            concurrency=12,
            started_at_ms=1_781_000_000_000,
            updated_at_ms=1_781_000_030_000,
            finished_at_ms=1_781_000_030_000,
        ),
        generated_at_ms=1_781_000_050_000,
    )

    payload = json.loads((tmp_path / "snapshots" / "service-state.json").read_text())
    assert payload["schemaVersion"] == 1
    assert payload["generatedAtMs"] == snapshot.generated_at_ms
    assert payload["productType"] == "USDT-FUTURES"
    assert payload["streamSymbols"] == 1
    assert payload["streamChannels"] == 2
    assert payload["diagnostics"]["schemaReady"] is True
    assert payload["backfill"]["status"] == "completed"
    assert payload["backfill"]["savedCount"] == 200
    assert "deepBackfill" not in payload
