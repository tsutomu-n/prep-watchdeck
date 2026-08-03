from __future__ import annotations

import aiohttp

from prep_watchdeck.bitget.ws_public import _send_text_ping


async def test_send_text_ping_stops_when_transport_is_closing() -> None:
    ws = ClosingWebSocket()

    await _send_text_ping(ws, 0)

    assert ws.calls == 1


class ClosingWebSocket:
    def __init__(self) -> None:
        self.calls = 0

    async def send_str(self, _value: str) -> None:
        self.calls += 1
        raise aiohttp.ClientConnectionResetError("Cannot write to closing transport")
