from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any
from weakref import WeakKeyDictionary

import aiohttp

from prep_watchdeck_market.sources.common import CatalogSourceError
from prep_watchdeck_market.sources.mexc import MEXC_WS_URL

MEXC_WS_CLOSE_TIMEOUT_SECONDS = 1.0


class MexcStreamFailure(RuntimeError):
    """Only a native network/decode boundary failed; retry with a fresh stream."""


async def source_call[T](operation: Awaitable[T]) -> T:
    try:
        return await operation
    except (aiohttp.ClientError, OSError, TimeoutError, CatalogSourceError):
        raise MexcStreamFailure("MEXC native stream request unavailable") from None


@asynccontextmanager
async def source_connection(connect: Callable[[str], Any]) -> AsyncIterator[Any]:
    manager = connect(MEXC_WS_URL)
    websocket = await source_call(manager.__aenter__())
    try:
        yield websocket
    finally:
        # Bound peer close below the selected-group cleanup deadline. Socket teardown
        # must not replace a writer failure or cancellation.
        with suppress(MexcStreamFailure, TimeoutError):
            await asyncio.wait_for(
                source_call(manager.__aexit__(None, None, None)),
                timeout=MEXC_WS_CLOSE_TIMEOUT_SECONDS,
            )


def decode_message(message: Any) -> dict[str, object]:
    try:
        payload = json.loads(message.data)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise MexcStreamFailure("MEXC native stream JSON invalid") from None
    if not isinstance(payload, dict):
        raise MexcStreamFailure("MEXC native stream envelope invalid")
    return payload


class MexcSubscriptionPacer:
    """Design budget: five subscription commands/second across all local connections."""

    def __init__(self, interval_seconds: float = 0.2) -> None:
        self.interval_seconds = interval_seconds
        self.lock = asyncio.Lock()
        self.next_at = 0.0

    async def acquire(self) -> None:
        async with self.lock:
            loop = asyncio.get_running_loop()
            delay = self.next_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_at = loop.time() + self.interval_seconds


_subscription_pacers: WeakKeyDictionary[asyncio.AbstractEventLoop, MexcSubscriptionPacer] = (
    WeakKeyDictionary()
)


def mexc_subscription_pacer() -> MexcSubscriptionPacer:
    loop = asyncio.get_running_loop()
    if loop not in _subscription_pacers:
        _subscription_pacers[loop] = MexcSubscriptionPacer()
    return _subscription_pacers[loop]
