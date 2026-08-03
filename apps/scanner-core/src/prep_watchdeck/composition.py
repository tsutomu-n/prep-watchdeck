from __future__ import annotations

from prep_watchdeck.adapters.bitget_live import BitgetLiveProvider
from prep_watchdeck.adapters.cache import DuckDbCacheProvider
from prep_watchdeck.adapters.duckdb import DuckDbServiceStore, DuckDbSnapshotCache
from prep_watchdeck.adapters.fixture import FixtureProvider
from prep_watchdeck.adapters.local_snapshot import AtomicServiceStateWriter, AtomicSnapshotWriter
from prep_watchdeck.application.ticker_runtime import AtomicTickerRuntimeWriter
from prep_watchdeck.domain.enums import DataSource
from prep_watchdeck.ports.market_data import MarketDataProvider
from prep_watchdeck.settings import Settings


def build_providers(settings: Settings) -> dict[DataSource, MarketDataProvider]:
    cache = build_snapshot_cache(settings)
    return {
        DataSource.LIVE: BitgetLiveProvider(settings),
        DataSource.CACHE: DuckDbCacheProvider(cache),
        DataSource.FIXTURE: FixtureProvider(settings.fixtures_dir),
    }


def build_snapshot_writer(settings: Settings) -> AtomicSnapshotWriter:
    return AtomicSnapshotWriter(settings.latest_snapshot_path)


def build_service_snapshot_writer(settings: Settings) -> AtomicSnapshotWriter:
    return AtomicSnapshotWriter(settings.latest_snapshot_path, archive=False)


def build_service_state_writer(settings: Settings) -> AtomicServiceStateWriter:
    return AtomicServiceStateWriter(settings.service_state_path)


def build_ticker_runtime_writer(settings: Settings) -> AtomicTickerRuntimeWriter:
    return AtomicTickerRuntimeWriter(settings.ticker_runtime_path)


def build_snapshot_cache(settings: Settings) -> DuckDbSnapshotCache:
    return DuckDbSnapshotCache(
        settings.cache_db_path,
        lock_timeout_seconds=settings.cache_lock_timeout_seconds,
        lock_retry_interval_seconds=settings.cache_lock_retry_interval_seconds,
    )


def build_service_store(settings: Settings) -> DuckDbServiceStore:
    return DuckDbServiceStore(settings.cache_db_path)
