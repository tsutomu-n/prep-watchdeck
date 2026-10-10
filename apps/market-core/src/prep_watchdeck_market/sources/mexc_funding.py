from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp

from prep_watchdeck_market.market_state import finite_decimal
from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.sources.common import (
    CatalogSourceError,
    observed_now,
    positive_int,
    require_mapping,
    timestamp_from_milliseconds,
)
from prep_watchdeck_market.sources.mexc import fetch_mexc_json, mexc_data

FUNDING_TTL_SECONDS = 90
FUNDING_SWEEP_SECONDS = 60
FUNDING_START_INTERVAL_SECONDS = 0.5
FUNDING_MAX_IN_FLIGHT = 4


@dataclass(frozen=True, slots=True)
class MexcFundingSnapshot:
    payload: object | None
    contract_version: str
    source_at: datetime | None
    observed_at: datetime | None
    valid_until: datetime | None
    error_code: str | None = None


def funding_snapshot(
    payload: object, instrument: CatalogInstrument, *, observed_at: datetime
) -> MexcFundingSnapshot:
    try:
        row = require_mapping(mexc_data(payload), field_name="MEXC funding")
    except CatalogSourceError:
        return MexcFundingSnapshot(
            None,
            instrument.semantic_definition_sha256(),
            None,
            observed_at,
            None,
            "funding_invalid",
        )
    source_at = timestamp_from_milliseconds(row.get("timestamp"))
    next_at = timestamp_from_milliseconds(row.get("nextSettleTime"))
    valid_until = (
        min(
            source_at + timedelta(seconds=FUNDING_TTL_SECONDS),
            observed_at + timedelta(seconds=FUNDING_TTL_SECONDS),
            next_at,
        )
        if source_at is not None and next_at is not None
        else None
    )
    invalid = (
        row.get("symbol") != instrument.source_symbol
        or finite_decimal(row.get("fundingRate")) is None
        or positive_int(row.get("collectCycle")) is None
        or source_at is None
        or source_at > observed_at
        or next_at is None
    )
    return MexcFundingSnapshot(
        None if invalid else payload,
        instrument.semantic_definition_sha256(),
        source_at,
        observed_at,
        valid_until,
        "funding_invalid" if invalid else None,
    )


def funding_reason(
    snapshot: MexcFundingSnapshot | None, instrument: CatalogInstrument, now: datetime
) -> str | None:
    if snapshot is None:
        return "funding_missing"
    if snapshot.contract_version != instrument.semantic_definition_sha256():
        return "funding_contract_changed"
    if snapshot.error_code:
        return snapshot.error_code
    if snapshot.observed_at is None or snapshot.source_at is None or snapshot.valid_until is None:
        return "funding_invalid"
    if snapshot.observed_at > now or snapshot.source_at > now:
        return "funding_invalid"
    if snapshot.payload is None:
        return "funding_invalid"
    row = require_mapping(mexc_data(snapshot.payload), field_name="MEXC funding")
    next_at = timestamp_from_milliseconds(row.get("nextSettleTime"))
    if next_at is None or now >= next_at:
        return "funding_settlement_passed"
    if now >= snapshot.valid_until:
        return "funding_expired"
    return None


class MexcFundingRuntime:
    """Independent bounded Funding reader; cache timestamps only advance on HTTP completion."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        instruments: Callable[[], Collection[CatalogInstrument]],
    ) -> None:
        self._session = session
        self._instruments = instruments
        self.snapshots: dict[str, MexcFundingSnapshot] = {}

    async def fetch_one(self, instrument: CatalogInstrument) -> None:
        try:
            payload = await fetch_mexc_json(
                self._session,
                "/api/v1/contract/funding_rate/" + instrument.source_symbol,
                lane="funding",
            )
            snapshot = funding_snapshot(payload, instrument, observed_at=observed_now())
        except (CatalogSourceError, ValueError):
            snapshot = MexcFundingSnapshot(
                None,
                instrument.semantic_definition_sha256(),
                None,
                None,
                None,
                "funding_fetch_failed",
            )
        self.snapshots[instrument.source_symbol] = snapshot

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        run = asyncio.create_task(self._run(stop_event))
        stop = asyncio.create_task(stop_event.wait())
        try:
            completed, _ = await asyncio.wait((run, stop), return_when=asyncio.FIRST_COMPLETED)
            if run in completed:
                await run
        finally:
            run.cancel()
            stop.cancel()
            await asyncio.gather(run, stop, return_exceptions=True)

    async def _run(self, stop_event: asyncio.Event) -> None:
        running: set[asyncio.Task[None]] = set()
        loop = asyncio.get_running_loop()
        try:
            while not stop_event.is_set():
                started = loop.time()
                instruments = tuple(
                    i for i in self._instruments() if i.venue == "mexc" and i.active
                )
                active_symbols = {i.source_symbol for i in instruments}
                for symbol in set(self.snapshots) - active_symbols:
                    del self.snapshots[symbol]
                for item in instruments:
                    if stop_event.is_set():
                        return
                    if len(running) >= FUNDING_MAX_IN_FLIGHT:
                        completed, running = await asyncio.wait(
                            running, return_when=asyncio.FIRST_COMPLETED
                        )
                        await asyncio.gather(*completed)
                    running.add(asyncio.create_task(self.fetch_one(item)))
                    with suppress(TimeoutError):
                        await asyncio.wait_for(stop_event.wait(), FUNDING_START_INTERVAL_SECONDS)
                    completed = {task for task in running if task.done()}
                    await asyncio.gather(*completed)
                    running -= completed
                if running:
                    await asyncio.gather(*running)
                    running.clear()
                delay = max(0, started + FUNDING_SWEEP_SECONDS - loop.time())
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), delay)
        finally:
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)
