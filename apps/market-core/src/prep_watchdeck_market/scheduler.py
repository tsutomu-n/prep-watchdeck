from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from loguru import logger

from prep_watchdeck_market.market_state import MarketBatch
from prep_watchdeck_market.market_store import MarketStoreResult
from prep_watchdeck_market.models import Venue, canonical_json_sha256
from prep_watchdeck_market.sources.common import safe_source_error_code

CycleStatus = Literal["succeeded", "partial", "failed", "skipped"]
FETCH_DEADLINE_SECONDS = 20.0


MarketFetcher = Callable[[datetime], Coroutine[Any, Any, MarketBatch]]
CyclePersister = Callable[
    [datetime, datetime, Sequence[MarketBatch]],
    Coroutine[Any, Any, MarketStoreResult],
]


@dataclass(frozen=True, slots=True)
class VenueFetcher:
    venue: Venue
    endpoint: str
    fetch: MarketFetcher


@dataclass(frozen=True, slots=True)
class CycleRunResult:
    cycle_at: datetime
    status: CycleStatus
    store_result: MarketStoreResult | None
    error_codes: tuple[str, ...] = ()


class L1Scheduler:
    """Run all Venue L1 fetches on a fixed UTC grid without overlapping cycles."""

    def __init__(
        self,
        fetchers: Sequence[VenueFetcher],
        persist_cycle: CyclePersister,
        *,
        interval_seconds: int = 60,
        deadline_seconds: float = 50.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        venues = [fetcher.venue for fetcher in fetchers]
        if len(fetchers) != 3 or set(venues) != {"bitget", "hyperliquid", "aster"}:
            raise ValueError("L1 scheduler requires exactly one fetcher for each supported Venue")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if not 0 < deadline_seconds < interval_seconds:
            raise ValueError("deadline_seconds must be positive and below the interval")
        self._fetchers = tuple(fetchers)
        self._persist_cycle = persist_cycle
        self._interval_seconds = interval_seconds
        self._deadline_seconds = deadline_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cycle_lock = asyncio.Lock()
        self.grid_skips = 0

    async def run_cycle(self, cycle_at: datetime) -> CycleRunResult:
        _require_aware(cycle_at, "cycle_at")
        loop = asyncio.get_running_loop()
        cycle_started = loop.time()
        if self._cycle_lock.locked():
            return self._finish_cycle(
                CycleRunResult(cycle_at=cycle_at, status="skipped", store_result=None),
                cycle_started=cycle_started,
            )

        async with self._cycle_lock:
            deadline_at = loop.time() + self._deadline_seconds
            started_at = self._clock()
            tasks = {
                fetcher.venue: asyncio.create_task(
                    fetcher.fetch(cycle_at),
                    name=f"l1-{fetcher.venue}-{cycle_at.isoformat()}",
                )
                for fetcher in self._fetchers
            }
            done, pending = await asyncio.wait(
                tasks.values(),
                timeout=min(FETCH_DEADLINE_SECONDS, max(0.0, deadline_at - loop.time())),
                return_when=asyncio.ALL_COMPLETED,
            )
            del done

            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            batches: list[MarketBatch] = []
            error_codes: list[str] = []
            for fetcher in self._fetchers:
                task = tasks[fetcher.venue]
                error_code: str | None = None
                if task.cancelled():
                    error_code = "fetch_timeout"
                else:
                    try:
                        batch = task.result()
                        if batch.venue != fetcher.venue or batch.cycle_at != cycle_at:
                            error_code = "source_contract_mismatch"
                        else:
                            batches.append(batch)
                    except Exception as error:
                        error_code = safe_source_error_code(error)
                if error_code is not None:
                    error_codes.append(f"{fetcher.venue}:{error_code}")
                    batches.append(
                        _unavailable_batch(
                            fetcher.venue,
                            endpoint=fetcher.endpoint,
                            cycle_at=cycle_at,
                            observed_at=self._clock(),
                            error_code=error_code,
                        )
                    )

            remaining_seconds = deadline_at - loop.time()
            if remaining_seconds <= 0:
                return self._finish_cycle(
                    CycleRunResult(
                        cycle_at=cycle_at,
                        status="failed",
                        store_result=None,
                        error_codes=(*error_codes, "persistence:cycle_deadline_exceeded"),
                    ),
                    cycle_started=cycle_started,
                )
            try:
                store_result = await asyncio.wait_for(
                    self._persist_cycle(cycle_at, started_at, tuple(batches)),
                    timeout=remaining_seconds,
                )
            except TimeoutError:
                return self._finish_cycle(
                    CycleRunResult(
                        cycle_at=cycle_at,
                        status="failed",
                        store_result=None,
                        error_codes=(*error_codes, "persistence:cycle_deadline_exceeded"),
                    ),
                    cycle_started=cycle_started,
                )
            except Exception:
                self._log_cycle(
                    CycleRunResult(
                        cycle_at=cycle_at,
                        status="failed",
                        store_result=None,
                        error_codes=(*error_codes, "persistence:error"),
                    ),
                    duration_seconds=loop.time() - cycle_started,
                )
                raise
            return self._finish_cycle(
                CycleRunResult(
                    cycle_at=cycle_at,
                    status=store_result.status,
                    store_result=store_result,
                    error_codes=tuple(error_codes),
                ),
                cycle_started=cycle_started,
            )

    def _finish_cycle(
        self,
        result: CycleRunResult,
        *,
        cycle_started: float,
    ) -> CycleRunResult:
        self._log_cycle(
            result,
            duration_seconds=asyncio.get_running_loop().time() - cycle_started,
        )
        return result

    def _log_cycle(self, result: CycleRunResult, *, duration_seconds: float) -> None:
        error_codes = ",".join(result.error_codes) if result.error_codes else "none"
        fetch_timeout_count = sum(code.endswith(":fetch_timeout") for code in result.error_codes)
        commit_seconds = None if result.store_result is None else result.store_result.commit_seconds
        fields = {
            "event": "l1_cycle",
            "cycle_at": result.cycle_at.isoformat(),
            "duration_seconds": max(0.0, duration_seconds),
            "status": result.status,
            "fetch_timeout_count": fetch_timeout_count,
            "error_codes": error_codes,
            "grid_skips": self.grid_skips,
            "commit_seconds": commit_seconds,
        }
        logger.bind(**fields).info(
            "l1_cycle cycle_at={cycle_at} duration_seconds={duration_seconds:.6f} "
            "status={status} fetch_timeout_count={fetch_timeout_count} "
            "error_codes={error_codes} grid_skips={grid_skips} "
            "commit_seconds={commit_seconds}",
            **fields,
        )

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        next_cycle = next_grid_at(self._clock(), self._interval_seconds)
        while not stop_event.is_set():
            delay = max(0.0, (next_cycle - self._clock()).total_seconds())
            with suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            if stop_event.is_set():
                return

            await self.run_cycle(next_cycle)
            next_cycle += timedelta(seconds=self._interval_seconds)
            now = self._clock()
            while next_cycle <= now:
                self.grid_skips += 1
                next_cycle += timedelta(seconds=self._interval_seconds)


def next_grid_at(value: datetime, interval_seconds: int = 60) -> datetime:
    _require_aware(value, "value")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    epoch_seconds = int(value.timestamp())
    remainder = epoch_seconds % interval_seconds
    if remainder == 0 and value.microsecond == 0:
        return value
    seconds = interval_seconds - remainder
    return value.replace(microsecond=0) + timedelta(seconds=seconds)


def _unavailable_batch(
    venue: Venue,
    *,
    endpoint: str,
    cycle_at: datetime,
    observed_at: datetime,
    error_code: str,
) -> MarketBatch:
    raw_payload: dict[str, object] = {
        "cycleAt": cycle_at.isoformat(),
        "errorCode": error_code,
        "venue": venue,
    }
    return MarketBatch(
        venue=venue,
        cycle_at=cycle_at,
        observed_at=observed_at,
        endpoint=endpoint,
        payload_hash=canonical_json_sha256(raw_payload),
        observations=(),
        raw_payload=raw_payload,
    )


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
