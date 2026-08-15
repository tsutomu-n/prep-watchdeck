from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import aiohttp

from prep_watchdeck_market.candles import Candle1m
from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.sources.aster_candle_stream import produce_aster_candles
from prep_watchdeck_market.sources.hyperliquid_candle_stream import (
    HYPERLIQUID_SUBSCRIPTION_INTERVAL_SECONDS,
    produce_hyperliquid_candles,
)


def test_hyperliquid_stream_retains_finalizer_across_reconnect_and_cleans_up() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        emitted: list[Candle1m] = []
        clock = _MutableClock(datetime(2026, 8, 14, 10, 0, 30, tzinfo=UTC))
        first = _FakeWebSocket((_text_message(_hyperliquid_event()), _closed_message()))
        second = _FakeWebSocket(())
        factory = _FakeFactory((first, second), on_second=lambda: clock.set(_bucket_end_plus_5()))

        async def emit(candle: Candle1m) -> None:
            emitted.append(candle)
            stop_event.set()

        await asyncio.wait_for(
            produce_hyperliquid_candles(
                None,
                (
                    _instrument("hyperliquid", "BTC"),
                    _instrument("hyperliquid", "ETH"),
                    _instrument("aster", "IGNOREDUSDT"),
                ),
                emit,
                stop_event,
                ws_factory=factory,
                subscription_interval_seconds=0,
                receive_poll_seconds=0.01,
                reconnect_delay_seconds=0,
                clock=clock,
            ),
            timeout=1,
        )

        assert factory.calls == 2
        assert first.exited and second.exited
        assert first.sent == second.sent
        assert first.sent == [
            {
                "method": "subscribe",
                "subscription": {"type": "candle", "coin": "BTC", "interval": "1m"},
            },
            {
                "method": "subscribe",
                "subscription": {"type": "candle", "coin": "ETH", "interval": "1m"},
            },
        ]
        assert HYPERLIQUID_SUBSCRIPTION_INTERVAL_SECONDS >= 1 / 20
        assert len(emitted) == 1
        assert emitted[0].venue_instrument_id == "hyperliquid:BTC"
        assert emitted[0].finality == "derived_final"
        assert emitted[0].close_price == Decimal("106")

    asyncio.run(scenario())


def test_aster_stream_shards_181_symbols_and_emits_only_closed_candles() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        emitted: list[Candle1m] = []
        sockets = (_AsterFakeWebSocket(), _AsterFakeWebSocket())
        factory = _FakeFactory(sockets)
        instruments = tuple(_instrument("aster", f"S{index:03d}USDT") for index in range(181))

        async def emit(candle: Candle1m) -> None:
            emitted.append(candle)
            if len(emitted) == 2:
                stop_event.set()

        await asyncio.wait_for(
            produce_aster_candles(
                None,
                instruments,
                emit,
                stop_event,
                ws_factory=factory,
                receive_poll_seconds=0.01,
                reconnect_delay_seconds=0,
            ),
            timeout=1,
        )

        assert factory.calls == 2
        assert all(socket.exited for socket in sockets)
        subscriptions = [socket.sent[0] for socket in sockets]
        parameter_lists: list[list[object]] = []
        for item in subscriptions:
            params = item["params"]
            assert isinstance(params, list)
            parameter_lists.append(params)
        assert sorted(len(params) for params in parameter_lists) == [1, 180]
        assert all(item["method"] == "SUBSCRIBE" for item in subscriptions)
        raw_streams = [stream for params in parameter_lists for stream in params]
        assert all(isinstance(stream, str) for stream in raw_streams)
        streams = [stream for stream in raw_streams if isinstance(stream, str)]
        assert all(stream == stream.lower() and stream.endswith("@kline_1m") for stream in streams)
        assert len(emitted) == 2
        assert all(candle.finality == "confirmed" for candle in emitted)

    asyncio.run(scenario())


@dataclass
class _MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value

    def set(self, value: datetime) -> None:
        self.value = value


class _FakeFactory:
    def __init__(self, sockets: tuple[_FakeWebSocket, ...], on_second=None) -> None:
        self._sockets = sockets
        self._on_second = on_second
        self.calls = 0

    def __call__(self, url: str):
        assert url.startswith("wss://")
        index = self.calls
        self.calls += 1
        if self.calls == 2 and self._on_second is not None:
            self._on_second()
        return self._sockets[index]


class _FakeWebSocket:
    def __init__(self, messages: tuple[object, ...]) -> None:
        self._messages = list(messages)
        self.sent: list[dict[str, object]] = []
        self.exited = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.exited = True

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    async def receive(self):
        if self._messages:
            return self._messages.pop(0)
        await asyncio.Event().wait()


class _AsterFakeWebSocket(_FakeWebSocket):
    def __init__(self) -> None:
        super().__init__(())
        self._receive_count = 0

    async def receive(self):
        self._receive_count += 1
        params = self.sent[0]["params"]
        assert isinstance(params, list)
        symbol = str(params[0]).split("@", maxsplit=1)[0].upper()
        if self._receive_count == 1:
            return _text_message(_aster_event(symbol, closed=False))
        if self._receive_count == 2:
            return _text_message(_aster_event(symbol, closed=True))
        await asyncio.Event().wait()


def _instrument(venue: str, symbol: str) -> CatalogInstrument:
    return CatalogInstrument(
        venue=venue,  # type: ignore[arg-type]
        source_symbol=symbol,
        active=True,
        source_status="normal",
        asset_class="crypto",
        market_type="linear_perpetual",
        execution_model="clob",
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        settle_asset="USDC" if venue == "hyperliquid" else "USDT",
        collateral_asset="USDC" if venue == "hyperliquid" else "USDT",
        quantity_unit="base",
        contract_multiplier=Decimal("1"),
        price_tick=None,
        amount_step=None,
        funding_interval_seconds=3_600,
        raw_definition={},
    )


def _hyperliquid_event() -> dict[str, object]:
    return {
        "channel": "candle",
        "data": {
            "t": 1_786_701_600_000,
            "T": 1_786_701_660_000,
            "s": "BTC",
            "i": "1m",
            "o": "100",
            "h": "110",
            "l": "90",
            "c": "106",
            "v": "5",
            "n": 10,
        },
    }


def _aster_event(symbol: str, *, closed: bool) -> dict[str, object]:
    return {
        "E": 1_786_701_660_000,
        "s": symbol,
        "k": {
            "t": 1_786_701_600_000,
            "s": symbol,
            "i": "1m",
            "o": "100",
            "h": "110",
            "l": "90",
            "c": "105",
            "v": "5",
            "q": "525",
            "n": 10,
            "x": closed,
        },
    }


def _bucket_end_plus_5() -> datetime:
    return datetime(2026, 8, 14, 10, 1, 5, tzinfo=UTC)


def _text_message(payload: dict[str, object]):
    return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(payload))


def _closed_message():
    return SimpleNamespace(type=aiohttp.WSMsgType.CLOSED, data=None)
