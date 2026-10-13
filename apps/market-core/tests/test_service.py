from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import aiohttp
import pytest
from loguru import logger

from prep_watchdeck_market.artifacts import ArtifactPublishResult
from prep_watchdeck_market.market_store import MarketStoreError, MarketStoreResult
from prep_watchdeck_market.models import (
    CatalogBatch,
    CatalogInstrument,
    CatalogProvenance,
    Venue,
    canonical_json_sha256,
)
from prep_watchdeck_market.service import MarketService


def test_catalog_is_published_only_for_venues_that_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service = MarketService(
            "postgresql://not-used",
            Path("/not-used"),
            enabled_venues=("bitget", "hyperliquid", "aster"),
        )
        service._session = cast(aiohttp.ClientSession, object())
        old_hyperliquid = _batch("hyperliquid", "OLD")
        service._catalogs["hyperliquid"] = old_hyperliquid
        fetched = {
            "bitget": _batch("bitget", "BTCUSDT"),
            "hyperliquid": _batch("hyperliquid", "BTC"),
            "aster": _batch("aster", "BTCUSDT"),
        }

        async def fetch_bitget(_session: aiohttp.ClientSession) -> CatalogBatch:
            return fetched["bitget"]

        async def fetch_hyperliquid(_session: aiohttp.ClientSession) -> CatalogBatch:
            return fetched["hyperliquid"]

        async def fetch_aster(_session: aiohttp.ClientSession) -> CatalogBatch:
            return fetched["aster"]

        old_visible_during_persist: list[bool] = []

        def fake_persist(
            _database_url: str,
            _changed_batches: Sequence[CatalogBatch],
            _current_batches: Sequence[CatalogBatch],
            _started_at: datetime,
            _source_failures: Sequence[Venue],
        ) -> tuple[Venue, ...]:
            old_visible_during_persist.append(
                service._instruments("hyperliquid")[0].source_symbol == "OLD"
            )
            return ("bitget", "aster")

        monkeypatch.setattr("prep_watchdeck_market.service.fetch_bitget_catalog", fetch_bitget)
        monkeypatch.setattr(
            "prep_watchdeck_market.service.fetch_hyperliquid_catalog", fetch_hyperliquid
        )
        monkeypatch.setattr("prep_watchdeck_market.service.fetch_aster_catalog", fetch_aster)
        monkeypatch.setattr("prep_watchdeck_market.service._persist_catalog_refresh", fake_persist)
        monkeypatch.setattr(
            "prep_watchdeck_market.service._load_current_candle_version_starts_url",
            lambda _database_url: {
                "bitget:BTCUSDT": fetched["bitget"].provenance.observed_at,
                "hyperliquid:OLD": old_hyperliquid.provenance.observed_at,
                "aster:BTCUSDT": fetched["aster"].provenance.observed_at,
            },
        )

        result = await service.refresh_catalog()

        assert old_visible_during_persist == [True]
        assert result.status == "partial"
        assert result.venues_succeeded == ("bitget", "aster")
        assert result.venues_failed == ("hyperliquid",)
        assert service._instruments("bitget")[0].source_symbol == "BTCUSDT"
        assert service._instruments("hyperliquid")[0].source_symbol == "OLD"
        assert service._instruments("aster")[0].source_symbol == "BTCUSDT"

    asyncio.run(scenario())


def test_empty_catalog_is_a_source_failure_and_retains_last_safe_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service = MarketService(
            "postgresql://not-used",
            Path("/not-used"),
            enabled_venues=("bitget", "hyperliquid", "aster"),
        )
        service._session = cast(aiohttp.ClientSession, object())
        previous_aster = _batch("aster", "BTCUSDT")
        service._catalogs["aster"] = previous_aster
        fetched = {
            "bitget": _batch("bitget", "BTCUSDT"),
            "hyperliquid": _batch("hyperliquid", "BTC"),
            "aster": replace(_batch("aster", "UNKNOWN"), instruments=()),
        }

        async def fetch_bitget(_session: aiohttp.ClientSession) -> CatalogBatch:
            return fetched["bitget"]

        async def fetch_hyperliquid(_session: aiohttp.ClientSession) -> CatalogBatch:
            return fetched["hyperliquid"]

        async def fetch_aster(_session: aiohttp.ClientSession) -> CatalogBatch:
            return fetched["aster"]

        def fake_persist(
            _database_url: str,
            changed_batches: Sequence[CatalogBatch],
            current_batches: Sequence[CatalogBatch],
            _started_at: datetime,
            source_failures: Sequence[Venue],
        ) -> tuple[Venue, ...]:
            assert tuple(batch.provenance.venue for batch in changed_batches) == (
                "bitget",
                "hyperliquid",
            )
            current_by_venue = {batch.provenance.venue: batch for batch in current_batches}
            assert current_by_venue["aster"] is previous_aster
            assert source_failures == ("aster",)
            return ("bitget", "hyperliquid")

        monkeypatch.setattr("prep_watchdeck_market.service.fetch_bitget_catalog", fetch_bitget)
        monkeypatch.setattr(
            "prep_watchdeck_market.service.fetch_hyperliquid_catalog", fetch_hyperliquid
        )
        monkeypatch.setattr("prep_watchdeck_market.service.fetch_aster_catalog", fetch_aster)
        monkeypatch.setattr("prep_watchdeck_market.service._persist_catalog_refresh", fake_persist)
        monkeypatch.setattr(
            "prep_watchdeck_market.service._load_current_candle_version_starts_url",
            lambda _database_url: {},
        )

        result = await service.refresh_catalog()

        assert result.status == "partial"
        assert result.venues_succeeded == ("bitget", "hyperliquid")
        assert result.venues_failed == ("aster",)
        assert result.instruments_received == 2
        assert service._catalogs["aster"] is previous_aster

    asyncio.run(scenario())


def test_successful_l1_persistence_triggers_artifact_publish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = MarketService("postgresql://not-used", tmp_path)
        cycle_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        persisted = _store_result()
        published: list[Path] = []

        def fake_persist(
            _database_url: str,
            _cycle_at: datetime,
            _started_at: datetime,
            _batches: Sequence[object],
        ) -> MarketStoreResult:
            return persisted

        def fake_publish(
            _database_url: str,
            artifact_root: Path,
            _generated_at: datetime,
        ) -> ArtifactPublishResult:
            published.append(artifact_root)
            stop_event.set()
            return ArtifactPublishResult(status="ready", files=())

        monkeypatch.setattr("prep_watchdeck_market.service.persist_market_cycle_url", fake_persist)
        monkeypatch.setattr("prep_watchdeck_market.service._publish_artifacts_url", fake_publish)

        result = await service._persist_l1_cycle(cycle_at, cycle_at, ())
        assert result is persisted

        stop_event = asyncio.Event()
        await service._artifact_loop(stop_event)
        assert published == [tmp_path / "artifacts"]

    asyncio.run(scenario())


def _store_result() -> MarketStoreResult:
    return MarketStoreResult(
        run_id=uuid4(),
        status="succeeded",
        records_received=0,
        records_written=0,
        raw_payloads_written=0,
        unknown_source_rows=0,
        commit_seconds=0.01,
    )


def _batch(venue: Venue, source_symbol: str) -> CatalogBatch:
    observed_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    raw_payload: dict[str, object] = {"venue": venue, "symbol": source_symbol}
    instrument = CatalogInstrument(
        venue=venue,
        source_symbol=source_symbol,
        active=True,
        source_status="active",
        asset_class="crypto",
        market_type="linear_perpetual",
        execution_model="clob",
        base_asset="BTC",
        quote_asset="USDT" if venue != "hyperliquid" else "USD",
        settle_asset="USDT" if venue != "hyperliquid" else "USDC",
        collateral_asset="USDT" if venue != "hyperliquid" else "USDC",
        quantity_unit="base",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.1"),
        amount_step=Decimal("0.001"),
        funding_interval_seconds=3_600,
        raw_definition=raw_payload,
    )
    return CatalogBatch(
        provenance=CatalogProvenance(
            venue=venue,
            source_kind="native_rest",
            endpoint="https://example.invalid/catalog",
            documentation_url="https://example.invalid/docs",
            observed_at=observed_at,
            source_at=None,
            payload_hash=canonical_json_sha256(raw_payload),
        ),
        instruments=(instrument,),
        exclusions=(),
        capabilities=(),
        raw_payload=raw_payload,
    )


def test_metrics_worker_coalesces_failures_and_waits_for_shutdown(monkeypatch, tmp_path):
    import threading
    import time

    async def scenario():
        service = MarketService("unused", tmp_path)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        starts = []
        entered = asyncio.Event()
        release = threading.Event()

        def publish(*args, **kwargs):
            starts.append(time.monotonic())
            if len(starts) == 1:
                for _ in range(20):
                    loop.call_soon_threadsafe(service._metrics_trigger.set)
                raise ValueError("isolated projection failure")
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(3)
            return 1

        monkeypatch.setattr("prep_watchdeck_market.service.publish_market_metrics", publish)
        task = asyncio.create_task(service._metrics_loop(stop))
        await asyncio.wait_for(entered.wait(), 7)
        assert len(starts) == 2
        assert starts[1] - starts[0] >= 4.95
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(starts) == 2

    asyncio.run(scenario())


def test_metrics_notification_follows_successful_persistence_only(monkeypatch, tmp_path):
    async def scenario():
        service = MarketService("unused", tmp_path)
        now = datetime.now(UTC)

        def fail(*args):
            assert not service._metrics_trigger.is_set()
            raise ValueError("isolated persistence failure")

        monkeypatch.setattr("prep_watchdeck_market.service.persist_market_cycle_url", fail)
        with pytest.raises(ValueError):
            await service._persist_l1_cycle(now, now, ())
        assert not service._metrics_trigger.is_set()
        monkeypatch.setattr(
            "prep_watchdeck_market.service.persist_market_cycle_url", lambda *args: _store_result()
        )
        await service._persist_l1_cycle(now, now, ())
        assert service._metrics_trigger.is_set()

    asyncio.run(scenario())


def test_recovery_startup_failure_is_isolated_and_periodic_run_follows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def scenario() -> None:
        service = MarketService("unused", tmp_path, recovery_enabled=True)
        service._session = cast(aiohttp.ClientSession, object())
        stop = asyncio.Event()
        triggers: list[str] = []

        class FakeRecovery:
            def __init__(
                self, _database_url: str, _state_dir: Path, *, on_inserted, enabled_venues
            ) -> None:
                self.on_inserted = on_inserted

            async def run(self, _session, _window, *, apply: bool, trigger: str):
                assert apply
                triggers.append(trigger)
                if trigger == "startup":
                    raise RuntimeError("isolated recovery failure")
                self.on_inserted()
                stop.set()
                return SimpleNamespace(
                    execution="succeeded", summary=SimpleNamespace(inserted=1, remaining=0)
                )

        monkeypatch.setattr("prep_watchdeck_market.service.CandleRecovery", FakeRecovery)
        monkeypatch.setattr(
            "prep_watchdeck_market.service.next_grid_at", lambda _now, _seconds: datetime.now(UTC)
        )
        await asyncio.wait_for(service._recovery_loop(stop), timeout=1)
        assert triggers == ["startup", "periodic"]
        assert service._artifact_trigger.is_set()
        assert service._metrics_trigger.is_set()

    asyncio.run(scenario())


def test_endpoint_recovery_failure_is_isolated_and_runs_on_minute_grid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def scenario() -> None:
        service = MarketService("unused", tmp_path, recovery_enabled=True)
        service._session = cast(aiohttp.ClientSession, object())
        stop = asyncio.Event()
        triggers: list[str] = []
        grids: list[int] = []

        class FakeRecovery:
            def __init__(self, _database_url, _state_dir, *, on_inserted, enabled_venues):
                self.on_inserted = on_inserted

            async def run(self, _session, *, trigger: str):
                triggers.append(trigger)
                if trigger == "startup":
                    raise RuntimeError("isolated endpoint failure")
                self.on_inserted()
                stop.set()
                return SimpleNamespace(
                    execution="partial", summary=SimpleNamespace(inserted=1, remaining=2)
                )

        def grid(_now, seconds: int):
            grids.append(seconds)
            return datetime.now(UTC)

        monkeypatch.setattr("prep_watchdeck_market.service.CandleEndpointRecovery", FakeRecovery)
        monkeypatch.setattr("prep_watchdeck_market.service.next_grid_at", grid)
        await asyncio.wait_for(service._endpoint_recovery_loop(stop), timeout=1)
        assert triggers == ["startup", "periodic"]
        assert grids == [60]
        assert service._artifact_trigger.is_set() and service._metrics_trigger.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["endpoint", "history"])
def test_recovery_service_stop_cancels_and_joins_active_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    async def scenario() -> None:
        service = MarketService("unused", tmp_path, recovery_enabled=True)
        service._session = cast(aiohttp.ClientSession, object())
        stop = asyncio.Event()
        active = asyncio.Event()
        joined = asyncio.Event()

        class FakeRecovery:
            def __init__(self, *_args, **_kwargs):
                pass

            async def run(self, *_args, **_kwargs):
                active.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(0)
                    joined.set()

        name = "CandleEndpointRecovery" if mode == "endpoint" else "CandleRecovery"
        monkeypatch.setattr(f"prep_watchdeck_market.service.{name}", FakeRecovery)
        recovery_loop = (
            service._endpoint_recovery_loop if mode == "endpoint" else service._recovery_loop
        )
        task = asyncio.create_task(recovery_loop(stop))
        await active.wait()
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        assert joined.is_set()

    asyncio.run(scenario())


def test_activity_worker_keeps_projection_failure_optional(monkeypatch, tmp_path):
    async def scenario():
        service = MarketService("unused", tmp_path)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        calls = []

        def publish(*args, **kwargs):
            calls.append(1)
            loop.call_soon_threadsafe(stop.set)
            raise ValueError("isolated activity failure")

        monkeypatch.setattr(
            "prep_watchdeck_market.service.publish_native_activity", publish, raising=False
        )
        await asyncio.wait_for(service._activity_loop(stop), timeout=1)
        assert calls == [1]

    asyncio.run(scenario())


def test_service_entrypoint_disables_all_mexc_runtime_acquisition(monkeypatch, tmp_path):
    from prep_watchdeck_market.service import run_market_service

    enabled = []

    async def run(self, stop_event):
        enabled.extend(f.venue for f in self._l1_fetchers())
        assert self._enabled_venues == ("bitget", "hyperliquid", "aster")
        # Real catalog refresh runs only enabled fetches; any MEXC call is a regression.
        self._session = cast(aiohttp.ClientSession, object())
        await self.refresh_catalog()

    monkeypatch.setattr(MarketService, "run_forever", run)

    async def fetch(venue, session):
        return _batch(venue, "BTC")

    for venue in ("bitget", "hyperliquid", "aster"):

        async def current(session, venue=venue):
            return await fetch(venue, session)

        monkeypatch.setattr("prep_watchdeck_market.service.fetch_" + venue + "_catalog", current)

    async def forbidden(session):
        raise AssertionError("MEXC acquisition disabled")

    monkeypatch.setattr("prep_watchdeck_market.service.fetch_mexc_catalog", forbidden)
    monkeypatch.setattr(
        "prep_watchdeck_market.service._persist_catalog_refresh", lambda *_: tuple(enabled)
    )
    monkeypatch.setattr(
        "prep_watchdeck_market.service._load_current_candle_version_starts_url", lambda *_: {}
    )
    asyncio.run(run_market_service("unused", tmp_path, asyncio.Event(), mexc_enabled=False))
    assert enabled == ["bitget", "hyperliquid", "aster"]


@pytest.mark.parametrize("failure_kind", ("source", "version_ids"))
def test_initial_mexc_failure_keeps_service_running_and_funding_recovers(
    monkeypatch, tmp_path, failure_kind
):
    from prep_watchdeck_market.market_state import MarketBatch
    from prep_watchdeck_market.sources.common import CatalogSourceError

    async def scenario():
        service = MarketService("unused", tmp_path)
        stop = asyncio.Event()
        funded = asyncio.Event()
        mexc_attempts = 0
        version_attempts = 0
        persisted_venues = []
        funding_writes = []
        other_venues: tuple[Venue, ...] = ("bitget", "hyperliquid", "aster")

        for venue in other_venues:

            async def fetch(session, venue: Venue = venue):
                return _batch(venue, "BTC")

            monkeypatch.setattr("prep_watchdeck_market.service.fetch_" + venue + "_catalog", fetch)

        async def fetch_mexc(session):
            nonlocal mexc_attempts
            mexc_attempts += 1
            if mexc_attempts == 1 and failure_kind == "source":
                raise CatalogSourceError("catalog unavailable")
            return _batch("mexc", "BTC_USDT")

        def load_versions(_database_url):
            nonlocal version_attempts
            version_attempts += 1
            if version_attempts == 1 and failure_kind == "version_ids":
                raise MarketStoreError("version IDs unavailable")
            return {"BTC_USDT": 7}

        async def fetch_funding(session, endpoint, **kwargs):
            assert endpoint == "/api/v1/contract/funding_rate/BTC_USDT"
            funded.set()
            timestamp = int(datetime.now(UTC).timestamp() * 1000)
            return {
                "success": True,
                "code": 0,
                "data": {
                    "symbol": "BTC_USDT",
                    "fundingRate": "0.0001",
                    "collectCycle": 8,
                    "timestamp": timestamp,
                    "nextSettleTime": timestamp + 3_600_000,
                },
            }

        def persist_cycle(database_url, cycle_at, started_at, batches, **kwargs):
            persisted_venues.extend(batch.venue for batch in batches)
            return _store_result()

        def persist_funding(database_url, updates, as_of):
            funding_writes.extend(updates)
            assert updates["BTC_USDT"][1].native_version_id == 7
            return len(updates)

        async def wait(self, event):
            await event.wait()

        async def collect(self, event):
            runtime = service._mexc_funding
            assert runtime is not None
            assert tuple(runtime._instruments()) == ()
            with pytest.raises(CatalogSourceError, match="mexc catalog is unavailable"):
                service._instruments("mexc")
            assert await service._flush_mexc_funding() == 0
            now = datetime.now(UTC)
            batches = tuple(
                MarketBatch(venue, now, now, "unused", "0" * 64, (), {}) for venue in other_venues
            )
            await service._persist_l1_cycle(now, now, batches)
            assert (await service.refresh_catalog()).status == "succeeded"
            await funded.wait()
            assert await service._flush_mexc_funding() == 1
            event.set()

        monkeypatch.setattr("prep_watchdeck_market.service.fetch_mexc_catalog", fetch_mexc)
        monkeypatch.setattr(
            "prep_watchdeck_market.service._persist_catalog_refresh",
            lambda database_url, changed, *_: tuple(batch.provenance.venue for batch in changed),
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.service._load_current_candle_version_starts_url", lambda *_: {}
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.service.load_current_mexc_version_ids_url",
            load_versions,
        )
        monkeypatch.setattr("prep_watchdeck_market.service.persist_market_cycle_url", persist_cycle)
        monkeypatch.setattr(
            "prep_watchdeck_market.service.persist_mexc_funding_url", persist_funding
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.sources.mexc_funding.fetch_mexc_json", fetch_funding
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.sources.mexc_funding.FUNDING_SWEEP_SECONDS", 0.01
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.sources.mexc_funding.FUNDING_START_INTERVAL_SECONDS", 0.01
        )
        monkeypatch.setattr("prep_watchdeck_market.service.L1Scheduler.run_forever", collect)
        monkeypatch.setattr("prep_watchdeck_market.service.CandleRuntime.run_forever", wait)
        monkeypatch.setattr("prep_watchdeck_market.service.SelectionRuntime.run_forever", wait)
        for name in (
            "_catalog_loop",
            "_artifact_loop",
            "_selected_artifact_loop",
            "_metrics_loop",
            "_activity_loop",
            "_funding_flush_loop",
        ):
            monkeypatch.setattr(MarketService, name, wait)

        await asyncio.wait_for(service.run_forever(stop), timeout=1)
        assert persisted_venues == ["bitget", "hyperliquid", "aster"]
        assert funding_writes == ["BTC_USDT"]
        assert service._session is None

    asyncio.run(scenario())


def _mexc_version_read_failure_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    enabled_venues: tuple[Venue, ...],
) -> MarketService:
    service = MarketService("unused", tmp_path, enabled_venues=enabled_venues)
    service._session = cast(aiohttp.ClientSession, object())
    service._catalogs["mexc"] = _batch("mexc", "OLD_USDT")
    service._mexc_version_ids = {"OLD_USDT": 1}
    for venue in enabled_venues:

        async def fetch(_session: aiohttp.ClientSession, venue: Venue = venue) -> CatalogBatch:
            return _batch(venue, "BTC_USDT" if venue == "mexc" else "BTC")

        monkeypatch.setattr("prep_watchdeck_market.service.fetch_" + venue + "_catalog", fetch)
    monkeypatch.setattr(
        "prep_watchdeck_market.service._persist_catalog_refresh",
        lambda _url, changed, *_: tuple(batch.provenance.venue for batch in changed),
    )
    monkeypatch.setattr(
        "prep_watchdeck_market.service._load_current_candle_version_starts_url", lambda *_: {}
    )
    attempts = 0

    def load_versions(_database_url: str) -> dict[str, int]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise MarketStoreError("synthetic-private-marker")
        return {"BTC_USDT": 7}

    monkeypatch.setattr(
        "prep_watchdeck_market.service.load_current_mexc_version_ids_url", load_versions
    )
    return service


@pytest.mark.parametrize(
    ("enabled_venues", "expected_status", "other_venues"),
    [
        (("bitget", "hyperliquid", "aster", "mexc"), "partial", ("bitget", "hyperliquid", "aster")),
        (("mexc",), "failed", ()),
    ],
)
def test_mexc_version_read_failure_invalidates_old_state_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    enabled_venues: tuple[Venue, ...],
    expected_status: str,
    other_venues: tuple[Venue, ...],
) -> None:
    from prep_watchdeck_market.sources.common import CatalogSourceError

    async def scenario() -> None:
        service = _mexc_version_read_failure_service(monkeypatch, tmp_path, enabled_venues)
        messages: list[str] = []
        sink = logger.add(messages.append, format="{message}", level="WARNING")
        try:
            failed = await service.refresh_catalog()
        finally:
            logger.remove(sink)
        assert failed.status == expected_status
        assert failed.venues_succeeded == other_venues
        assert failed.venues_failed == ("mexc",)
        assert service._mexc_version_ids == {}
        assert service._mexc_funding_instruments() == ()
        with pytest.raises(CatalogSourceError, match="mexc catalog is unavailable"):
            service._instruments("mexc")
        assert {item.venue for item in service._all_instruments()} == set(other_venues)
        assert all(service._instruments(venue)[0].source_symbol == "BTC" for venue in other_venues)
        assert len(messages) == 1
        assert "MarketStoreError" in messages[0]
        assert "mexc" in messages[0].lower()
        assert "synthetic-private-marker" not in messages[0]

        recovered = await service.refresh_catalog()
        assert recovered.status == "succeeded"
        assert recovered.venues_succeeded == enabled_venues
        assert recovered.venues_failed == ()
        assert service._mexc_version_ids == {"BTC_USDT": 7}
        assert service._instruments("mexc")[0].source_symbol == "BTC_USDT"
        assert service._mexc_funding_instruments()[0].source_symbol == "BTC_USDT"

    asyncio.run(scenario())


def test_periodic_mexc_version_read_failure_does_not_end_catalog_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def scenario() -> None:
        service = _mexc_version_read_failure_service(
            monkeypatch, tmp_path, ("bitget", "hyperliquid", "aster", "mexc")
        )
        stop = asyncio.Event()
        statuses: list[str] = []
        refresh = service.refresh_catalog

        async def record_refresh():
            result = await refresh()
            statuses.append(result.status)
            if len(statuses) == 2:
                stop.set()
            return result

        async def skip_grid_wait(awaitable, *, timeout):
            awaitable.close()
            raise TimeoutError

        monkeypatch.setattr(service, "refresh_catalog", record_refresh)
        monkeypatch.setattr("prep_watchdeck_market.service.asyncio.wait_for", skip_grid_wait)
        async with asyncio.timeout(1):
            await service._catalog_loop(stop)
        assert statuses == ["partial", "succeeded"]
        assert service._instruments("bitget")[0].source_symbol == "BTC"
        assert service._instruments("mexc")[0].source_symbol == "BTC_USDT"

    asyncio.run(scenario())


def test_disabled_selection_runtime_excludes_saved_mexc_members(monkeypatch, tmp_path):
    from prep_watchdeck_market.selection_runtime import (
        InvalidSelectionCommandError,
        SelectionRuntime,
    )

    original = _batch("bitget", "BTCUSDT").instruments[0]
    mexc = replace(original, venue="mexc", source_symbol="BTC_USDT")
    monkeypatch.setattr(
        "prep_watchdeck_market.selection_runtime._load_group_instruments",
        lambda *_: (original, mexc),
    )
    runtime = SelectionRuntime(
        "unused", tmp_path, None, enabled_venues=("bitget", "hyperliquid", "aster")
    )
    assert runtime._enabled_group_instruments(
        cast(Any, object()), "crypto:BTC:linear-perp", "bitget:BTCUSDT"
    ) == (original,)
    with pytest.raises(InvalidSelectionCommandError):
        runtime._enabled_group_instruments(
            cast(Any, object()), "crypto:BTC:linear-perp", "mexc:BTC_USDT"
        )
