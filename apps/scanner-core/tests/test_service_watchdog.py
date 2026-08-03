from __future__ import annotations

import asyncio

import pytest

from prep_watchdeck.application.service_watchdog import (
    ServiceStalledError,
    ServiceWatchdogConfig,
    run_service_watchdog,
)
from prep_watchdeck.errors import BitgetAPIError


async def test_watchdog_is_disabled_when_interval_is_zero() -> None:
    calls: list[str] = []

    async def latest_candle() -> int | None:
        calls.append("latest")
        return 100

    async def probe() -> bool:
        calls.append("probe")
        return True

    async def sleep(_seconds: float) -> None:
        calls.append("sleep")

    await run_service_watchdog(
        latest_candle_provider=latest_candle,
        upstream_probe=probe,
        config=watchdog_config(interval_seconds=0),
        monotonic=lambda: 0.0,
        sleep=sleep,
    )

    assert calls == []


async def test_watchdog_does_not_probe_during_startup_grace() -> None:
    clock = DeterministicClock(stop_at_seconds=240)
    probe_calls = 0

    async def probe() -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return True

    with pytest.raises(StopWatchdog):
        await run_service_watchdog(
            latest_candle_provider=constant_latest_candle(100),
            upstream_probe=probe,
            config=watchdog_config(
                interval_seconds=60,
                stall_seconds=120,
                startup_grace_seconds=300,
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert probe_calls == 0


async def test_regular_timestamp_progress_prevents_probe() -> None:
    clock = DeterministicClock(stop_at_seconds=100)
    probe_calls = 0

    async def latest_candle() -> int:
        return 100 + int(clock.now_seconds // 20) * 60_000

    async def probe() -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return True

    with pytest.raises(StopWatchdog):
        await run_service_watchdog(
            latest_candle_provider=latest_candle,
            upstream_probe=probe,
            config=watchdog_config(
                interval_seconds=10,
                stall_seconds=30,
                startup_grace_seconds=0,
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert probe_calls == 0


async def test_timestamp_recovery_resets_stall_confirmations() -> None:
    clock = DeterministicClock(stop_at_seconds=60)
    probe_calls = 0

    async def latest_candle() -> int:
        return 100 if clock.now_seconds < 40 else 200

    async def probe() -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return True

    with pytest.raises(StopWatchdog):
        await run_service_watchdog(
            latest_candle_provider=latest_candle,
            upstream_probe=probe,
            config=watchdog_config(
                interval_seconds=10,
                stall_seconds=30,
                confirmations=3,
                startup_grace_seconds=0,
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert probe_calls == 1


async def test_upstream_failure_does_not_stop_service() -> None:
    clock = DeterministicClock(stop_at_seconds=60)
    probe_calls = 0

    async def unavailable_probe() -> bool:
        nonlocal probe_calls
        probe_calls += 1
        raise BitgetAPIError("Bitget unavailable")

    with pytest.raises(StopWatchdog):
        await run_service_watchdog(
            latest_candle_provider=constant_latest_candle(100),
            upstream_probe=unavailable_probe,
            config=watchdog_config(
                interval_seconds=10,
                stall_seconds=20,
                confirmations=2,
                startup_grace_seconds=0,
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert probe_calls >= 2


async def test_false_upstream_probe_resets_confirmations() -> None:
    clock = DeterministicClock(stop_at_seconds=70)
    probe_results = iter([True, False, True, False, True])

    async def probe() -> bool:
        return next(probe_results)

    with pytest.raises(StopWatchdog):
        await run_service_watchdog(
            latest_candle_provider=constant_latest_candle(100),
            upstream_probe=probe,
            config=watchdog_config(
                interval_seconds=10,
                stall_seconds=20,
                confirmations=2,
                startup_grace_seconds=0,
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )


async def test_reachable_upstream_and_three_stalled_checks_raise() -> None:
    clock = DeterministicClock()
    probe_calls = 0

    async def reachable_probe() -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return True

    with pytest.raises(ServiceStalledError, match="latestCandleTsMs=100"):
        await run_service_watchdog(
            latest_candle_provider=constant_latest_candle(100),
            upstream_probe=reachable_probe,
            config=watchdog_config(
                interval_seconds=10,
                stall_seconds=20,
                confirmations=3,
                startup_grace_seconds=0,
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert probe_calls == 3
    assert clock.now_seconds == 40


async def test_watchdog_propagates_cancellation() -> None:
    async def cancelled_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_service_watchdog(
            latest_candle_provider=constant_latest_candle(100),
            upstream_probe=reachable_probe,
            config=watchdog_config(),
            monotonic=lambda: 0.0,
            sleep=cancelled_sleep,
        )


def watchdog_config(
    *,
    interval_seconds: float = 10,
    stall_seconds: float = 30,
    confirmations: int = 3,
    startup_grace_seconds: float = 0,
) -> ServiceWatchdogConfig:
    return ServiceWatchdogConfig(
        interval_seconds=interval_seconds,
        stall_seconds=stall_seconds,
        confirmations=confirmations,
        startup_grace_seconds=startup_grace_seconds,
    )


def constant_latest_candle(value: int):
    async def provider() -> int:
        return value

    return provider


async def reachable_probe() -> bool:
    return True


class StopWatchdog(BaseException):
    pass


class DeterministicClock:
    def __init__(self, *, stop_at_seconds: float | None = None) -> None:
        self.now_seconds = 0.0
        self.stop_at_seconds = stop_at_seconds

    def monotonic(self) -> float:
        return self.now_seconds

    async def sleep(self, seconds: float) -> None:
        self.now_seconds += seconds
        if self.stop_at_seconds is not None and self.now_seconds >= self.stop_at_seconds:
            raise StopWatchdog
