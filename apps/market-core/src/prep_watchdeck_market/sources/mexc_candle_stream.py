from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime

import aiohttp

from prep_watchdeck_market.candles import CandleParseError
from prep_watchdeck_market.sources.mexc_candles import MexcCandleFinalizer
from prep_watchdeck_market.sources.mexc_stream_common import (
    MexcStreamFailure,
    decode_message,
    source_call,
    source_connection,
)


async def produce_mexc_candles(
    session,
    instruments,
    emit,
    stop_event,
    *,
    ws_factory=None,
    receive_poll_seconds=1.0,
    reconnect_delay_seconds=1.0,
):
    selected = tuple(i for i in instruments if i.venue == "mexc" and i.active)
    if not selected:
        return
    if session is None and ws_factory is None:
        raise ValueError("MEXC candles require session or websocket factory")
    connect = ws_factory or (lambda url: session.ws_connect(url, heartbeat=15))
    while not stop_event.is_set():
        finalizer = MexcCandleFinalizer(selected)
        try:
            async with source_connection(connect) as websocket:
                for item in selected:
                    await source_call(
                        websocket.send_json(
                            {
                                "method": "sub.kline",
                                "param": {"symbol": item.source_symbol, "interval": "Min1"},
                            }
                        )
                    )
                ping_at = asyncio.get_running_loop().time() + 15
                while not stop_event.is_set():
                    if asyncio.get_running_loop().time() >= ping_at:
                        await source_call(websocket.send_json({"method": "ping"}))
                        ping_at = asyncio.get_running_loop().time() + 15
                    try:
                        message = await asyncio.wait_for(
                            source_call(websocket.receive()), timeout=receive_poll_seconds
                        )
                    except TimeoutError:
                        message = None
                    if message is not None:
                        if message.type in {
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        }:
                            break
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = decode_message(message)
                            if payload.get("channel") == "push.kline":
                                try:
                                    finalizer.ingest(payload, observed_at=datetime.now(UTC))
                                except CandleParseError:
                                    raise MexcStreamFailure(
                                        "MEXC candle stream decode failed"
                                    ) from None
                    for candle in finalizer.finalize(now=datetime.now(UTC)):
                        await emit(candle)
        except MexcStreamFailure:
            pass
        if not stop_event.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=reconnect_delay_seconds)
