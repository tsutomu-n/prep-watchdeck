from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import aiohttp
import pytest
from loguru import logger
from psycopg import Connection

from prep_watchdeck_market.candle_runtime import (
    CandleBatchWriter,
    poll_bitget_sweep,
)
from prep_watchdeck_market.candle_store import CandleStoreResult
from prep_watchdeck_market.candles import Candle1m
from prep_watchdeck_market.models import CatalogInstrument


def test_writer_deduplicates_before_single_batched_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        stored_batches: list[tuple[Candle1m, ...]] = []
        flush_logs: list[dict[str, object]] = []

        def fake_upsert(
            _connection: Connection[Any], candles: tuple[Candle1m, ...]
        ) -> CandleStoreResult:
            stored_batches.append(candles)
            return CandleStoreResult(received=len(candles), stored=len(candles), ignored=0)

        monkeypatch.setattr("prep_watchdeck_market.candle_runtime.upsert_candles", fake_upsert)
        connection = cast(Connection[Any], object())
        writer = CandleBatchWriter(connection)
        task = asyncio.create_task(writer.run())
        first = _candle("BTCUSDT", observed_second=5, close_price="101")
        newer = replace(
            first,
            close_price=Decimal("102"),
            observed_at=first.observed_at + timedelta(seconds=1),
        )
        second = _candle("ETHUSDT", observed_second=5, close_price="105")

        sink_id = logger.add(
            lambda message: flush_logs.append(dict(message.record["extra"])),
            filter=lambda record: record["extra"].get("event") == "candle_flush",
        )
        try:
            await writer.add((first, newer, second))
            await writer.close()
            await task
        finally:
            logger.remove(sink_id)

        assert len(stored_batches) == 1
        assert len(stored_batches[0]) == 2
        assert stored_batches[0][0].close_price == Decimal("102")
        assert flush_logs == [
            {
                "event": "candle_flush",
                "received": 3,
                "deduplicated": 2,
                "stored": 2,
                "ignored": 0,
                "error_code": None,
            }
        ]

    asyncio.run(scenario())


def test_writer_waits_for_catalog_transition_and_drops_removed_instrument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        stored_batches: list[tuple[Candle1m, ...]] = []

        def fake_upsert(
            _connection: Connection[Any], candles: tuple[Candle1m, ...]
        ) -> CandleStoreResult:
            stored_batches.append(candles)
            return CandleStoreResult(received=len(candles), stored=len(candles), ignored=0)

        monkeypatch.setattr("prep_watchdeck_market.candle_runtime.upsert_candles", fake_upsert)
        connection = cast(Connection[Any], object())
        catalog_transition = asyncio.Lock()
        writer = CandleBatchWriter(
            connection,
            catalog_update_lock=catalog_transition,
            active_instrument_ids=lambda: {"bitget:BTCUSDT"},
        )
        await catalog_transition.acquire()
        task = asyncio.create_task(writer.run())

        await writer.add(
            (
                _candle("BTCUSDT", observed_second=5, close_price="101"),
                _candle("ETHUSDT", observed_second=5, close_price="102"),
            )
        )
        await writer.close()
        await asyncio.sleep(0.01)
        assert stored_batches == []

        catalog_transition.release()
        await task

        assert len(stored_batches) == 1
        assert [item.venue_instrument_id for item in stored_batches[0]] == ["bitget:BTCUSDT"]

    asyncio.run(scenario())


def test_writer_admits_only_candles_covered_by_current_catalog_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        stored_batches: list[tuple[Candle1m, ...]] = []
        flush_logs: list[dict[str, object]] = []

        def fake_upsert(
            _connection: Connection[Any], candles: tuple[Candle1m, ...]
        ) -> CandleStoreResult:
            stored_batches.append(candles)
            return CandleStoreResult(received=len(candles), stored=len(candles), ignored=0)

        monkeypatch.setattr("prep_watchdeck_market.candle_runtime.upsert_candles", fake_upsert)
        current_version_starts = {
            "bitget:BTCUSDT": datetime(2026, 8, 14, 10, 1, 5, tzinfo=UTC),
            "hyperliquid:BTC": datetime(2026, 8, 14, 10, 1, 5, tzinfo=UTC),
            "aster:BTCUSDT": datetime(2026, 8, 14, 10, 1, 5, tzinfo=UTC),
        }
        writer = CandleBatchWriter(
            cast(Connection[Any], object()),
            catalog_update_lock=asyncio.Lock(),
            active_instrument_ids=lambda: set(current_version_starts),
            current_version_starts=lambda: current_version_starts,
        )
        first_bucket = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)

        def at(candle: Candle1m, venue: str, symbol: str, minute: int) -> Candle1m:
            bucket = first_bucket + timedelta(minutes=minute)
            return replace(
                candle,
                venue=cast(Any, venue),
                source_symbol=symbol,
                bucket_start=bucket,
                source_at=bucket + timedelta(minutes=1),
                observed_at=bucket + timedelta(minutes=1, seconds=5),
            )

        candidates = (
            at(_candle("BTCUSDT", observed_second=5, close_price="101"), "bitget", "BTCUSDT", 0),
            at(_candle("BTCUSDT", observed_second=5, close_price="102"), "bitget", "BTCUSDT", 1),
            at(_candle("BTCUSDT", observed_second=5, close_price="103"), "bitget", "BTCUSDT", 2),
            at(_candle("BTC", observed_second=5, close_price="104"), "hyperliquid", "BTC", 2),
            at(_candle("BTCUSDT", observed_second=5, close_price="105"), "aster", "BTCUSDT", 1),
            at(_candle("BTCUSDT", observed_second=5, close_price="106"), "aster", "BTCUSDT", 2),
        )

        sink_id = logger.add(
            lambda message: flush_logs.append(dict(message.record["extra"])),
            filter=lambda record: record["extra"].get("event") == "candle_flush",
        )
        try:
            await writer.add(candidates)
            current_version_starts["bitget:BTCUSDT"] = datetime(2026, 8, 14, 10, 2, 30, tzinfo=UTC)
            task = asyncio.create_task(writer.run())
            await writer.close()
            await task
        finally:
            logger.remove(sink_id)

        assert [[item.venue_instrument_id for item in batch] for batch in stored_batches] == [
            ["aster:BTCUSDT", "hyperliquid:BTC"]
        ]
        assert flush_logs == [
            {
                "event": "candle_flush",
                "received": 3,
                "deduplicated": 3,
                "stored": 2,
                "ignored": 1,
                "error_code": None,
            }
        ]

    asyncio.run(scenario())


def test_bitget_sweep_aligns_end_time_limits_concurrency_and_keeps_last_three() -> None:
    async def scenario() -> None:
        session = _FakeSession(expected_concurrency=4)
        writer = _CollectingWriter()
        observed_at = datetime(2026, 8, 14, 10, 1, 37, tzinfo=UTC)
        instruments = tuple(_instrument(f"COIN{index}USDT") for index in range(6))

        await poll_bitget_sweep(
            cast(aiohttp.ClientSession, session),
            instruments,
            cast(CandleBatchWriter, writer),
            asyncio.Event(),
            utc_clock=lambda: observed_at,
            sweep_seconds=0,
        )

        assert session.max_active == 4
        assert len(session.calls) == 6
        assert all(call["productType"] == "USDT-FUTURES" for call in session.calls)
        assert all(call["granularity"] == "1m" for call in session.calls)
        assert all(call["limit"] == "3" for call in session.calls)
        expected_end = int(observed_at.replace(second=0, microsecond=0).timestamp() * 1_000)
        assert all(call["endTime"] == str(expected_end) for call in session.calls)
        assert len(writer.batches) == 6
        assert all(len(batch) == 3 for batch in writer.batches)
        assert len({candle.storage_key for batch in writer.batches for candle in batch}) == 18

    asyncio.run(scenario())


class _FakeSession:
    def __init__(self, *, expected_concurrency: int) -> None:
        self.expected_concurrency = expected_concurrency
        self.active = 0
        self.max_active = 0
        self.release = asyncio.Event()
        self.calls: list[dict[str, str]] = []

    def get(
        self,
        _url: str,
        *,
        params: dict[str, str],
        timeout: aiohttp.ClientTimeout,
    ) -> _FakeResponse:
        assert timeout.total == 20
        self.calls.append(dict(params))
        return _FakeResponse(self)


class _FakeResponse:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self, *, content_type: object = None) -> dict[str, object]:
        del content_type
        self._session.active += 1
        self._session.max_active = max(
            self._session.max_active,
            self._session.active,
        )
        if self._session.active == self._session.expected_concurrency:
            self._session.release.set()
        await self._session.release.wait()
        self._session.active -= 1
        return {
            "code": "00000",
            "requestTime": 1_786_701_660_000,
            "data": [
                ["1786701420000", "100", "101", "99", "100", "1", "100"],
                ["1786701480000", "100", "102", "99", "101", "2", "201"],
                ["1786701540000", "101", "103", "100", "102", "3", "305"],
                ["1786701600000", "102", "104", "101", "103", "4", "410"],
            ],
        }


class _CollectingWriter:
    def __init__(self) -> None:
        self.batches: list[tuple[Candle1m, ...]] = []

    async def add(self, candles: tuple[Candle1m, ...]) -> None:
        self.batches.append(candles)


def _instrument(symbol: str) -> CatalogInstrument:
    return CatalogInstrument(
        venue="bitget",
        source_symbol=symbol,
        active=True,
        source_status="normal",
        asset_class="crypto",
        market_type="linear_perpetual",
        execution_model="clob",
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        settle_asset="USDT",
        collateral_asset="USDT",
        quantity_unit="base",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.01"),
        amount_step=Decimal("0.001"),
        funding_interval_seconds=28_800,
        raw_definition={"symbol": symbol},
    )


def _candle(symbol: str, *, observed_second: int, close_price: str) -> Candle1m:
    bucket = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    return Candle1m(
        venue="bitget",
        source_symbol=symbol,
        bucket_start=bucket,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal(close_price),
        volume_base=Decimal("5"),
        volume_notional=Decimal("500"),
        trade_count=None,
        finality="confirmed",
        source_at=bucket + timedelta(minutes=1),
        observed_at=bucket + timedelta(minutes=1, seconds=observed_second),
    )
