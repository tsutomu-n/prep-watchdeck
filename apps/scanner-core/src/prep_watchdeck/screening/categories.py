from __future__ import annotations

from decimal import Decimal

from prep_watchdeck.config.filter_config import FilterConfig
from prep_watchdeck.models import ContractInfo, TickerInfo


def contract_is_valid(contract: ContractInfo) -> bool:
    return (
        contract.product_type == "USDT-FUTURES"
        and (contract.symbol_type or "").lower() == "perpetual"
        and (contract.symbol_status or "").lower() == "normal"
    )


def universe_symbols(
    config: FilterConfig,
    contracts: list[ContractInfo],
    tickers: list[TickerInfo],
) -> list[str]:
    contract_map = {contract.symbol: contract for contract in contracts}
    symbols: list[str] = []
    for ticker in tickers:
        contract = contract_map.get(ticker.symbol)
        if contract is None or not contract_is_valid(contract):
            continue
        if ticker.symbol in config.universe.exclude_symbols:
            continue
        if config.universe.exclude_rwa and contract.is_rwa is True:
            continue
        volume = ticker.usdt_volume_24h or Decimal("0")
        if not (
            Decimal(str(config.universe.min_24h_usdt_volume))
            <= volume
            <= Decimal(str(config.universe.max_24h_usdt_volume))
        ):
            continue
        symbols.append(ticker.symbol)
    return symbols


def choose_category(
    config: FilterConfig,
    *,
    label: str,
    priority_score: float,
    turnover_1h: float | None,
    roughness_15m: str,
    funding_bias: str,
    risk_tags: list[str],
    data_quality: str,
    contract_valid: bool,
) -> str:
    if (
        data_quality != "OK"
        or not contract_valid
        or (turnover_1h or 0.0) < config.turnover.min_turnover_1h_usdt
        or label in {"THIN_SPIKE", "TOO_ROUGH"}
        or len(risk_tags) >= config.category.risk_tags_for_no_trade
    ):
        return "NO_TRADE"
    if label == "LOW_REACTION" and priority_score < config.category.min_priority_score_for_caution:
        return "LOW_PRIORITY"
    if (
        label == "PRICE_LEADING_WEAK_VOLUME"
        or funding_bias == "OVERHEATED"
        or roughness_15m == "WARN"
        or len(risk_tags) >= 1
    ):
        return "CAUTION"
    if (
        label in {"VOLUME_CONFIRMED_UP", "VOLUME_CONFIRMED_DOWN", "VOLUME_LEADING"}
        and priority_score >= config.category.min_priority_score_for_watch
        and len(risk_tags) <= config.category.max_risk_tags_for_watch
    ):
        return "WATCH"
    return "LOW_PRIORITY"
