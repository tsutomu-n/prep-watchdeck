from __future__ import annotations

import pytest

from prep_watchdeck.adapters.duckdb.service_store import DuckDbServiceStore
from prep_watchdeck.application.ws_ingestion import (
    WsBatchBuffer,
    WsIngestResult,
    ingest_ws_payload,
)
from prep_watchdeck.domain.service_models import Candle1mRecord, TickerLatestRecord


def test_ingest_ws_payload_saves_ticker_and_candle_batches(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")

    ticker_result = ingest_ws_payload(
        store,
        {
            "arg": {
                "instType": "USDT-FUTURES",
                "channel": "ticker",
                "instId": "BTCUSDT",
            },
            "data": [
                {
                    "symbol": "BTCUSDT",
                    "ts": "1781000000123",
                    "lastPr": "101.5",
                    "quoteVolume": "101500",
                }
            ],
            "ts": "1781000000456",
        },
    )
    candle_result = ingest_ws_payload(
        store,
        {
            "arg": {
                "instType": "USDT-FUTURES",
                "channel": "candle1m",
                "instId": "BTCUSDT",
            },
            "data": [
                [
                    "1781000040000",
                    "100.0",
                    "102.0",
                    "99.0",
                    "101.0",
                    "10.0",
                    "1010.0",
                    "1010.0",
                ]
            ],
            "ts": "1781000040500",
        },
    )

    diagnostics = store.diagnostics()

    assert ticker_result == WsIngestResult(ticker_count=1, candle_1m_count=0)
    assert candle_result == WsIngestResult(ticker_count=0, candle_1m_count=1)
    assert diagnostics.ticker_count == 1
    assert diagnostics.candle_1m_count == 1
    assert diagnostics.latest_candle_1m_ts_ms == 1_781_000_040_000


def test_ingest_ws_payload_ignores_empty_ack_without_writes() -> None:
    store = RecordingStore()

    result = ingest_ws_payload(
        store,
        {
            "event": "subscribe",
            "arg": {
                "instType": "USDT-FUTURES",
                "channel": "ticker",
                "instId": "BTCUSDT",
            },
        },
    )

    assert result == WsIngestResult(ticker_count=0, candle_1m_count=0)
    assert store.tickers == []
    assert store.candles == []


def test_batch_forwards_tickers_only_after_all_market_rows_persist() -> None:
    batch = WsBatchBuffer(
        tickers=[
            TickerLatestRecord(
                symbol="BTCUSDT",
                ts_ms=100,
                last_price=101.0,
                updated_at_ms=100,
            )
        ],
        candles_1m=[
            Candle1mRecord(
                symbol="BTCUSDT",
                ts_ms=60,
                open=100.0,
                high=102.0,
                low=99.0,
                close=101.0,
                is_closed=True,
                source="test",
                updated_at_ms=100,
            )
        ],
    )
    store = FailingCandleStore()
    sink = RecordingTickerSink()

    with pytest.raises(RuntimeError, match="candle persistence failed"):
        batch.flush(store, ticker_sink=sink)

    assert store.events == ["tickers", "candles"]
    assert sink.tickers == []
    assert batch.record_count == 2


class RecordingStore:
    def __init__(self) -> None:
        self.tickers: list[TickerLatestRecord] = []
        self.candles: list[Candle1mRecord] = []

    def upsert_ticker_latest(self, tickers: list[TickerLatestRecord]) -> None:
        self.tickers.extend(tickers)

    def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
        self.candles.extend(candles)


class FailingCandleStore(RecordingStore):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []

    def upsert_ticker_latest(self, tickers: list[TickerLatestRecord]) -> None:
        self.events.append("tickers")
        super().upsert_ticker_latest(tickers)

    def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
        self.events.append("candles")
        raise RuntimeError("candle persistence failed")


class RecordingTickerSink:
    def __init__(self) -> None:
        self.tickers: list[TickerLatestRecord] = []

    def record(self, tickers: list[TickerLatestRecord]) -> None:
        self.tickers.extend(tickers)
