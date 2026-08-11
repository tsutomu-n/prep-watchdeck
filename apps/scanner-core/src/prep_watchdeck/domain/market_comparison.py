from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median

MARKET_COMPARISON_SOURCES = ("bitget", "hyperliquid", "bybit")
MARKET_COMPARISON_SYMBOLS = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL",
}
DEFAULT_MAX_AGE_MS = 10 * 60 * 1_000


@dataclass(frozen=True)
class MarketPriceObservation:
    source: str
    symbol: str
    source_symbol: str
    quote: str
    mark_price: float
    observed_at_ms: int
    source_at_ms: int | None = None


def build_market_comparison(
    observations: list[MarketPriceObservation],
    *,
    generated_at_ms: int,
    errors: dict[str, str] | None = None,
    max_age_ms: int = DEFAULT_MAX_AGE_MS,
) -> dict[str, object]:
    by_key = {(item.symbol, item.source): item for item in observations}
    source_errors = errors or {}
    symbols: list[dict[str, object]] = []

    for symbol in MARKET_COMPARISON_SYMBOLS:
        source_items: list[dict[str, object]] = []
        valid_prices: list[float] = []
        for source in MARKET_COMPARISON_SOURCES:
            observation = by_key.get((symbol, source))
            valid = observation is not None and _is_valid(observation, generated_at_ms, max_age_ms)
            if valid:
                assert observation is not None
                valid_prices.append(observation.mark_price)
                source_items.append(_serialize_observation(observation))
            else:
                source_items.append(
                    {
                        "source": source,
                        "status": "unavailable",
                        "sourceSymbol": None,
                        "quote": None,
                        "markPrice": None,
                        "observedAt": None,
                        "sourceAt": None,
                        "error": source_errors.get(source),
                    }
                )

        ready = len(valid_prices) == len(MARKET_COMPARISON_SOURCES)
        median_price = float(median(valid_prices)) if ready else None
        spread_pct = (
            (max(valid_prices) - min(valid_prices)) / median_price * 100
            if ready and median_price
            else None
        )
        symbols.append(
            {
                "symbol": symbol,
                "status": "ready" if ready else "incomplete",
                "coverage": {
                    "valid": len(valid_prices),
                    "required": len(MARKET_COMPARISON_SOURCES),
                },
                "medianMarkPrice": median_price,
                "spreadPct": spread_pct,
                "sources": source_items,
            }
        )

    return {
        "schemaVersion": 1,
        "mode": "mark_price_pilot_v1",
        "generatedAt": generated_at_ms,
        "refreshIntervalSeconds": 300,
        "symbols": symbols,
    }


def _is_valid(
    observation: MarketPriceObservation,
    generated_at_ms: int,
    max_age_ms: int,
) -> bool:
    age_ms = generated_at_ms - observation.observed_at_ms
    source_age_ms = (
        None if observation.source_at_ms is None else generated_at_ms - observation.source_at_ms
    )
    return (
        observation.source in MARKET_COMPARISON_SOURCES
        and observation.symbol in MARKET_COMPARISON_SYMBOLS
        and isfinite(observation.mark_price)
        and observation.mark_price > 0
        and 0 <= age_ms <= max_age_ms
        and (source_age_ms is None or 0 <= source_age_ms <= max_age_ms)
    )


def _serialize_observation(observation: MarketPriceObservation) -> dict[str, object]:
    return {
        "source": observation.source,
        "status": "ok",
        "sourceSymbol": observation.source_symbol,
        "quote": observation.quote,
        "markPrice": observation.mark_price,
        "observedAt": observation.observed_at_ms,
        "sourceAt": observation.source_at_ms,
        "error": None,
    }
