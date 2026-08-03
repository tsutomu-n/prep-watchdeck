from __future__ import annotations

import time
from decimal import Decimal

from prep_watchdeck.bitget.client import BitgetPublicClient
from prep_watchdeck.models import CandleBar

FIVE_MINUTES_MS = 300_000
HISTORY_CANDLES_LIMIT = 200
MAX_HISTORY_RANGE_MS = 90 * 24 * 60 * 60 * 1000
GRANULARITY_MS = {
    "1m": 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1H": 60 * 60 * 1000,
    "4H": 4 * 60 * 60 * 1000,
    "1Dutc": 24 * 60 * 60 * 1000,
    "3Dutc": 3 * 24 * 60 * 60 * 1000,
}


def parse_candle_row(symbol: str, row: list[str | int | float]) -> CandleBar:
    return CandleBar(
        symbol=symbol,
        ts=int(row[0]),
        open=Decimal(str(row[1])),
        high=Decimal(str(row[2])),
        low=Decimal(str(row[3])),
        close=Decimal(str(row[4])),
        base_vol=Decimal(str(row[5])),
        quote_vol=Decimal(str(row[6])),
    )


def parse_candle_rows(symbol: str, rows: list[list[str | int | float]]) -> list[CandleBar]:
    return sorted((parse_candle_row(symbol, row) for row in rows), key=lambda bar: bar.ts)


def latest_closed_5m_bucket_ms(now_ms: int | None = None) -> int:
    current = int(time.time() * 1000) if now_ms is None else now_ms
    return current // FIVE_MINUTES_MS * FIVE_MINUTES_MS - FIVE_MINUTES_MS


def align_5m_ms(ts_ms: int) -> int:
    return ts_ms // FIVE_MINUTES_MS * FIVE_MINUTES_MS


async def fetch_latest_5m_candles(
    client: BitgetPublicClient,
    symbol: str,
    product_type: str,
    limit: int = 1000,
    exclude_open_candle: bool = True,
) -> list[CandleBar]:
    payload = await client.get_json(
        "/api/v2/mix/market/candles",
        {
            "symbol": symbol,
            "productType": product_type,
            "granularity": "5m",
            "limit": limit,
        },
    )
    current_bucket = int(time.time() * 1000) // FIVE_MINUTES_MS * FIVE_MINUTES_MS
    bars = parse_candle_rows(symbol, payload.get("data", []))
    if exclude_open_candle:
        bars = [bar for bar in bars if bar.ts < current_bucket]
    return bars


async def fetch_latest_candles(
    client: BitgetPublicClient,
    symbol: str,
    product_type: str,
    *,
    granularity: str,
    limit: int,
    exclude_open_candle: bool = True,
) -> list[CandleBar]:
    payload = await client.get_json(
        "/api/v2/mix/market/candles",
        {
            "symbol": symbol,
            "productType": product_type,
            "granularity": granularity,
            "limit": limit,
        },
    )
    bars = parse_candle_rows(symbol, payload.get("data", []))
    granularity_ms = GRANULARITY_MS.get(granularity)
    if exclude_open_candle and granularity_ms is not None:
        current_bucket = int(time.time() * 1000) // granularity_ms * granularity_ms
        bars = [bar for bar in bars if bar.ts < current_bucket]
    return bars[-limit:]


async def fetch_recent_history_candles(
    client: BitgetPublicClient,
    symbol: str,
    product_type: str,
    *,
    granularity: str,
    limit: int,
) -> list[CandleBar]:
    granularity_ms = GRANULARITY_MS[granularity]
    max_bars_per_request = max(
        1,
        min(HISTORY_CANDLES_LIMIT, MAX_HISTORY_RANGE_MS // granularity_ms),
    )
    max_attempts = max(1, (limit + max_bars_per_request - 1) // max_bars_per_request + 2)
    bars_by_ts: dict[int, CandleBar] = {}
    end_ms = int(time.time() * 1000) // granularity_ms * granularity_ms
    attempts = 0

    while len(bars_by_ts) < limit and attempts < max_attempts:
        attempts += 1
        request_limit = min(max_bars_per_request, limit - len(bars_by_ts))
        start_ms = end_ms - granularity_ms * request_limit
        payload = await client.get_json(
            "/api/v2/mix/market/history-candles",
            {
                "symbol": symbol,
                "productType": product_type,
                "granularity": granularity,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": request_limit,
            },
        )
        chunk_bars = parse_candle_rows(symbol, payload.get("data", []))
        if not chunk_bars:
            break
        for bar in chunk_bars:
            bars_by_ts[bar.ts] = bar
        oldest_ts = min(bar.ts for bar in chunk_bars)
        # Bitget history-candles returns rows before endTime; oldest_ts keeps pages contiguous.
        next_end_ms = oldest_ts
        if next_end_ms >= end_ms:
            break
        end_ms = next_end_ms

    return sorted(bars_by_ts.values(), key=lambda bar: bar.ts)[-limit:]


async def fetch_history_5m_candles(
    client: BitgetPublicClient,
    symbol: str,
    product_type: str,
    start_ms: int,
    end_ms: int,
    limit: int = HISTORY_CANDLES_LIMIT,
) -> list[CandleBar]:
    request_limit = min(max(limit, 1), HISTORY_CANDLES_LIMIT)
    cursor = align_5m_ms(start_ms)
    end = align_5m_ms(end_ms)
    bars_by_ts: dict[int, CandleBar] = {}
    while cursor <= end:
        chunk_end = min(end, cursor + FIVE_MINUTES_MS * (request_limit - 1))
        payload = await client.get_json(
            "/api/v2/mix/market/history-candles",
            {
                "symbol": symbol,
                "productType": product_type,
                "granularity": "5m",
                "startTime": cursor,
                "endTime": chunk_end + FIVE_MINUTES_MS,
                "limit": request_limit,
            },
        )
        chunk_bars = parse_candle_rows(symbol, payload.get("data", []))
        for bar in chunk_bars:
            if cursor <= bar.ts <= end:
                bars_by_ts[bar.ts] = bar
        if chunk_bars:
            next_cursor = max(bar.ts for bar in chunk_bars) + FIVE_MINUTES_MS
            cursor = next_cursor if next_cursor > cursor else chunk_end + FIVE_MINUTES_MS
        else:
            cursor = chunk_end + FIVE_MINUTES_MS
    return sorted(bars_by_ts.values(), key=lambda bar: bar.ts)


async def fetch_history_candles_range(
    client: BitgetPublicClient,
    symbol: str,
    product_type: str,
    *,
    granularity: str,
    start_ms: int,
    end_ms: int,
    limit: int = HISTORY_CANDLES_LIMIT,
) -> list[CandleBar]:
    granularity_ms = GRANULARITY_MS[granularity]
    request_limit = min(max(limit, 1), HISTORY_CANDLES_LIMIT)
    cursor = start_ms - (start_ms % granularity_ms)
    end = end_ms - (end_ms % granularity_ms)
    bars_by_ts: dict[int, CandleBar] = {}
    while cursor <= end:
        chunk_end = min(end, cursor + granularity_ms * (request_limit - 1))
        payload = await client.get_json(
            "/api/v2/mix/market/history-candles",
            {
                "symbol": symbol,
                "productType": product_type,
                "granularity": granularity,
                "startTime": cursor,
                "endTime": chunk_end + granularity_ms,
                "limit": request_limit,
            },
        )
        chunk_bars = parse_candle_rows(symbol, payload.get("data", []))
        for bar in chunk_bars:
            if cursor <= bar.ts <= end:
                bars_by_ts[bar.ts] = bar
        if chunk_bars:
            next_cursor = max(bar.ts for bar in chunk_bars) + granularity_ms
            cursor = next_cursor if next_cursor > cursor else chunk_end + granularity_ms
        else:
            cursor = chunk_end + granularity_ms
    return sorted(bars_by_ts.values(), key=lambda bar: bar.ts)
