from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from prep_watchdeck.application.service_backfill import (
    CandleHistoryFetcher,
    normalize_symbols,
)
from prep_watchdeck.domain.service_models import (
    BackfillProgressStatus,
    BackfillResult,
    BackfillSymbolResult,
    Candle1mRecord,
    DeepBackfillProgress,
)


class DeepBackfillStore(Protocol):
    def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
        """Persist canonical 1m candle rows."""

    def candle_1m_count_by_symbol(self, symbols: Iterable[str]) -> dict[str, int]:
        """Return current persisted 1m candle counts by symbol."""

    def candle_1m_count_since_by_symbol(
        self,
        symbols: Iterable[str],
        start_ts_ms: int,
    ) -> dict[str, int]:
        """Return persisted 1m candle counts by symbol inside the recent target window."""


@dataclass(frozen=True)
class DeepBackfillSelection:
    completed_symbols: list[str]
    pending_symbols: list[str]
    ready_symbols: list[str]
    batch_symbols: list[str]
    next_retry_at: float | None


def select_deep_backfill_batch(
    *,
    symbols: Iterable[str],
    counts_by_symbol: dict[str, int],
    target_limit: int,
    settled_symbols: set[str],
    retry_after_by_symbol: dict[str, float],
    now_seconds: float,
    batch_size: int,
) -> DeepBackfillSelection:
    normalized_symbols = normalize_symbols(symbols)
    if target_limit < 1:
        raise ValueError("target_limit must be positive")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    completed_symbols = [
        symbol
        for symbol in normalized_symbols
        if counts_by_symbol.get(symbol, 0) >= target_limit or symbol in settled_symbols
    ]
    pending_symbols = [symbol for symbol in normalized_symbols if symbol not in completed_symbols]
    ready_symbols = [
        symbol
        for symbol in pending_symbols
        if retry_after_by_symbol.get(symbol, 0.0) <= now_seconds
    ]
    retry_times = [
        retry_after_by_symbol[symbol]
        for symbol in pending_symbols
        if retry_after_by_symbol.get(symbol, 0.0) > now_seconds
    ]
    return DeepBackfillSelection(
        completed_symbols=completed_symbols,
        pending_symbols=pending_symbols,
        ready_symbols=ready_symbols,
        batch_symbols=ready_symbols[:batch_size],
        next_retry_at=min(retry_times) if retry_times else None,
    )


class DeepBackfillProgressTracker:
    def __init__(
        self,
        symbols: Iterable[str],
        *,
        target_limit: int,
        batch_size: int,
        concurrency: int,
        rate_limit_per_second: float,
        cooldown_seconds: float,
        retry_delay_seconds: float,
        started_at_ms: int | None = None,
    ) -> None:
        if target_limit < 1:
            raise ValueError("target_limit must be positive")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        if rate_limit_per_second <= 0:
            raise ValueError("rate_limit_per_second must be positive")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")

        self._target_symbols = len(normalize_symbols(symbols))
        self._target_limit = target_limit
        self._batch_size = batch_size
        self._concurrency = concurrency
        self._rate_limit_per_second = rate_limit_per_second
        self._cooldown_seconds = cooldown_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._started_at_ms = _now_ms() if started_at_ms is None else started_at_ms
        self._updated_at_ms = self._started_at_ms
        self._finished_at_ms: int | None = None
        self._status: BackfillProgressStatus = "running"
        self._completed_symbols = 0
        self._pending_symbols = self._target_symbols
        self._saved_count = 0
        self._error_count = 0
        self._cycle_count = 0
        self._current_symbols: list[str] = []
        self._latest_error: str | None = None
        self._lock = RLock()

    def record_cycle_start(
        self,
        symbols: Iterable[str],
        *,
        completed_symbols: int,
        pending_symbols: int,
    ) -> None:
        with self._lock:
            self._cycle_count += 1
            self._current_symbols = normalize_symbols(symbols)
            self._completed_symbols = completed_symbols
            self._pending_symbols = pending_symbols
            self._updated_at_ms = _now_ms()

    def record_symbol(self, result: BackfillSymbolResult) -> None:
        with self._lock:
            self._saved_count += result.saved_count
            if result.error is not None:
                self._error_count += 1
                self._latest_error = f"{result.symbol}: {result.error}"
            self._updated_at_ms = _now_ms()

    def update_coverage(
        self,
        *,
        completed_symbols: int,
        pending_symbols: int,
        current_symbols: Iterable[str] | None = None,
    ) -> None:
        with self._lock:
            self._completed_symbols = completed_symbols
            self._pending_symbols = pending_symbols
            if current_symbols is not None:
                self._current_symbols = normalize_symbols(current_symbols)
            self._updated_at_ms = _now_ms()

    def mark_completed(self) -> None:
        self._mark_finished("completed")

    def mark_failed(self, error: str) -> None:
        with self._lock:
            self._status = "failed"
            self._latest_error = error
            self._current_symbols = []
            self._finished_at_ms = _now_ms()
            self._updated_at_ms = self._finished_at_ms

    def mark_cancelled(self) -> None:
        self._mark_finished("cancelled")

    def snapshot(self) -> DeepBackfillProgress:
        with self._lock:
            return DeepBackfillProgress(
                status=self._status,
                target_symbols=self._target_symbols,
                completed_symbols=self._completed_symbols,
                pending_symbols=self._pending_symbols,
                saved_count=self._saved_count,
                error_count=self._error_count,
                target_limit=self._target_limit,
                batch_size=self._batch_size,
                concurrency=self._concurrency,
                rate_limit_per_second=self._rate_limit_per_second,
                cooldown_seconds=self._cooldown_seconds,
                retry_delay_seconds=self._retry_delay_seconds,
                cycle_count=self._cycle_count,
                started_at_ms=self._started_at_ms,
                updated_at_ms=self._updated_at_ms,
                finished_at_ms=self._finished_at_ms,
                current_symbols=list(self._current_symbols),
                latest_error=self._latest_error,
            )

    def _mark_finished(self, status: BackfillProgressStatus) -> None:
        with self._lock:
            self._status = status
            self._current_symbols = []
            self._finished_at_ms = _now_ms()
            self._updated_at_ms = self._finished_at_ms


async def run_deep_backfill_worker(
    *,
    store: DeepBackfillStore,
    fetcher: CandleHistoryFetcher,
    symbols: Iterable[str],
    product_type: str,
    target_limit: int,
    batch_size: int,
    concurrency: int,
    cooldown_seconds: float,
    retry_delay_seconds: float,
    tracker: DeepBackfillProgressTracker,
    blocked_by: Callable[[], bool] | None = None,
) -> BackfillResult | None:
    normalized_symbols = normalize_symbols(symbols)
    if not normalized_symbols:
        raise ValueError("at least one symbol is required")
    if target_limit < 1:
        raise ValueError("target_limit must be positive")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    if cooldown_seconds < 0:
        raise ValueError("cooldown_seconds must be non-negative")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds must be non-negative")

    from prep_watchdeck.application.service_backfill import backfill_1m_candles

    retry_after_by_symbol: dict[str, float] = {}
    settled_symbols: set[str] = set()
    last_result: BackfillResult | None = None

    try:
        while True:
            while blocked_by is not None and blocked_by():
                await asyncio.sleep(_idle_sleep_seconds(cooldown_seconds))

            counts_by_symbol = await asyncio.to_thread(
                store.candle_1m_count_since_by_symbol,
                normalized_symbols,
                _target_window_start_ms(target_limit),
            )
            selection = select_deep_backfill_batch(
                symbols=normalized_symbols,
                counts_by_symbol=counts_by_symbol,
                target_limit=target_limit,
                settled_symbols=settled_symbols,
                retry_after_by_symbol=retry_after_by_symbol,
                now_seconds=asyncio.get_running_loop().time(),
                batch_size=batch_size,
            )
            tracker.update_coverage(
                completed_symbols=len(selection.completed_symbols),
                pending_symbols=len(selection.pending_symbols),
                current_symbols=[],
            )
            if not selection.pending_symbols:
                tracker.mark_completed()
                return last_result
            if not selection.batch_symbols:
                await asyncio.sleep(
                    _retry_wait_seconds(
                        next_retry_at=selection.next_retry_at,
                        cooldown_seconds=cooldown_seconds,
                    )
                )
                continue

            tracker.record_cycle_start(
                selection.batch_symbols,
                completed_symbols=len(selection.completed_symbols),
                pending_symbols=len(selection.pending_symbols),
            )
            result = await backfill_1m_candles(
                store=store,
                fetcher=fetcher,
                symbols=selection.batch_symbols,
                product_type=product_type,
                limit=target_limit,
                concurrency=concurrency,
                on_symbol_result=tracker.record_symbol,
            )
            last_result = result

            now = asyncio.get_running_loop().time()
            for symbol_result in result.symbols:
                if symbol_result.error is None:
                    settled_symbols.add(symbol_result.symbol)
                    retry_after_by_symbol.pop(symbol_result.symbol, None)
                else:
                    retry_after_by_symbol[symbol_result.symbol] = now + retry_delay_seconds

            counts_by_symbol = await asyncio.to_thread(
                store.candle_1m_count_since_by_symbol,
                normalized_symbols,
                _target_window_start_ms(target_limit),
            )
            selection = select_deep_backfill_batch(
                symbols=normalized_symbols,
                counts_by_symbol=counts_by_symbol,
                target_limit=target_limit,
                settled_symbols=settled_symbols,
                retry_after_by_symbol=retry_after_by_symbol,
                now_seconds=asyncio.get_running_loop().time(),
                batch_size=batch_size,
            )
            tracker.update_coverage(
                completed_symbols=len(selection.completed_symbols),
                pending_symbols=len(selection.pending_symbols),
                current_symbols=[],
            )
            if selection.pending_symbols:
                await asyncio.sleep(cooldown_seconds)
    except asyncio.CancelledError:
        tracker.mark_cancelled()
        raise
    except Exception as exc:
        tracker.mark_failed(f"{type(exc).__name__}: {exc}")
        return last_result


def _retry_wait_seconds(*, next_retry_at: float | None, cooldown_seconds: float) -> float:
    idle_sleep = _idle_sleep_seconds(cooldown_seconds)
    if next_retry_at is None:
        return idle_sleep
    wait_seconds = max(0.0, next_retry_at - asyncio.get_running_loop().time())
    return min(max(wait_seconds, 0.1), idle_sleep)


def _idle_sleep_seconds(cooldown_seconds: float) -> float:
    return max(0.1, min(max(cooldown_seconds, 0.0), 5.0))


def _target_window_start_ms(target_limit: int, now_ms: int | None = None) -> int:
    if target_limit < 1:
        raise ValueError("target_limit must be positive")
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    latest_bucket_ms = current_ms - (current_ms % 60_000)
    return latest_bucket_ms - (target_limit - 1) * 60_000


def _now_ms() -> int:
    return int(time.time() * 1000)
