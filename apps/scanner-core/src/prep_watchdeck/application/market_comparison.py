from __future__ import annotations

import asyncio
import copy
import time
from threading import RLock

from prep_watchdeck.adapters.multisource_public import fetch_market_comparison_observations
from prep_watchdeck.domain.market_comparison import build_market_comparison

MARKET_COMPARISON_INTERVAL_SECONDS = 300.0
MARKET_COMPARISON_TIMEOUT_SECONDS = 15.0


class MarketComparisonCollector:
    def __init__(self) -> None:
        self._lock = RLock()
        self._block: dict[str, object] | None = None

    def replace(self, block: dict[str, object]) -> None:
        with self._lock:
            self._block = copy.deepcopy(block)

    def snapshot(self) -> dict[str, object] | None:
        with self._lock:
            return copy.deepcopy(self._block)


def collect_market_comparison_once() -> dict[str, object] | None:
    collector = MarketComparisonCollector()
    asyncio.run(refresh_market_comparison_once(collector))
    return collector.snapshot()


async def refresh_market_comparison_once(collector: MarketComparisonCollector) -> None:
    try:
        async with asyncio.timeout(MARKET_COMPARISON_TIMEOUT_SECONDS):
            observations, errors = await fetch_market_comparison_observations()
    except Exception as exc:
        observations = []
        errors = {source: type(exc).__name__ for source in ("bitget", "hyperliquid", "bybit")}
    generated_at_ms = int(time.time() * 1_000)
    collector.replace(
        build_market_comparison(
            observations,
            generated_at_ms=generated_at_ms,
            errors=errors,
        )
    )


async def refresh_market_comparison_periodically(
    collector: MarketComparisonCollector,
    *,
    interval_seconds: float = MARKET_COMPARISON_INTERVAL_SECONDS,
    refresh_immediately: bool = True,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if refresh_immediately:
        await refresh_market_comparison_once(collector)
    while True:
        await asyncio.sleep(interval_seconds)
        await refresh_market_comparison_once(collector)
