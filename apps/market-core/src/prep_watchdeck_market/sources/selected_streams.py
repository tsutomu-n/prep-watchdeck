from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import aiohttp

from prep_watchdeck_market.models import CatalogInstrument, Venue
from prep_watchdeck_market.selected_market import (
    DepthLevel,
    SelectedContractError,
    SelectedDepth,
    SelectedEvent,
    SelectedTrade,
    validate_selected_instrument,
)

BITGET_SELECTED_WS_URL = "wss://ws.bitget.com/v2/ws/public"
HYPERLIQUID_SELECTED_WS_URL = "wss://api.hyperliquid.xyz/ws"
ASTER_SELECTED_WS_URL = "wss://fstream.asterdex.com/ws"

SelectedEmitter = Callable[[SelectedEvent], Awaitable[None]]
WebSocketFactory = Callable[[str], AbstractAsyncContextManager[Any]]


def parse_bitget_selected(
    payload: dict[str, object],
    instrument: CatalogInstrument,
    *,
    received_at: datetime,
) -> tuple[SelectedEvent, ...]:
    _require_venue(instrument, "bitget")
    argument = payload.get("arg")
    if not isinstance(argument, dict):
        return ()
    channel = argument.get("channel")
    if channel not in ("books15", "trade"):
        return ()
    if (
        argument.get("instType") != "USDT-FUTURES"
        or argument.get("instId") != instrument.source_symbol
    ):
        raise SelectedContractError("Bitget event does not match the selected instrument")
    data = payload.get("data")
    if not isinstance(data, list):
        raise SelectedContractError("Bitget selected event data must be a list")

    if channel == "books15":
        if payload.get("action") != "snapshot" or len(data) != 1 or not isinstance(data[0], dict):
            raise SelectedContractError("Bitget books15 event must contain one snapshot")
        row = data[0]
        return (
            SelectedDepth(
                venue="bitget",
                source_symbol=instrument.source_symbol,
                bids=_pair_levels(row.get("bids"), descending=True),
                asks=_pair_levels(row.get("asks"), descending=False),
                source_at=_milliseconds(row.get("ts")),
                received_at=received_at,
                source_channel="books15",
                raw_payload=payload,
            ),
        )

    trades: list[SelectedEvent] = []
    for row in data:
        if not isinstance(row, dict):
            raise SelectedContractError("Bitget trade row must be an object")
        side = row.get("side")
        if side not in ("buy", "sell"):
            raise SelectedContractError("Bitget trade side is unknown")
        trades.append(
            SelectedTrade(
                venue="bitget",
                source_symbol=instrument.source_symbol,
                trade_id=_required_text(row.get("tradeId"), "Bitget tradeId"),
                side=side,
                price=_decimal(row.get("price"), "Bitget trade price"),
                size_base=_decimal(row.get("size"), "Bitget trade size"),
                source_at=_milliseconds(row.get("ts")),
                received_at=received_at,
                source_channel="trade",
                raw_payload={"arg": argument, "data": row},
            )
        )
    return tuple(trades)


def parse_hyperliquid_selected(
    payload: dict[str, object],
    instrument: CatalogInstrument,
    *,
    received_at: datetime,
) -> tuple[SelectedEvent, ...]:
    _require_venue(instrument, "hyperliquid")
    channel = payload.get("channel")
    if channel not in ("l2Book", "trades"):
        return ()
    data = payload.get("data")

    if channel == "l2Book":
        if not isinstance(data, dict) or data.get("coin") != instrument.source_symbol:
            raise SelectedContractError("Hyperliquid book does not match the selected instrument")
        levels = data.get("levels")
        if not isinstance(levels, list) or len(levels) != 2:
            raise SelectedContractError("Hyperliquid book levels must contain bids and asks")
        return (
            SelectedDepth(
                venue="hyperliquid",
                source_symbol=instrument.source_symbol,
                bids=_hyperliquid_levels(levels[0], descending=True),
                asks=_hyperliquid_levels(levels[1], descending=False),
                source_at=_milliseconds(data.get("time")),
                received_at=received_at,
                source_channel="l2Book",
                raw_payload=payload,
            ),
        )

    if not isinstance(data, list):
        raise SelectedContractError("Hyperliquid trades data must be a list")
    trades: list[SelectedEvent] = []
    for row in data:
        if not isinstance(row, dict) or row.get("coin") != instrument.source_symbol:
            raise SelectedContractError("Hyperliquid trade does not match the selected instrument")
        source_side = row.get("side")
        if source_side not in ("B", "A"):
            raise SelectedContractError("Hyperliquid trade side is unknown")
        trades.append(
            SelectedTrade(
                venue="hyperliquid",
                source_symbol=instrument.source_symbol,
                trade_id=_required_text(row.get("tid"), "Hyperliquid tid"),
                side="buy" if source_side == "B" else "sell",
                price=_decimal(row.get("px"), "Hyperliquid trade price"),
                size_base=_decimal(row.get("sz"), "Hyperliquid trade size"),
                source_at=_milliseconds(row.get("time")),
                received_at=received_at,
                source_channel="trades",
                raw_payload={"channel": "trades", "data": row},
            )
        )
    return tuple(trades)


def parse_aster_selected(
    payload: dict[str, object],
    instrument: CatalogInstrument,
    *,
    received_at: datetime,
) -> tuple[SelectedEvent, ...]:
    _require_venue(instrument, "aster")
    event_type = payload.get("e")
    if event_type not in ("depthUpdate", "aggTrade"):
        return ()
    if payload.get("s") != instrument.source_symbol:
        raise SelectedContractError("Aster event does not match the selected instrument")

    if event_type == "depthUpdate":
        return (
            SelectedDepth(
                venue="aster",
                source_symbol=instrument.source_symbol,
                bids=_pair_levels(payload.get("b"), descending=True),
                asks=_pair_levels(payload.get("a"), descending=False),
                source_at=_milliseconds(payload.get("T")),
                received_at=received_at,
                source_channel="depth20@100ms",
                raw_payload=payload,
            ),
        )

    buyer_is_maker = payload.get("m")
    if not isinstance(buyer_is_maker, bool):
        raise SelectedContractError("Aster aggTrade maker flag is unknown")
    return (
        SelectedTrade(
            venue="aster",
            source_symbol=instrument.source_symbol,
            trade_id=_required_text(payload.get("a"), "Aster aggregate trade id"),
            side="sell" if buyer_is_maker else "buy",
            price=_decimal(payload.get("p"), "Aster aggregate trade price"),
            size_base=_decimal(payload.get("q"), "Aster aggregate trade size"),
            source_at=_milliseconds(payload.get("T")),
            received_at=received_at,
            source_channel="aggTrade",
            raw_payload=payload,
        ),
    )


async def produce_selected_stream(
    session: aiohttp.ClientSession | None,
    instrument: CatalogInstrument,
    emit: SelectedEmitter,
    stop_event: asyncio.Event,
    *,
    ws_factory: WebSocketFactory | None = None,
    receive_poll_seconds: float = 0.25,
    reconnect_delay_seconds: float = 1.0,
    clock: Callable[[], datetime] | None = None,
) -> None:
    """Produce selected CLOB depth/trades for one fail-closed catalog instrument."""

    validate_selected_instrument(instrument)
    if receive_poll_seconds <= 0 or reconnect_delay_seconds < 0:
        raise ValueError("poll and reconnect intervals must be valid")
    connect = _resolve_factory(session, ws_factory)
    now = clock or (lambda: datetime.now(UTC))
    url = _venue_url(instrument.venue)

    while not stop_event.is_set():
        try:
            async with connect(url) as websocket:
                for request in _subscriptions(instrument):
                    await websocket.send_json(request)
                while not stop_event.is_set():
                    try:
                        message = await asyncio.wait_for(
                            websocket.receive(), timeout=receive_poll_seconds
                        )
                    except TimeoutError:
                        continue
                    if _is_closed(message):
                        break
                    payload = _json_payload(message)
                    if payload is None:
                        continue
                    try:
                        events = _parse_selected(payload, instrument, received_at=now())
                    except SelectedContractError:
                        continue
                    for event in events:
                        await emit(event)
        except (aiohttp.ClientError, OSError):
            pass

        if not stop_event.is_set() and await _wait_for_stop(stop_event, reconnect_delay_seconds):
            return


class SelectedStreamController:
    """Own exactly the websocket tasks for the current selected venue instruments."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None,
        emit: SelectedEmitter,
        *,
        ws_factories: Mapping[Venue, WebSocketFactory] | None = None,
        cleanup_timeout_seconds: float = 10.0,
        receive_poll_seconds: float = 0.25,
        reconnect_delay_seconds: float = 1.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 0 < cleanup_timeout_seconds <= 10:
            raise ValueError("cleanup_timeout_seconds must be in (0, 10]")
        self._session = session
        self._emit = emit
        self._ws_factories = dict(ws_factories or {})
        self._cleanup_timeout_seconds = cleanup_timeout_seconds
        self._receive_poll_seconds = receive_poll_seconds
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._clock = clock
        self._lock = asyncio.Lock()
        self._generation = 0
        self._stop_event: asyncio.Event | None = None
        self._tasks: tuple[asyncio.Task[None], ...] = ()
        self._fingerprints: tuple[tuple[str, str], ...] = ()

    @property
    def active_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks)

    async def replace_selection(self, instruments: Sequence[CatalogInstrument]) -> None:
        selected = tuple(sorted(instruments, key=lambda item: item.venue))
        for instrument in selected:
            validate_selected_instrument(instrument)
        venues = tuple(instrument.venue for instrument in selected)
        if len(venues) != len(set(venues)):
            raise SelectedContractError("a selection may contain at most one instrument per venue")
        fingerprints = tuple(
            (instrument.venue_instrument_id, instrument.definition_sha256())
            for instrument in selected
        )

        async with self._lock:
            if fingerprints == self._fingerprints and all(not task.done() for task in self._tasks):
                return
            self._generation += 1
            await self._stop_current()
            self._fingerprints = fingerprints
            if not selected:
                return
            stop_event = asyncio.Event()
            generation = self._generation

            async def emit_current(event: SelectedEvent) -> None:
                if generation == self._generation and not stop_event.is_set():
                    await self._emit(event)

            self._stop_event = stop_event
            self._tasks = tuple(
                asyncio.create_task(
                    produce_selected_stream(
                        self._session,
                        instrument,
                        emit_current,
                        stop_event,
                        ws_factory=self._ws_factories.get(instrument.venue),
                        receive_poll_seconds=self._receive_poll_seconds,
                        reconnect_delay_seconds=self._reconnect_delay_seconds,
                        clock=self._clock,
                    ),
                    name=f"selected-{instrument.venue}-{instrument.source_symbol}",
                )
                for instrument in selected
            )

    async def close(self) -> None:
        async with self._lock:
            self._generation += 1
            await self._stop_current()
            self._fingerprints = ()

    async def _stop_current(self) -> None:
        tasks = self._tasks
        if not tasks:
            self._stop_event = None
            return
        if self._stop_event is not None:
            self._stop_event.set()
        for task in tasks:
            task.cancel()
        done, pending = await asyncio.wait(tasks, timeout=self._cleanup_timeout_seconds)
        if pending:
            self._tasks = tuple(pending)
            raise TimeoutError("selected websocket cleanup exceeded its bounded timeout")
        self._tasks = ()
        self._stop_event = None
        failures = [task.exception() for task in done if not task.cancelled()]
        failures = [failure for failure in failures if failure is not None]
        if failures:
            raise BaseExceptionGroup("selected websocket producer failed", failures)


def _parse_selected(
    payload: dict[str, object],
    instrument: CatalogInstrument,
    *,
    received_at: datetime,
) -> tuple[SelectedEvent, ...]:
    if instrument.venue == "bitget":
        return parse_bitget_selected(payload, instrument, received_at=received_at)
    if instrument.venue == "hyperliquid":
        return parse_hyperliquid_selected(payload, instrument, received_at=received_at)
    if instrument.venue == "aster":
        return parse_aster_selected(payload, instrument, received_at=received_at)
    raise SelectedContractError(f"unsupported selected venue: {instrument.venue}")


def _require_venue(instrument: CatalogInstrument, venue: Venue) -> None:
    validate_selected_instrument(instrument)
    if instrument.venue != venue:
        raise SelectedContractError(f"expected {venue} instrument, got {instrument.venue}")


def _venue_url(venue: Venue) -> str:
    return {
        "bitget": BITGET_SELECTED_WS_URL,
        "hyperliquid": HYPERLIQUID_SELECTED_WS_URL,
        "aster": ASTER_SELECTED_WS_URL,
    }[venue]


def _subscriptions(instrument: CatalogInstrument) -> tuple[dict[str, object], ...]:
    symbol = instrument.source_symbol
    if instrument.venue == "bitget":
        return (
            {
                "op": "subscribe",
                "args": [
                    {"instType": "USDT-FUTURES", "channel": "books15", "instId": symbol},
                    {"instType": "USDT-FUTURES", "channel": "trade", "instId": symbol},
                ],
            },
        )
    if instrument.venue == "hyperliquid":
        return (
            {"method": "subscribe", "subscription": {"type": "l2Book", "coin": symbol}},
            {"method": "subscribe", "subscription": {"type": "trades", "coin": symbol}},
        )
    if instrument.venue == "aster":
        lower_symbol = symbol.lower()
        return (
            {
                "method": "SUBSCRIBE",
                "params": [f"{lower_symbol}@depth20@100ms", f"{lower_symbol}@aggTrade"],
                "id": 1,
            },
        )
    raise SelectedContractError(f"unsupported selected venue: {instrument.venue}")


def _pair_levels(value: object, *, descending: bool) -> tuple[DepthLevel, ...]:
    if not isinstance(value, list) or not value:
        raise SelectedContractError("depth levels must be a non-empty list")
    levels: list[DepthLevel] = []
    for row in value:
        if not isinstance(row, list) or len(row) != 2:
            raise SelectedContractError("depth level must contain price and base size")
        levels.append(
            DepthLevel(
                price=_decimal(row[0], "depth price"),
                size_base=_decimal(row[1], "depth size"),
            )
        )
    return _ordered_levels(levels, descending=descending)


def _hyperliquid_levels(value: object, *, descending: bool) -> tuple[DepthLevel, ...]:
    if not isinstance(value, list) or not value:
        raise SelectedContractError("Hyperliquid depth levels must be a non-empty list")
    levels: list[DepthLevel] = []
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("n"), int):
            raise SelectedContractError("Hyperliquid depth level is incomplete")
        levels.append(
            DepthLevel(
                price=_decimal(row.get("px"), "Hyperliquid depth price"),
                size_base=_decimal(row.get("sz"), "Hyperliquid depth size"),
            )
        )
    return _ordered_levels(levels, descending=descending)


def _ordered_levels(
    levels: Sequence[DepthLevel],
    *,
    descending: bool,
) -> tuple[DepthLevel, ...]:
    ordered = sorted(levels, key=lambda level: level.price, reverse=descending)
    if len({level.price for level in ordered}) != len(ordered):
        raise SelectedContractError("depth contains duplicate prices")
    return tuple(ordered[:20])


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise SelectedContractError(f"{field_name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise SelectedContractError(f"{field_name} must be numeric") from error
    if not parsed.is_finite() or parsed <= 0:
        raise SelectedContractError(f"{field_name} must be positive and finite")
    return parsed


def _milliseconds(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SelectedContractError("source timestamp must be milliseconds")
    try:
        milliseconds = int(value)
    except ValueError as error:
        raise SelectedContractError("source timestamp must be milliseconds") from error
    if milliseconds <= 0:
        raise SelectedContractError("source timestamp must be positive")
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise SelectedContractError("source timestamp is outside datetime range") from error


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).strip():
        raise SelectedContractError(f"{field_name} must not be empty")
    return str(value)


def _resolve_factory(
    session: aiohttp.ClientSession | None,
    factory: WebSocketFactory | None,
) -> WebSocketFactory:
    if factory is not None:
        return factory
    if session is None:
        raise ValueError("session or ws_factory is required")
    return lambda url: session.ws_connect(url, heartbeat=20)


def _is_closed(message: object) -> bool:
    return getattr(message, "type", None) in {
        aiohttp.WSMsgType.CLOSE,
        aiohttp.WSMsgType.CLOSED,
        aiohttp.WSMsgType.ERROR,
    }


def _json_payload(message: object) -> dict[str, object] | None:
    if isinstance(message, dict):
        return message if all(isinstance(key, str) for key in message) else None
    data = getattr(message, "data", None)
    if isinstance(data, dict):
        return data if all(isinstance(key, str) for key in data) else None
    if not isinstance(data, str):
        return None
    try:
        decoded = json.loads(data)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


async def _wait_for_stop(stop_event: asyncio.Event, seconds: float) -> bool:
    if seconds <= 0:
        return stop_event.is_set()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True
