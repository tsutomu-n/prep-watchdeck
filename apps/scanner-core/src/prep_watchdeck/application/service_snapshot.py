from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from typing import Any, Protocol

from prep_watchdeck.adapters.bitget_live.provider import snapshot_from_pipeline
from prep_watchdeck.adapters.local_snapshot import AtomicSnapshotWriter
from prep_watchdeck.application.chart_artifacts import (
    chart_timeframes_from_5m,
    publish_snapshot_artifacts,
)
from prep_watchdeck.application.service_gap_audit import SymbolGapAudit, audit_service_gaps
from prep_watchdeck.config.filter_config import FilterConfig
from prep_watchdeck.config.vpi_config import VpiConfig
from prep_watchdeck.constants import TIMEFRAME_BARS
from prep_watchdeck.domain.dto import SnapshotDTO
from prep_watchdeck.domain.service_models import (
    Candle1mRecord,
    InstrumentRecord,
    OpenInterestSampleRecord,
    TickerLatestRecord,
)
from prep_watchdeck.domain.symbols import is_safe_public_symbol
from prep_watchdeck.models import CandleBar, ContractInfo, ScannerRow, TickerInfo
from prep_watchdeck.ports.snapshot_cache import SnapshotCache
from prep_watchdeck.screening.pipeline import PipelineResult, build_scanner_rows, make_run_id
from prep_watchdeck.screening.reasons import build_reason
from prep_watchdeck.vpi.compute import compute_vpi_lite_plus
from prep_watchdeck.vpi.models import VpiSourceBar
from prep_watchdeck.vpi.serialize import build_vpi_snapshot_block, serialize_vpi_result

ONE_SECOND_MS = 1_000
ONE_MINUTE_MS = 60 * ONE_SECOND_MS
FIVE_MINUTES_MS = 5 * ONE_MINUTE_MS
DEFAULT_MAX_SERVICE_SNAPSHOT_DATA_LAG_MS = 2 * ONE_MINUTE_MS
OPEN_INTEREST_RETENTION_MS = 24 * 60 * ONE_MINUTE_MS
logger = logging.getLogger(__name__)


class ServiceSnapshotStore(Protocol):
    def load_instruments(self) -> list[InstrumentRecord]:
        """Load service instrument records."""

    def load_ticker_latest(self) -> list[TickerLatestRecord]:
        """Load latest service ticker records."""

    def upsert_open_interest_samples(self, samples: list[OpenInterestSampleRecord]) -> None:
        """Persist current OI samples."""

    def load_open_interest_samples(
        self, start_ts_ms: int, end_ts_ms: int
    ) -> list[OpenInterestSampleRecord]:
        """Load OI samples from an inclusive bucket range."""

    def delete_open_interest_samples_before(self, cutoff_ts_ms: int) -> int:
        """Delete OI samples older than the retention cutoff."""

    def load_recent_candles_1m(self, limit_per_symbol: int) -> list[Candle1mRecord]:
        """Load recent 1m candle records."""

    def load_candles_1m_since(self, start_ts_ms: int) -> list[Candle1mRecord]:
        """Load 1m candle records from the snapshot lookback window."""

    def load_candles_1m_range(
        self,
        symbols: list[str],
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> list[Candle1mRecord]:
        """Load 1m candle records from an inclusive timestamp window."""


@dataclass(frozen=True)
class ServiceSnapshotBuild:
    snapshot: SnapshotDTO
    candles_by_symbol: dict[str, list[CandleBar]]
    latest_candle_1m_ts_ms: int | None


def snapshot_from_service_store(
    store: ServiceSnapshotStore,
    *,
    template: str,
    config: FilterConfig,
    vpi_config: VpiConfig | None = None,
    generated_at_ms: int | None = None,
    run_id: str | None = None,
) -> SnapshotDTO:
    return build_service_snapshot(
        store,
        template=template,
        config=config,
        vpi_config=vpi_config,
        generated_at_ms=generated_at_ms,
        run_id=run_id,
    ).snapshot


def build_service_snapshot(
    store: ServiceSnapshotStore,
    *,
    template: str,
    config: FilterConfig,
    vpi_config: VpiConfig | None = None,
    generated_at_ms: int | None = None,
    run_id: str | None = None,
) -> ServiceSnapshotBuild:
    generated_at_ms = int(time.time() * 1000) if generated_at_ms is None else generated_at_ms
    run_id = run_id or make_run_id()
    contracts = [
        _contract_from_instrument(item)
        for item in store.load_instruments()
        if is_safe_public_symbol(item.symbol)
    ]
    ticker_records = store.load_ticker_latest()
    tickers = [
        _ticker_from_latest(item) for item in ticker_records if is_safe_public_symbol(item.symbol)
    ]
    required_1m_limit = _required_1m_limit(config)
    required_window_start_ms = _required_1m_window_start_ms(generated_at_ms, required_1m_limit)
    candles_1m = store.load_candles_1m_since(start_ts_ms=required_window_start_ms)
    generated_window_end_ms = generated_at_ms - (generated_at_ms % ONE_MINUTE_MS)
    required_window_end_ms = _service_gap_window_end_ms(candles_1m, generated_window_end_ms)
    adjusted_window_start_ms = required_window_end_ms - (required_1m_limit - 1) * ONE_MINUTE_MS
    if adjusted_window_start_ms < required_window_start_ms:
        required_window_start_ms = adjusted_window_start_ms
        candles_1m = store.load_candles_1m_since(start_ts_ms=required_window_start_ms)
    vpi_block = _build_vpi_block(
        candles_1m,
        tickers=ticker_records,
        config=vpi_config,
        generated_at_ms=generated_at_ms,
    )
    candles_by_symbol = aggregate_1m_to_5m(candles_1m)
    try:
        previous_oi_by_symbol, oi_diagnostics = _prepare_open_interest_history(
            store,
            ticker_records=ticker_records,
            allowed_symbols={contract.symbol for contract in contracts},
            generated_at_ms=generated_at_ms,
            lookback_minutes=config.open_interest.change_lookback_minutes,
        )
    except Exception as exc:
        logger.warning("OI history cycle failed: %s", type(exc).__name__)
        previous_oi_by_symbol = {}
        oi_diagnostics = {
            "status": "degraded",
            "code": "OI_HISTORY_UNAVAILABLE",
            "errorType": type(exc).__name__,
        }
    rows = build_scanner_rows(
        config=config,
        contracts=contracts,
        tickers=tickers,
        candles_by_symbol=candles_by_symbol,
        previous_oi_by_symbol=previous_oi_by_symbol,
    )
    _append_service_gap_risk_tags(
        rows,
        store=store,
        symbols=[contract.symbol for contract in contracts],
        window_start_ms=required_window_start_ms,
        window_end_ms=required_window_end_ms,
    )
    result = PipelineResult(
        run_id=run_id,
        generated_at_ms=generated_at_ms,
        rows=rows,
        contracts=contracts,
        tickers=tickers,
        candles_by_symbol=candles_by_symbol,
        chart_candles_by_symbol={
            symbol: {"5m": bars[-128:]} for symbol, bars in candles_by_symbol.items()
        },
        candle_errors={},
    )
    snapshot = snapshot_from_pipeline(
        result,
        template=template,
        config=config,
        product_type=config.universe.product_type,
        include_chart_bars=False,
        sparkline_points_limit=5,
    )
    snapshot.summary["serviceSource"] = "duckdb-service"
    snapshot.summary["serviceCandles1m"] = len(candles_1m)
    snapshot.summary["oiDiagnostics"] = oi_diagnostics
    if vpi_block is not None:
        snapshot.summary["vpiLitePlus"] = vpi_block
        items_by_symbol = {
            item["symbol"]: item for item in [*vpi_block["benchmarks"], *vpi_block["targets"]]
        }
        for row in snapshot.rows:
            if item := items_by_symbol.get(row.symbol):
                row.display["vpiLitePlus"] = item
    return ServiceSnapshotBuild(
        snapshot=snapshot,
        candles_by_symbol=candles_by_symbol,
        latest_candle_1m_ts_ms=max((candle.ts_ms for candle in candles_1m), default=None),
    )


def publish_service_snapshot_once(
    store: ServiceSnapshotStore,
    writer: AtomicSnapshotWriter,
    cache: SnapshotCache,
    *,
    template: str,
    config: FilterConfig,
    vpi_config: VpiConfig | None = None,
    generated_at_ms: int | None = None,
    run_id: str | None = None,
    max_data_lag_ms: int | None = None,
) -> SnapshotDTO:
    build = build_service_snapshot(
        store,
        template=template,
        config=config,
        vpi_config=vpi_config,
        generated_at_ms=generated_at_ms,
        run_id=run_id,
    )
    if max_data_lag_ms is not None:
        _validate_service_snapshot_freshness(
            latest_candle_1m_ts_ms=build.latest_candle_1m_ts_ms,
            generated_at_ms=build.snapshot.generated_at,
            max_data_lag_ms=max_data_lag_ms,
        )
    snapshot = build.snapshot
    publish_snapshot_artifacts(
        snapshot=snapshot,
        writer=writer,
        cache=cache,
        chart_candles_by_symbol={
            symbol: chart_timeframes_from_5m(bars)
            for symbol, bars in build.candles_by_symbol.items()
        },
    )
    return snapshot


def _validate_service_snapshot_freshness(
    *,
    latest_candle_1m_ts_ms: int | None,
    generated_at_ms: int,
    max_data_lag_ms: int,
) -> None:
    if max_data_lag_ms < 0:
        raise ValueError("max_data_lag_ms must be non-negative")
    if latest_candle_1m_ts_ms is None:
        raise ValueError("service candle data is unavailable")
    lag_ms = max(0, generated_at_ms - latest_candle_1m_ts_ms)
    if lag_ms // ONE_SECOND_MS > max_data_lag_ms // ONE_SECOND_MS:
        raise ValueError(
            "service candle data is stale: "
            f"lag={lag_ms}ms max={max_data_lag_ms}ms "
            f"latest={latest_candle_1m_ts_ms} generated={generated_at_ms}"
        )


async def publish_service_snapshot_periodically(
    store: ServiceSnapshotStore,
    writer: AtomicSnapshotWriter,
    cache: SnapshotCache,
    *,
    template: str,
    config: FilterConfig,
    vpi_config: VpiConfig | None = None,
    interval_seconds: float,
    publish_immediately: bool = True,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if publish_immediately:
        await asyncio.to_thread(
            publish_service_snapshot_once,
            store,
            writer,
            cache,
            template=template,
            config=config,
            vpi_config=vpi_config,
        )
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(
            publish_service_snapshot_once,
            store,
            writer,
            cache,
            template=template,
            config=config,
            vpi_config=vpi_config,
        )


def _prepare_open_interest_history(
    store: ServiceSnapshotStore,
    *,
    ticker_records: list[TickerLatestRecord],
    allowed_symbols: set[str],
    generated_at_ms: int,
    lookback_minutes: int,
) -> tuple[dict[str, float], dict[str, object]]:
    samples: list[OpenInterestSampleRecord] = []
    target_bucket_by_symbol: dict[str, int] = {}
    lookback_ms = lookback_minutes * ONE_MINUTE_MS
    for ticker in ticker_records:
        if ticker.symbol not in allowed_symbols or not _is_valid_current_oi(
            ticker, generated_at_ms=generated_at_ms
        ):
            continue
        holding_amount = ticker.holding_amount
        assert holding_amount is not None
        bucket_ts_ms = ticker.ts_ms - (ticker.ts_ms % FIVE_MINUTES_MS)
        samples.append(
            OpenInterestSampleRecord(
                symbol=ticker.symbol,
                bucket_ts_ms=bucket_ts_ms,
                holding_amount=float(holding_amount),
                source_ts_ms=ticker.ts_ms,
                updated_at_ms=generated_at_ms,
            )
        )
        target_bucket_by_symbol[ticker.symbol] = bucket_ts_ms - lookback_ms

    store.upsert_open_interest_samples(samples)
    reference_rows: list[OpenInterestSampleRecord] = []
    if target_bucket_by_symbol:
        reference_rows = store.load_open_interest_samples(
            min(target_bucket_by_symbol.values()),
            max(target_bucket_by_symbol.values()),
        )
    reference_by_key = {(sample.symbol, sample.bucket_ts_ms): sample for sample in reference_rows}
    previous_oi_by_symbol = {
        symbol: reference.holding_amount
        for symbol, target_bucket_ts_ms in target_bucket_by_symbol.items()
        if (reference := reference_by_key.get((symbol, target_bucket_ts_ms))) is not None
    }
    pruned = store.delete_open_interest_samples_before(generated_at_ms - OPEN_INTEREST_RETENTION_MS)
    return previous_oi_by_symbol, {
        "status": "ok",
        "lookbackMinutes": lookback_minutes,
        "sampled": len(samples),
        "references": len(previous_oi_by_symbol),
        "pruned": pruned,
    }


def _is_valid_current_oi(ticker: TickerLatestRecord, *, generated_at_ms: int) -> bool:
    holding_amount = ticker.holding_amount
    if (
        holding_amount is None
        or not isfinite(holding_amount)
        or holding_amount <= 0
        or ticker.ts_ms <= 0
        or ticker.updated_at_ms <= 0
    ):
        return False
    return (
        max(0, generated_at_ms - ticker.ts_ms) <= DEFAULT_MAX_SERVICE_SNAPSHOT_DATA_LAG_MS
        and max(0, generated_at_ms - ticker.updated_at_ms)
        <= DEFAULT_MAX_SERVICE_SNAPSHOT_DATA_LAG_MS
    )


def _build_vpi_block(
    candles: list[Candle1mRecord],
    *,
    tickers: list[TickerLatestRecord],
    config: VpiConfig | None,
    generated_at_ms: int,
) -> dict[str, Any] | None:
    if config is None or not config.enabled:
        return None
    try:
        configured_symbols = set(config.benchmark_symbols) | set(config.target_symbols)
        candles_by_symbol: dict[str, list[VpiSourceBar]] = {}
        for candle in candles:
            if candle.symbol not in configured_symbols:
                continue
            candles_by_symbol.setdefault(candle.symbol, []).append(
                VpiSourceBar(
                    ts_ms=candle.ts_ms,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    usdt_volume=candle.usdt_volume,
                    quote_volume=candle.quote_volume,
                    is_closed=candle.is_closed,
                    updated_at_ms=candle.updated_at_ms,
                )
            )
        ticker_by_symbol = {ticker.symbol: ticker for ticker in tickers}

        def compute_symbols(symbols: tuple[str, ...]) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            for symbol in symbols:
                ticker = ticker_by_symbol.get(symbol)
                try:
                    result = compute_vpi_lite_plus(
                        symbol=symbol,
                        source_bars=candles_by_symbol.get(symbol, []),
                        config=config,
                        generated_at_ms=generated_at_ms,
                        funding_rate=ticker.funding_rate if ticker is not None else None,
                        holding_amount=ticker.holding_amount if ticker is not None else None,
                    )
                except Exception as exc:
                    logger.warning("VPI compute failed for %s: %s", symbol, type(exc).__name__)
                    continue
                items.append(serialize_vpi_result(result))
            return items

        return build_vpi_snapshot_block(
            generated_at_ms=generated_at_ms,
            benchmarks=compute_symbols(config.benchmark_symbols),
            targets=compute_symbols(config.target_symbols),
        )
    except Exception as exc:
        logger.warning("VPI block build failed: %s", type(exc).__name__)
        return None


def aggregate_1m_to_5m(candles: Iterable[Candle1mRecord]) -> dict[str, list[CandleBar]]:
    grouped: dict[tuple[str, int], list[Candle1mRecord]] = {}
    for candle in sorted(candles, key=lambda item: (item.symbol, item.ts_ms)):
        bucket_ts = candle.ts_ms - (candle.ts_ms % FIVE_MINUTES_MS)
        grouped.setdefault((candle.symbol, bucket_ts), []).append(candle)

    bars_by_symbol: dict[str, list[CandleBar]] = {}
    for (symbol, bucket_ts), bucket in grouped.items():
        bars_by_symbol.setdefault(symbol, []).append(
            CandleBar(
                symbol=symbol,
                ts=bucket_ts,
                open=_decimal(bucket[0].open),
                high=_decimal(max(item.high for item in bucket)),
                low=_decimal(min(item.low for item in bucket)),
                close=_decimal(bucket[-1].close),
                base_vol=_decimal(sum(item.base_volume or 0.0 for item in bucket)),
                quote_vol=_decimal(
                    sum(
                        item.usdt_volume
                        if item.usdt_volume is not None
                        else item.quote_volume or 0.0
                        for item in bucket
                    )
                ),
            )
        )
    return bars_by_symbol


def _append_service_gap_risk_tags(
    rows: list[ScannerRow],
    *,
    store: ServiceSnapshotStore,
    symbols: list[str],
    window_start_ms: int,
    window_end_ms: int,
) -> None:
    audit = audit_service_gaps(
        store,
        symbols=symbols,
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
    )
    audit_by_symbol = {item.symbol: item for item in audit.symbols}
    for row in rows:
        item = audit_by_symbol.get(row.symbol)
        if item is None:
            continue
        tags = _risk_tags_for_gap_audit(item)
        if not tags:
            continue
        if item.classification == "TAIL_LAG" and row.data_quality == "OK":
            row.data_quality = "STALE"
            row.category = "NO_TRADE"
            row.priority_score = 0.0
            tags = ["DATA_NOT_OK", *tags]
        row.risk_tags = list(dict.fromkeys([*row.risk_tags, *tags]))
        row.reason = build_reason(row.label, row.risk_tags)
    rows.sort(key=lambda row: row.priority_score, reverse=True)


def _risk_tags_for_gap_audit(item: SymbolGapAudit) -> list[str]:
    tags: list[str] = []
    if item.classification == "REPAIRABLE_GAP":
        tags.append("DATA_GAP_REPAIRABLE")
    elif item.classification == "TAIL_LAG":
        tags.append("DATA_STALE")
    elif item.classification == "LISTING_OR_HISTORY_SHORT":
        tags.append("DATA_HISTORY_SHORT")
    if item.zero_volume_count > 0:
        tags.append("DATA_ZERO_VOLUME")
    return tags


def _service_gap_window_end_ms(
    candles: Iterable[Candle1mRecord],
    generated_window_end_ms: int,
) -> int:
    latest_candle_ts = max((candle.ts_ms for candle in candles), default=None)
    if latest_candle_ts is None:
        generated_bucket_ts = generated_window_end_ms - (generated_window_end_ms % FIVE_MINUTES_MS)
        return generated_bucket_ts - FIVE_MINUTES_MS
    latest_bucket_ts = latest_candle_ts - (latest_candle_ts % FIVE_MINUTES_MS)
    generated_bucket_ts = generated_window_end_ms - (generated_window_end_ms % FIVE_MINUTES_MS)
    return min(latest_bucket_ts, generated_bucket_ts) - FIVE_MINUTES_MS


def _required_1m_limit(config: FilterConfig) -> int:
    return max(config.candles.min_required_bars * 5, max(TIMEFRAME_BARS.values()) * 5)


def _required_1m_window_start_ms(generated_at_ms: int, required_1m_limit: int) -> int:
    latest_bucket_ms = generated_at_ms - (generated_at_ms % ONE_MINUTE_MS)
    return latest_bucket_ms - (required_1m_limit - 1) * ONE_MINUTE_MS


def _contract_from_instrument(item: InstrumentRecord) -> ContractInfo:
    return ContractInfo.model_validate(
        {
            "symbol": item.symbol,
            "productType": item.product_type,
            "baseCoin": item.base_coin,
            "quoteCoin": item.quote_coin,
            "symbolType": item.symbol_type,
            "symbolStatus": item.symbol_status,
            "maxLever": str(item.max_leverage) if item.max_leverage is not None else None,
            "isRwa": item.is_rwa,
        }
    )


def _ticker_from_latest(item: TickerLatestRecord) -> TickerInfo:
    return TickerInfo.model_validate(
        {
            "symbol": item.symbol,
            "ts": item.ts_ms,
            "lastPr": _optional_str(item.last_price),
            "high24h": _optional_str(item.high_24h),
            "low24h": _optional_str(item.low_24h),
            "change24h": _optional_str(item.change_24h),
            "usdtVolume": _optional_str(item.quote_volume_24h),
            "fundingRate": _optional_str(item.funding_rate),
            "holdingAmount": _optional_str(item.holding_amount),
        }
    )


def _optional_str(value: float | int | None) -> str | None:
    return str(value) if value is not None else None


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))
