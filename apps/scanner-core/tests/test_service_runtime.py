from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prep_watchdeck.adapters.duckdb.service_store import DuckDbServiceStore
from prep_watchdeck.application.service_backfill import (
    BackfillProgressTracker,
    backfill_1m_candles,
)
from prep_watchdeck.application.service_bootstrap import (
    bootstrap_universe,
    refresh_ticker_latest_periodically,
)
from prep_watchdeck.application.service_plan import build_subscription_plan
from prep_watchdeck.application.service_runtime import ServiceRunResult
from prep_watchdeck.application.service_watchdog import ServiceStalledError
from prep_watchdeck.application.ws_runtime import WsStreamIngestResult
from prep_watchdeck.application.ws_shards import WsShardIngestResult
from prep_watchdeck.config.templates import load_template
from prep_watchdeck.domain.service_models import (
    BackfillResult,
    BootstrapResult,
    Candle1mRecord,
    InstrumentRecord,
    OpenInterestSampleRecord,
    StreamHealthRecord,
    TickerLatestRecord,
)
from prep_watchdeck.interfaces import cli
from prep_watchdeck.interfaces.cli import _run_service_reconcile_loop_from_bitget, app
from prep_watchdeck.models import CandleBar, ContractInfo, TickerInfo

runner = CliRunner()


def test_service_store_initializes_and_upserts_market_state(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")

    store.initialize()
    store.upsert_instruments(
        [
            InstrumentRecord(
                symbol="ALTUSDT",
                product_type="USDT-FUTURES",
                symbol_type="perpetual",
                symbol_status="normal",
                base_coin="ALT",
                quote_coin="USDT",
                max_leverage=25.0,
                min_trade_num=1.0,
                is_rwa=False,
                updated_at_ms=1_781_000_000_000,
            )
        ]
    )
    store.upsert_ticker_latest(
        [
            TickerLatestRecord(
                symbol="ALTUSDT",
                ts_ms=1_781_000_000_000,
                last_price=1.23,
                bid_price=1.22,
                ask_price=1.24,
                quote_volume_24h=1_000_000.0,
                updated_at_ms=1_781_000_000_100,
            )
        ]
    )
    store.upsert_candles_1m(
        [
            Candle1mRecord(
                symbol="ALTUSDT",
                ts_ms=1_781_000_000_000,
                open=1.0,
                high=1.3,
                low=0.9,
                close=1.2,
                base_volume=100.0,
                quote_volume=120.0,
                usdt_volume=120.0,
                is_closed=True,
                source="test",
                updated_at_ms=1_781_000_000_200,
            ),
            Candle1mRecord(
                symbol="ALTUSDT",
                ts_ms=1_781_000_060_000,
                open=1.2,
                high=1.4,
                low=1.1,
                close=1.35,
                base_volume=110.0,
                quote_volume=148.5,
                usdt_volume=148.5,
                is_closed=True,
                source="test",
                updated_at_ms=1_781_000_060_200,
            ),
        ]
    )
    store.upsert_stream_health(
        [
            StreamHealthRecord(
                shard_id="ticker-0",
                stream_kind="ticker",
                channel_count=1,
                connected=False,
                reconnect_count=0,
                gap_count=0,
            )
        ]
    )

    diagnostics = store.diagnostics()

    assert diagnostics.schema_ready is True
    assert diagnostics.instrument_count == 1
    assert diagnostics.ticker_count == 1
    assert diagnostics.candle_1m_count == 2
    assert diagnostics.stream_health_count == 1
    assert diagnostics.latest_candle_1m_ts_ms == 1_781_000_060_000


def test_service_cli_once_and_doctor_initialize_service_store(tmp_path, monkeypatch) -> None:
    cache_db = tmp_path / "watchdeck.duckdb"
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_DB_PATH", str(cache_db))

    service_result = runner.invoke(app, ["service", "--once"])
    doctor_result = runner.invoke(app, ["doctor"])

    assert service_result.exit_code == 0
    assert "service initialized" in service_result.output
    assert doctor_result.exit_code == 0
    assert "serviceStore=OK" in doctor_result.output
    assert "candles1m=0" in doctor_result.output


def test_service_cli_help_omits_deep_backfill_options() -> None:
    result = runner.invoke(app, ["service", "--help"])

    assert result.exit_code == 0
    assert "--deep-backfill-" not in result.output


def test_service_cli_runs_stream_without_network(monkeypatch) -> None:
    async def fake_run_service_from_bitget(
        settings,
        template: str,
        universe: str,
        max_symbols: int | None,
        shard_channels: int,
        backfill_limit: int,
        backfill_concurrency: int,
        await_backfill: bool,
        reconcile_interval_sec: float,
        reconcile_limit: int,
        reconcile_concurrency: int,
        ticker_refresh_interval_sec: float,
        watchdog_interval_sec: float,
        watchdog_stall_sec: float,
        watchdog_confirmations: int,
        watchdog_startup_grace_sec: float,
        stop_after_records: int | None,
    ) -> ServiceRunResult:
        _ = settings
        assert template == "balanced"
        assert universe == "all"
        assert max_symbols == 1
        assert shard_channels == 48
        assert backfill_limit == 200
        assert backfill_concurrency == 12
        assert await_backfill is False
        assert reconcile_interval_sec == 60.0
        assert reconcile_limit == 60
        assert reconcile_concurrency == 2
        assert ticker_refresh_interval_sec == 60.0
        assert watchdog_interval_sec == 60.0
        assert watchdog_stall_sec == 300.0
        assert watchdog_confirmations == 3
        assert watchdog_startup_grace_sec == 300.0
        assert stop_after_records == 1
        return ServiceRunResult(
            bootstrap=BootstrapResult(
                product_type="USDT-FUTURES",
                template="balanced",
                fetched_contract_count=10,
                fetched_ticker_count=10,
                selected_symbols=["BTCUSDT"],
                valid_symbols=["BTCUSDT"],
            ),
            subscription=build_subscription_plan(["BTCUSDT"], product_type="USDT-FUTURES"),
            stream=WsShardIngestResult(
                shard_count=1,
                payload_count=1,
                ticker_count=1,
                candle_1m_count=0,
            ),
        )

    monkeypatch.setattr(
        "prep_watchdeck.interfaces.cli.run_service_from_bitget",
        fake_run_service_from_bitget,
    )

    result = runner.invoke(
        app,
        ["service", "--max-symbols", "1", "--stop-after-records", "1"],
    )

    assert result.exit_code == 0
    assert "service stopped" in result.output
    assert "valid=1" in result.output
    assert "streamShards=1" in result.output
    assert "tickers=1" in result.output


def test_service_cli_returns_nonzero_for_watchdog_failure(monkeypatch) -> None:
    async def fake_run_service_from_bitget(
        *_args: object,
        **_kwargs: object,
    ) -> ServiceRunResult:
        raise ServiceStalledError("stalled")

    monkeypatch.setattr(cli, "run_service_from_bitget", fake_run_service_from_bitget)

    result = runner.invoke(app, ["service"])

    assert result.exit_code == 1
    assert isinstance(result.exception, ServiceStalledError)


async def test_backfill_1m_candles_saves_explicit_symbols(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    fetcher = FakeCandleFetcher()
    progress: list[str] = []

    result = await backfill_1m_candles(
        store=store,
        fetcher=fetcher,
        symbols=["altusdt", " BTCUSDT "],
        product_type="USDT-FUTURES",
        limit=2,
        concurrency=1,
        on_symbol_result=lambda item: progress.append(item.symbol),
    )

    diagnostics = store.diagnostics()
    latest_by_symbol = store.latest_candle_1m_ts_by_symbol(["ALTUSDT", "BTCUSDT", "MISSINGUSDT"])
    counts_by_symbol = store.candle_1m_count_by_symbol(["ALTUSDT", "BTCUSDT", "MISSINGUSDT"])

    assert result.granularity == "1m"
    assert result.saved_count == 4
    assert [item.symbol for item in result.symbols] == ["ALTUSDT", "BTCUSDT"]
    assert fetcher.calls == [
        ("ALTUSDT", "USDT-FUTURES", "1m", 2),
        ("BTCUSDT", "USDT-FUTURES", "1m", 2),
    ]
    assert progress == ["ALTUSDT", "BTCUSDT"]
    assert diagnostics.candle_1m_count == 4
    assert latest_by_symbol == {
        "ALTUSDT": 1_781_000_060_000,
        "BTCUSDT": 1_781_000_060_000,
        "MISSINGUSDT": None,
    }
    assert counts_by_symbol == {"ALTUSDT": 2, "BTCUSDT": 2, "MISSINGUSDT": 0}


async def test_backfill_parent_cancellation_cancels_and_awaits_children() -> None:
    all_started = asyncio.Event()
    child_tasks: list[asyncio.Task[object]] = []
    cancelled_symbols: set[str] = set()

    class Store:
        def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
            _ = candles
            raise AssertionError("cancelled fetches must not write")

    async def fetcher(
        symbol: str,
        product_type: str,
        granularity: str,
        limit: int,
    ) -> list[CandleBar]:
        _ = (product_type, granularity, limit)
        task = asyncio.current_task()
        assert task is not None
        child_tasks.append(task)
        if len(child_tasks) == 2:
            all_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled_symbols.add(symbol)
            raise
        raise AssertionError("fetch unexpectedly resumed")

    parent = asyncio.create_task(
        backfill_1m_candles(
            store=Store(),
            fetcher=fetcher,
            symbols=["ALTUSDT", "BTCUSDT"],
            product_type="USDT-FUTURES",
            limit=2,
            concurrency=2,
        )
    )
    await all_started.wait()

    try:
        parent.cancel()
        with pytest.raises(asyncio.CancelledError):
            await parent
        await asyncio.sleep(0)

        assert cancelled_symbols == {"ALTUSDT", "BTCUSDT"}
        assert all(task.done() for task in child_tasks)
    finally:
        for task in child_tasks:
            task.cancel()
        await asyncio.gather(*child_tasks, return_exceptions=True)


def test_backfill_progress_tracker_summarizes_symbol_results() -> None:
    tracker = BackfillProgressTracker(
        ["btcusdt", "ethusdt"],
        limit=200,
        concurrency=12,
        started_at_ms=1_781_000_000_000,
    )

    tracker.record_symbol(
        BackfillResult(
            product_type="USDT-FUTURES",
            granularity="1m",
            requested_symbols=["BTCUSDT"],
            saved_count=2,
            symbols=[
                {"symbol": "BTCUSDT", "fetchedCount": 2, "savedCount": 2},
            ],
        ).symbols[0]
    )
    tracker.record_symbol(
        BackfillResult(
            product_type="USDT-FUTURES",
            granularity="1m",
            requested_symbols=["ETHUSDT"],
            saved_count=0,
            symbols=[
                {
                    "symbol": "ETHUSDT",
                    "fetchedCount": 0,
                    "savedCount": 0,
                    "error": "TimeoutError: slow",
                },
            ],
        ).symbols[0]
    )
    tracker.mark_failed("symbols=1 ETHUSDT: TimeoutError: slow")

    snapshot = tracker.snapshot()

    assert snapshot.status == "failed"
    assert snapshot.requested_symbols == 2
    assert snapshot.completed_symbols == 2
    assert snapshot.saved_count == 2
    assert snapshot.error_count == 1
    assert snapshot.latest_error == "symbols=1 ETHUSDT: TimeoutError: slow"


async def test_reconcile_loop_evaluates_once_before_interval_sleep(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    trackers: list[BackfillProgressTracker] = []

    def record_tracker(tracker: BackfillProgressTracker | None) -> None:
        assert tracker is not None
        trackers.append(tracker)

    def fake_select_reconcile_symbols(store, symbols, *, window_limit):
        _ = store
        calls.append(("select", (tuple(symbols), window_limit)))
        return []

    async def fake_sleep(seconds: float) -> None:
        calls.append(("sleep", seconds))
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "prep_watchdeck.interfaces.cli.select_reconcile_symbols",
        fake_select_reconcile_symbols,
    )
    monkeypatch.setattr("prep_watchdeck.interfaces.cli.asyncio.sleep", fake_sleep)

    with contextlib.suppress(asyncio.CancelledError):
        await _run_service_reconcile_loop_from_bitget(
            store=object(),
            symbols=["BTCUSDT"],
            product_type="USDT-FUTURES",
            interval_seconds=60.0,
            limit=60,
            concurrency=2,
            set_tracker=record_tracker,
            blocked_by_tracker=None,
        )

    assert calls == [
        ("select", (("BTCUSDT",), 60)),
        ("sleep", 60.0),
    ]
    assert trackers[0].snapshot().status == "completed"


async def test_service_supervisor_propagates_watchdog_failure_and_cancels_stream() -> None:
    stream_started = asyncio.Event()
    stream_cancelled = asyncio.Event()

    async def stream() -> WsShardIngestResult:
        stream_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            stream_cancelled.set()
            raise
        raise AssertionError("stream unexpectedly resumed")

    async def watchdog() -> None:
        await stream_started.wait()
        raise ServiceStalledError("stalled")

    with pytest.raises(ServiceStalledError, match="stalled"):
        await cli._run_service_until_stopped(stream(), watchdog(), stop_event=None)

    assert stream_cancelled.is_set()


async def test_service_supervisor_returns_stream_result_and_cancels_watchdog() -> None:
    watchdog_started = asyncio.Event()
    watchdog_cancelled = asyncio.Event()
    expected = WsShardIngestResult(
        shard_count=1,
        payload_count=2,
        ticker_count=1,
        candle_1m_count=1,
    )

    async def stream() -> WsShardIngestResult:
        await watchdog_started.wait()
        return expected

    async def watchdog() -> None:
        watchdog_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            watchdog_cancelled.set()
            raise

    result = await cli._run_service_until_stopped(stream(), watchdog(), stop_event=None)

    assert result == expected
    assert watchdog_cancelled.is_set()


async def test_service_supervisor_signal_stop_cancels_stream_and_watchdog() -> None:
    stop_event = asyncio.Event()
    stream_started = asyncio.Event()
    watchdog_started = asyncio.Event()
    stream_cancelled = asyncio.Event()
    watchdog_cancelled = asyncio.Event()

    async def wait_until_cancelled(started: asyncio.Event, cancelled: asyncio.Event) -> None:
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def trigger_stop() -> None:
        await stream_started.wait()
        await watchdog_started.wait()
        stop_event.set()

    async def stream() -> WsShardIngestResult:
        await wait_until_cancelled(stream_started, stream_cancelled)
        raise AssertionError("stream unexpectedly resumed")

    async def watchdog() -> None:
        await wait_until_cancelled(watchdog_started, watchdog_cancelled)

    trigger_task = asyncio.create_task(trigger_stop())
    with pytest.raises(KeyboardInterrupt):
        await cli._run_service_until_stopped(
            stream(),
            watchdog(),
            stop_event=stop_event,
        )
    await trigger_task

    assert stream_cancelled.is_set()
    assert watchdog_cancelled.is_set()


async def test_service_supervisor_without_watchdog_returns_stream_result() -> None:
    expected = WsShardIngestResult(
        shard_count=1,
        payload_count=2,
        ticker_count=1,
        candle_1m_count=1,
    )

    async def stream() -> WsShardIngestResult:
        return expected

    result = await cli._run_service_until_stopped(stream(), None, stop_event=None)

    assert result == expected


async def test_service_supervisor_without_watchdog_honors_signal_stop() -> None:
    stop_event = asyncio.Event()
    stream_started = asyncio.Event()
    stream_cancelled = asyncio.Event()

    async def stream() -> WsShardIngestResult:
        stream_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            stream_cancelled.set()
            raise
        raise AssertionError("stream unexpectedly resumed")

    async def trigger_stop() -> None:
        await stream_started.wait()
        stop_event.set()

    trigger_task = asyncio.create_task(trigger_stop())
    with pytest.raises(KeyboardInterrupt):
        await cli._run_service_until_stopped(stream(), None, stop_event=stop_event)
    await trigger_task

    assert stream_cancelled.is_set()


async def test_service_background_cleanup_cancels_and_awaits_all_task_kinds() -> None:
    started = {
        name: asyncio.Event()
        for name in (
            "state",
            "snapshot",
            "ticker",
            "ticker_refresh",
            "backfill",
            "reconcile",
        )
    }
    cancelled: list[str] = []

    async def background_task(name: str) -> None:
        started[name].set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.append(name)
            raise

    tasks = [asyncio.create_task(background_task(name)) for name in started]
    await asyncio.gather(*(event.wait() for event in started.values()))

    await cli._cancel_service_tasks(*tasks)

    assert cancelled == list(started)
    assert all(task.done() for task in tasks)


async def test_service_background_cleanup_signals_all_tasks_before_awaiting() -> None:
    second_cancelled = asyncio.Event()

    async def first_task() -> None:
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await second_cancelled.wait()
            raise

    async def second_task() -> None:
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            second_cancelled.set()
            raise

    tasks = [asyncio.create_task(first_task()), asyncio.create_task(second_task())]
    await asyncio.sleep(0)

    started_at = asyncio.get_running_loop().time()
    await asyncio.wait_for(cli._cancel_service_tasks(*tasks), timeout=0.1)
    elapsed = asyncio.get_running_loop().time() - started_at

    assert second_cancelled.is_set()
    assert all(task.done() for task in tasks)
    assert elapsed < 0.05


async def test_service_background_cleanup_does_not_hide_task_failure() -> None:
    async def task_failing_during_cancel() -> None:
        try:
            await asyncio.Future()
        except asyncio.CancelledError as exc:
            raise RuntimeError("background cleanup failed") from exc

    task = asyncio.create_task(task_failing_during_cancel())
    await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="background cleanup failed"):
        await cli._cancel_service_tasks(task)

    assert task.done()


@pytest.mark.parametrize(("has_candle", "expected"), [(True, True), (False, False)])
async def test_service_upstream_probe_requests_one_recent_candle(
    monkeypatch,
    has_candle: bool,
    expected: bool,
) -> None:
    calls: list[tuple[str, str, int]] = []

    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def fake_fetch(
        _client,
        symbol: str,
        product_type: str,
        *,
        granularity: str,
        limit: int,
    ) -> list[object]:
        assert granularity == "1m"
        calls.append((symbol, product_type, limit))
        return [object()] if has_candle else []

    monkeypatch.setattr(cli, "BitgetPublicClient", FakeClient)
    monkeypatch.setattr(cli, "fetch_recent_history_candles", fake_fetch)

    result = await cli._probe_service_upstream_from_bitget(
        symbol="BTCUSDT",
        product_type="USDT-FUTURES",
    )

    assert result is expected
    assert calls == [("BTCUSDT", "USDT-FUTURES", 1)]


def test_backfill_cli_uses_explicit_symbols_without_network(monkeypatch) -> None:
    async def fake_backfill_1m_from_bitget(
        settings,
        symbols: list[str],
        limit: int,
        concurrency: int,
    ) -> BackfillResult:
        _ = settings
        assert symbols == ["ALTUSDT", "BTCUSDT"]
        assert limit == 2
        assert concurrency == 8
        return BackfillResult(
            product_type="USDT-FUTURES",
            granularity="1m",
            requested_symbols=["ALTUSDT", "BTCUSDT"],
            saved_count=4,
            symbols=[
                {"symbol": "ALTUSDT", "fetchedCount": 2, "savedCount": 2},
                {"symbol": "BTCUSDT", "fetchedCount": 2, "savedCount": 2},
            ],
        )

    monkeypatch.setattr(
        "prep_watchdeck.interfaces.cli.backfill_1m_from_bitget", fake_backfill_1m_from_bitget
    )

    result = runner.invoke(app, ["backfill", "--symbols", "altusdt,btcusdt", "--limit", "2"])

    assert result.exit_code == 0
    assert "backfill written" in result.output
    assert "symbols=2" in result.output
    assert "candles=4" in result.output
    assert "errors=0" in result.output


async def test_bootstrap_universe_stores_market_state_and_filters_candidates(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    config = load_template(Path("../../config/scanner-filters"), "balanced")
    fetcher = FakeUniverseFetcher()

    result = await bootstrap_universe(
        store=store,
        fetcher=fetcher,
        config=config,
        template="balanced",
        max_symbols=1,
        now_ms=1_781_000_000_000,
    )

    diagnostics = store.diagnostics()

    assert result.fetched_contract_count == 5
    assert result.fetched_ticker_count == 5
    assert result.selected_symbols == ["ALTUSDT"]
    assert result.valid_symbols == ["ALTUSDT", "BIGUSDT", "BTCUSDT", "RWAUSDT"]
    assert diagnostics.instrument_count == 5
    assert diagnostics.ticker_count == 5


async def test_bootstrap_universe_excludes_unsupported_symbols_from_storage_and_streams(
    tmp_path,
) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    config = load_template(Path("../../config/scanner-filters"), "balanced")

    class UnsafeUniverseFetcher:
        async def fetch_contracts(self, product_type: str) -> list[ContractInfo]:
            return [
                contract("ALTUSDT", product_type),
                contract("龙虾USDT", product_type),
            ]

        async def fetch_tickers(self, product_type: str) -> list[TickerInfo]:
            _ = product_type
            return [
                ticker("ALTUSDT", "1000000"),
                ticker("龙虾USDT", "1000000"),
            ]

    result = await bootstrap_universe(
        store=store,
        fetcher=UnsafeUniverseFetcher(),
        config=config,
        template="balanced",
        max_symbols=None,
        now_ms=1_781_000_000_000,
    )

    assert result.fetched_contract_count == 2
    assert result.fetched_ticker_count == 2
    assert result.selected_symbols == ["ALTUSDT"]
    assert result.valid_symbols == ["ALTUSDT"]
    assert [item.symbol for item in store.load_instruments()] == ["ALTUSDT"]
    assert [item.symbol for item in store.load_ticker_latest()] == ["ALTUSDT"]


async def test_periodic_ticker_refresh_persists_fresh_open_interest() -> None:
    stored: list[TickerLatestRecord] = []
    collected: list[TickerLatestRecord] = []

    class Store:
        def upsert_instruments(self, instruments: list[InstrumentRecord]) -> None:
            _ = instruments

        def upsert_ticker_latest(self, tickers: list[TickerLatestRecord]) -> None:
            stored.extend(tickers)

    async def fetcher(product_type: str) -> list[TickerInfo]:
        assert product_type == "USDT-FUTURES"
        return [ticker("ALTUSDT", "1000000")]

    async def stop_after_refresh(_seconds: float) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await refresh_ticker_latest_periodically(
            store=Store(),
            fetcher=fetcher,
            product_type="USDT-FUTURES",
            interval_seconds=60.0,
            publish_immediately=True,
            ticker_sink=collected.extend,
            on_error=lambda exc: pytest.fail(f"unexpected refresh error: {exc}"),
            now_ms_provider=lambda: 1_781_000_000_500,
            sleep=stop_after_refresh,
        )

    assert stored == collected
    assert len(stored) == 1
    assert stored[0].symbol == "ALTUSDT"
    assert stored[0].holding_amount == 12345.0
    assert stored[0].ts_ms == 1_781_000_000_000
    assert stored[0].updated_at_ms == 1_781_000_000_500


async def test_periodic_ticker_refresh_recovers_after_transient_fetch_failure() -> None:
    stored: list[TickerLatestRecord] = []
    errors: list[Exception] = []
    fetch_count = 0
    sleep_count = 0

    class Store:
        def upsert_instruments(self, instruments: list[InstrumentRecord]) -> None:
            _ = instruments

        def upsert_ticker_latest(self, tickers: list[TickerLatestRecord]) -> None:
            stored.extend(tickers)

    async def fetcher(product_type: str) -> list[TickerInfo]:
        nonlocal fetch_count
        assert product_type == "USDT-FUTURES"
        fetch_count += 1
        if fetch_count == 1:
            raise RuntimeError("temporary public ticker failure")
        return [ticker("ALTUSDT", "1000000")]

    async def stop_after_second_cycle(_seconds: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count == 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await refresh_ticker_latest_periodically(
            store=Store(),
            fetcher=fetcher,
            product_type="USDT-FUTURES",
            interval_seconds=60.0,
            publish_immediately=True,
            ticker_sink=None,
            on_error=errors.append,
            now_ms_provider=lambda: 1_781_000_000_500,
            sleep=stop_after_second_cycle,
        )

    assert fetch_count == 2
    assert [type(error) for error in errors] == [RuntimeError]
    assert len(stored) == 1
    assert stored[0].symbol == "ALTUSDT"
    assert stored[0].holding_amount == 12345.0


def test_build_subscription_plan_counts_channels_and_shards() -> None:
    plan = build_subscription_plan(
        ["ethusdt", "btcusdt"],
        product_type="USDT-FUTURES",
        max_channels=3,
    )

    assert plan.product_type == "USDT-FUTURES"
    assert plan.symbol_count == 2
    assert plan.channel_count == 4
    assert plan.shard_count == 2
    assert [len(shard) for shard in plan.shards] == [3, 1]


def test_bootstrap_cli_uses_template_filter_without_network(monkeypatch) -> None:
    async def fake_bootstrap_universe_from_bitget(
        settings, template: str, max_symbols: int | None
    ) -> BootstrapResult:
        _ = settings
        assert template == "aggressive"
        assert max_symbols == 3
        return BootstrapResult(
            product_type="USDT-FUTURES",
            template="aggressive",
            fetched_contract_count=10,
            fetched_ticker_count=10,
            selected_symbols=["ALTUSDT", "BETAUSDT", "GAMMAUSDT"],
            valid_symbols=["ALTUSDT", "BETAUSDT", "GAMMAUSDT", "OMEGAUSDT"],
        )

    monkeypatch.setattr(
        "prep_watchdeck.interfaces.cli.bootstrap_universe_from_bitget",
        fake_bootstrap_universe_from_bitget,
    )

    result = runner.invoke(app, ["bootstrap", "--template", "aggressive", "--max-symbols", "3"])

    assert result.exit_code == 0
    assert "bootstrap written" in result.output
    assert "contracts=10" in result.output
    assert "tickers=10" in result.output
    assert "selected=3" in result.output
    assert "valid=4" in result.output
    assert "streamChannels=8" in result.output
    assert "streamShards=1" in result.output
    assert "ALTUSDT,BETAUSDT,GAMMAUSDT" in result.output


def test_ws_smoke_cli_uses_explicit_symbols_without_network(monkeypatch) -> None:
    async def fake_ws_smoke_from_bitget(
        settings,
        symbols: list[str],
        records: int,
        timeout_sec: float,
    ) -> WsStreamIngestResult:
        _ = settings
        assert symbols == ["BTCUSDT", "ETHUSDT"]
        assert records == 2
        assert timeout_sec == 1.5
        return WsStreamIngestResult(payload_count=3, ticker_count=1, candle_1m_count=1)

    monkeypatch.setattr(
        "prep_watchdeck.interfaces.cli.ws_smoke_from_bitget",
        fake_ws_smoke_from_bitget,
    )

    result = runner.invoke(
        app,
        [
            "ws-smoke",
            "--symbols",
            "btcusdt,ethusdt",
            "--records",
            "2",
            "--timeout-sec",
            "1.5",
        ],
    )

    assert result.exit_code == 0
    assert "ws-smoke ingested" in result.output
    assert "payloads=3" in result.output
    assert "tickers=1" in result.output
    assert "candles1m=1" in result.output


class FakeCandleFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, int]] = []

    async def __call__(
        self, symbol: str, product_type: str, granularity: str, limit: int
    ) -> list[CandleBar]:
        self.calls.append((symbol, product_type, granularity, limit))
        return [
            CandleBar(
                symbol=symbol,
                ts=1_781_000_000_000,
                open=Decimal("1.0"),
                high=Decimal("1.2"),
                low=Decimal("0.9"),
                close=Decimal("1.1"),
                base_vol=Decimal("100"),
                quote_vol=Decimal("110"),
            ),
            CandleBar(
                symbol=symbol,
                ts=1_781_000_060_000,
                open=Decimal("1.1"),
                high=Decimal("1.4"),
                low=Decimal("1.0"),
                close=Decimal("1.3"),
                base_vol=Decimal("120"),
                quote_vol=Decimal("156"),
            ),
        ]


class FakeUniverseFetcher:
    async def fetch_contracts(self, product_type: str) -> list[ContractInfo]:
        return [
            contract("ALTUSDT", product_type),
            contract("BIGUSDT", product_type),
            contract("BTCUSDT", product_type),
            contract("RWAUSDT", product_type, is_rwa=True),
            contract("DEADUSDT", product_type, symbol_status="off"),
        ]

    async def fetch_tickers(self, product_type: str) -> list[TickerInfo]:
        _ = product_type
        return [
            ticker("ALTUSDT", "1000000"),
            ticker("BIGUSDT", "30000000"),
            ticker("BTCUSDT", "1000000"),
            ticker("RWAUSDT", "1000000"),
            ticker("DEADUSDT", "1000000"),
        ]


def contract(
    symbol: str,
    product_type: str,
    *,
    is_rwa: bool = False,
    symbol_status: str = "normal",
) -> ContractInfo:
    return ContractInfo.model_validate(
        {
            "symbol": symbol,
            "productType": product_type,
            "baseCoin": symbol.replace("USDT", ""),
            "quoteCoin": "USDT",
            "symbolType": "perpetual",
            "symbolStatus": symbol_status,
            "minTradeUSDT": "5",
            "maxLever": "25",
            "isRwa": is_rwa,
        }
    )


def ticker(symbol: str, usdt_volume: str) -> TickerInfo:
    return TickerInfo.model_validate(
        {
            "symbol": symbol,
            "ts": 1_781_000_000_000,
            "lastPr": "1.23",
            "high24h": "1.40",
            "low24h": "0.80",
            "change24h": "0.05",
            "usdtVolume": usdt_volume,
            "fundingRate": "0.0001",
            "holdingAmount": "12345",
        }
    )


def test_open_interest_store_is_idempotent_ordered_bounded_and_restart_safe(tmp_path) -> None:
    db_path = tmp_path / "watchdeck.duckdb"
    store = DuckDbServiceStore(db_path)
    bucket_ts_ms = 1_781_000_000_000 - (1_781_000_000_000 % 300_000)
    cutoff_ts_ms = bucket_ts_ms - 24 * 60 * 60 * 1000
    old_bucket_ts_ms = cutoff_ts_ms - 300_000

    store.initialize()
    store.upsert_open_interest_samples(
        [
            OpenInterestSampleRecord(
                symbol="ALTUSDT",
                bucket_ts_ms=bucket_ts_ms,
                holding_amount=100.0,
                source_ts_ms=bucket_ts_ms + 1_000,
                updated_at_ms=bucket_ts_ms + 2_000,
            ),
            OpenInterestSampleRecord(
                symbol="ALTUSDT",
                bucket_ts_ms=cutoff_ts_ms,
                holding_amount=80.0,
                source_ts_ms=cutoff_ts_ms + 1_000,
                updated_at_ms=bucket_ts_ms,
            ),
            OpenInterestSampleRecord(
                symbol="ALTUSDT",
                bucket_ts_ms=old_bucket_ts_ms,
                holding_amount=70.0,
                source_ts_ms=old_bucket_ts_ms + 1_000,
                updated_at_ms=bucket_ts_ms,
            ),
        ]
    )
    store.upsert_open_interest_samples(
        [
            OpenInterestSampleRecord(
                symbol="ALTUSDT",
                bucket_ts_ms=bucket_ts_ms,
                holding_amount=50.0,
                source_ts_ms=bucket_ts_ms + 500,
                updated_at_ms=bucket_ts_ms + 3_000,
            ),
            OpenInterestSampleRecord(
                symbol="ALTUSDT",
                bucket_ts_ms=bucket_ts_ms,
                holding_amount=110.0,
                source_ts_ms=bucket_ts_ms + 1_500,
                updated_at_ms=bucket_ts_ms + 4_000,
            ),
        ]
    )

    rows = store.load_open_interest_samples(old_bucket_ts_ms, bucket_ts_ms)
    current = next(row for row in rows if row.bucket_ts_ms == bucket_ts_ms)
    assert current.holding_amount == 110.0
    assert current.source_ts_ms == bucket_ts_ms + 1_500

    assert store.delete_open_interest_samples_before(cutoff_ts_ms) == 1
    restarted = DuckDbServiceStore(db_path)
    restarted.initialize()
    retained = restarted.load_open_interest_samples(old_bucket_ts_ms, bucket_ts_ms)

    assert {row.bucket_ts_ms for row in retained} == {cutoff_ts_ms, bucket_ts_ms}


def test_service_store_schema_failure_is_startup_failure(tmp_path, monkeypatch) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")

    def fail_schema(_connection) -> None:
        raise RuntimeError("schema failed")

    monkeypatch.setattr(store, "_ensure_schema", fail_schema)

    with pytest.raises(RuntimeError, match="schema failed"):
        store.initialize()
