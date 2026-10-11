from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest

from prep_watchdeck_market import candle_endpoint_recovery, candle_recovery, service
from prep_watchdeck_market.candle_recovery_store import RecoveryTarget
from prep_watchdeck_market.candles import Candle1m
from prep_watchdeck_market.runtime_lock import RuntimeLockUnavailable, exclusive_runtime_lock
from prep_watchdeck_market.sources.candle_history import HistoryFetchResult


async def _wait_until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


class _Connection:
    def __init__(self, path: Path) -> None:
        self.file = path.open("w", encoding="utf-8")

    @property
    def closed(self) -> bool:
        return self.file.closed

    def close(self) -> None:
        self.file.close()


@pytest.mark.parametrize("mode", ["endpoint", "history"])
def test_sibling_shutdown_failure_keeps_recovery_connection_and_lock_until_insert_finishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    module = candle_endpoint_recovery if mode == "endpoint" else candle_recovery
    prefix = "candle-endpoint-recovery" if mode == "endpoint" else "candle-recovery"
    connection = _Connection(tmp_path / "inserted.data")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    audits: list[dict[str, Any]] = []
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    bucket = now - timedelta(minutes=4)
    target = RecoveryTarget(
        1, "hyperliquid", "BTC", "a" * 64, now - timedelta(days=3), "BTC", "USDC", "USDC"
    )
    candle = Candle1m(
        venue="hyperliquid",
        source_symbol="BTC",
        bucket_start=bucket,
        open_price=Decimal("100"),
        high_price=Decimal("101"),
        low_price=Decimal("99"),
        close_price=Decimal("100"),
        volume_base=Decimal("0"),
        volume_notional=None,
        trade_count=0,
        finality="derived_final",
        source_at=None,
        observed_at=now,
    )

    async def open_connection(_url: str, *, apply: bool) -> psycopg.Connection[Any]:
        assert apply
        return cast(psycopg.Connection[Any], connection)

    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.request_count = 0

        async def fetch_missing(self, *_args: object, **_kwargs: object) -> HistoryFetchResult:
            self.request_count += 1
            return HistoryFetchResult((candle,), 0, 1)

    def insert(_connection, received_target, candles, *, run_id):
        assert received_target == target and candles == (candle,)
        entered.set()
        assert release.wait(3)
        connection.file.write("committed\n")
        connection.file.flush()
        finished.set()
        return 1

    async def idle(_self: object, stop: asyncio.Event) -> None:
        await stop.wait()

    async def catalog(_self: object) -> service.CatalogRefreshResult:
        return service.CatalogRefreshResult("succeeded", ("hyperliquid",), (), 1)

    monkeypatch.setattr(module, "_open_connection", open_connection)
    monkeypatch.setattr(module, "load_recovery_targets", lambda *_a, **_k: (target,))
    if mode == "endpoint":
        monkeypatch.setattr(module, "load_missing_endpoints", lambda *_a, **_k: {target: (bucket,)})
    else:
        monkeypatch.setattr(module, "scan_missing_candles", lambda *_a, **_k: (bucket,))
    monkeypatch.setattr(module, "NativeCandleHistoryClient", Client)
    monkeypatch.setattr(module, "insert_missing_candles", insert)
    monkeypatch.setattr(module, "start_recovery_run", lambda *_a, **_k: None)
    monkeypatch.setattr(module, "finish_recovery_run", lambda *_a, **kw: audits.append(kw))
    monkeypatch.setattr(service.CandleRuntime, "run_forever", idle)
    monkeypatch.setattr(service.SelectionRuntime, "run_forever", idle)
    monkeypatch.setattr(service.MarketService, "refresh_catalog", catalog)
    for name in (
        "_catalog_loop",
        "_artifact_loop",
        "_selected_artifact_loop",
        "_metrics_loop",
        "_activity_loop",
        "_recovery_loop" if mode == "endpoint" else "_endpoint_recovery_loop",
    ):
        monkeypatch.setattr(service.MarketService, name, idle)

    async def exercise() -> None:
        sibling_failure = asyncio.Event()

        class Scheduler:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            async def run_forever(self, stop: asyncio.Event) -> None:
                await stop.wait()
                await sibling_failure.wait()
                raise RuntimeError("injected sibling shutdown failure")

        monkeypatch.setattr(service, "L1Scheduler", Scheduler)
        market = service.MarketService(
            "unused", tmp_path, recovery_enabled=True, enabled_venues=("hyperliquid",)
        )
        stop = asyncio.Event()
        task = asyncio.create_task(market.run_forever(stop))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            run = next(
                active
                for active in asyncio.all_tasks()
                if active.get_name() == f"market-{prefix}-run"
            )
            stop.set()
            await _wait_until(lambda: run.cancelling() >= 1)
            sibling_failure.set()
            await _wait_until(lambda: run.cancelling() >= 2)
            await asyncio.sleep(0.01)
            assert not finished.is_set()
            assert not task.done() and not connection.closed
            with (
                pytest.raises(RuntimeLockUnavailable),
                exclusive_runtime_lock(tmp_path / "control" / f"{prefix}.lock"),
            ):
                pass
        finally:
            release.set()
            stop.set()
            sibling_failure.set()
            result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], RuntimeError)
        assert finished.is_set() and connection.closed
        assert (tmp_path / "inserted.data").read_text() == "committed\n"
        state = json.loads((tmp_path / "artifacts" / f"{prefix}-state.json").read_text())
        assert state["execution"] == "failed" and state["summary"]["inserted"] == 1
        assert audits[-1]["status"] == "failed" and audits[-1]["inserted"] == 1
        with exclusive_runtime_lock(tmp_path / "control" / f"{prefix}.lock"):
            pass

    asyncio.run(exercise())


def test_repeated_connect_and_close_cancellation_closes_late_connection_before_unlocking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    connection = _Connection(tmp_path / "connection.data")
    connect_entered, release_connect = threading.Event(), threading.Event()
    close_entered, release_close = threading.Event(), threading.Event()
    original_close = connection.close
    lock_path = tmp_path / "connect.lock"

    def connect(*_args: object, **_kwargs: object) -> psycopg.Connection[Any]:
        connect_entered.set()
        assert release_connect.wait(3)
        return cast(psycopg.Connection[Any], connection)

    def close() -> None:
        close_entered.set()
        assert release_close.wait(3)
        original_close()

    monkeypatch.setattr(candle_recovery.psycopg, "connect", connect)
    monkeypatch.setattr(connection, "close", close)

    async def open_locked() -> None:
        with exclusive_runtime_lock(lock_path):
            await candle_recovery._open_connection("unused", apply=True)

    async def exercise() -> None:
        task = asyncio.create_task(open_locked())
        try:
            assert await asyncio.to_thread(connect_entered.wait, 2)
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0.01)
            assert not task.done() and not connection.closed
            with pytest.raises(RuntimeLockUnavailable), exclusive_runtime_lock(lock_path):
                pass
            release_connect.set()
            assert await asyncio.to_thread(close_entered.wait, 2)
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0.01)
            assert not task.done() and not connection.closed
            with pytest.raises(RuntimeLockUnavailable), exclusive_runtime_lock(lock_path):
                pass
        finally:
            release_connect.set()
            release_close.set()
            await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled() and connection.closed
        with exclusive_runtime_lock(lock_path):
            pass

    try:
        asyncio.run(exercise())
    finally:
        original_close()
