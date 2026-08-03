from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

import aiohttp

from prep_watchdeck.application.ws_frames import ChannelSpec

BITGET_PUBLIC_WS_URL = "wss://ws.bitget.com/v2/ws/public"


class TextPingWebSocket(Protocol):
    async def send_str(self, data: str, /) -> None:
        """Send a text websocket frame."""


async def stream_public_payloads(
    specs: Sequence[ChannelSpec],
    *,
    url: str = BITGET_PUBLIC_WS_URL,
    ping_interval_sec: float = 30.0,
) -> AsyncIterator[dict[str, Any]]:
    if not specs:
        raise ValueError("at least one websocket channel spec is required")

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10)
    async with (
        aiohttp.ClientSession(timeout=timeout) as session,
        session.ws_connect(url, heartbeat=None) as ws,
    ):
        await ws.send_json({"op": "subscribe", "args": [spec.to_arg() for spec in specs]})
        ping_task = (
            asyncio.create_task(_send_text_ping(ws, ping_interval_sec))
            if ping_interval_sec > 0
            else None
        )
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    text = str(msg.data)
                    if text == "pong":
                        continue
                    payload: Any = json.loads(text)
                    if not isinstance(payload, dict):
                        raise ValueError("websocket payload must be a JSON object")
                    yield payload
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    exc = ws.exception()
                    raise RuntimeError(f"websocket error: {exc}") from exc
                elif msg.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                }:
                    break
        finally:
            if ping_task is not None:
                ping_task.cancel()
                with contextlib.suppress(
                    asyncio.CancelledError,
                    aiohttp.ClientConnectionResetError,
                ):
                    await ping_task


async def _send_text_ping(
    ws: TextPingWebSocket,
    ping_interval_sec: float,
) -> None:
    while True:
        await asyncio.sleep(ping_interval_sec)
        with contextlib.suppress(aiohttp.ClientConnectionResetError):
            await ws.send_str("ping")
            continue
        return
