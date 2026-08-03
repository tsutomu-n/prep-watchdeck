from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from prep_watchdeck.config.templates import load_template
from prep_watchdeck.constants import SCHEMA_VERSION
from prep_watchdeck.domain.dto import (
    ChartBarDTO,
    ScannerRowDTO,
    SnapshotDTO,
    SnapshotSourceDTO,
    SparklineDTO,
)
from prep_watchdeck.domain.enums import DataSource, SnapshotStatus
from prep_watchdeck.domain.features.long_horizon import compute_74h_features
from prep_watchdeck.domain.features.time_grid import normalize_5m_grid
from prep_watchdeck.domain.screening.rankings import build_rankings
from prep_watchdeck.models import CandleBar, ContractInfo, ScannerRow, TickerInfo
from prep_watchdeck.screening.pipeline import PipelineResult, run_live_pipeline
from prep_watchdeck.settings import Settings

if TYPE_CHECKING:
    from prep_watchdeck.config.filter_config import FilterConfig, UserRuleConfig


class BitgetLiveProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.latest_candles_by_symbol: dict[str, list[CandleBar]] = {}
        self.latest_chart_candles_by_symbol: dict[str, dict[str, list[CandleBar]]] = {}

    def build_snapshot(self, *, template: str, fixture_set: str | None = None) -> SnapshotDTO:
        config = load_template(self.settings.config_dir, template)
        result = asyncio.run(
            run_live_pipeline(
                config,
                max_symbols=self.settings.live_max_symbols,
                candle_concurrency=self.settings.live_candle_concurrency,
            )
        )
        self.latest_candles_by_symbol = result.candles_by_symbol
        self.latest_chart_candles_by_symbol = result.chart_candles_by_symbol
        return snapshot_from_pipeline(
            result,
            template=template,
            config=config,
            product_type=config.universe.product_type,
        )


def snapshot_from_pipeline(
    result: PipelineResult,
    *,
    template: str,
    config: FilterConfig | None = None,
    product_type: str,
    include_chart_bars: bool = True,
    sparkline_points_limit: int = 5,
) -> SnapshotDTO:
    contract_map = {contract.symbol: contract for contract in result.contracts}
    ticker_map = {ticker.symbol: ticker for ticker in result.tickers}
    user_rule = config.user_rule if config is not None else None
    rows = [
        _row_to_dto(
            row,
            contract=contract_map.get(row.symbol),
            ticker=ticker_map.get(row.symbol),
            bars=result.candles_by_symbol.get(row.symbol, []),
            chart_bars_by_timeframe=result.chart_candles_by_symbol.get(row.symbol, {}),
            user_rule=user_rule,
            include_chart_bars=include_chart_bars,
            sparkline_points_limit=sparkline_points_limit,
        )
        for row in result.rows
    ]
    counts = {"WATCH": 0, "CAUTION": 0, "NO_TRADE": 0, "LOW_PRIORITY": 0}
    for row in rows:
        counts[row.category.value] += 1

    # config_hash is "template:vX" (lightweight versioned form, not content hash)
    config_hash = template
    if config is not None:
        config_hash = f"{template}:v{config.version}"

    return SnapshotDTO(
        schema_version=SCHEMA_VERSION,
        engine_version="0.1.0",
        feature_version="2",
        ruleset_version="2",
        config_hash=config_hash,
        run_id=result.run_id,
        generated_at=result.generated_at_ms,
        data_as_of=max((row.ts for row in rows), default=result.generated_at_ms),
        snapshot_status=SnapshotStatus.PARTIAL if result.candle_errors else SnapshotStatus.OK,
        source=SnapshotSourceDTO(
            exchange="bitget",
            product_type=product_type,
            template_name=template,
            data_source=DataSource.LIVE,
        ),
        summary={
            "counts": counts,
            "contracts": len(result.contracts),
            "tickers": len(result.tickers),
            "candleErrors": result.candle_errors,
        },
        rankings=build_rankings(
            rows,
            top_n=config.ranking.top_n if config is not None else 10,
        ),
        rows=rows,
    )


def _row_to_dto(
    row: ScannerRow,
    *,
    contract: ContractInfo | None,
    ticker: TickerInfo | None,
    bars: list[CandleBar],
    chart_bars_by_timeframe: dict[str, list[CandleBar]] | None = None,
    user_rule: UserRuleConfig | None = None,
    include_chart_bars: bool = True,
    sparkline_points_limit: int = 5,
) -> ScannerRowDTO:
    _grid, quality = normalize_5m_grid(bars)
    range_24h = _range_24h_from_ticker(ticker, fallback_close=float(row.close))

    if user_rule is not None:
        long_horizon = compute_74h_features(
            bars,
            price_threshold_abs_pct=user_rule.price_74h_abs_pct,
            volume_increase_threshold_pct=user_rule.volume_74h_min_increase_pct,
        )
    else:
        long_horizon = compute_74h_features(bars)
    points_limit = min(max(sparkline_points_limit, 0), 16)
    sparkline: SparklineDTO = {
        "tf": "5m",
        "points": [float(bar.close) for bar in bars[-points_limit:]] if points_limit else [],
    }
    if include_chart_bars:
        sparkline["bars"] = [_chart_bar_payload(bar) for bar in bars[-16:]]
        sparkline["timeframes"] = {
            timeframe: [_chart_bar_payload(bar) for bar in chart_bars[-16:]]
            for timeframe, chart_bars in (chart_bars_by_timeframe or {}).items()
        }

    return ScannerRowDTO(
        symbol=row.symbol,
        ts=row.ts,
        last_price=float(ticker.last_price) if ticker and ticker.last_price is not None else None,
        analysis_price=float(row.close),
        max_leverage=(
            float(contract.max_lever) if contract and contract.max_lever is not None else None
        ),
        min_trade_usdt=(
            float(contract.min_trade_usdt)
            if contract and contract.min_trade_usdt is not None
            else None
        ),
        category=row.category,
        label=row.label,
        direction=row.direction,
        attention_score=row.priority_score,
        change_pct_by_tf=row.change_pct_by_tf,
        turnover_usdt_by_tf=row.turnover_usdt_by_tf,
        volume_ratio_by_tf=row.volume_ratio_by_tf,
        range_24h_high=range_24h["high"],
        range_24h_low=range_24h["low"],
        range_24h_position_pct=range_24h["position_pct"],
        range_24h_pct=range_24h["range_pct"],
        price_change_74h_pct=long_horizon.price_change_74h_pct,
        turnover_current_24h_usdt=long_horizon.turnover_current_24h_usdt,
        turnover_24h_ending_74h_ago_usdt=long_horizon.turnover_24h_ending_74h_ago_usdt,
        volume_change_74h_24h_pct=long_horizon.volume_change_74h_24h_pct,
        user_rule_74h_matched=long_horizon.user_rule_74h_matched,
        roughness_15m=row.roughness_15m,
        btc_relative_15m=row.btc_relative_15m,
        funding_bias=row.funding_bias,
        open_interest_state=row.open_interest_state,
        data_quality=row.data_quality,
        coverage_ratio=quality.coverage_ratio,
        missing_bar_count=quality.missing_bar_count,
        zero_volume_bar_ratio=quality.zero_volume_bar_ratio,
        reason_codes=[row.label],
        risk_tag_codes=row.risk_tags,
        sparkline=sparkline,
    )


def _range_24h_from_ticker(
    ticker: TickerInfo | None,
    *,
    fallback_close: float,
) -> dict[str, float | None]:
    high = float(ticker.high_24h) if ticker and ticker.high_24h is not None else None
    low = float(ticker.low_24h) if ticker and ticker.low_24h is not None else None
    close = float(ticker.last_price) if ticker and ticker.last_price is not None else fallback_close
    if high is None or low is None or high <= 0 or low <= 0 or close <= 0 or high < low:
        return {"high": high, "low": low, "position_pct": None, "range_pct": None}
    if high == low:
        return {"high": high, "low": low, "position_pct": 50.0, "range_pct": 0.0}
    position_pct = max(0.0, min(100.0, ((close - low) / (high - low)) * 100.0))
    return {
        "high": high,
        "low": low,
        "position_pct": round(position_pct, 2),
        "range_pct": round((high / low - 1.0) * 100.0, 2),
    }


def _chart_bar_payload(bar: CandleBar) -> ChartBarDTO:
    return {
        "ts": bar.ts,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "quoteVolume": float(bar.quote_vol),
    }
