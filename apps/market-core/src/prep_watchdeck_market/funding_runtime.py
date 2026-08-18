from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiohttp
from loguru import logger

from prep_watchdeck_market.funding_store import (
    FundingFailure,
    FundingStoreResult,
    load_funding_catalog_url,
    load_latest_funding_times_url,
    persist_funding_sweep_url,
)
from prep_watchdeck_market.models import CatalogInstrument, Venue
from prep_watchdeck_market.sources.common import CatalogSourceError
from prep_watchdeck_market.sources.funding import FundingBatch, fetch_funding_history

FUNDING_LOOKBACK = timedelta(hours=48)
FUNDING_PUBLICATION_GRACE = timedelta(minutes=5)
FUNDING_REQUEST_PACE_SECONDS: dict[Venue, float] = {
    "bitget": 0.10,
    "hyperliquid": 1.50,
    "aster": 0.10,
}

InstrumentSupplier = Callable[[], Sequence[CatalogInstrument]]
CurrentVersionStartSupplier = Callable[[], Mapping[str, datetime]]
UtcClock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class FundingRequestWindow:
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True, slots=True)
class FundingSweepSummary:
    requests_attempted: int
    requests_succeeded: int
    instruments_not_due: int
    failures: int
    store: FundingStoreResult | None


async def run_funding_sync_once(database_url: str) -> FundingSweepSummary:
    """Run one isolated public funding-history sync against the current DB catalog."""

    snapshot = await asyncio.to_thread(load_funding_catalog_url, database_url)
    async with aiohttp.ClientSession() as session:
        runtime = FundingRuntime(
            database_url,
            session,
            lambda: snapshot.instruments,
            lambda: snapshot.version_starts,
        )
        return await runtime.run_once(asyncio.Event())


class FundingRuntime:
    """Collect settled funding events without turning current rate predictions into history."""

    def __init__(
        self,
        database_url: str,
        session: aiohttp.ClientSession,
        instrument_supplier: InstrumentSupplier,
        current_version_starts: CurrentVersionStartSupplier,
        *,
        utc_clock: UtcClock | None = None,
    ) -> None:
        self._database_url = database_url
        self._session = session
        self._instrument_supplier = instrument_supplier
        self._current_version_starts = current_version_starts
        self._utc_clock = utc_clock or (lambda: datetime.now(UTC))

    async def run_once(
        self,
        stop_event: asyncio.Event,
        *,
        started_at: datetime | None = None,
    ) -> FundingSweepSummary:
        sweep_at = started_at or self._utc_clock()
        _require_aware(sweep_at, "funding sweep started_at")
        instruments = tuple(
            sorted(
                (
                    item
                    for item in self._instrument_supplier()
                    if item.active and item.market_type == "linear_perpetual"
                ),
                key=lambda item: (item.venue, item.source_symbol),
            )
        )
        version_starts = dict(self._current_version_starts())
        latest = await asyncio.to_thread(load_latest_funding_times_url, self._database_url)
        venue_results = await asyncio.gather(
            *(
                self._fetch_venue(
                    venue,
                    tuple(item for item in instruments if item.venue == venue),
                    version_starts,
                    latest,
                    sweep_at,
                    stop_event,
                )
                for venue in ("bitget", "hyperliquid", "aster")
            )
        )
        batches = tuple(batch for result in venue_results for batch in result[0])
        failures = tuple(failure for result in venue_results for failure in result[1])
        attempted = sum(result[2] for result in venue_results)
        not_due = sum(result[3] for result in venue_results)
        if stop_event.is_set():
            return FundingSweepSummary(
                requests_attempted=attempted,
                requests_succeeded=len(batches),
                instruments_not_due=not_due,
                failures=len(failures),
                store=None,
            )
        store = None
        if batches or failures:
            store = await asyncio.to_thread(
                persist_funding_sweep_url,
                self._database_url,
                sweep_at,
                batches,
                failures,
            )
        logger.bind(
            event="funding_sweep",
            requests_attempted=attempted,
            requests_succeeded=len(batches),
            instruments_not_due=not_due,
            failures=len(failures),
            records_written=0 if store is None else store.records_written,
            records_unchanged=0 if store is None else store.records_unchanged,
            admission_rejected=0 if store is None else store.admission_rejected,
            status="idle" if store is None else store.status,
        ).info("funding sweep complete")
        return FundingSweepSummary(
            requests_attempted=attempted,
            requests_succeeded=len(batches),
            instruments_not_due=not_due,
            failures=len(failures),
            store=store,
        )

    async def _fetch_venue(
        self,
        venue: Venue,
        instruments: Sequence[CatalogInstrument],
        version_starts: Mapping[str, datetime],
        latest: Mapping[str, datetime],
        sweep_at: datetime,
        stop_event: asyncio.Event,
    ) -> tuple[list[FundingBatch], list[FundingFailure], int, int]:
        batches: list[FundingBatch] = []
        failures: list[FundingFailure] = []
        attempted = 0
        not_due = 0
        for instrument in instruments:
            if stop_event.is_set():
                break
            version_start = version_starts.get(instrument.venue_instrument_id)
            if version_start is None:
                failures.append(
                    FundingFailure(
                        venue=venue,
                        source_symbol=instrument.source_symbol,
                        error_code="missing_catalog_version",
                    )
                )
                continue
            window = funding_request_window(
                instrument,
                version_start=version_start,
                latest_funding_at=latest.get(instrument.venue_instrument_id),
                now=sweep_at,
            )
            if window is None:
                not_due += 1
                continue
            attempted += 1
            try:
                batch = await fetch_funding_history(
                    self._session,
                    instrument,
                    start_at=window.start_at,
                    end_at=window.end_at,
                )
            except CatalogSourceError as error:
                failures.append(
                    FundingFailure(
                        venue=venue,
                        source_symbol=instrument.source_symbol,
                        error_code=error.error_code,
                    )
                )
            else:
                batches.append(batch)
            if await _wait_or_stop(stop_event, FUNDING_REQUEST_PACE_SECONDS[venue]):
                break
        return batches, failures, attempted, not_due


def funding_request_window(
    instrument: CatalogInstrument,
    *,
    version_start: datetime,
    latest_funding_at: datetime | None,
    now: datetime,
) -> FundingRequestWindow | None:
    """Return a bounded settled-history request only when the instrument may be due."""

    _require_aware(version_start, "version_start")
    _require_aware(now, "now")
    if latest_funding_at is not None:
        _require_aware(latest_funding_at, "latest_funding_at")
    if not instrument.active or instrument.market_type != "linear_perpetual":
        return None
    interval = instrument.funding_interval_seconds
    if (
        latest_funding_at is not None
        and interval is not None
        and now < latest_funding_at + timedelta(seconds=interval) + FUNDING_PUBLICATION_GRACE
    ):
        return None
    candidates = [version_start, now - FUNDING_LOOKBACK]
    if latest_funding_at is not None:
        candidates.append(latest_funding_at + timedelta(milliseconds=1))
    start_at = max(candidates)
    if start_at > now:
        return None
    return FundingRequestWindow(start_at=start_at, end_at=now)


async def _wait_or_stop(stop_event: asyncio.Event, seconds: float) -> bool:
    if seconds <= 0:
        return stop_event.is_set()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
