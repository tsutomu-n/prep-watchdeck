from __future__ import annotations

from decimal import Decimal

from prep_watchdeck.adapters.duckdb.service_store import DuckDbServiceStore
from prep_watchdeck.application.service_deep_backfill import (
    DeepBackfillProgressTracker,
    run_deep_backfill_worker,
    select_deep_backfill_batch,
)
from prep_watchdeck.domain.service_models import Candle1mRecord
from prep_watchdeck.interfaces import cli
from prep_watchdeck.models import CandleBar


def test_select_deep_backfill_batch_skips_symbols_waiting_for_retry() -> None:
    selection = select_deep_backfill_batch(
        symbols=["aaausdt", "bbbusdt", "cccusdt"],
        counts_by_symbol={"CCCUSDT": 10},
        target_limit=10,
        settled_symbols=set[str](),
        retry_after_by_symbol={"AAAUSDT": 105.0},
        now_seconds=100.0,
        batch_size=2,
    )

    assert selection.completed_symbols == ["CCCUSDT"]
    assert selection.pending_symbols == ["AAAUSDT", "BBBUSDT"]
    assert selection.ready_symbols == ["BBBUSDT"]
    assert selection.batch_symbols == ["BBBUSDT"]
    assert selection.next_retry_at == 105.0


async def test_run_deep_backfill_worker_retries_failed_symbol_without_starving_ready_symbol(
    tmp_path,
) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    fetcher = FlakyDeepFetcher()
    tracker = DeepBackfillProgressTracker(
        ["AAAUSDT", "BBBUSDT"],
        target_limit=2,
        batch_size=1,
        concurrency=1,
        rate_limit_per_second=5.0,
        cooldown_seconds=0.0,
        retry_delay_seconds=0.2,
        started_at_ms=1_781_000_000_000,
    )

    await run_deep_backfill_worker(
        store=store,
        fetcher=fetcher,
        symbols=["AAAUSDT", "BBBUSDT"],
        product_type="USDT-FUTURES",
        target_limit=2,
        batch_size=1,
        concurrency=1,
        cooldown_seconds=0.0,
        retry_delay_seconds=0.2,
        tracker=tracker,
    )

    snapshot = tracker.snapshot()

    assert fetcher.calls == [
        ("AAAUSDT", "USDT-FUTURES", "1m", 2),
        ("BBBUSDT", "USDT-FUTURES", "1m", 2),
        ("AAAUSDT", "USDT-FUTURES", "1m", 2),
    ]
    assert store.candle_1m_count_by_symbol(["AAAUSDT", "BBBUSDT"]) == {
        "AAAUSDT": 2,
        "BBBUSDT": 2,
    }
    assert snapshot.status == "completed"
    assert snapshot.target_symbols == 2
    assert snapshot.completed_symbols == 2
    assert snapshot.pending_symbols == 0
    assert snapshot.saved_count == 4
    assert snapshot.error_count == 1
    assert snapshot.cycle_count == 3
    assert snapshot.latest_error == "AAAUSDT: TimeoutError: slow"


async def test_run_deep_backfill_worker_does_not_complete_from_old_rows(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    store.upsert_candles_1m(
        [
            Candle1mRecord(
                symbol="AAAUSDT",
                ts_ms=1_780_000_000_000 + index * 60_000,
                open=1.0,
                high=1.2,
                low=0.9,
                close=1.1,
                base_volume=100.0,
                quote_volume=110.0,
                usdt_volume=110.0,
                is_closed=True,
                source="old-test",
                updated_at_ms=1_780_000_000_000 + index * 60_000,
            )
            for index in range(2)
        ]
    )
    fetcher = FlakyDeepFetcher()
    tracker = DeepBackfillProgressTracker(
        ["AAAUSDT"],
        target_limit=2,
        batch_size=1,
        concurrency=1,
        rate_limit_per_second=5.0,
        cooldown_seconds=0.0,
        retry_delay_seconds=0.0,
        started_at_ms=1_781_000_000_000,
    )

    await run_deep_backfill_worker(
        store=store,
        fetcher=fetcher,
        symbols=["AAAUSDT"],
        product_type="USDT-FUTURES",
        target_limit=2,
        batch_size=1,
        concurrency=1,
        cooldown_seconds=0.0,
        retry_delay_seconds=0.0,
        tracker=tracker,
    )

    assert fetcher.calls == [
        ("AAAUSDT", "USDT-FUTURES", "1m", 2),
        ("AAAUSDT", "USDT-FUTURES", "1m", 2),
    ]


async def test_service_deep_backfill_wrapper_marks_failed_without_raising(
    tmp_path,
    monkeypatch,
) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    tracker = DeepBackfillProgressTracker(
        ["AAAUSDT"],
        target_limit=2,
        batch_size=1,
        concurrency=1,
        rate_limit_per_second=5.0,
        cooldown_seconds=0.0,
        retry_delay_seconds=0.0,
        started_at_ms=1_781_000_000_000,
    )

    class FailingClient:
        def __init__(self, rate_limit_per_second: float) -> None:
            assert rate_limit_per_second == 5.0

        async def __aenter__(self):
            raise RuntimeError("client unavailable")

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(cli, "BitgetPublicClient", FailingClient)

    result = await cli._run_service_deep_backfill_from_bitget(
        store=store,
        symbols=["AAAUSDT"],
        product_type="USDT-FUTURES",
        target_limit=2,
        batch_size=1,
        concurrency=1,
        cooldown_seconds=0.0,
        retry_delay_seconds=0.0,
        rate_limit_per_second=5.0,
        tracker=tracker,
        blocked_by=None,
    )

    snapshot = tracker.snapshot()
    assert result is None
    assert snapshot.status == "failed"
    assert snapshot.latest_error == "RuntimeError: client unavailable"


class FlakyDeepFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, int]] = []
        self._failed_once = False

    async def __call__(
        self,
        symbol: str,
        product_type: str,
        granularity: str,
        limit: int,
    ) -> list[CandleBar]:
        self.calls.append((symbol, product_type, granularity, limit))
        if symbol == "AAAUSDT" and not self._failed_once:
            self._failed_once = True
            raise TimeoutError("slow")
        return [
            CandleBar(
                symbol=symbol,
                ts=1_781_000_000_000 + index * 60_000,
                open=Decimal("1.0"),
                high=Decimal("1.2"),
                low=Decimal("0.9"),
                close=Decimal("1.1"),
                base_vol=Decimal("100"),
                quote_vol=Decimal("110"),
            )
            for index in range(limit)
        ]
