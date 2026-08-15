from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic

import pytest

from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.selected_market import (
    SelectedContractError,
    SelectedDepth,
    SelectedTrade,
)
from prep_watchdeck_market.sources.selected_streams import (
    SelectedStreamController,
    parse_aster_selected,
    parse_bitget_selected,
    parse_hyperliquid_selected,
)

RECEIVED_AT = datetime(2026, 8, 14, 10, 0, 1, tzinfo=UTC)
SOURCE_MS = 1_786_701_600_000


def test_three_venue_selected_parsers_normalize_depth_trades_and_fail_closed() -> None:
    bitget = _instrument("bitget", "BTCUSDT")
    hyperliquid = _instrument("hyperliquid", "BTC")
    aster = _instrument("aster", "BTCUSDT")

    bitget_depth = parse_bitget_selected(
        {
            "action": "snapshot",
            "arg": {
                "instType": "USDT-FUTURES",
                "channel": "books15",
                "instId": "BTCUSDT",
            },
            "data": [
                {"bids": [["100", "2"], ["99", "3"]], "asks": [["101", "4"]], "ts": str(SOURCE_MS)}
            ],
        },
        bitget,
        received_at=RECEIVED_AT,
    )
    bitget_trade = parse_bitget_selected(
        {
            "arg": {
                "instType": "USDT-FUTURES",
                "channel": "trade",
                "instId": "BTCUSDT",
            },
            "data": [
                {
                    "ts": str(SOURCE_MS + 1),
                    "price": "100.5",
                    "size": "0.25",
                    "side": "buy",
                    "tradeId": "bg-1",
                }
            ],
        },
        bitget,
        received_at=RECEIVED_AT,
    )
    hyperliquid_depth = parse_hyperliquid_selected(
        {
            "channel": "l2Book",
            "data": {
                "coin": "BTC",
                "time": SOURCE_MS,
                "levels": [
                    [{"px": str(100 - index), "sz": "1", "n": index + 1} for index in range(21)],
                    [{"px": str(101 + index), "sz": "2", "n": index + 1} for index in range(21)],
                ],
            },
        },
        hyperliquid,
        received_at=RECEIVED_AT,
    )
    hyperliquid_trade = parse_hyperliquid_selected(
        {
            "channel": "trades",
            "data": [
                {
                    "coin": "BTC",
                    "side": "A",
                    "px": "100.25",
                    "sz": "0.5",
                    "time": SOURCE_MS + 2,
                    "tid": 123,
                    "hash": "0xabc",
                }
            ],
        },
        hyperliquid,
        received_at=RECEIVED_AT,
    )
    aster_depth = parse_aster_selected(
        {
            "e": "depthUpdate",
            "E": SOURCE_MS + 3,
            "T": SOURCE_MS + 2,
            "s": "BTCUSDT",
            "U": 1,
            "u": 2,
            "pu": 0,
            "b": [["100", "3"]],
            "a": [["101", "4"]],
        },
        aster,
        received_at=RECEIVED_AT,
    )
    aster_trade = parse_aster_selected(
        {
            "e": "aggTrade",
            "E": SOURCE_MS + 4,
            "s": "BTCUSDT",
            "a": 456,
            "p": "100.75",
            "q": "0.75",
            "f": 1,
            "l": 2,
            "T": SOURCE_MS + 3,
            "m": False,
        },
        aster,
        received_at=RECEIVED_AT,
    )

    raw_depths = (bitget_depth[0], hyperliquid_depth[0], aster_depth[0])
    assert all(isinstance(event, SelectedDepth) for event in raw_depths)
    depths = tuple(event for event in raw_depths if isinstance(event, SelectedDepth))
    assert [(len(event.bids), len(event.asks)) for event in depths] == [(2, 1), (20, 20), (1, 1)]
    assert [event.venue for event in depths] == ["bitget", "hyperliquid", "aster"]
    assert all(event.received_at == RECEIVED_AT and event.source_at is not None for event in depths)
    assert all(len(event.payload_hash) == 64 for event in depths)

    raw_trades = (bitget_trade[0], hyperliquid_trade[0], aster_trade[0])
    assert all(isinstance(event, SelectedTrade) for event in raw_trades)
    trades = tuple(event for event in raw_trades if isinstance(event, SelectedTrade))
    assert [event.side for event in trades] == ["buy", "sell", "buy"]
    assert [event.trade_id for event in trades] == ["bg-1", "123", "456"]
    assert [event.size_base for event in trades] == [
        Decimal("0.25"),
        Decimal("0.5"),
        Decimal("0.75"),
    ]

    with pytest.raises(SelectedContractError, match="USD-like"):
        parse_hyperliquid_selected(
            {"channel": "l2Book", "data": {}},
            _instrument("hyperliquid", "BTC", quote="EUR"),
            received_at=RECEIVED_AT,
        )
    with pytest.raises(SelectedContractError, match="maker flag"):
        parse_aster_selected(
            {
                "e": "aggTrade",
                "s": "BTCUSDT",
                "a": 1,
                "p": "100",
                "q": "1",
                "T": SOURCE_MS,
                "m": "unknown",
            },
            aster,
            received_at=RECEIVED_AT,
        )
    assert parse_bitget_selected({"event": "subscribe"}, bitget, received_at=RECEIVED_AT) == ()


def test_selection_replacement_closes_old_three_venue_sockets_without_orphans() -> None:
    async def scenario() -> None:
        event_log: list[str] = []
        sockets = {
            venue: (
                _FakeWebSocket(f"{venue}-old", event_log),
                _FakeWebSocket(f"{venue}-new", event_log),
            )
            for venue in ("bitget", "hyperliquid", "aster")
        }
        factories = {venue: _FakeFactory(items) for venue, items in sockets.items()}
        emitted: list[object] = []

        async def emit(event: object) -> None:
            emitted.append(event)

        controller = SelectedStreamController(
            None,
            emit,  # type: ignore[arg-type]
            ws_factories=factories,  # type: ignore[arg-type]
            cleanup_timeout_seconds=0.5,
            receive_poll_seconds=0.01,
            reconnect_delay_seconds=0,
            clock=lambda: RECEIVED_AT,
        )
        old_group = (
            _instrument("bitget", "BTCUSDT"),
            _instrument("hyperliquid", "BTC"),
            _instrument("aster", "BTCUSDT"),
        )
        new_group = (
            _instrument("bitget", "ETHUSDT"),
            _instrument("hyperliquid", "ETH"),
            _instrument("aster", "ETHUSDT"),
        )

        await controller.replace_selection(old_group)
        await _wait_until(
            lambda: sum(item.entered for items in sockets.values() for item in items) == 3
        )
        started = monotonic()
        await controller.replace_selection(new_group)
        elapsed = monotonic() - started
        await _wait_until(
            lambda: sum(item.entered for items in sockets.values() for item in items) == 6
        )

        old_sockets = [items[0] for items in sockets.values()]
        new_sockets = [items[1] for items in sockets.values()]
        assert elapsed < 0.5
        assert all(item.exited for item in old_sockets)
        assert controller.active_task_count == 3
        assert max(event_log.index(f"exit:{item.name}") for item in old_sockets) < min(
            event_log.index(f"enter:{item.name}") for item in new_sockets
        )
        assert sockets["bitget"][0].sent == [
            {
                "op": "subscribe",
                "args": [
                    {
                        "instType": "USDT-FUTURES",
                        "channel": "books15",
                        "instId": "BTCUSDT",
                    },
                    {
                        "instType": "USDT-FUTURES",
                        "channel": "trade",
                        "instId": "BTCUSDT",
                    },
                ],
            }
        ]
        assert sockets["hyperliquid"][0].sent == [
            {"method": "subscribe", "subscription": {"type": "l2Book", "coin": "BTC"}},
            {"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}},
        ]
        assert sockets["aster"][0].sent == [
            {
                "method": "SUBSCRIBE",
                "params": ["btcusdt@depth20@100ms", "btcusdt@aggTrade"],
                "id": 1,
            }
        ]

        await controller.close()
        assert controller.active_task_count == 0
        assert all(item.exited for item in new_sockets)
        assert emitted == []

    asyncio.run(scenario())


class _FakeFactory:
    def __init__(self, sockets: tuple[_FakeWebSocket, ...]) -> None:
        self._sockets = sockets
        self.calls = 0

    def __call__(self, url: str) -> _FakeWebSocket:
        assert url.startswith("wss://")
        socket = self._sockets[self.calls]
        self.calls += 1
        return socket


class _FakeWebSocket:
    def __init__(self, name: str, event_log: list[str]) -> None:
        self.name = name
        self._event_log = event_log
        self.sent: list[dict[str, object]] = []
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> _FakeWebSocket:
        self.entered = True
        self._event_log.append(f"enter:{self.name}")
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.exited = True
        self._event_log.append(f"exit:{self.name}")

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    async def receive(self) -> None:
        await asyncio.Event().wait()


async def _wait_until(predicate, *, timeout_seconds: float = 0.5) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0)


def _instrument(
    venue: str,
    symbol: str,
    *,
    quote: str = "USDT",
) -> CatalogInstrument:
    collateral = "USDC" if venue == "hyperliquid" else "USDT"
    return CatalogInstrument(
        venue=venue,  # type: ignore[arg-type]
        source_symbol=symbol,
        active=True,
        source_status="normal",
        asset_class="crypto",
        market_type="linear_perpetual",
        execution_model="clob",
        base_asset=symbol.removesuffix("USDT"),
        quote_asset=quote,
        settle_asset=collateral,
        collateral_asset=collateral,
        quantity_unit="base",
        contract_multiplier=Decimal("1"),
        price_tick=None,
        amount_step=None,
        funding_interval_seconds=3_600,
        raw_definition={},
    )
