from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from prep_watchdeck.adapters.local_snapshot import AtomicSnapshotWriter
from prep_watchdeck.constants import TIMEFRAME_BARS
from prep_watchdeck.domain.dto import SnapshotDTO
from prep_watchdeck.domain.symbols import is_safe_public_symbol
from prep_watchdeck.models import CandleBar
from prep_watchdeck.ports.snapshot_cache import SnapshotCache

FIVE_MINUTES_MS = 5 * 60_000
DETAIL_CHART_SCHEMA_VERSION = 2
DETAIL_CHART_BAR_LIMIT = 128


@dataclass(frozen=True)
class PreparedChartFile:
    final_path: Path
    temporary_path: Path


@dataclass
class PreparedChartFiles:
    chart_dir: Path
    active_symbols: set[str]
    files: list[PreparedChartFile]

    def commit(self) -> None:
        try:
            for item in self.files:
                os.replace(item.temporary_path, item.final_path)
        finally:
            self.discard()

    def discard(self) -> None:
        for item in self.files:
            item.temporary_path.unlink(missing_ok=True)

    def remove_stale(self) -> None:
        active_filenames = {f"{symbol}.json" for symbol in self.active_symbols}
        for path in self.chart_dir.glob("*.json"):
            if path.name not in active_filenames:
                path.unlink()


def publish_snapshot_artifacts(
    *,
    snapshot: SnapshotDTO,
    writer: AtomicSnapshotWriter,
    cache: SnapshotCache,
    chart_candles_by_symbol: Mapping[str, Mapping[str, list[CandleBar]]],
    candles_5m_by_symbol: dict[str, list[CandleBar]] | None = None,
) -> None:
    chart_dir = writer.latest_path.parent / "charts" / "latest"
    payloads = {
        row.symbol: build_detail_chart_payload(
            snapshot_run_id=snapshot.run_id,
            symbol=row.symbol,
            generated_at_ms=snapshot.generated_at,
            data_as_of_ms=snapshot.data_as_of,
            bars_by_timeframe=chart_candles_by_symbol.get(row.symbol, {}),
        )
        for row in snapshot.rows
    }
    prepared = prepare_chart_files(chart_dir, payloads)
    prepared.commit()

    if candles_5m_by_symbol:
        cache.save_candles_5m(candles_5m_by_symbol)
    cache.save(snapshot)
    writer.write(snapshot)
    prepared.remove_stale()


def write_chart_files(
    chart_dir: Path,
    *,
    snapshot_run_id: str,
    generated_at_ms: int,
    data_as_of_ms: int,
    chart_candles_by_symbol: Mapping[str, Mapping[str, list[CandleBar]]],
    symbols: Iterable[str],
) -> None:
    payloads = {
        symbol: build_detail_chart_payload(
            snapshot_run_id=snapshot_run_id,
            symbol=symbol,
            generated_at_ms=generated_at_ms,
            data_as_of_ms=data_as_of_ms,
            bars_by_timeframe=chart_candles_by_symbol.get(symbol, {}),
        )
        for symbol in set(symbols)
    }
    prepared = prepare_chart_files(chart_dir, payloads)
    prepared.commit()
    prepared.remove_stale()


def prepare_chart_files(
    chart_dir: Path,
    payloads: Mapping[str, dict[str, object]],
) -> PreparedChartFiles:
    chart_dir.mkdir(parents=True, exist_ok=True)
    prepared = PreparedChartFiles(
        chart_dir=chart_dir,
        active_symbols=set(payloads),
        files=[],
    )
    try:
        for symbol, payload in sorted(payloads.items()):
            _validate_symbol(symbol)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                prefix=f".{symbol}.",
                suffix=".json.tmp",
                dir=chart_dir,
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            prepared.files.append(
                PreparedChartFile(
                    final_path=chart_dir / f"{symbol}.json",
                    temporary_path=temporary_path,
                )
            )
    except Exception:
        prepared.discard()
        raise
    return prepared


def build_detail_chart_payload(
    *,
    snapshot_run_id: str,
    symbol: str,
    generated_at_ms: int,
    data_as_of_ms: int,
    bars_by_timeframe: Mapping[str, list[CandleBar]],
) -> dict[str, object]:
    if not snapshot_run_id:
        raise ValueError("snapshot_run_id is required")
    _validate_symbol(symbol)
    return {
        "schemaVersion": DETAIL_CHART_SCHEMA_VERSION,
        "snapshotRunId": snapshot_run_id,
        "symbol": symbol,
        "generatedAt": generated_at_ms,
        "dataAsOf": data_as_of_ms,
        "timeframes": {
            timeframe: [_chart_bar_payload(bar) for bar in normalize_chart_bars(bars)]
            for timeframe, bars in bars_by_timeframe.items()
        },
    }


def chart_timeframes_from_5m(bars: list[CandleBar]) -> dict[str, list[CandleBar]]:
    return {timeframe: aggregate_5m_bars(bars, timeframe) for timeframe in TIMEFRAME_BARS}


def aggregate_5m_bars(bars: list[CandleBar], timeframe: str) -> list[CandleBar]:
    deduplicated = _deduplicate_bars(bars)
    if timeframe == "5m":
        return deduplicated
    timeframe_bars = TIMEFRAME_BARS.get(timeframe)
    if timeframe_bars is None or timeframe_bars <= 1:
        return deduplicated

    bucket_ms = timeframe_bars * FIVE_MINUTES_MS
    grouped: dict[int, list[CandleBar]] = {}
    for bar in deduplicated:
        grouped.setdefault(bar.ts - (bar.ts % bucket_ms), []).append(bar)

    return [
        CandleBar(
            symbol=bucket[0].symbol,
            ts=bucket_ts,
            open=bucket[0].open,
            high=max(bar.high for bar in bucket),
            low=min(bar.low for bar in bucket),
            close=bucket[-1].close,
            base_vol=sum((bar.base_vol for bar in bucket), Decimal("0")),
            quote_vol=sum((bar.quote_vol for bar in bucket), Decimal("0")),
        )
        for bucket_ts, bucket in sorted(grouped.items())
    ]


def normalize_chart_bars(bars: Iterable[CandleBar]) -> list[CandleBar]:
    return _deduplicate_bars(bars)[-DETAIL_CHART_BAR_LIMIT:]


def _deduplicate_bars(bars: Iterable[CandleBar]) -> list[CandleBar]:
    by_timestamp: dict[int, CandleBar] = {}
    for bar in bars:
        _validate_bar(bar)
        by_timestamp[bar.ts] = bar
    return [by_timestamp[timestamp] for timestamp in sorted(by_timestamp)]


def _validate_bar(bar: CandleBar) -> None:
    if bar.ts <= 0:
        raise ValueError("chart bar ts must be positive")
    if any(value <= 0 for value in (bar.open, bar.high, bar.low, bar.close)):
        raise ValueError("chart bar OHLC values must be positive")
    if bar.quote_vol < 0:
        raise ValueError("chart bar quote volume must be non-negative")


def _validate_symbol(symbol: str) -> None:
    if not is_safe_public_symbol(symbol):
        raise ValueError(f"invalid chart symbol: {symbol}")


def _chart_bar_payload(bar: CandleBar) -> dict[str, float | int]:
    return {
        "ts": bar.ts,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "quoteVolume": float(bar.quote_vol),
    }
