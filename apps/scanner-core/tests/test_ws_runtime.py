from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from prep_watchdeck.adapters.duckdb.service_store import DuckDbServiceStore
from prep_watchdeck.application.ws_runtime import WsStreamIngestResult, ingest_ws_payload_stream


async def test_ingest_ws_payload_stream_accumulates_until_max_records(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")

    result = await ingest_ws_payload_stream(store, fake_payloads(), max_records=2)
    diagnostics = store.diagnostics()

    assert result == WsStreamIngestResult(
        payload_count=3,
        ticker_count=1,
        candle_1m_count=1,
    )
    assert diagnostics.ticker_count == 1
    assert diagnostics.candle_1m_count == 1


async def fake_payloads() -> AsyncIterator[dict[str, Any]]:
    yield {
        "event": "subscribe",
        "arg": {
            "instType": "USDT-FUTURES",
            "channel": "ticker",
            "instId": "BTCUSDT",
        },
    }
    yield {
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
            }
        ],
        "ts": "1781000000456",
    }
    yield {
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
    }
    yield {
        "arg": {
            "instType": "USDT-FUTURES",
            "channel": "ticker",
            "instId": "ETHUSDT",
        },
        "data": [{"symbol": "ETHUSDT", "ts": "1781000000123", "lastPr": "2500.0"}],
        "ts": "1781000000456",
    }
