from __future__ import annotations

import asyncio
import os
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import aiohttp
import psycopg
import pytest
from psycopg.types.json import Jsonb

from prep_watchdeck_market.candle_endpoint_recovery import (
    CandleEndpointRecovery,
    load_missing_endpoints,
)
from prep_watchdeck_market.candle_recovery_store import RecoveryTarget
from prep_watchdeck_market.candles import Candle1m
from prep_watchdeck_market.runtime_lock import exclusive_runtime_lock
from prep_watchdeck_market.sources.candle_history import (
    HistoryFetchResult,
    NativeCandleHistoryClient,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.usefixtures("isolated_feature_database")
MODULE = "prep_watchdeck_market.candle_endpoint_recovery"


def _target(symbol: str, version_id: int = 1) -> RecoveryTarget:
    return RecoveryTarget(
        version_id,
        "hyperliquid",
        symbol,
        "a" * 64,
        datetime(2026, 8, 27, tzinfo=UTC),
        "BTC",
        "USDC",
        "USDC",
    )


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _fake_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_Connection, list[dict[str, Any]]]:
    connection = _Connection()
    audits: list[dict[str, Any]] = []

    async def open_connection(_url: str, *, apply: bool) -> psycopg.Connection[Any]:
        assert apply
        return cast(psycopg.Connection[Any], connection)

    monkeypatch.setattr(f"{MODULE}._open_connection", open_connection)
    monkeypatch.setattr(f"{MODULE}.start_recovery_run", lambda *_a, **_k: None)
    monkeypatch.setattr(f"{MODULE}.finish_recovery_run", lambda *_a, **kw: audits.append(kw))
    return connection, audits


def test_endpoints_refresh_cutoff_and_resume_after_the_last_requested_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    connection, audits = _fake_connection(monkeypatch)
    now = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)
    targets = [_target(symbol, index + 1) for index, symbol in enumerate(("A", "B", "C", "D"))]
    requested: list[tuple[str, datetime]] = []
    scans: list[datetime] = []

    def scan(_connection, *, now: datetime, version_id: int | None = None):
        scans.append(now)
        bucket = now.replace(second=0, microsecond=0) - timedelta(minutes=4)
        return {target: (bucket,) for target in targets if version_id in (None, target.version_id)}

    class Client:
        def __init__(self, _session, **kwargs):
            assert kwargs["min_interval_seconds"] == 3
            self.request_count = 0

        async def fetch_missing(self, target, missing, **kwargs):
            assert kwargs == {"max_pages": 2, "coalesce": True, "newest_first": True}
            nonlocal now
            requested.append((target.source_symbol, missing[0]))
            self.request_count += 1
            now += timedelta(minutes=1)
            return HistoryFetchResult((), 0, 1)

    monkeypatch.setattr(f"{MODULE}.load_missing_endpoints", scan)
    monkeypatch.setattr(f"{MODULE}._remaining_snapshot", lambda _c, before: before)
    monkeypatch.setattr(f"{MODULE}.NativeCandleHistoryClient", Client)
    monkeypatch.setattr(f"{MODULE}.ENDPOINT_MAX_REQUESTS", 2)

    async def exercise():
        recovery = CandleEndpointRecovery("unused", tmp_path, utc_clock=lambda: now)
        session = cast(aiohttp.ClientSession, object())
        first = await recovery.run(session)
        second = await recovery.run(session)
        return first, second

    first, second = asyncio.run(exercise())
    assert [symbol for symbol, _ in requested] == ["A", "B", "C", "D"]
    assert requested[1][1] - requested[0][1] == timedelta(minutes=1)
    assert first.summary.http_requests == second.summary.http_requests == 2
    assert first.summary.inserted == second.summary.inserted == 0
    assert first.summary.deferred_targets == second.summary.deferred_targets == 2
    assert first.summary.missing_before == first.summary.remaining == 5
    assert second.summary.missing_before == second.summary.remaining == 5
    assert all(audit["metrics"]["recoveryMode"] == "endpoints" for audit in audits)
    assert connection.closed


def test_new_cutoff_missing_keys_are_included_in_insert_and_rescan_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, audits = _fake_connection(monkeypatch)
    initial_now = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)
    now = initial_now
    target = _target("BTC")
    initial_bucket = initial_now - timedelta(minutes=4)
    saved: set[datetime] = set()

    def scan(_connection, *, now: datetime, version_id: int | None = None):
        if version_id is None:
            return {target: (initial_bucket,)}
        return {target: (now - timedelta(minutes=4), now - timedelta(minutes=19))}

    class Client:
        request_count = 0

        def __init__(self, *_a, **_k):
            nonlocal now
            now += timedelta(minutes=1)

        async def fetch_missing(self, received_target, missing, **_kwargs):
            self.request_count += 1
            candles = tuple(
                Candle1m(
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
                for bucket in missing
            )
            return HistoryFetchResult(candles, 0, 1)

    def insert(_connection, _target, candles, **_kwargs):
        saved.update(c.bucket_start for c in candles)
        return len(candles)

    def rescan(_connection, before):
        return {t: tuple(b for b in buckets if b not in saved) for t, buckets in before.items()}

    monkeypatch.setattr(f"{MODULE}.load_missing_endpoints", scan)
    monkeypatch.setattr(f"{MODULE}.NativeCandleHistoryClient", Client)
    monkeypatch.setattr(f"{MODULE}.insert_missing_candles", insert)
    monkeypatch.setattr(f"{MODULE}._remaining_snapshot", rescan)

    async def exercise():
        return await CandleEndpointRecovery("unused", tmp_path, utc_clock=lambda: now).run(
            cast(aiohttp.ClientSession, object())
        )

    result = asyncio.run(exercise())
    assert result.summary.missing_before == 3
    assert result.summary.inserted == result.summary.newly_present == 2
    assert result.summary.remaining == 1
    assert result.window.end == initial_now - timedelta(minutes=2)
    assert (
        audits[-1]["metrics"]["initialCutoff"] == (initial_now - timedelta(minutes=3)).isoformat()
    )
    assert audits[-1]["metrics"]["lastTargetCutoff"] == result.window.end.isoformat()


def test_endpoint_cancellation_joins_insert_and_finalizes_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    connection, audits = _fake_connection(monkeypatch)
    now = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)
    target = _target("BTC")
    bucket = now - timedelta(minutes=4)
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
        source_at=bucket + timedelta(seconds=59),
        observed_at=now,
    )
    insert_started = threading.Event()
    release_insert = threading.Event()

    class Client:
        request_count = 1

        def __init__(self, *_a, **_k):
            pass

        async def fetch_missing(self, *_a, **_k):
            return HistoryFetchResult((candle,), 0, 1)

    def insert(_connection, received_target, candles, *, run_id):
        assert received_target == target and candles == (candle,)
        insert_started.set()
        assert release_insert.wait(timeout=2)
        return 1

    monkeypatch.setattr(f"{MODULE}.load_missing_endpoints", lambda *_a, **_k: {target: (bucket,)})
    monkeypatch.setattr(f"{MODULE}.NativeCandleHistoryClient", Client)
    monkeypatch.setattr(f"{MODULE}.insert_missing_candles", insert)

    async def exercise():
        recovery = CandleEndpointRecovery("unused", tmp_path, utc_clock=lambda: now)
        task = asyncio.create_task(recovery.run(cast(aiohttp.ClientSession, object())))
        assert await asyncio.to_thread(insert_started.wait, 1)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done() and not connection.closed
        release_insert.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        with exclusive_runtime_lock(tmp_path / "control" / "candle-endpoint-recovery.lock"):
            pass

    asyncio.run(exercise())
    assert audits[-1]["status"] == "failed" and audits[-1]["inserted"] == 1
    assert connection.closed


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires isolated TEST_DATABASE_URL")
def test_endpoint_sql_version_start_existing_rows_and_native_insert_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert TEST_DATABASE_URL is not None
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    cutoff = now - timedelta(minutes=3)
    symbol = f"PWEND{uuid4().hex[:8].upper()}"
    digest = uuid4().hex * 2
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        payload = connection.execute(
            """INSERT INTO raw_catalog_payloads (
                venue, endpoint, source_kind, documentation_url,
                payload_hash, observed_at, last_observed_at, payload
            ) VALUES ('hyperliquid', '/catalog', 'native_rest', 'https://example.invalid',
                      %s, %s, %s, %s) RETURNING raw_catalog_payload_id""",
            (digest, now, now, Jsonb({"symbol": symbol})),
        ).fetchone()
        assert payload is not None
        version = connection.execute(
            """INSERT INTO venue_instrument_versions (
                venue, source_symbol, definition_hash, valid_from, active, asset_class,
                market_type, base_asset, quote_asset, settle_asset, quantity_unit,
                contract_multiplier, raw_definition, raw_catalog_payload_id
            ) VALUES ('hyperliquid', %s, %s, %s, true, 'crypto', 'linear_perpetual',
                      'BTC', 'USDC', 'USDC', 'base', 1, '{}'::jsonb, %s)
            RETURNING venue_instrument_version_id""",
            (symbol, digest, cutoff - timedelta(minutes=20), payload[0]),
        ).fetchone()
        assert version is not None
        version_id = version[0]
        connection.execute(
            """INSERT INTO candle_1m (
                venue_instrument_version_id, bucket_at, open_price, high_price,
                low_price, close_price, finality, observed_at
            ) VALUES (%s, %s, 100, 101, 99, 100, 'derived_final', %s)""",
            (version_id, cutoff - timedelta(minutes=16), now),
        )
        snapshot = load_missing_endpoints(connection, now=now, version_id=version_id)
        target = next(iter(snapshot))
        assert snapshot[target] == (cutoff - timedelta(minutes=1),)
        connection.execute(
            "UPDATE venue_instrument_versions SET valid_to=%s WHERE venue_instrument_version_id=%s",
            (now, version_id),
        )
        assert load_missing_endpoints(connection, now=now, version_id=version_id) == {}
        connection.execute(
            "UPDATE venue_instrument_versions SET valid_to=NULL "
            "WHERE venue_instrument_version_id=%s",
            (version_id,),
        )

        async def exercise():
            recovery = CandleEndpointRecovery(TEST_DATABASE_URL, tmp_path, utc_clock=lambda: now)
            async with aiohttp.ClientSession() as session:

                async def fetch(_client, received_target, missing, **kwargs):
                    assert received_target.version_id == version_id
                    assert missing == (cutoff - timedelta(minutes=1),)
                    candle = Candle1m(
                        venue="hyperliquid",
                        source_symbol=symbol,
                        bucket_start=missing[0],
                        open_price=Decimal("110"),
                        high_price=Decimal("111"),
                        low_price=Decimal("109"),
                        close_price=Decimal("110"),
                        volume_base=Decimal("0"),
                        volume_notional=None,
                        trade_count=0,
                        finality="derived_final",
                        source_at=None,
                        observed_at=now,
                    )
                    return HistoryFetchResult((candle,), 0, 1)

                monkeypatch.setattr(NativeCandleHistoryClient, "fetch_missing", fetch)
                return await recovery.run(session)

        result = asyncio.run(exercise())
        assert result.execution == "succeeded" and result.summary.inserted == 1
        assert result.summary.missing_before == result.summary.newly_present == 1
        assert result.summary.remaining == 0
        assert connection.execute(
            "SELECT close_price FROM candle_1m "
            "WHERE venue_instrument_version_id=%s AND bucket_at=%s",
            (version_id, cutoff - timedelta(minutes=16)),
        ).fetchone() == (Decimal("100"),)
        assert load_missing_endpoints(connection, now=now, version_id=version_id) == {}
