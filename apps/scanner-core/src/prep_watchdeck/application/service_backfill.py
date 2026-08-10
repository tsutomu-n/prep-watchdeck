from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from threading import RLock
from typing import Protocol

from prep_watchdeck.domain.service_models import (
    BackfillProgress,
    BackfillProgressStatus,
    BackfillResult,
    BackfillSymbolResult,
    Candle1mRecord,
)
from prep_watchdeck.models import CandleBar


class CandleHistoryFetcher(Protocol):
    def __call__(
        self,
        symbol: str,
        product_type: str,
        granularity: str,
        limit: int,
    ) -> Awaitable[list[CandleBar]]:
        """Fetch recent closed candles."""


class Candle1mStore(Protocol):
    def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
        """Persist canonical 1m candle rows."""


async def backfill_1m_candles(
    *,
    store: Candle1mStore,
    fetcher: CandleHistoryFetcher,
    symbols: Iterable[str],
    product_type: str,
    limit: int,
    concurrency: int = 8,
    on_symbol_result: Callable[[BackfillSymbolResult], None] | None = None,
) -> BackfillResult:
    normalized_symbols = normalize_symbols(symbols)
    if not normalized_symbols:
        raise ValueError("at least one symbol is required")
    if limit < 1:
        raise ValueError("limit must be positive")
    if concurrency < 1:
        raise ValueError("concurrency must be positive")

    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_symbol(symbol: str) -> tuple[BackfillSymbolResult, list[Candle1mRecord]]:
        async with semaphore:
            return await _fetch_symbol(fetcher, symbol, product_type, limit)

    tasks = [asyncio.create_task(fetch_symbol(symbol)) for symbol in normalized_symbols]
    symbol_results: list[BackfillSymbolResult] = []
    try:
        for task in asyncio.as_completed(tasks):
            symbol_result, records = await task
            store.upsert_candles_1m(records)
            if on_symbol_result is not None:
                on_symbol_result(symbol_result)
            symbol_results.append(symbol_result)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    order = {symbol: index for index, symbol in enumerate(normalized_symbols)}
    symbol_results = sorted(symbol_results, key=lambda item: order[item.symbol])

    return BackfillResult(
        product_type=product_type,
        granularity="1m",
        requested_symbols=normalized_symbols,
        saved_count=sum(item.saved_count for item in symbol_results),
        symbols=symbol_results,
    )


async def _fetch_symbol(
    fetcher: CandleHistoryFetcher,
    symbol: str,
    product_type: str,
    limit: int,
) -> tuple[BackfillSymbolResult, list[Candle1mRecord]]:
    try:
        bars = await fetcher(symbol, product_type, "1m", limit)
        records = [_record_from_bar(bar) for bar in bars]
        return (
            BackfillSymbolResult(
                symbol=symbol,
                fetched_count=len(bars),
                saved_count=len(records),
                latest_ts_ms=max((bar.ts for bar in bars), default=None),
            ),
            records,
        )
    except Exception as exc:
        return (
            BackfillSymbolResult(
                symbol=symbol,
                fetched_count=0,
                saved_count=0,
                error=f"{type(exc).__name__}: {exc}",
            ),
            [],
        )


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    return sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})


class BackfillProgressTracker:
    def __init__(
        self,
        symbols: Iterable[str],
        *,
        limit: int,
        concurrency: int,
        started_at_ms: int | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        self._requested_symbols = len(normalize_symbols(symbols))
        self._limit = limit
        self._concurrency = concurrency
        self._started_at_ms = _now_ms() if started_at_ms is None else started_at_ms
        self._updated_at_ms = self._started_at_ms
        self._finished_at_ms: int | None = None
        self._status: BackfillProgressStatus = "running"
        self._completed_symbols = 0
        self._saved_count = 0
        self._error_count = 0
        self._latest_error: str | None = None
        self._lock = RLock()

    def record_symbol(self, result: BackfillSymbolResult) -> None:
        with self._lock:
            self._completed_symbols += 1
            self._saved_count += result.saved_count
            if result.error is not None:
                self._error_count += 1
                self._latest_error = f"{result.symbol}: {result.error}"
            self._updated_at_ms = _now_ms()

    def mark_completed(self) -> None:
        self._mark_finished("completed")

    def mark_failed(self, error: str) -> None:
        with self._lock:
            self._status = "failed"
            self._latest_error = error
            self._finished_at_ms = _now_ms()
            self._updated_at_ms = self._finished_at_ms

    def mark_cancelled(self) -> None:
        self._mark_finished("cancelled")

    def snapshot(self) -> BackfillProgress:
        with self._lock:
            return BackfillProgress(
                status=self._status,
                requested_symbols=self._requested_symbols,
                completed_symbols=self._completed_symbols,
                saved_count=self._saved_count,
                error_count=self._error_count,
                limit=self._limit,
                concurrency=self._concurrency,
                started_at_ms=self._started_at_ms,
                updated_at_ms=self._updated_at_ms,
                finished_at_ms=self._finished_at_ms,
                latest_error=self._latest_error,
            )

    def _mark_finished(self, status: BackfillProgressStatus) -> None:
        with self._lock:
            self._status = status
            self._finished_at_ms = _now_ms()
            self._updated_at_ms = self._finished_at_ms


def _now_ms() -> int:
    return int(time.time() * 1000)


def _record_from_bar(bar: CandleBar) -> Candle1mRecord:
    quote_volume = float(bar.quote_vol)
    return Candle1mRecord(
        symbol=bar.symbol.strip().upper(),
        ts_ms=bar.ts,
        open=float(bar.open),
        high=float(bar.high),
        low=float(bar.low),
        close=float(bar.close),
        base_volume=float(bar.base_vol),
        quote_volume=quote_volume,
        usdt_volume=quote_volume,
        is_closed=True,
        source="rest-history",
        updated_at_ms=bar.ts,
    )
