from __future__ import annotations

from prep_watchdeck.adapters.duckdb.service_store import DuckDbServiceStore
from prep_watchdeck.application.service_reconcile import (
    latest_closed_1m_bucket_ms,
    select_reconcile_symbols,
)
from prep_watchdeck.domain.service_models import Candle1mRecord

ONE_MINUTE_MS = 60_000


def test_select_reconcile_symbols_uses_recent_coverage_not_only_latest_ts(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    now_ms = 1_800_003_660_123
    window_end_ms = latest_closed_1m_bucket_ms(now_ms)
    window_start_ms = window_end_ms - 59 * ONE_MINUTE_MS
    candles: list[Candle1mRecord] = []

    for symbol in ["COMPLETEUSDT", "GAPPEDUSDT", "ZEROVOLUSDT"]:
        for index in range(60):
            if symbol == "GAPPEDUSDT" and index == 17:
                continue
            quote_volume = 0.0 if symbol == "ZEROVOLUSDT" and index == 23 else 10.0
            candles.append(candle(symbol, window_start_ms + index * ONE_MINUTE_MS, quote_volume))
    store.upsert_candles_1m(candles)

    selected = select_reconcile_symbols(
        store,
        ["zerovolusdt", "completeusdt", "gappedusdt"],
        window_limit=60,
        now_ms=now_ms,
    )

    assert selected == ["GAPPEDUSDT"]


def candle(symbol: str, ts_ms: int, quote_volume: float) -> Candle1mRecord:
    return Candle1mRecord(
        symbol=symbol,
        ts_ms=ts_ms,
        open=1.0,
        high=1.2,
        low=0.9,
        close=1.1,
        base_volume=quote_volume,
        quote_volume=quote_volume,
        usdt_volume=quote_volume,
        is_closed=True,
        source="test",
        updated_at_ms=ts_ms,
    )
