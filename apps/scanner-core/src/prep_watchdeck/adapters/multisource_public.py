from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import pybotters

from prep_watchdeck.domain.market_comparison import (
    MARKET_COMPARISON_SYMBOLS,
    MarketPriceObservation,
)

BITGET_PRICE_URL = "https://api.bitget.com/api/v2/mix/market/symbol-price"
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


async def fetch_market_comparison_observations() -> tuple[
    list[MarketPriceObservation], dict[str, str]
]:
    async with pybotters.Client() as client:
        tasks: list[tuple[str, Callable[[], Awaitable[list[MarketPriceObservation]]]]] = [
            ("bitget", lambda: _fetch_bitget(client)),
            ("hyperliquid", lambda: _fetch_hyperliquid(client)),
            ("bybit", lambda: _fetch_bybit(client)),
        ]
        results = await asyncio.gather(
            *(factory() for _, factory in tasks),
            return_exceptions=True,
        )

    observations: list[MarketPriceObservation] = []
    errors: dict[str, str] = {}
    for (source, _), result in zip(tasks, results, strict=True):
        if isinstance(result, BaseException):
            errors[source] = type(result).__name__
        else:
            observations.extend(result)
    return observations, errors


async def _fetch_bitget(client: pybotters.Client) -> list[MarketPriceObservation]:
    observations: list[MarketPriceObservation] = []
    for symbol in MARKET_COMPARISON_SYMBOLS:
        async with client.get(
            BITGET_PRICE_URL,
            params={"productType": "USDT-FUTURES", "symbol": symbol},
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        if payload.get("code") != "00000" or not payload.get("data"):
            raise ValueError("unexpected Bitget response")
        item = payload["data"][0]
        observed_at_ms = _now_ms()
        observations.append(
            MarketPriceObservation(
                source="bitget",
                symbol=symbol,
                source_symbol=str(item["symbol"]),
                quote="USDT",
                mark_price=_positive_float(item["markPrice"]),
                observed_at_ms=observed_at_ms,
                source_at_ms=_optional_int(item.get("ts")),
            )
        )
    return observations


async def _fetch_bybit(client: pybotters.Client) -> list[MarketPriceObservation]:
    observations: list[MarketPriceObservation] = []
    for symbol in MARKET_COMPARISON_SYMBOLS:
        async with client.get(
            BYBIT_TICKERS_URL,
            params={"category": "linear", "symbol": symbol},
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        items = payload.get("result", {}).get("list", [])
        if payload.get("retCode") != 0 or not items:
            raise ValueError("unexpected Bybit response")
        item = items[0]
        observations.append(
            MarketPriceObservation(
                source="bybit",
                symbol=symbol,
                source_symbol=str(item["symbol"]),
                quote="USDT",
                mark_price=_positive_float(item["markPrice"]),
                observed_at_ms=_now_ms(),
                source_at_ms=_optional_int(payload.get("time")),
            )
        )
    return observations


async def _fetch_hyperliquid(client: pybotters.Client) -> list[MarketPriceObservation]:
    async with client.post(
        HYPERLIQUID_INFO_URL,
        data={"type": "metaAndAssetCtxs"},
    ) as response:
        response.raise_for_status()
        payload = await response.json()
    if not isinstance(payload, list) or len(payload) != 2:
        raise ValueError("unexpected Hyperliquid response")
    meta, contexts = payload
    by_name = {
        asset["name"]: context for asset, context in zip(meta["universe"], contexts, strict=True)
    }
    observed_at_ms = _now_ms()
    return [
        MarketPriceObservation(
            source="hyperliquid",
            symbol=symbol,
            source_symbol=coin,
            quote="USD",
            mark_price=_positive_float(by_name[coin]["markPx"]),
            observed_at_ms=observed_at_ms,
            source_at_ms=None,
        )
        for symbol, coin in MARKET_COMPARISON_SYMBOLS.items()
    ]


def _positive_float(value: Any) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError("mark price must be positive")
    return number


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _now_ms() -> int:
    return int(time.time() * 1_000)
