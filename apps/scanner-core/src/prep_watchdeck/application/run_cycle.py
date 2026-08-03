from __future__ import annotations

from prep_watchdeck.adapters.local_snapshot import AtomicSnapshotWriter
from prep_watchdeck.application.chart_artifacts import publish_snapshot_artifacts
from prep_watchdeck.domain.dto import SnapshotDTO
from prep_watchdeck.domain.enums import DataSource
from prep_watchdeck.domain.source_mode import SourceMode
from prep_watchdeck.models import CandleBar
from prep_watchdeck.ports.market_data import MarketDataProvider
from prep_watchdeck.ports.snapshot_cache import SnapshotCache
from prep_watchdeck.ports.snapshot_writer import SnapshotWriter


def run_scan_cycle(
    *,
    source: SourceMode,
    template: str,
    fixture_set: str | None,
    providers: dict[DataSource, MarketDataProvider],
    writer: SnapshotWriter,
    cache: SnapshotCache,
) -> SnapshotDTO:
    if source == SourceMode.AUTO:
        try:
            provider = providers[DataSource.LIVE]
            snapshot = provider.build_snapshot(template=template, fixture_set=fixture_set)
        except NotImplementedError:
            provider = providers[DataSource.CACHE]
            snapshot = provider.build_snapshot(template=template, fixture_set=fixture_set)
    else:
        data_source = DataSource(source.value)
        provider = providers[data_source]
        snapshot = provider.build_snapshot(template=template, fixture_set=fixture_set)
    if snapshot.source.data_source == DataSource.LIVE:
        candles_by_symbol = _provider_candles_5m(provider)
        if isinstance(writer, AtomicSnapshotWriter):
            publish_snapshot_artifacts(
                snapshot=snapshot,
                writer=writer,
                cache=cache,
                chart_candles_by_symbol=_provider_chart_candles(provider),
                candles_5m_by_symbol=candles_by_symbol,
            )
            return snapshot
        if candles_by_symbol:
            cache.save_candles_5m(candles_by_symbol)
    cache.save(snapshot)
    writer.write(snapshot)
    return snapshot


def _provider_candles_5m(provider: MarketDataProvider) -> dict[str, list[CandleBar]]:
    value = getattr(provider, "latest_candles_by_symbol", None)
    if not isinstance(value, dict):
        return {}
    return {
        str(symbol): bars
        for symbol, bars in value.items()
        if isinstance(symbol, str) and isinstance(bars, list)
    }


def _provider_chart_candles(
    provider: MarketDataProvider,
) -> dict[str, dict[str, list[CandleBar]]]:
    value = getattr(provider, "latest_chart_candles_by_symbol", None)
    if not isinstance(value, dict):
        return {}
    return {
        str(symbol): {
            str(timeframe): bars
            for timeframe, bars in timeframes.items()
            if isinstance(timeframe, str) and isinstance(bars, list)
        }
        for symbol, timeframes in value.items()
        if isinstance(symbol, str) and isinstance(timeframes, dict)
    }
