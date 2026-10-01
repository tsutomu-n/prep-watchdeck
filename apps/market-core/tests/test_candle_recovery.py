from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import aiohttp
import psycopg
import pytest
from aiohttp import web
from psycopg.types.json import Jsonb

from prep_watchdeck_market.candle_recovery import (
    CandleRecovery,
    RecoveryWindowRequest,
    recovery_window,
)
from prep_watchdeck_market.candle_recovery_store import (
    RecoveryTarget,
    RecoveryVersionChanged,
    insert_missing_candles,
    load_recovery_targets,
    scan_missing_candles,
    start_recovery_run,
)
from prep_watchdeck_market.candle_store import upsert_candles
from prep_watchdeck_market.candles import Candle1m
from prep_watchdeck_market.runtime_lock import exclusive_runtime_lock
from prep_watchdeck_market.sources.bitget_candles import parse_bitget_history_candles
from prep_watchdeck_market.sources.candle_history import (
    HistoryBudgetExceeded,
    HistoryFetchError,
    HistoryRateLimited,
    NativeCandleHistoryClient,
    _parse_hyperliquid_page,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.usefixtures("isolated_feature_database")


def _now() -> datetime:
    return datetime.now(UTC).replace(second=0, microsecond=0)


def _target(symbol: str, start: datetime) -> RecoveryTarget:
    return RecoveryTarget(
        version_id=1,
        venue="bitget",
        source_symbol=symbol,
        definition_hash="a" * 64,
        valid_from=start - timedelta(minutes=1),
        base_asset="BTC",
        quote_asset="USDT",
        settle_asset="USDT",
    )


def _bitget_row(bucket: datetime, price: str = "100") -> list[str]:
    return [str(int(bucket.timestamp() * 1000)), price, "102", "99", "101", "5", "505"]


def test_recovery_window_and_full_bitget_history_parser() -> None:
    now = _now() + timedelta(seconds=7)
    window = recovery_window(now)
    assert window.end == _now() - timedelta(minutes=3)
    assert window.end - window.start == timedelta(hours=6)
    with pytest.raises(ValueError):
        recovery_window(now, since=window.start, until=now)
    rows = [_bitget_row(window.start + timedelta(minutes=index)) for index in range(8)]
    candles, conflicts = parse_bitget_history_candles(
        {"code": "00000", "data": rows}, source_symbol="BTCUSDT", observed_at=now
    )
    assert len(candles) == 8  # The live poll's last-three slice must not affect history.
    assert conflicts == ()
    assert all(item.finality == "confirmed" and item.observed_at == now for item in candles)
    assert all(item.source_at is None for item in candles)
    rows.append(_bitget_row(window.start + timedelta(minutes=3), "101"))
    candles, conflicts = parse_bitget_history_candles(
        {"code": "00000", "data": rows}, source_symbol="BTCUSDT", observed_at=now
    )
    assert len(candles) == 7
    assert conflicts == (window.start + timedelta(minutes=3),)


def test_hyperliquid_close_timestamp_and_partial_page_budget() -> None:
    now = _now()
    start = now - timedelta(minutes=15)
    hl = RecoveryTarget(
        version_id=10,
        venue="hyperliquid",
        source_symbol="BTC",
        definition_hash="b" * 64,
        valid_from=start - timedelta(minutes=1),
        base_asset="BTC",
        quote_asset="USDC",
        settle_asset="USDC",
    )
    row = {
        "t": int(start.timestamp() * 1000),
        "T": int(start.timestamp() * 1000) + 59_999,
        "s": "BTC",
        "i": "1m",
        "o": "100",
        "h": "102",
        "l": "99",
        "c": "101",
        "v": "5",
        "n": 3,
    }
    candle = _parse_hyperliquid_page([row], hl, observed_at=now)[0]
    assert candle.finality == "derived_final"
    assert candle.bucket_start == start
    assert candle.observed_at == now

    async def exercise() -> None:
        async with aiohttp.ClientSession() as session:
            client = NativeCandleHistoryClient(session, max_requests=10, deadline_seconds=30)
            target = _target("BTCUSDT", start)
            calls = 0

            async def fake_request(*_args: object, **_kwargs: object) -> tuple[object, datetime]:
                nonlocal calls
                calls += 1
                return {
                    "code": "00000",
                    "data": [
                        _bitget_row(start + timedelta(minutes=2)),
                        _bitget_row(start + timedelta(minutes=3)),
                    ],
                }, now

            client._request_json = fake_request  # type: ignore[method-assign]
            result = await client.fetch_missing(
                target,
                tuple(start + timedelta(minutes=index) for index in range(4)),
                max_pages=1,
            )
            assert calls == 1
            assert result.budget_scope == "target"
            assert [item.bucket_start for item in result.candles] == [
                start + timedelta(minutes=2),
                start + timedelta(minutes=3),
            ]

    asyncio.run(exercise())


def test_history_timeout_retries_have_a_bounded_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimeoutSession:
        def request(self, *_args: object, **_kwargs: object) -> object:
            raise TimeoutError("secret URL from transport")

    monkeypatch.setattr(
        "prep_watchdeck_market.sources.candle_history.MIN_REQUEST_INTERVAL_SECONDS", 0.0
    )

    async def exercise() -> None:
        client = NativeCandleHistoryClient(
            cast(aiohttp.ClientSession, TimeoutSession()),
            max_requests=3,
            deadline_seconds=5,
        )
        with pytest.raises(HistoryFetchError, match="history transport unavailable") as error:
            await client._request_json("GET", "https://example.invalid/private")
        assert "secret" not in str(error.value)
        assert client.request_count == 3

    asyncio.run(exercise())


def test_history_request_timeout_uses_the_remaining_run_budget() -> None:
    async def exercise() -> None:
        async def handler(_request: web.Request) -> web.Response:
            await asyncio.sleep(0.2)
            return web.json_response([])

        application = web.Application()
        application.router.add_get("/history", handler)
        runner = web.AppRunner(application)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        try:
            port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
            async with aiohttp.ClientSession() as session:
                client = NativeCandleHistoryClient(session, max_requests=10, deadline_seconds=0.03)
                with pytest.raises(HistoryBudgetExceeded):
                    await asyncio.wait_for(
                        client._request_json("GET", f"http://127.0.0.1:{port}/history"),
                        timeout=0.15,
                    )
                assert client.request_count == 1
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_bitget_rounded_exclusive_end_keeps_the_last_expected_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = _now() - timedelta(minutes=20)
    expected = tuple(start + timedelta(minutes=i) for i in range(6))

    async def exercise() -> None:
        async def handler(request: web.Request) -> web.Response:
            end_ms = int(request.query["endTime"])
            rounded = datetime.fromtimestamp((end_ms // 60_000) * 60, tz=UTC)
            return web.json_response(
                {
                    "code": "00000",
                    "data": [_bitget_row(rounded - timedelta(minutes=i)) for i in range(6, 0, -1)],
                }
            )

        application = web.Application()
        application.router.add_get("/history", handler)
        runner = web.AppRunner(application)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        try:
            port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
            monkeypatch.setattr(
                "prep_watchdeck_market.sources.candle_history.BITGET_HISTORY_URL",
                f"http://127.0.0.1:{port}/history",
            )
            async with aiohttp.ClientSession() as session:
                client = NativeCandleHistoryClient(session, max_requests=1, deadline_seconds=5)
                result = await client.fetch_missing(
                    _target("BTCUSDT", start), expected, max_pages=1
                )
                assert tuple(x.bucket_start for x in result.candles) == expected
                assert result.budget_scope is None and client.request_count == 1
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires isolated TEST_DATABASE_URL")
def test_scan_budget_defers_unscanned_targets_without_inventing_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert TEST_DATABASE_URL is not None
    start = _now() - timedelta(minutes=12)
    targets = (_target("BTCUSDT", start), _target("ETHUSDT", start))
    scanned = []

    def slow_scan(_connection: object, target: RecoveryTarget, **_kwargs: object):
        scanned.append(target)
        time.sleep(0.04)
        return ()

    monkeypatch.setattr("prep_watchdeck_market.candle_recovery.AUTOMATIC_RUN_SECONDS", 0.02)
    monkeypatch.setattr(
        "prep_watchdeck_market.candle_recovery.load_recovery_targets", lambda *_a, **_k: targets
    )
    monkeypatch.setattr("prep_watchdeck_market.candle_recovery.scan_missing_candles", slow_scan)

    async def exercise():
        async with aiohttp.ClientSession() as session:
            return await CandleRecovery(TEST_DATABASE_URL, tmp_path).run(
                session,
                RecoveryWindowRequest(start, start + timedelta(minutes=3)),
                apply=True,
                trigger="startup",
            )

    state = asyncio.run(exercise())
    assert scanned == [targets[0]]
    assert state.execution == "partial" and state.error_code == "recovery_budget_exceeded"
    assert state.summary.scanned_target_count == 1 and state.summary.deferred_targets == 2
    assert state.summary.missing_before is None and state.summary.remaining is None
    assert state.summary.http_requests == 0
    assert state.details[0].missing_before == 0 and state.details[0].remaining is None
    assert state.details[1].missing_before is None
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        try:
            assert connection.execute(
                "SELECT status FROM collector_runs WHERE run_id=%s", (UUID(hex=state.run_id),)
            ).fetchone() == ("partial",)
        finally:
            connection.execute(
                "DELETE FROM collector_runs WHERE run_id=%s", (UUID(hex=state.run_id),)
            )


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires isolated TEST_DATABASE_URL")
def test_recovery_internal_gap_insert_only_and_version_lock(tmp_path: Path) -> None:
    assert TEST_DATABASE_URL is not None
    symbol = f"PWREC{uuid4().hex[:8].upper()}USDT"
    digest = uuid4().hex * 2
    now = _now()
    start = now - timedelta(minutes=12)
    payload_id: int | None = None
    version_id: int | None = None
    run_id = uuid4()
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        try:
            row = connection.execute(
                """
                INSERT INTO raw_catalog_payloads (
                    venue, endpoint, source_kind, documentation_url,
                    payload_hash, observed_at, last_observed_at, payload
                ) VALUES ('bitget', '/catalog', 'native_rest', 'https://example.invalid',
                          %s, %s, %s, %s) RETURNING raw_catalog_payload_id
                """,
                (digest, now, now, Jsonb({"symbol": symbol})),
            ).fetchone()
            assert row is not None
            payload_id = row[0]
            row = connection.execute(
                """
                INSERT INTO venue_instrument_versions (
                    venue, source_symbol, definition_hash, valid_from, active, asset_class,
                    market_type, base_asset, quote_asset, settle_asset, quantity_unit,
                    contract_multiplier, raw_definition, raw_catalog_payload_id
                ) VALUES ('bitget', %s, %s, %s, true, 'crypto', 'linear_perpetual',
                          'BTC', 'USDT', 'USDT', 'base', 1, '{}'::jsonb, %s)
                RETURNING venue_instrument_version_id
                """,
                (symbol, digest, start - timedelta(minutes=1), payload_id),
            ).fetchone()
            assert row is not None
            version_id = row[0]
            for bucket in (start, start + timedelta(minutes=2)):
                connection.execute(
                    """
                    INSERT INTO candle_1m (
                        venue_instrument_version_id, bucket_at, open_price, high_price,
                        low_price, close_price, finality, observed_at
                    ) VALUES (%s, %s, 100, 102, 99, 101, 'confirmed', %s)
                    """,
                    (version_id, bucket, now),
                )
            start_recovery_run(connection, run_id, now, metrics={"test": True})
            targets = load_recovery_targets(connection, instrument_id=f"bitget:{symbol}")
            assert len(targets) == 1
            target = targets[0]
            assert scan_missing_candles(
                connection, target, start=start, end=start + timedelta(minutes=3)
            ) == (start + timedelta(minutes=1),)
            recovered = Candle1m(
                venue="bitget",
                source_symbol=symbol,
                bucket_start=start + timedelta(minutes=1),
                open_price=Decimal("100.125"),
                high_price=Decimal("102.25"),
                low_price=Decimal("99.5"),
                close_price=Decimal("101.75"),
                volume_base=None,
                volume_notional=None,
                trade_count=None,
                finality="confirmed",
                source_at=None,
                observed_at=now,
            )
            assert insert_missing_candles(connection, target, [recovered], run_id=run_id) == 1
            assert insert_missing_candles(connection, target, [recovered], run_id=run_id) == 0
            assert (
                scan_missing_candles(
                    connection, target, start=start, end=start + timedelta(minutes=3)
                )
                == ()
            )
            assert connection.execute(
                "SELECT open_price FROM candle_1m "
                "WHERE venue_instrument_version_id=%s AND bucket_at=%s",
                (version_id, start),
            ).fetchone() == (Decimal("100"),)
            race_bucket = start + timedelta(minutes=3)
            recovery_race = replace(recovered, bucket_start=race_bucket)
            live_race = replace(
                recovered,
                bucket_start=race_bucket,
                open_price=Decimal("110"),
                high_price=Decimal("112"),
                low_price=Decimal("109"),
                close_price=Decimal("111"),
                observed_at=now + timedelta(seconds=1),
            )
            barrier = threading.Barrier(2)

            def race_live() -> None:
                with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as participant:
                    barrier.wait(timeout=3)
                    upsert_candles(participant, [live_race])

            def race_recovery() -> None:
                with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as participant:
                    barrier.wait(timeout=3)
                    insert_missing_candles(participant, target, [recovery_race], run_id=run_id)

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = (pool.submit(race_live), pool.submit(race_recovery))
                for future in futures:
                    future.result(timeout=5)
            assert connection.execute(
                "SELECT open_price, collector_run_id FROM candle_1m "
                "WHERE venue_instrument_version_id=%s AND bucket_at=%s",
                (version_id, race_bucket),
            ).fetchone() == (Decimal("110"), None)
            connection.execute(
                "UPDATE venue_instrument_versions SET definition_hash=%s "
                "WHERE venue_instrument_version_id=%s",
                ("c" * 64, version_id),
            )
            with pytest.raises(RecoveryVersionChanged):
                insert_missing_candles(connection, target, [recovered], run_id=run_id)
        finally:
            if version_id is not None:
                connection.execute(
                    "DELETE FROM candle_1m WHERE venue_instrument_version_id=%s", (version_id,)
                )
                connection.execute(
                    "DELETE FROM venue_instrument_versions WHERE venue_instrument_version_id=%s",
                    (version_id,),
                )
            connection.execute("DELETE FROM collector_runs WHERE run_id=%s", (run_id,))
            if payload_id is not None:
                connection.execute(
                    "DELETE FROM raw_catalog_payloads WHERE raw_catalog_payload_id=%s",
                    (payload_id,),
                )


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires isolated TEST_DATABASE_URL")
def test_cancel_while_connecting_closes_the_returned_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert TEST_DATABASE_URL is not None
    entered = threading.Event()
    release = threading.Event()
    original_connect = psycopg.connect
    connections = []

    def delayed_connect(database_url: str, *, connect_timeout: int, options: str, autocommit: bool):
        connection = original_connect(
            database_url, connect_timeout=connect_timeout, options=options, autocommit=autocommit
        )
        connections.append(connection)
        entered.set()
        assert release.wait(3)
        return connection

    monkeypatch.setattr("prep_watchdeck_market.candle_recovery.psycopg.connect", delayed_connect)

    async def exercise() -> None:
        async with aiohttp.ClientSession() as session:
            start = _now() - timedelta(minutes=12)
            task = asyncio.create_task(
                CandleRecovery(TEST_DATABASE_URL, tmp_path).run(
                    session,
                    RecoveryWindowRequest(start, start + timedelta(minutes=3)),
                    apply=True,
                )
            )
            try:
                assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 3), timeout=4)
                task.cancel()
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(exercise())
    assert len(connections) == 1 and connections[0].closed
    assert not (tmp_path / "artifacts" / "candle-recovery-state.json").exists()
    with exclusive_runtime_lock(tmp_path / "control" / "candle-recovery.lock"):
        pass


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires isolated TEST_DATABASE_URL")
@pytest.mark.parametrize("phase", ["start", "targets"])
def test_recovery_cancel_finishes_run_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    assert TEST_DATABASE_URL is not None
    entered = threading.Event()
    release = threading.Event()

    def paused_targets(*_args: object, **_kwargs: object) -> tuple[()]:
        entered.set()
        assert release.wait(3)
        return ()

    if phase == "targets":
        monkeypatch.setattr(
            "prep_watchdeck_market.candle_recovery.load_recovery_targets", paused_targets
        )
    else:

        def paused_start(*args, **kwargs):
            start_recovery_run(*args, **kwargs)
            entered.set()
            assert release.wait(3)

        monkeypatch.setattr(
            "prep_watchdeck_market.candle_recovery.start_recovery_run", paused_start
        )

    async def exercise() -> None:
        async with aiohttp.ClientSession() as session:
            recovery = CandleRecovery(TEST_DATABASE_URL, tmp_path)
            start = _now() - timedelta(minutes=12)
            task = asyncio.create_task(
                recovery.run(
                    session,
                    RecoveryWindowRequest(start, start + timedelta(minutes=3)),
                    apply=True,
                )
            )
            try:
                assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 3), timeout=4)
                task.cancel()
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(exercise())
    state_path = tmp_path / "artifacts" / "candle-recovery-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["execution"] == "failed"
    assert state["finishedAt"] is not None
    with exclusive_runtime_lock(tmp_path / "control" / "candle-recovery.lock"):
        pass
    run_id = UUID(hex=state["runId"])
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        try:
            assert connection.execute(
                "SELECT status, error_code FROM collector_runs WHERE run_id=%s", (run_id,)
            ).fetchone() == ("failed", "recovery_run_failed")
        finally:
            connection.execute("DELETE FROM collector_runs WHERE run_id=%s", (run_id,))


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires isolated TEST_DATABASE_URL")
def test_recovery_http_to_database_to_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert TEST_DATABASE_URL is not None
    symbol = f"PWHTTP{uuid4().hex[:8].upper()}USDT"
    digest = uuid4().hex * 2
    now = _now()
    start = now - timedelta(minutes=12)
    missing_bucket = start + timedelta(minutes=1)
    version_id: int | None = None
    payload_id: int | None = None
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        try:
            row = connection.execute(
                """
                INSERT INTO raw_catalog_payloads (
                    venue, endpoint, source_kind, documentation_url,
                    payload_hash, observed_at, last_observed_at, payload
                ) VALUES ('bitget', '/catalog', 'native_rest', 'https://example.invalid',
                          %s, %s, %s, %s) RETURNING raw_catalog_payload_id
                """,
                (digest, now, now, Jsonb({"symbol": symbol})),
            ).fetchone()
            assert row is not None
            payload_id = row[0]
            row = connection.execute(
                """
                INSERT INTO venue_instrument_versions (
                    venue, source_symbol, definition_hash, valid_from, active, asset_class,
                    market_type, base_asset, quote_asset, settle_asset, quantity_unit,
                    contract_multiplier, raw_definition, raw_catalog_payload_id
                ) VALUES ('bitget', %s, %s, %s, true, 'crypto', 'linear_perpetual',
                          'BTC', 'USDT', 'USDT', 'base', 1, '{}'::jsonb, %s)
                RETURNING venue_instrument_version_id
                """,
                (symbol, digest, start - timedelta(minutes=1), payload_id),
            ).fetchone()
            assert row is not None
            version_id = row[0]
            for bucket in (start, start + timedelta(minutes=2)):
                connection.execute(
                    """
                    INSERT INTO candle_1m (
                        venue_instrument_version_id, bucket_at, open_price, high_price,
                        low_price, close_price, finality, observed_at
                    ) VALUES (%s, %s, 100, 102, 99, 101, 'confirmed', %s)
                    """,
                    (version_id, bucket, now),
                )

            async def exercise() -> None:
                status = 200
                calls: list[dict[str, str]] = []

                async def handler(request: web.Request) -> web.Response:
                    calls.append(dict(request.query))
                    if status == 429:
                        return web.Response(status=429, headers={"Retry-After": "12"})
                    return web.json_response(
                        {"code": "00000", "data": [_bitget_row(missing_bucket)]}
                    )

                application = web.Application()
                application.router.add_get("/history", handler)
                runner = web.AppRunner(application)
                await runner.setup()
                site = web.TCPSite(runner, "127.0.0.1", 0)
                await site.start()
                try:
                    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
                    monkeypatch.setattr(
                        "prep_watchdeck_market.sources.candle_history.BITGET_HISTORY_URL",
                        f"http://127.0.0.1:{port}/history",
                    )
                    monkeypatch.setattr(
                        "prep_watchdeck_market.sources.candle_history.MIN_REQUEST_INTERVAL_SECONDS",
                        0.0,
                    )
                    async with aiohttp.ClientSession() as session:
                        recovery = CandleRecovery(TEST_DATABASE_URL, tmp_path)
                        state = await recovery.run(
                            session,
                            RecoveryWindowRequest(start, start + timedelta(minutes=3)),
                            apply=True,
                            instrument_id=f"bitget:{symbol}",
                        )
                        assert state.execution == "succeeded"
                        assert state.summary.missing_before == 1
                        assert state.summary.inserted == 1
                        assert state.summary.remaining == 0
                        assert state.summary.http_requests == 1
                        assert calls == [
                            {
                                "symbol": symbol,
                                "productType": "USDT-FUTURES",
                                "granularity": "1m",
                                "startTime": str(int(missing_bucket.timestamp() * 1000)),
                                "endTime": str(
                                    int((missing_bucket + timedelta(minutes=1)).timestamp() * 1000)
                                ),
                                "limit": "200",
                            }
                        ]
                        assert (tmp_path / "artifacts" / "candle-recovery-state.json").exists()
                        status = 429
                        client = NativeCandleHistoryClient(
                            session, max_requests=2, deadline_seconds=5
                        )
                        with pytest.raises(HistoryRateLimited) as rate:
                            await client._request_json("GET", f"http://127.0.0.1:{port}/history")
                        assert rate.value.retry_after_seconds == 12
                        extended = RecoveryWindowRequest(start, start + timedelta(minutes=4))
                        first_limited = await recovery.run(
                            session, extended, apply=True, instrument_id=f"bitget:{symbol}"
                        )
                        assert first_limited.summary.http_requests == 1
                        assert first_limited.summary.failed_targets == 1
                        calls_before = len(calls)
                        second_limited = await recovery.run(
                            session, extended, apply=True, instrument_id=f"bitget:{symbol}"
                        )
                        assert second_limited.summary.http_requests == 0
                        assert second_limited.summary.deferred_targets == 1
                        assert second_limited.summary.remaining == 1
                        assert len(calls) == calls_before
                finally:
                    await runner.cleanup()

            asyncio.run(exercise())
            assert connection.execute(
                "SELECT open_price FROM candle_1m "
                "WHERE venue_instrument_version_id=%s AND bucket_at=%s",
                (version_id, missing_bucket),
            ).fetchone() == (Decimal("100"),)
            cli_env = os.environ.copy()
            cli_env["PREP_WATCHDECK_MARKET_DATABASE_URL"] = TEST_DATABASE_URL
            cli_env["PREP_WATCHDECK_MARKET_STATE_DIR"] = str(tmp_path)
            cli_env["PREP_WATCHDECK_MARKET_ALLOW_NONSTANDARD_DATABASE_TARGET"] = "true"
            command = str(Path(sys.executable).with_name("watchdeck-market"))
            dry_run = subprocess.run(
                [
                    command,
                    "recover-candles",
                    "--instrument",
                    f"bitget:{symbol}",
                    "--since",
                    start.isoformat(),
                    "--until",
                    (start + timedelta(minutes=3)).isoformat(),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=cli_env,
                timeout=30,
            )
            assert dry_run.returncode == 0, dry_run.stdout
            dry_state = json.loads(dry_run.stdout)
            assert dry_state["execution"] == "succeeded"
            assert dry_state["summary"]["missingBefore"] == 0
            assert dry_state["summary"]["inserted"] == 0
        finally:
            if version_id is not None:
                connection.execute(
                    "DELETE FROM candle_1m WHERE venue_instrument_version_id=%s", (version_id,)
                )
                connection.execute(
                    "DELETE FROM venue_instrument_versions WHERE venue_instrument_version_id=%s",
                    (version_id,),
                )
            if payload_id is not None:
                connection.execute(
                    "DELETE FROM raw_catalog_payloads WHERE raw_catalog_payload_id=%s",
                    (payload_id,),
                )
