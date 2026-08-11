from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable
from threading import RLock

from prep_watchdeck.adapters.perp_venue_public import fetch_perp_venue_inputs
from prep_watchdeck.domain.perp_venue_comparison import (
    PERP_VENUES,
    PerpVenueContract,
    PerpVenueObservation,
    build_perp_venue_comparison,
)

PERP_VENUE_COMPARISON_INTERVAL_SECONDS = 300.0
PERP_VENUE_COMPARISON_INITIAL_DELAY_SECONDS = 30.0
PERP_VENUE_COMPARISON_TIMEOUT_SECONDS = 20.0
PERP_VENUE_CONTRACT_CATALOG_TTL_MS = 30 * 60 * 1_000

PerpVenueFetchResult = tuple[
    list[PerpVenueContract],
    list[PerpVenueObservation],
    dict[str, str],
]
PerpVenueFetcher = Callable[[], Awaitable[PerpVenueFetchResult]]
PerpVenueRefreshCallback = Callable[[dict[str, object], float], None]
PerpVenueRefreshErrorCallback = Callable[[Exception], None]


class PerpVenueComparisonCollector:
    def __init__(self) -> None:
        self._lock = RLock()
        self._block: dict[str, object] | None = None
        self._contract_catalogs: dict[str, tuple[int, list[PerpVenueContract]]] = {}

    def replace(self, block: dict[str, object]) -> None:
        with self._lock:
            self._block = copy.deepcopy(block)

    def snapshot(self) -> dict[str, object] | None:
        with self._lock:
            return copy.deepcopy(self._block)

    def contracts_for_refresh(
        self,
        contracts: list[PerpVenueContract],
        *,
        errors: dict[str, str],
        generated_at_ms: int,
        catalog_ttl_ms: int = PERP_VENUE_CONTRACT_CATALOG_TTL_MS,
    ) -> list[PerpVenueContract]:
        current_by_venue = {
            venue: [contract for contract in contracts if contract.venue == venue]
            for venue in PERP_VENUES
        }
        selected: list[PerpVenueContract] = []
        with self._lock:
            for venue in PERP_VENUES:
                current = current_by_venue[venue]
                if current and venue not in errors:
                    cached = copy.deepcopy(current)
                    self._contract_catalogs[venue] = (generated_at_ms, cached)
                    selected.extend(cached)
                    continue
                catalog = self._contract_catalogs.get(venue)
                if catalog is None:
                    continue
                cached_at_ms, cached_contracts = catalog
                age_ms = generated_at_ms - cached_at_ms
                if 0 <= age_ms <= catalog_ttl_ms:
                    selected.extend(copy.deepcopy(cached_contracts))
                else:
                    del self._contract_catalogs[venue]
        return selected

    def replace_with_failure(self, exc: Exception) -> None:
        generated_at_ms = int(time.time() * 1_000)
        error = f"internal:{type(exc).__name__}"
        errors = {venue: error for venue in PERP_VENUES}
        contracts = self.contracts_for_refresh(
            [],
            errors=errors,
            generated_at_ms=generated_at_ms,
        )
        block: dict[str, object]
        try:
            block = build_perp_venue_comparison(
                contracts,
                [],
                generated_at_ms=generated_at_ms,
                errors=errors,
            )
        except Exception:
            block = {
                "schemaVersion": 1,
                "mode": "perp_venue_comparison_v1",
                "generatedAt": generated_at_ms,
                "refreshIntervalSeconds": 300,
                "sources": [
                    {
                        "venue": venue,
                        "status": "unavailable",
                        "observedAt": None,
                        "error": error,
                    }
                    for venue in PERP_VENUES
                ],
                "items": [],
            }
        self.replace(block)


def collect_perp_venue_comparison_once() -> dict[str, object] | None:
    collector = PerpVenueComparisonCollector()
    asyncio.run(refresh_perp_venue_comparison_once(collector))
    return collector.snapshot()


async def refresh_perp_venue_comparison_once(
    collector: PerpVenueComparisonCollector,
    *,
    fetcher: PerpVenueFetcher = fetch_perp_venue_inputs,
    generated_at_ms: int | None = None,
) -> dict[str, object]:
    try:
        async with asyncio.timeout(PERP_VENUE_COMPARISON_TIMEOUT_SECONDS):
            contracts, observations, errors = await fetcher()
    except Exception as exc:
        contracts = []
        observations = []
        errors = {venue: type(exc).__name__ for venue in PERP_VENUES}
    generated_at_ms = int(time.time() * 1_000) if generated_at_ms is None else generated_at_ms
    source_errors = dict(errors)
    for venue in PERP_VENUES:
        if not any(contract.venue == venue for contract in contracts):
            source_errors.setdefault(venue, "missing_contracts")
        if not any(observation.venue == venue for observation in observations):
            source_errors.setdefault(venue, "missing_observations")
    effective_contracts = collector.contracts_for_refresh(
        contracts,
        errors=source_errors,
        generated_at_ms=generated_at_ms,
    )
    block = build_perp_venue_comparison(
        effective_contracts,
        observations,
        generated_at_ms=generated_at_ms,
        errors=source_errors,
    )
    collector.replace(block)
    return block


async def refresh_perp_venue_comparison_periodically(
    collector: PerpVenueComparisonCollector,
    *,
    interval_seconds: float = PERP_VENUE_COMPARISON_INTERVAL_SECONDS,
    initial_delay_seconds: float = 0.0,
    refresh_immediately: bool = True,
    fetcher: PerpVenueFetcher = fetch_perp_venue_inputs,
    on_refresh: PerpVenueRefreshCallback | None = None,
    on_error: PerpVenueRefreshErrorCallback | None = None,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if initial_delay_seconds < 0:
        raise ValueError("initial_delay_seconds must be non-negative")

    async def refresh() -> None:
        started_at = time.monotonic()
        try:
            block = await refresh_perp_venue_comparison_once(collector, fetcher=fetcher)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            collector.replace_with_failure(exc)
            if on_error is not None:
                on_error(exc)
            return
        if on_refresh is not None:
            on_refresh(block, time.monotonic() - started_at)

    if initial_delay_seconds > 0:
        await asyncio.sleep(initial_delay_seconds)
    if refresh_immediately:
        await refresh()
    while True:
        await asyncio.sleep(interval_seconds)
        await refresh()
