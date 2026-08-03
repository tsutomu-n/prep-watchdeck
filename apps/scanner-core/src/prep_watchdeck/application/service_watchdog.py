from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from prep_watchdeck.errors import WatchdeckError

LatestCandleProvider = Callable[[], Awaitable[int | None]]
UpstreamProbe = Callable[[], Awaitable[bool]]
MonotonicClock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class ServiceStalledError(WatchdeckError):
    """Service remained locally stalled while Bitget REST was reachable."""


@dataclass(frozen=True)
class ServiceWatchdogConfig:
    interval_seconds: float = 60.0
    stall_seconds: float = 300.0
    confirmations: int = 3
    startup_grace_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")
        if self.stall_seconds <= 0:
            raise ValueError("stall_seconds must be positive")
        if self.confirmations < 1:
            raise ValueError("confirmations must be positive")
        if self.startup_grace_seconds < 0:
            raise ValueError("startup_grace_seconds must be non-negative")


async def run_service_watchdog(
    *,
    latest_candle_provider: LatestCandleProvider,
    upstream_probe: UpstreamProbe,
    config: ServiceWatchdogConfig,
    monotonic: MonotonicClock = time.monotonic,
    sleep: Sleep = asyncio.sleep,
) -> None:
    if config.interval_seconds == 0:
        return

    started_at = monotonic()
    last_progress_at = started_at
    latest_candle_ts_ms = await latest_candle_provider()
    stalled_confirmations = 0

    while True:
        await sleep(config.interval_seconds)
        now = monotonic()
        observed_ts_ms = await latest_candle_provider()
        if _timestamp_advanced(latest_candle_ts_ms, observed_ts_ms):
            latest_candle_ts_ms = observed_ts_ms
            last_progress_at = now
            stalled_confirmations = 0
            continue
        if now - started_at < config.startup_grace_seconds:
            continue
        stalled_for_seconds = now - last_progress_at
        if stalled_for_seconds < config.stall_seconds:
            continue

        try:
            upstream_reachable = await upstream_probe()
        except Exception:
            stalled_confirmations = 0
            continue
        if not upstream_reachable:
            stalled_confirmations = 0
            continue

        stalled_confirmations += 1
        if stalled_confirmations >= config.confirmations:
            raise ServiceStalledError(
                "service data stalled: "
                f"latestCandleTsMs={latest_candle_ts_ms} "
                f"stalledForSeconds={stalled_for_seconds:.1f} "
                f"confirmations={stalled_confirmations}"
            )


def _timestamp_advanced(previous: int | None, current: int | None) -> bool:
    if current is None:
        return False
    return previous is None or current > previous
