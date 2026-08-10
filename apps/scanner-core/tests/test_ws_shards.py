from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from typing import Any

import duckdb
import pytest

from prep_watchdeck.adapters.duckdb.service_store import DuckDbServiceStore
from prep_watchdeck.application.ws_frames import ChannelSpec
from prep_watchdeck.application.ws_shards import (
    ShardRuntimeConfig,
    WsShardIngestResult,
    ingest_ws_shards,
)
from prep_watchdeck.domain.service_models import (
    Candle1mRecord,
    StreamHealthRecord,
    TickerLatestRecord,
)


async def test_ingest_ws_shards_runs_each_shard_until_record_limit(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    shards = [
        [ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="BTCUSDT")],
        [ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="ETHUSDT")],
    ]

    result = await ingest_ws_shards(
        store,
        shards,
        payload_source_factory=fake_payload_source,
        max_records_per_shard=1,
    )
    diagnostics = store.diagnostics()

    assert result == WsShardIngestResult(
        shard_count=2,
        payload_count=2,
        ticker_count=2,
        candle_1m_count=0,
    )
    assert diagnostics.ticker_count == 2


async def test_ingest_ws_shards_marks_health_disconnected_on_cancellation(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    source = HangingPayloadSource()
    shards = [[ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="BTCUSDT")]]

    task = asyncio.create_task(
        ingest_ws_shards(
            store,
            shards,
            payload_source_factory=source,
            runtime=ShardRuntimeConfig(base_backoff_seconds=0),
        )
    )
    await source.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with duckdb.connect(str(tmp_path / "watchdeck.duckdb")) as con:
        row = con.execute(
            "SELECT connected, last_message_at_ms, last_error FROM stream_health"
        ).fetchone()

    assert row == (False, 1_781_000_000_456, None)


async def test_ingest_ws_shards_reconnects_and_persists_stream_health(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    source = FlakyPayloadSource()
    shards = [
        [
            ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="BTCUSDT"),
            ChannelSpec(inst_type="USDT-FUTURES", channel="candle1m", inst_id="BTCUSDT"),
        ]
    ]

    result = await ingest_ws_shards(
        store,
        shards,
        payload_source_factory=source,
        max_records_per_shard=2,
        runtime=ShardRuntimeConfig(max_reconnects=1, base_backoff_seconds=0),
    )

    assert source.calls == 2
    assert source.specs_by_call == [shards[0], shards[0]]
    assert result == WsShardIngestResult(
        shard_count=1,
        payload_count=2,
        ticker_count=1,
        candle_1m_count=1,
        reconnect_count=1,
    )
    with duckdb.connect(str(tmp_path / "watchdeck.duckdb")) as con:
        row = con.execute(
            """
            SELECT shard_id, stream_kind, channel_count, connected,
                   last_message_at_ms, reconnect_count, gap_count, last_error
            FROM stream_health
            """
        ).fetchone()

    assert row == ("ws-000", "mixed", 2, False, 1_781_000_040_500, 1, 0, None)
    diagnostics = store.diagnostics()
    assert diagnostics.ticker_count == 1
    assert diagnostics.candle_1m_count == 1


async def test_ingest_ws_shards_reconnects_after_stream_close(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    source = ClosedThenPayloadSource()
    shards = [[ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="BTCUSDT")]]

    result = await ingest_ws_shards(
        store,
        shards,
        payload_source_factory=source,
        max_records_per_shard=1,
        runtime=ShardRuntimeConfig(max_reconnects=1, base_backoff_seconds=0),
    )

    assert source.calls == 2
    assert result.reconnect_count == 1
    assert result.ticker_count == 1


async def test_ingest_ws_shards_batches_payload_writes() -> None:
    store = RecordingShardStore()
    shards = [[ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="BTCUSDT")]]

    result = await ingest_ws_shards(
        store,
        shards,
        payload_source_factory=two_ticker_payload_source,
        max_records_per_shard=2,
        runtime=ShardRuntimeConfig(base_backoff_seconds=0, batch_flush_records=10),
    )

    assert result.ticker_count == 2
    assert len(store.ticker_batches) == 1
    assert [ticker.symbol for ticker in store.ticker_batches[0]] == ["BTCUSDT", "BTCUSDT"]


async def test_ingest_ws_shards_forwards_only_persisted_tickers_to_runtime_sink() -> None:
    store = RecordingShardStore()
    sink = RecordingTickerSink()
    shards = [[ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="BTCUSDT")]]

    await ingest_ws_shards(
        store,
        shards,
        payload_source_factory=fake_payload_source,
        max_records_per_shard=1,
        ticker_sink=sink,
    )

    assert len(store.ticker_batches) == 1
    assert sink.tickers == store.ticker_batches[0]


async def test_ingest_ws_shards_persists_channel_gap_health(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    shards = [
        [
            ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="BTCUSDT"),
            ChannelSpec(inst_type="USDT-FUTURES", channel="candle1m", inst_id="BTCUSDT"),
        ]
    ]

    await ingest_ws_shards(
        store,
        shards,
        payload_source_factory=ticker_only_payload_source,
        max_records_per_shard=1,
        runtime=ShardRuntimeConfig(
            base_backoff_seconds=0,
            channel_gap_seconds=60,
            now_ms=lambda: 1_781_000_030_000,
        ),
    )

    with duckdb.connect(str(tmp_path / "watchdeck.duckdb")) as con:
        rows = con.execute(
            """
            SELECT shard_id, stream_kind, connected, last_message_at_ms, gap_count
            FROM stream_health
            ORDER BY shard_id
            """
        ).fetchall()

    assert rows == [
        ("ws-000", "mixed", False, 1_781_000_000_456, 1),
        ("ws-000:candle1m", "candle1m", False, None, 1),
        ("ws-000:ticker", "ticker", False, 1_781_000_000_456, 0),
    ]


async def test_ingest_ws_shards_does_not_reconnect_schema_errors(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    source = InvalidPayloadSource()
    shards = [[ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="BTCUSDT")]]

    try:
        await ingest_ws_shards(
            store,
            shards,
            payload_source_factory=source,
            runtime=ShardRuntimeConfig(max_reconnects=1, base_backoff_seconds=0),
        )
    except ValueError as exc:
        assert "unsupported websocket channel" in str(exc)
    else:
        raise AssertionError("expected schema error")

    assert source.calls == 1
    with duckdb.connect(str(tmp_path / "watchdeck.duckdb")) as con:
        row = con.execute(
            "SELECT connected, reconnect_count, last_error FROM stream_health"
        ).fetchone()

    assert row == (False, 0, "unsupported websocket channel: books")


def fake_payload_source(
    specs: Sequence[ChannelSpec],
) -> AsyncIterable[dict[str, Any]]:
    async def payloads() -> AsyncIterator[dict[str, Any]]:
        symbol = specs[0].inst_id
        yield {
            "arg": {
                "instType": "USDT-FUTURES",
                "channel": "ticker",
                "instId": symbol,
            },
            "data": [{"symbol": symbol, "ts": "1781000000123", "lastPr": "101.5"}],
            "ts": "1781000000456",
        }

    return payloads()


def two_ticker_payload_source(
    specs: Sequence[ChannelSpec],
) -> AsyncIterable[dict[str, Any]]:
    async def payloads() -> AsyncIterator[dict[str, Any]]:
        symbol = specs[0].inst_id
        for index in range(2):
            yield {
                "arg": {
                    "instType": "USDT-FUTURES",
                    "channel": "ticker",
                    "instId": symbol,
                },
                "data": [
                    {
                        "symbol": symbol,
                        "ts": str(1_781_000_000_123 + index),
                        "lastPr": "101.5",
                    }
                ],
                "ts": str(1_781_000_000_456 + index),
            }

    return payloads()


def ticker_only_payload_source(
    specs: Sequence[ChannelSpec],
) -> AsyncIterable[dict[str, Any]]:
    async def payloads() -> AsyncIterator[dict[str, Any]]:
        symbol = specs[0].inst_id
        yield {
            "arg": {
                "instType": "USDT-FUTURES",
                "channel": "ticker",
                "instId": symbol,
            },
            "data": [{"symbol": symbol, "ts": "1781000000123", "lastPr": "101.5"}],
            "ts": "1781000000456",
        }

    return payloads()


class RecordingShardStore:
    def __init__(self) -> None:
        self.ticker_batches: list[list[TickerLatestRecord]] = []
        self.candle_batches: list[list[Candle1mRecord]] = []
        self.health_batches: list[list[StreamHealthRecord]] = []

    def upsert_ticker_latest(self, tickers: list[TickerLatestRecord]) -> None:
        self.ticker_batches.append(tickers)

    def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
        self.candle_batches.append(candles)

    def upsert_stream_health(self, health: list[StreamHealthRecord]) -> None:
        self.health_batches.append(health)


class RecordingTickerSink:
    def __init__(self) -> None:
        self.tickers: list[TickerLatestRecord] = []

    def record(self, tickers: list[TickerLatestRecord]) -> None:
        self.tickers.extend(tickers)


class FlakyPayloadSource:
    def __init__(self) -> None:
        self.calls = 0
        self.specs_by_call: list[list[ChannelSpec]] = []

    def __call__(
        self,
        specs: Sequence[ChannelSpec],
    ) -> AsyncIterable[dict[str, Any]]:
        self.calls += 1
        self.specs_by_call.append(list(specs))

        async def payloads() -> AsyncIterator[dict[str, Any]]:
            if self.calls == 1:
                raise RuntimeError("temporary websocket failure")
            symbol = specs[0].inst_id
            yield {
                "arg": {
                    "instType": "USDT-FUTURES",
                    "channel": "ticker",
                    "instId": symbol,
                },
                "data": [{"symbol": symbol, "ts": "1781000000123", "lastPr": "101.5"}],
                "ts": "1781000000456",
            }
            yield {
                "arg": {
                    "instType": "USDT-FUTURES",
                    "channel": "candle1m",
                    "instId": symbol,
                },
                "data": [
                    [
                        "1781000040000",
                        "101.5",
                        "102.0",
                        "101.0",
                        "101.8",
                        "10.0",
                        "1018.0",
                        "1018.0",
                        "1",
                    ]
                ],
                "ts": "1781000040500",
            }

        return payloads()


class HangingPayloadSource:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    def __call__(
        self,
        specs: Sequence[ChannelSpec],
    ) -> AsyncIterable[dict[str, Any]]:
        async def payloads() -> AsyncIterator[dict[str, Any]]:
            symbol = specs[0].inst_id
            yield {
                "arg": {
                    "instType": "USDT-FUTURES",
                    "channel": "ticker",
                    "instId": symbol,
                },
                "data": [{"symbol": symbol, "ts": "1781000000123", "lastPr": "101.5"}],
                "ts": "1781000000456",
            }
            self.started.set()
            await asyncio.Event().wait()

        return payloads()


class ClosedThenPayloadSource:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        specs: Sequence[ChannelSpec],
    ) -> AsyncIterable[dict[str, Any]]:
        self.calls += 1

        async def payloads() -> AsyncIterator[dict[str, Any]]:
            if self.calls == 1:
                return
            symbol = specs[0].inst_id
            yield {
                "arg": {
                    "instType": "USDT-FUTURES",
                    "channel": "ticker",
                    "instId": symbol,
                },
                "data": [{"symbol": symbol, "ts": "1781000000123", "lastPr": "101.5"}],
                "ts": "1781000000456",
            }

        return payloads()


class InvalidPayloadSource:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        _specs: Sequence[ChannelSpec],
    ) -> AsyncIterable[dict[str, Any]]:
        self.calls += 1

        async def payloads() -> AsyncIterator[dict[str, Any]]:
            yield {
                "arg": {
                    "instType": "USDT-FUTURES",
                    "channel": "books",
                    "instId": "BTCUSDT",
                },
                "data": [{"unexpected": "payload"}],
                "ts": "1781000000456",
            }

        return payloads()
