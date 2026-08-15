from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Collection, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

import aiohttp

from prep_watchdeck_market.candles import Candle1m, CandleParseError
from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.sources.aster_candles import parse_aster_candle

ASTER_WS_URL = "wss://fstream.asterdex.com/ws"
ASTER_MAX_SYMBOLS_PER_CONNECTION = 180
ASTER_MAX_CONNECTION_SECONDS = 23 * 60 * 60

CandleEmitter = Callable[[Candle1m], Awaitable[None]]
WebSocketFactory = Callable[[str], AbstractAsyncContextManager[Any]]


async def produce_aster_candles(
    session: aiohttp.ClientSession | None,
    instruments: Collection[CatalogInstrument],
    emit: CandleEmitter,
    stop_event: asyncio.Event,
    *,
    ws_factory: WebSocketFactory | None = None,
    max_symbols_per_connection: int = ASTER_MAX_SYMBOLS_PER_CONNECTION,
    max_connection_seconds: float = ASTER_MAX_CONNECTION_SECONDS,
    receive_poll_seconds: float = 1.0,
    reconnect_delay_seconds: float = 1.0,
) -> None:
    """Produce source-confirmed Aster candles using bounded websocket shards."""

    if not 0 < max_symbols_per_connection <= ASTER_MAX_SYMBOLS_PER_CONNECTION:
        raise ValueError("max_symbols_per_connection must be between 1 and 180")
    if max_connection_seconds <= 0 or receive_poll_seconds <= 0 or reconnect_delay_seconds < 0:
        raise ValueError("connection, poll, and reconnect intervals must be valid")
    connect = _resolve_factory(session, ws_factory)
    symbols = tuple(
        sorted(
            {
                instrument.source_symbol
                for instrument in instruments
                if instrument.venue == "aster" and instrument.active
            }
        )
    )
    if not symbols:
        return
    shards = tuple(_chunks(symbols, max_symbols_per_connection))
    async with asyncio.TaskGroup() as group:
        for shard_index, shard in enumerate(shards, start=1):
            group.create_task(
                _run_shard(
                    connect,
                    shard,
                    emit,
                    stop_event,
                    request_id=shard_index,
                    max_connection_seconds=max_connection_seconds,
                    receive_poll_seconds=receive_poll_seconds,
                    reconnect_delay_seconds=reconnect_delay_seconds,
                ),
                name=f"aster-candle-shard-{shard_index}",
            )


async def _run_shard(
    connect: WebSocketFactory,
    symbols: Sequence[str],
    emit: CandleEmitter,
    stop_event: asyncio.Event,
    *,
    request_id: int,
    max_connection_seconds: float,
    receive_poll_seconds: float,
    reconnect_delay_seconds: float,
) -> None:
    while not stop_event.is_set():
        try:
            async with connect(ASTER_WS_URL) as websocket:
                await websocket.send_json(
                    {
                        "method": "SUBSCRIBE",
                        "params": [f"{symbol.lower()}@kline_1m" for symbol in symbols],
                        "id": request_id,
                    }
                )
                loop = asyncio.get_running_loop()
                reconnect_at = loop.time() + max_connection_seconds
                while not stop_event.is_set():
                    remaining = reconnect_at - loop.time()
                    if remaining <= 0:
                        break
                    try:
                        message = await asyncio.wait_for(
                            websocket.receive(),
                            timeout=min(receive_poll_seconds, remaining),
                        )
                    except TimeoutError:
                        continue
                    if _is_closed(message):
                        break
                    payload = _json_payload(message)
                    if payload is None or ("k" not in payload and "data" not in payload):
                        continue
                    try:
                        candle = parse_aster_candle(payload, observed_at=_utc_now())
                    except CandleParseError:
                        continue
                    if candle is not None:
                        await emit(candle)
        except (aiohttp.ClientError, OSError, TimeoutError):
            pass

        if not stop_event.is_set() and await _wait_for_stop(stop_event, reconnect_delay_seconds):
            return


def _chunks(symbols: Sequence[str], size: int) -> Sequence[tuple[str, ...]]:
    return tuple(tuple(symbols[index : index + size]) for index in range(0, len(symbols), size))


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
    message_type = getattr(message, "type", None)
    return message_type in {
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


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _wait_for_stop(stop_event: asyncio.Event, seconds: float) -> bool:
    if seconds <= 0:
        return stop_event.is_set()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True
