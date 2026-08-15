from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import aiohttp
import psycopg
from loguru import logger
from psycopg.types.json import Jsonb

from prep_watchdeck_market.artifacts import (
    ArtifactContractError,
    ArtifactFileStatus,
    ArtifactPublishResult,
    publish_artifacts,
    publish_selected_artifact,
)
from prep_watchdeck_market.candle_runtime import CandleRuntime
from prep_watchdeck_market.candle_store import (
    CandleStoreError,
    load_current_candle_version_starts,
)
from prep_watchdeck_market.catalog_store import CatalogStoreError, persist_catalog
from prep_watchdeck_market.identity import resolve_market_groups
from prep_watchdeck_market.market_state import MarketBatch
from prep_watchdeck_market.market_store import (
    DATABASE_TIMEOUT_OPTIONS,
    MarketStoreResult,
    persist_market_cycle_url,
)
from prep_watchdeck_market.models import CatalogBatch, CatalogInstrument, Venue
from prep_watchdeck_market.scheduler import L1Scheduler, VenueFetcher, next_grid_at
from prep_watchdeck_market.selected_store import SelectedStoreError
from prep_watchdeck_market.selection_runtime import SelectionRuntime
from prep_watchdeck_market.sources.aster import fetch_aster_catalog
from prep_watchdeck_market.sources.aster_l1 import ASTER_L1_ENDPOINT, fetch_aster_l1
from prep_watchdeck_market.sources.bitget import fetch_bitget_catalog
from prep_watchdeck_market.sources.bitget_l1 import BITGET_L1_ENDPOINT, fetch_bitget_l1
from prep_watchdeck_market.sources.common import CatalogSourceError
from prep_watchdeck_market.sources.hyperliquid import fetch_hyperliquid_catalog
from prep_watchdeck_market.sources.hyperliquid_l1 import (
    HYPERLIQUID_L1_ENDPOINT,
    fetch_hyperliquid_l1,
)


class MarketServiceError(RuntimeError):
    """The market service could not continue without exposing credentials."""


SELECTED_ARTIFACT_REFRESH_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class CatalogRefreshResult:
    status: str
    venues_succeeded: tuple[Venue, ...]
    venues_failed: tuple[Venue, ...]
    instruments_received: int


class MarketService:
    def __init__(self, database_url: str, state_dir: Path) -> None:
        self._database_url = database_url
        self._state_dir = state_dir
        self._catalogs: dict[Venue, CatalogBatch] = {}
        self._candle_version_starts: dict[str, datetime] = {}
        self._catalog_update_lock = asyncio.Lock()
        self._artifact_trigger = asyncio.Event()
        self._artifact_publish_lock = asyncio.Lock()
        self._artifact_files: tuple[ArtifactFileStatus, ...] = ()
        self._session: aiohttp.ClientSession | None = None

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        async with aiohttp.ClientSession() as session:
            self._session = session
            initial = await self.refresh_catalog()
            logger.info(
                "initial catalog refresh status={status} venues={venues} instruments={count}",
                status=initial.status,
                venues=initial.venues_succeeded,
                count=initial.instruments_received,
            )
            scheduler = L1Scheduler(self._l1_fetchers(), self._persist_l1_cycle)
            candle_runtime = CandleRuntime(
                self._database_url,
                session,
                self._all_instruments,
                catalog_update_lock=self._catalog_update_lock,
                current_version_starts=self._current_candle_version_starts,
            )
            selection_runtime = SelectionRuntime(
                self._database_url,
                self._state_dir,
                session,
            )
            catalog_task = asyncio.create_task(
                self._catalog_loop(stop_event), name="market-catalog-loop"
            )
            l1_task = asyncio.create_task(scheduler.run_forever(stop_event), name="market-l1-loop")
            candle_task = asyncio.create_task(
                candle_runtime.run_forever(stop_event), name="market-candle-loop"
            )
            selection_task = asyncio.create_task(
                selection_runtime.run_forever(stop_event), name="market-selection-loop"
            )
            artifact_task = asyncio.create_task(
                self._artifact_loop(stop_event), name="market-artifact-loop"
            )
            selected_artifact_task = asyncio.create_task(
                self._selected_artifact_loop(stop_event),
                name="market-selected-artifact-loop",
            )
            try:
                await asyncio.gather(
                    catalog_task,
                    l1_task,
                    candle_task,
                    selection_task,
                    artifact_task,
                    selected_artifact_task,
                )
            finally:
                for task in (
                    catalog_task,
                    l1_task,
                    candle_task,
                    selection_task,
                    artifact_task,
                    selected_artifact_task,
                ):
                    task.cancel()
                await asyncio.gather(
                    catalog_task,
                    l1_task,
                    candle_task,
                    selection_task,
                    artifact_task,
                    selected_artifact_task,
                    return_exceptions=True,
                )
                self._session = None

    async def refresh_catalog(self) -> CatalogRefreshResult:
        session = self._require_session()
        venues: tuple[Venue, Venue, Venue] = "bitget", "hyperliquid", "aster"
        results = await asyncio.gather(
            fetch_bitget_catalog(session),
            fetch_hyperliquid_catalog(session),
            fetch_aster_catalog(session),
            return_exceptions=True,
        )
        succeeded: dict[Venue, CatalogBatch] = {}
        failed: list[Venue] = []
        for venue, result in zip(venues, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                failed.append(venue)
                logger.warning(
                    "catalog source unavailable venue={venue} errorType={error_type}",
                    venue=venue,
                    error_type=type(result).__name__,
                )
                continue
            succeeded[venue] = result

        started_at = datetime.now(UTC)
        async with self._catalog_update_lock:
            candidate_catalogs = dict(self._catalogs)
            candidate_catalogs.update(succeeded)
            persist_task = asyncio.create_task(
                asyncio.to_thread(
                    _persist_catalog_refresh,
                    self._database_url,
                    tuple(succeeded.values()),
                    tuple(candidate_catalogs.values()),
                    started_at,
                    tuple(failed),
                ),
                name="market-catalog-persist",
            )
            try:
                persisted = await asyncio.shield(persist_task)
            except asyncio.CancelledError:
                await asyncio.gather(persist_task, return_exceptions=True)
                raise
            version_starts_task = asyncio.create_task(
                asyncio.to_thread(
                    _load_current_candle_version_starts_url,
                    self._database_url,
                ),
                name="market-current-candle-versions-load",
            )
            try:
                version_starts = await asyncio.shield(version_starts_task)
            except asyncio.CancelledError:
                await asyncio.gather(version_starts_task, return_exceptions=True)
                raise
            except CandleStoreError as error:
                self._candle_version_starts = {}
                raise MarketServiceError(
                    "current candle catalog versions are unavailable"
                ) from error
            for venue in persisted:
                self._catalogs[venue] = succeeded[venue]
            self._candle_version_starts = version_starts

        persisted_set = set(persisted)
        failed_set = set(failed) | (set(succeeded) - persisted_set)
        persisted_venues = tuple(venue for venue in venues if venue in persisted_set)
        failed_venues = tuple(venue for venue in venues if venue in failed_set)
        if not persisted_venues:
            status = "failed"
        elif failed_venues:
            status = "partial"
        else:
            status = "succeeded"
        return CatalogRefreshResult(
            status=status,
            venues_succeeded=persisted_venues,
            venues_failed=failed_venues,
            instruments_received=sum(len(batch.instruments) for batch in succeeded.values()),
        )

    async def _catalog_loop(self, stop_event: asyncio.Event) -> None:
        next_refresh = next_grid_at(datetime.now(UTC) + timedelta(microseconds=1), 900)
        while not stop_event.is_set():
            delay = max(0.0, (next_refresh - datetime.now(UTC)).total_seconds())
            with suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            if stop_event.is_set():
                return
            try:
                await self.refresh_catalog()
            except MarketServiceError as exc:
                logger.error(
                    "catalog persistence unavailable errorType={error_type}",
                    error_type=type(exc).__name__,
                )
            next_refresh += timedelta(seconds=900)
            now = datetime.now(UTC)
            while next_refresh <= now:
                next_refresh += timedelta(seconds=900)

    def _l1_fetchers(self) -> tuple[VenueFetcher, VenueFetcher, VenueFetcher]:
        return (
            VenueFetcher("bitget", BITGET_L1_ENDPOINT, self._fetch_bitget),
            VenueFetcher("hyperliquid", HYPERLIQUID_L1_ENDPOINT, self._fetch_hyperliquid),
            VenueFetcher("aster", ASTER_L1_ENDPOINT, self._fetch_aster),
        )

    async def _fetch_bitget(self, cycle_at: datetime) -> MarketBatch:
        return await fetch_bitget_l1(
            self._require_session(), self._instruments("bitget"), cycle_at=cycle_at
        )

    async def _fetch_hyperliquid(self, cycle_at: datetime) -> MarketBatch:
        return await fetch_hyperliquid_l1(
            self._require_session(), self._instruments("hyperliquid"), cycle_at=cycle_at
        )

    async def _fetch_aster(self, cycle_at: datetime) -> MarketBatch:
        return await fetch_aster_l1(
            self._require_session(), self._instruments("aster"), cycle_at=cycle_at
        )

    async def _persist_l1_cycle(
        self,
        cycle_at: datetime,
        started_at: datetime,
        batches: Sequence[MarketBatch],
    ) -> MarketStoreResult:
        thread_task = asyncio.create_task(
            asyncio.to_thread(
                persist_market_cycle_url,
                self._database_url,
                cycle_at,
                started_at,
                batches,
            ),
            name=f"market-l1-persist-{cycle_at.isoformat()}",
        )
        try:
            result = await asyncio.shield(thread_task)
        except asyncio.CancelledError:
            await asyncio.gather(thread_task, return_exceptions=True)
            raise
        self._artifact_trigger.set()
        return result

    async def _artifact_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            trigger_task = asyncio.create_task(
                self._artifact_trigger.wait(), name="market-artifact-trigger"
            )
            stop_task = asyncio.create_task(stop_event.wait(), name="market-artifact-stop")
            done, pending = await asyncio.wait(
                (trigger_task, stop_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if stop_task in done:
                return
            self._artifact_trigger.clear()
            async with self._artifact_publish_lock:
                generated_at = datetime.now(UTC)
                publish_task = asyncio.create_task(
                    asyncio.to_thread(
                        _publish_artifacts_url,
                        self._database_url,
                        self._state_dir / "artifacts",
                        generated_at,
                    ),
                    name="market-artifact-publish",
                )
                try:
                    result = await asyncio.shield(publish_task)
                except asyncio.CancelledError:
                    await asyncio.gather(publish_task, return_exceptions=True)
                    raise
                except (
                    ArtifactContractError,
                    SelectedStoreError,
                    psycopg.Error,
                    OSError,
                ) as error:
                    logger.warning(
                        "artifact publish unavailable errorType={error_type}",
                        error_type=type(error).__name__,
                    )
                else:
                    self._artifact_files = result.files
                    logger.info("artifact publish status={status}", status=result.status)

    async def _selected_artifact_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=SELECTED_ARTIFACT_REFRESH_SECONDS,
                )
            if stop_event.is_set():
                return
            async with self._artifact_publish_lock:
                previous_files = self._artifact_files
                if not previous_files:
                    continue
                generated_at = datetime.now(UTC)
                publish_task = asyncio.create_task(
                    asyncio.to_thread(
                        _publish_selected_artifact_url,
                        self._database_url,
                        self._state_dir / "artifacts",
                        previous_files,
                        generated_at,
                    ),
                    name="market-selected-artifact-publish",
                )
                try:
                    result = await asyncio.shield(publish_task)
                except asyncio.CancelledError:
                    await asyncio.gather(publish_task, return_exceptions=True)
                    raise
                except (
                    ArtifactContractError,
                    SelectedStoreError,
                    psycopg.Error,
                    OSError,
                ) as error:
                    logger.warning(
                        "selected artifact publish unavailable errorType={error_type}",
                        error_type=type(error).__name__,
                    )
                else:
                    self._artifact_files = result.files

    def _instruments(self, venue: Venue) -> tuple[CatalogInstrument, ...]:
        batch = self._catalogs.get(venue)
        if batch is None or not batch.instruments:
            raise CatalogSourceError(f"{venue} catalog is unavailable")
        return batch.instruments

    def _all_instruments(self) -> tuple[CatalogInstrument, ...]:
        return tuple(
            instrument for batch in self._catalogs.values() for instrument in batch.instruments
        )

    def _current_candle_version_starts(self) -> dict[str, datetime]:
        return dict(self._candle_version_starts)

    def _require_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise MarketServiceError("market service session is not running")
        return self._session


async def run_market_service(
    database_url: str,
    state_dir: Path,
    stop_event: asyncio.Event,
) -> None:
    """Run catalog, L1, candle, and selected-data loops until stopped."""
    await MarketService(database_url, state_dir).run_forever(stop_event)


def _publish_artifacts_url(
    database_url: str,
    artifact_root: Path,
    generated_at: datetime,
) -> ArtifactPublishResult:
    with psycopg.connect(
        database_url,
        connect_timeout=5,
        options=DATABASE_TIMEOUT_OPTIONS,
    ) as connection:
        return publish_artifacts(connection, artifact_root, generated_at=generated_at)


def _publish_selected_artifact_url(
    database_url: str,
    artifact_root: Path,
    previous_files: Sequence[ArtifactFileStatus],
    generated_at: datetime,
) -> ArtifactPublishResult:
    with psycopg.connect(
        database_url,
        connect_timeout=5,
        options=DATABASE_TIMEOUT_OPTIONS,
    ) as connection:
        return publish_selected_artifact(
            connection,
            artifact_root,
            previous_files,
            generated_at=generated_at,
        )


def _load_current_candle_version_starts_url(database_url: str) -> dict[str, datetime]:
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=5,
            options=DATABASE_TIMEOUT_OPTIONS,
        ) as connection:
            return load_current_candle_version_starts(connection)
    except CandleStoreError:
        raise
    except (psycopg.Error, OSError):
        raise CandleStoreError("current candle catalog versions could not be loaded") from None


def _persist_catalog_refresh(
    database_url: str,
    changed_batches: Sequence[CatalogBatch],
    current_batches: Sequence[CatalogBatch],
    started_at: datetime,
    source_failures: Sequence[Venue],
) -> tuple[Venue, ...]:
    run_id = uuid4()
    received = sum(len(batch.instruments) for batch in changed_batches)
    all_instruments = tuple(
        instrument for batch in current_batches for instrument in batch.instruments
    )
    resolutions = resolve_market_groups(all_instruments)
    resolution_by_id = {item.venue_instrument_id: item for item in resolutions}
    persisted = 0
    persisted_venues: list[Venue] = []
    persistence_failures: list[Venue] = []

    try:
        with psycopg.connect(database_url, connect_timeout=5, autocommit=True) as connection:
            connection.execute(
                """
                    INSERT INTO collector_runs (
                        run_id, run_kind, started_at, status, records_received, metrics
                    )
                    VALUES (%s, 'catalog', %s, 'running', %s, %s)
                """,
                (
                    run_id,
                    started_at,
                    received,
                    Jsonb({"sourceFailures": tuple(source_failures)}),
                ),
            )
            for batch in changed_batches:
                identities = tuple(
                    resolution_by_id[instrument.venue_instrument_id]
                    for instrument in batch.instruments
                )
                try:
                    result = persist_catalog(
                        connection,
                        batch,
                        identities,
                        collector_run_id=run_id,
                    )
                except CatalogStoreError:
                    persistence_failures.append(batch.provenance.venue)
                    continue
                persisted += (
                    result.instrument_versions_created + result.instrument_versions_unchanged
                )
                persisted_venues.append(batch.provenance.venue)

            failure_count = len(source_failures) + len(persistence_failures)
            if not changed_batches or (failure_count and persisted == 0):
                status = "failed"
            elif failure_count:
                status = "partial"
            else:
                status = "succeeded"
            connection.execute(
                """
                    UPDATE collector_runs
                    SET completed_at = %s, status = %s, records_written = %s,
                        error_code = %s,
                        metrics = metrics || %s::jsonb
                    WHERE run_id = %s
                """,
                (
                    max(datetime.now(UTC), started_at),
                    status,
                    persisted,
                    None if status == "succeeded" else "catalog_partial_failure",
                    Jsonb({"persistenceFailures": tuple(persistence_failures)}),
                    run_id,
                ),
            )
        return tuple(persisted_venues)
    except (psycopg.Error, OSError):
        raise MarketServiceError("catalog persistence failed") from None
