from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from prep_watchdeck.bitget.candles import (
    FIVE_MINUTES_MS,
    fetch_history_5m_candles,
    fetch_recent_history_candles,
    latest_closed_5m_bucket_ms,
)
from prep_watchdeck.bitget.client import BitgetPublicClient
from prep_watchdeck.bitget.contracts import fetch_contracts
from prep_watchdeck.bitget.tickers import fetch_all_tickers
from prep_watchdeck.config.filter_config import FilterConfig
from prep_watchdeck.domain.features.time_grid import normalize_5m_grid
from prep_watchdeck.features.btc_relative import classify_btc_relative_15m
from prep_watchdeck.features.funding import classify_funding
from prep_watchdeck.features.open_interest import classify_open_interest_change
from prep_watchdeck.features.price_change import change_pct_by_timeframe, direction_from_change
from prep_watchdeck.features.roughness import classify_roughness_15m
from prep_watchdeck.features.turnover import turnover_usdt_by_timeframe
from prep_watchdeck.features.volume_ratio import volume_ratio_by_timeframe
from prep_watchdeck.models import CandleBar, ContractInfo, ScannerRow, TickerInfo
from prep_watchdeck.screening.categories import choose_category, contract_is_valid, universe_symbols
from prep_watchdeck.screening.labels import choose_label
from prep_watchdeck.screening.priority import priority_score
from prep_watchdeck.screening.reasons import build_reason, build_risk_tags


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    generated_at_ms: int
    rows: list[ScannerRow]
    contracts: list[ContractInfo]
    tickers: list[TickerInfo]
    candles_by_symbol: dict[str, list[CandleBar]]
    chart_candles_by_symbol: dict[str, dict[str, list[CandleBar]]]
    candle_errors: dict[str, str]


def make_run_id(now: datetime | None = None) -> str:
    stamp = now or datetime.now(UTC)
    return stamp.strftime("%Y%m%dT%H%M%SZ")


def short_error(exc: Exception, max_length: int = 240) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if len(message) <= max_length:
        return message
    return message[: max_length - 3] + "..."


def build_scanner_rows(
    *,
    config: FilterConfig,
    contracts: list[ContractInfo],
    tickers: list[TickerInfo],
    candles_by_symbol: dict[str, list[CandleBar]],
    previous_oi_by_symbol: dict[str, float] | None = None,
) -> list[ScannerRow]:
    previous_oi_by_symbol = previous_oi_by_symbol or {}
    contract_map = {contract.symbol: contract for contract in contracts}
    ticker_map = {ticker.symbol: ticker for ticker in tickers}
    btc_bars = candles_by_symbol.get(config.universe.benchmark_symbol, [])
    btc_changes = change_pct_by_timeframe(btc_bars)
    rows: list[ScannerRow] = []

    for symbol in universe_symbols(config, contracts, tickers):
        bars = candles_by_symbol.get(symbol, [])
        ticker = ticker_map[symbol]
        contract = contract_map[symbol]
        if len(bars) < config.candles.min_required_bars or any(bar.close <= 0 for bar in bars):
            data_quality = "MISSING"
        else:
            data_quality = "OK"

        # Use data_quality config thresholds to refine (coverage, missing bars)
        if bars and data_quality == "OK":
            _, q = normalize_5m_grid(bars)
            dq = config.data_quality
            if (
                q.coverage_ratio < dq.min_coverage_ratio
                or q.missing_bar_count > dq.max_missing_bar_count
            ):
                data_quality = "PARTIAL"

        changes = change_pct_by_timeframe(bars)
        turnovers = turnover_usdt_by_timeframe(bars)
        volume_ratios = volume_ratio_by_timeframe(
            bars,
            config.volume.baseline_window_bars,
            config.volume.volume_ratio_floor_usdt,
        )
        roughness = classify_roughness_15m(
            bars,
            config.roughness.warn_move_concentration_15m,
            config.roughness.avoid_move_concentration_15m,
        )
        btc_relative = classify_btc_relative_15m(
            changes.get("15m"),
            btc_changes.get("15m"),
            config.btc_relative.linked_threshold_15m_pct,
            config.btc_relative.individual_threshold_15m_pct,
        )
        funding_bias = classify_funding(
            float(ticker.funding_rate) if ticker.funding_rate is not None else None,
            config.funding.warn_abs_funding_rate_pct,
            config.funding.avoid_abs_funding_rate_pct,
        )
        current_oi = float(ticker.holding_amount) if ticker.holding_amount is not None else None
        oi_state = classify_open_interest_change(
            current_oi,
            previous_oi_by_symbol.get(symbol),
            config.open_interest.increase_threshold_pct,
            config.open_interest.decrease_threshold_pct,
        )
        label = choose_label(
            config,
            changes.get("15m"),
            volume_ratios.get("15m"),
            turnovers.get("15m"),
            roughness,
        )
        initial_tags = build_risk_tags(
            label=label,
            roughness_15m=roughness,
            funding_bias=funding_bias,
            btc_relative_15m=btc_relative,
            data_quality=data_quality,
        )
        score = priority_score(
            change_15m=changes.get("15m"),
            volume_ratio_15m=volume_ratios.get("15m"),
            turnover_1h=turnovers.get("1h"),
            min_turnover_1h=config.turnover.min_turnover_1h_usdt,
            btc_relative_15m=btc_relative,
            open_interest_state=oi_state,
            data_quality=data_quality,
            risk_tags=initial_tags,
        )
        category = choose_category(
            config,
            label=label,
            priority_score=score,
            turnover_1h=turnovers.get("1h"),
            roughness_15m=roughness,
            funding_bias=funding_bias,
            risk_tags=initial_tags,
            data_quality=data_quality,
            contract_valid=contract_is_valid(contract),
        )
        if not bars:
            continue
        rows.append(
            ScannerRow(
                symbol=symbol,
                ts=bars[-1].ts,
                close=bars[-1].close,
                category=category,  # type: ignore[arg-type]
                direction=direction_from_change(
                    changes.get("15m"),
                    config.price_change.surge_15m_pct,
                    config.price_change.move_15m_pct,
                ),
                label=label,
                priority_score=score,
                change_pct_by_tf=changes,
                turnover_usdt_by_tf=turnovers,
                volume_ratio_by_tf=volume_ratios,
                roughness_15m=roughness,
                btc_relative_15m=btc_relative,
                funding_bias=funding_bias,
                open_interest_state=oi_state,
                reason=build_reason(label, initial_tags),
                risk_tags=initial_tags,
                data_quality=data_quality,
            )
        )
    return sorted(rows, key=lambda row: row.priority_score, reverse=True)


async def run_live_pipeline(
    config: FilterConfig,
    max_symbols: int | None = None,
    previous_oi_by_symbol: dict[str, float] | None = None,
    candle_concurrency: int = 8,
    run_id: str | None = None,
) -> PipelineResult:
    generated_at = int(time.time() * 1000)
    run_id = run_id or make_run_id()
    async with BitgetPublicClient() as client:
        contracts = await fetch_contracts(client, config.universe.product_type)
        tickers = await fetch_all_tickers(client, config.universe.product_type)
        symbols = universe_symbols(config, contracts, tickers)
        if max_symbols is not None:
            symbols = symbols[:max_symbols]
        fetch_symbols = list(dict.fromkeys([config.universe.benchmark_symbol, *symbols]))
        candles_by_symbol: dict[str, list[CandleBar]] = {}
        candle_errors: dict[str, str] = {}
        semaphore = asyncio.Semaphore(max(1, candle_concurrency))

        async def fetch_symbol(symbol: str) -> tuple[str, list[CandleBar], str | None]:
            async with semaphore:
                try:
                    end_ms = latest_closed_5m_bucket_ms()
                    start_ms = end_ms - FIVE_MINUTES_MS * (config.candles.min_required_bars - 1)
                    return (
                        symbol,
                        await fetch_history_5m_candles(
                            client,
                            symbol,
                            config.universe.product_type,
                            start_ms=start_ms,
                            end_ms=end_ms,
                        ),
                        None,
                    )
                except Exception as exc:
                    return symbol, [], short_error(exc)

        for symbol, bars, error in await asyncio.gather(
            *(fetch_symbol(symbol) for symbol in fetch_symbols)
        ):
            if error is None:
                candles_by_symbol[symbol] = bars
            else:
                candle_errors[symbol] = error
        rows = build_scanner_rows(
            config=config,
            contracts=contracts,
            tickers=tickers,
            candles_by_symbol=candles_by_symbol,
            previous_oi_by_symbol=previous_oi_by_symbol,
        )
        chart_candles_by_symbol = await fetch_chart_candles(
            client=client,
            symbols=[row.symbol for row in rows],
            product_type=config.universe.product_type,
            candle_concurrency=candle_concurrency,
        )
    return PipelineResult(
        run_id=run_id,
        generated_at_ms=generated_at,
        rows=rows,
        contracts=contracts,
        tickers=tickers,
        candles_by_symbol=candles_by_symbol,
        chart_candles_by_symbol=chart_candles_by_symbol,
        candle_errors=candle_errors,
    )


async def fetch_chart_candles(
    *,
    client: BitgetPublicClient,
    symbols: list[str],
    product_type: str,
    candle_concurrency: int,
) -> dict[str, dict[str, list[CandleBar]]]:
    granularity_by_timeframe = {
        "5m": "5m",
        "15m": "15m",
        "1h": "1H",
        "4h": "4H",
        "24h": "1Dutc",
        "74h": "3Dutc",
    }
    semaphore = asyncio.Semaphore(max(1, candle_concurrency))
    result: dict[str, dict[str, list[CandleBar]]] = {}

    async def fetch(
        symbol: str,
        timeframe: str,
        granularity: str,
    ) -> tuple[str, str, list[CandleBar]]:
        async with semaphore:
            try:
                return (
                    symbol,
                    timeframe,
                    await fetch_recent_history_candles(
                        client,
                        symbol,
                        product_type,
                        granularity=granularity,
                        limit=128,
                    ),
                )
            except Exception:
                return symbol, timeframe, []

    tasks = [
        fetch(symbol, timeframe, granularity)
        for symbol in symbols
        for timeframe, granularity in granularity_by_timeframe.items()
    ]
    for symbol, timeframe, bars in await asyncio.gather(*tasks):
        result.setdefault(symbol, {})[timeframe] = bars
    return result
