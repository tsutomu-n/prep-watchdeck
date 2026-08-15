from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Collection
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

import aiohttp

from prep_watchdeck_market.candles import Candle1m, CandleParseError
from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.sources.hyperliquid_candles import HyperliquidCandleFinalizer

HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"
HYPERLIQUID_SUBSCRIPTION_INTERVAL_SECONDS = 0.05

CandleEmitter = Callable[[Candle1m], Awaitable[None]]
WebSocketFactory = Callable[[str], AbstractAsyncContextManager[Any]]


async def produce_hyperliquid_candles(
    session: aiohttp.ClientSession | None,
    instruments: Collection[CatalogInstrument],
    emit: CandleEmitter,
    stop_event: asyncio.Event,
    *,
    ws_factory: WebSocketFactory | None = None,
    subscription_interval_seconds: float = HYPERLIQUID_SUBSCRIPTION_INTERVAL_SECONDS,
    receive_poll_seconds: float = 0.25,
    reconnect_delay_seconds: float = 1.0,
    clock: Callable[[], datetime] | None = None,
) -> None:
    """Produce derived-final Core perp candles while retaining state across reconnects."""

    if subscription_interval_seconds < 0:
        raise ValueError("subscription_interval_seconds must not be negative")
    if receive_poll_seconds <= 0 or reconnect_delay_seconds < 0:
        raise ValueError("poll and reconnect intervals must be valid")
    connect = _resolve_factory(session, ws_factory)
    now = clock or (lambda: datetime.now(UTC))
    symbols = tuple(
        sorted(
            {
                instrument.source_symbol
                for instrument in instruments
                if instrument.venue == "hyperliquid"
                and instrument.active
                and ":" not in instrument.source_symbol
            }
        )
    )
    if not symbols:
        return

    finalizer = HyperliquidCandleFinalizer()
    while not stop_event.is_set():
        try:
            async with connect(HYPERLIQUID_WS_URL) as websocket:
                for symbol in symbols:
                    if stop_event.is_set():
                        return
                    await websocket.send_json(
                        {
                            "method": "subscribe",
                            "subscription": {
                                "type": "candle",
                                "coin": symbol,
                                "interval": "1m",
                            },
                        }
                    )
                    if subscription_interval_seconds and await _wait_for_stop(
                        stop_event, subscription_interval_seconds
                    ):
                        return

                await _emit_finalized(finalizer, emit, now())
                while not stop_event.is_set():
                    try:
                        message = await asyncio.wait_for(
                            websocket.receive(), timeout=receive_poll_seconds
                        )
                    except TimeoutError:
                        await _emit_finalized(finalizer, emit, now())
                        continue
                    if _is_closed(message):
                        break
                    payload = _json_payload(message)
                    if payload is None or payload.get("channel") != "candle":
                        continue
                    try:
                        finalizer.ingest(payload, observed_at=now())
                    except CandleParseError:
                        continue
                    await _emit_finalized(finalizer, emit, now())
        except (aiohttp.ClientError, OSError, TimeoutError):
            pass

        await _emit_finalized(finalizer, emit, now())
        if not stop_event.is_set() and await _wait_for_stop(stop_event, reconnect_delay_seconds):
            return


async def _emit_finalized(
    finalizer: HyperliquidCandleFinalizer,
    emit: CandleEmitter,
    now: datetime,
) -> None:
    for candle in finalizer.finalize(now=now):
        await emit(candle)


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


async def _wait_for_stop(stop_event: asyncio.Event, seconds: float) -> bool:
    if seconds <= 0:
        return stop_event.is_set()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True
