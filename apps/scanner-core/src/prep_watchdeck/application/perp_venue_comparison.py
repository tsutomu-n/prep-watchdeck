from __future__ import annotations

import asyncio
import copy
import time
from threading import RLock

from prep_watchdeck.adapters.perp_venue_public import fetch_perp_venue_inputs
from prep_watchdeck.domain.perp_venue_comparison import (
    PERP_VENUES,
    build_perp_venue_comparison,
)

PERP_VENUE_COMPARISON_INTERVAL_SECONDS = 300.0
PERP_VENUE_COMPARISON_TIMEOUT_SECONDS = 20.0


class PerpVenueComparisonCollector:
    def __init__(self) -> None:
        self._lock = RLock()
        self._block: dict[str, object] | None = None

    def replace(self, block: dict[str, object]) -> None:
        with self._lock:
            self._block = copy.deepcopy(block)

    def snapshot(self) -> dict[str, object] | None:
        with self._lock:
            return copy.deepcopy(self._block)


def collect_perp_venue_comparison_once() -> dict[str, object] | None:
    collector = PerpVenueComparisonCollector()
    asyncio.run(refresh_perp_venue_comparison_once(collector))
    return collector.snapshot()


async def refresh_perp_venue_comparison_once(
    collector: PerpVenueComparisonCollector,
) -> None:
    try:
        async with asyncio.timeout(PERP_VENUE_COMPARISON_TIMEOUT_SECONDS):
            contracts, observations, errors = await fetch_perp_venue_inputs()
    except Exception as exc:
        contracts = []
        observations = []
        errors = {venue: type(exc).__name__ for venue in PERP_VENUES}
    generated_at_ms = int(time.time() * 1_000)
    collector.replace(
        build_perp_venue_comparison(
            contracts,
            observations,
            generated_at_ms=generated_at_ms,
            errors=errors,
        )
    )


async def refresh_perp_venue_comparison_periodically(
    collector: PerpVenueComparisonCollector,
    *,
    interval_seconds: float = PERP_VENUE_COMPARISON_INTERVAL_SECONDS,
    refresh_immediately: bool = True,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if refresh_immediately:
        await refresh_perp_venue_comparison_once(collector)
    while True:
        await asyncio.sleep(interval_seconds)
        await refresh_perp_venue_comparison_once(collector)
