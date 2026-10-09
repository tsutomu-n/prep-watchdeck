from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

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
