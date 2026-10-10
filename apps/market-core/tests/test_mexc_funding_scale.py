import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from prep_watchdeck_market.sources import mexc_l1
from prep_watchdeck_market.sources.mexc import parse_mexc_catalog

NOW = datetime(2026, 10, 10, tzinfo=UTC)


def instrument():
    return parse_mexc_catalog(
        envelope(
            [
                {
                    "symbol": "BTC_USDT",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "futureType": 1,
                    "state": 0,
                    "contractSize": "0.0001",
                    "priceUnit": "0.1",
                    "volUnit": 1,
                }
            ]
        ),
        observed_at=NOW,
    ).instruments[0]


def ticker_row():
    return {
        "symbol": "BTC_USDT",
        "fairPrice": "100",
        "indexPrice": "101",
        "bid1": "99",
        "ask1": "100",
        "holdVol": 10000,
        "amount24": "4567",
        "timestamp": int(NOW.timestamp() * 1000),
    }


def envelope(data):
    return {"success": True, "code": 0, "data": data}


def funding_payload(next_at=NOW + timedelta(hours=4)):
    return envelope(
        {
            "symbol": "BTC_USDT",
            "fundingRate": "-.004",
            "collectCycle": 4,
            "nextSettleTime": int(next_at.timestamp() * 1000),
            "timestamp": int(NOW.timestamp() * 1000),
        }
    )


def test_l1_does_not_wait_for_funding_http(monkeypatch):
    async def fetch(session, endpoint, **kwargs):
        if "funding" in endpoint:
            await asyncio.Event().wait()
        return envelope([ticker_row()])

    monkeypatch.setattr(mexc_l1, "fetch_mexc_json", fetch)

    async def run():
        return await asyncio.wait_for(
            mexc_l1.fetch_mexc_l1(None, [instrument()], cycle_at=NOW, observed_at=NOW),
            timeout=0.1,
        )

    batch = asyncio.run(run())
    row = batch.observations[0]
    assert row.mark_price is not None
    assert row.source_at == NOW
    assert row.status == "partial"
    assert row.error_code == "funding_only_partial:funding_missing"


def test_expired_funding_is_null_but_valid_ticker_retained():
    row = mexc_l1.parse_mexc_l1(
        envelope([ticker_row()]),
        {"BTC_USDT": funding_payload()},
        [instrument()],
        cycle_at=NOW,
        observed_at=NOW + timedelta(seconds=90),
    ).observations[0]
    assert row.funding_rate_raw is None
    assert row.funding_interval_seconds is None
    assert row.funding_rate_per_hour is None
    assert row.next_funding_at is None
    assert row.source_at == NOW
    assert row.error_code == "funding_only_partial:funding_expired"


def test_stale_ticker_cannot_be_funding_only_partial():
    row = mexc_l1.parse_mexc_l1(
        envelope([ticker_row()]),
        {},
        [instrument()],
        cycle_at=NOW,
        observed_at=NOW + timedelta(seconds=121),
    ).observations[0]
    assert row.error_code == "incomplete_source_row"


def test_malformed_funding_does_not_poison_ticker_batch():
    row = mexc_l1.parse_mexc_l1(
        envelope([ticker_row()]),
        {"BTC_USDT": {"success": False, "code": 1}},
        [instrument()],
        cycle_at=NOW,
        observed_at=NOW,
    ).observations[0]
    assert row.mark_price is not None
    assert row.funding_rate_raw is None
    assert row.error_code == "funding_only_partial:funding_invalid"


def test_cache_reuse_preserves_real_funding_times_and_contract_change_invalidates():
    from dataclasses import replace

    from prep_watchdeck_market.sources.mexc_funding import funding_snapshot

    item = instrument()
    snapshot = funding_snapshot(funding_payload(), item, observed_at=NOW)
    current = NOW + timedelta(seconds=30)
    ticker = {**ticker_row(), "timestamp": int(current.timestamp() * 1000)}
    row = mexc_l1.parse_mexc_l1(
        envelope([ticker]),
        {"BTC_USDT": snapshot},
        [item],
        cycle_at=NOW,
        observed_at=current,
    ).observations[0]
    assert row.funding_source_at == NOW
    assert row.funding_observed_at == NOW
    assert row.funding_valid_until == NOW + timedelta(seconds=90)
    changed = replace(item, raw_definition={**item.raw_definition, "newContractField": 1})
    invalid = mexc_l1.parse_mexc_l1(
        envelope([ticker]),
        {"BTC_USDT": snapshot},
        [changed],
        cycle_at=NOW,
        observed_at=current,
    ).observations[0]
    assert invalid.mark_price is not None
    assert invalid.funding_rate_raw is None
    assert invalid.error_code == "funding_only_partial:funding_contract_changed"


def test_next_settlement_invalidates_all_funding_values():
    row = mexc_l1.parse_mexc_l1(
        envelope([ticker_row()]),
        {"BTC_USDT": funding_payload(NOW + timedelta(seconds=10))},
        [instrument()],
        cycle_at=NOW,
        observed_at=NOW + timedelta(seconds=10),
    ).observations[0]
    assert (
        row.funding_rate_raw,
        row.funding_interval_seconds,
        row.funding_rate_per_hour,
        row.next_funding_at,
    ) == (None, None, None, None)
    assert row.error_code == "funding_only_partial:funding_settlement_passed"


def test_failed_fetch_invalidates_only_its_instrument(monkeypatch):
    from prep_watchdeck_market.sources import mexc_funding
    from prep_watchdeck_market.sources.common import CatalogSourceError

    item = instrument()

    async def fail(*args, **kwargs):
        raise CatalogSourceError("failed")

    async def run():
        runtime = mexc_funding.MexcFundingRuntime(None, lambda: [item])
        previous = mexc_funding.funding_snapshot(funding_payload(), item, observed_at=NOW)
        runtime.snapshots.update({"BTC_USDT": previous, "OTHER_USDT": previous})
        monkeypatch.setattr(mexc_funding, "fetch_mexc_json", fail)
        await runtime.fetch_one(item)
        assert runtime.snapshots["OTHER_USDT"] is previous
        assert runtime.snapshots["BTC_USDT"].payload is None
        assert runtime.snapshots["BTC_USDT"].error_code == "funding_fetch_failed"

    asyncio.run(run())


def test_funding_runtime_bounds_starts_in_flight_and_cancels_on_stop(monkeypatch):
    from dataclasses import replace

    from prep_watchdeck_market.sources import mexc_funding

    items = [replace(instrument(), source_symbol=f"TEST{i}_USDT") for i in range(10)]
    monkeypatch.setattr(mexc_funding, "FUNDING_START_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(mexc_funding, "FUNDING_SWEEP_SECONDS", 0.3)
    monkeypatch.setattr(mexc_funding, "observed_now", lambda: NOW)

    async def run():
        active = peak = 0
        starts = []
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()

        async def fetch(session, endpoint, **kwargs):
            nonlocal active, peak
            assert kwargs["lane"] == "funding"
            starts.append(loop.time())
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.08)
                return envelope({**funding_payload()["data"], "symbol": endpoint.rsplit("/", 1)[1]})
            finally:
                active -= 1

        monkeypatch.setattr(mexc_funding, "fetch_mexc_json", fetch)
        runtime = mexc_funding.MexcFundingRuntime(None, lambda: items)
        task = asyncio.create_task(runtime.run_forever(stop))
        await asyncio.sleep(0.13)
        stop.set()
        await asyncio.wait_for(task, 0.03)
        assert peak == 4
        assert active == 0
        assert len(starts) >= 4
        assert all(right - left >= 0.009 for left, right in pairwise(starts))

    asyncio.run(run())


def test_funding_stamps_round_trip_and_migration_keeps_legacy_unknown(tmp_path):
    import os
    from uuid import uuid4

    import polars as pl
    import psycopg
    import pytest
    from psycopg import sql

    from prep_watchdeck_market.archive import archive_partition
    from prep_watchdeck_market.artifacts import build_universe_snapshot, read_universe_records
    from prep_watchdeck_market.catalog_store import persist_catalog
    from prep_watchdeck_market.database import apply_migrations, discover_migrations
    from prep_watchdeck_market.identity import resolve_market_groups
    from prep_watchdeck_market.market_store import persist_market_cycle

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires isolated TEST_DATABASE_URL")
    schema = "funding_scale_test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        try:
            migrations = discover_migrations()
            apply_migrations(connection, migrations[:5])
            catalog = parse_mexc_catalog(envelope([instrument().raw_definition]), observed_at=NOW)
            persist_catalog(connection, catalog, resolve_market_groups(catalog.instruments))
            first = mexc_l1.parse_mexc_l1(
                envelope([ticker_row()]),
                {"BTC_USDT": funding_payload()},
                catalog.instruments,
                cycle_at=NOW,
                observed_at=NOW,
            )
            # Insert a legacy state via the pre-0006 columns, retaining valid historical numbers.
            version_id = connection.execute(
                "SELECT venue_instrument_version_id FROM venue_instrument_versions"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO market_state_1m (venue_instrument_version_id, bucket_at, status, "
                "first_observed_at,last_observed_at,sample_count,reference_price_kind) "
                "VALUES (%s,%s,'partial',%s,%s,1,'none')",
                (version_id, NOW - timedelta(minutes=1), NOW, NOW),
            )
            legacy_run = uuid4()
            connection.execute(
                "INSERT INTO collector_runs (run_id,run_kind,cycle_at,started_at,status) "
                "VALUES (%s,'l1',%s,%s,'partial')",
                (legacy_run, NOW - timedelta(minutes=1), NOW),
            )
            connection.execute(
                "INSERT INTO latest_market_state (venue_instrument_version_id,collector_run_id,"
                "cycle_at,observed_at,status,quote_asset,mark_price,funding_rate_raw,"
                "funding_interval_seconds,funding_rate_per_hour,next_funding_at) "
                "VALUES (%s,%s,%s,%s,'partial','USDT',100,0.001,14400,0.00025,%s)",
                (version_id, legacy_run, NOW - timedelta(minutes=1), NOW, NOW + timedelta(hours=4)),
            )
            apply_migrations(connection)
            assert connection.execute(
                "SELECT funding_source_at,funding_observed_at,funding_valid_until "
                "FROM latest_market_state"
            ).fetchone() == (None, None, None)
            legacy_item = build_universe_snapshot(
                read_universe_records(connection), generated_at=NOW
            ).items[0]
            assert legacy_item.funding_rate_raw is None
            assert legacy_item.mark_price == 100
            assert connection.execute(
                "SELECT funding_source_at,funding_observed_at,funding_valid_until "
                "FROM market_state_1m"
            ).fetchone() == (None, None, None)
            persist_market_cycle(connection, NOW, NOW, [first])
            expected = (NOW, NOW, NOW + timedelta(seconds=90))
            assert (
                connection.execute(
                    "SELECT funding_source_at,funding_observed_at,funding_valid_until "
                    "FROM latest_market_state"
                ).fetchone()
                == expected
            )
            row = read_universe_records(connection)[0]
            assert (
                row.funding_source_at,
                row.funding_observed_at,
                row.funding_valid_until,
            ) == expected
            result = archive_partition(
                connection,
                tmp_path,
                dataset="market_state_1m",
                venue="mexc",
                partition_date=NOW.date(),
            )
            archived = pl.read_parquet(tmp_path / result.relative_path)
            assert archived.select(
                "funding_source_at", "funding_observed_at", "funding_valid_until"
            ).rows() == [expected]
        finally:
            connection.execute("RESET search_path")
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_funding_completion_rejects_native_version_aba_and_old_failure(monkeypatch):
    from prep_watchdeck_market.sources import mexc_funding
    from prep_watchdeck_market.sources.common import CatalogSourceError

    async def run():
        item = instrument()
        versions = {item.source_symbol: 1}
        runtime = mexc_funding.MexcFundingRuntime(None, lambda: [item], lambda: versions)
        started, finish = asyncio.Event(), asyncio.Event()

        async def fetch(*args, **kwargs):
            started.set()
            await finish.wait()
            return funding_payload()

        monkeypatch.setattr(mexc_funding, "fetch_mexc_json", fetch)
        old = asyncio.create_task(runtime.fetch_one(item))
        await started.wait()
        # Reversion to identical semantic definition still has a new native SCD2 ID.
        versions[item.source_symbol] = 3
        finish.set()
        await old
        assert runtime.snapshots == {}
        assert runtime.dirty_symbols == set()

        started.clear()
        finish.clear()

        async def fail(*args, **kwargs):
            started.set()
            await finish.wait()
            raise CatalogSourceError("safe failure")

        monkeypatch.setattr(mexc_funding, "fetch_mexc_json", fail)
        old = asyncio.create_task(runtime.fetch_one(item))
        await started.wait()
        versions[item.source_symbol] = 4
        fresh = mexc_funding.funding_snapshot(funding_payload(), item, observed_at=NOW)
        runtime.snapshots[item.source_symbol] = fresh
        finish.set()
        await old
        assert runtime.snapshots[item.source_symbol] is fresh

    asyncio.run(run())


def test_independent_funding_updates_existing_ticker_bucket_and_artifact():
    import os
    from dataclasses import replace
    from uuid import uuid4

    import psycopg
    import pytest
    from psycopg import sql

    from prep_watchdeck_market.artifacts import build_universe_snapshot, read_universe_records
    from prep_watchdeck_market.catalog_store import persist_catalog
    from prep_watchdeck_market.database import apply_migrations
    from prep_watchdeck_market.identity import resolve_market_groups
    from prep_watchdeck_market.market_store import persist_market_cycle, persist_mexc_funding
    from prep_watchdeck_market.sources.mexc_funding import MexcFundingSnapshot, funding_snapshot

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires isolated TEST_DATABASE_URL")
    schema = "funding_publication_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        try:
            apply_migrations(conn)
            catalog = parse_mexc_catalog(envelope([instrument().raw_definition]), observed_at=NOW)
            persist_catalog(conn, catalog, resolve_market_groups(catalog.instruments))
            item = catalog.instruments[0]
            version_id = conn.execute(
                "SELECT venue_instrument_version_id FROM venue_instrument_versions"
            ).fetchone()[0]
            batch = mexc_l1.parse_mexc_l1(
                envelope([ticker_row()]),
                {item.source_symbol: funding_payload()},
                [item],
                cycle_at=NOW,
                observed_at=NOW,
            )
            persist_market_cycle(
                conn, NOW, NOW, [batch], mexc_version_ids={item.source_symbol: version_id + 2}
            )
            assert conn.execute(
                "SELECT funding_rate_raw,error_code FROM latest_market_state"
            ).fetchone() == (None, "funding_only_partial:funding_contract_changed")
            latest_fixed = "collector_run_id,cycle_at,observed_at,source_at,mark_price," + (
                "reference_price,best_bid,best_ask,open_interest_raw,open_interest_base,"
                "open_interest_notional,volume_24h_raw,source_payload_hash"
            )
            minute_fixed = "collector_run_id,bucket_at,first_observed_at,last_observed_at," + (
                "source_at,sample_count,mark_price,reference_price,best_bid,best_ask,"
                "open_interest_raw,open_interest_base,open_interest_notional,volume_24h_raw"
            )
            before = conn.execute("SELECT " + latest_fixed + " FROM latest_market_state").fetchone()
            minute_before = conn.execute(
                "SELECT " + minute_fixed + " FROM market_state_1m"
            ).fetchone()
            current = NOW + timedelta(seconds=40)
            payload = envelope(
                {**funding_payload()["data"], "timestamp": int(current.timestamp() * 1000)}
            )
            snapshot = replace(
                funding_snapshot(payload, item, observed_at=current), native_version_id=version_id
            )
            assert persist_mexc_funding(conn, {item.source_symbol: (item, snapshot)}, current) == 1
            record = read_universe_records(conn)[0]
            artifact = build_universe_snapshot([record], generated_at=NOW + timedelta(seconds=57))
            assert artifact.items[0].funding_rate_raw is not None
            assert artifact.items[0].funding_observed_at == current
            assert (
                conn.execute("SELECT " + latest_fixed + " FROM latest_market_state").fetchone()
                == before
            )
            assert (
                conn.execute("SELECT " + minute_fixed + " FROM market_state_1m").fetchone()
                == minute_before
            )
            raw = conn.execute(
                "SELECT venue_instrument_version_id,observed_at,payload "
                "FROM raw_market_observations WHERE dataset='funding_current'"
            ).fetchone()
            assert raw[:2] == (version_id, current)
            assert raw[2]["nativeVersionId"] == version_id
            assert (
                persist_mexc_funding(
                    conn,
                    {
                        item.source_symbol: (
                            item,
                            replace(snapshot, native_version_id=version_id + 2),
                        )
                    },
                    current,
                )
                == 0
            )
            failure = MexcFundingSnapshot(
                None,
                snapshot.contract_version,
                None,
                None,
                None,
                "funding_fetch_failed",
                version_id,
            )
            persist_mexc_funding(conn, {item.source_symbol: (item, failure)}, current)
            record = read_universe_records(conn)[0]
            assert record.funding_rate_raw is None
            assert record.funding_observed_at is None
            assert record.error_code == "funding_only_partial:funding_fetch_failed"
            # Funding cannot turn an invalid ticker into ready.
            conn.execute("UPDATE latest_market_state SET error_code='incomplete_source_row'")
            persist_mexc_funding(conn, {item.source_symbol: (item, snapshot)}, current)
            assert conn.execute("SELECT status,error_code FROM latest_market_state").fetchone() == (
                "partial",
                "incomplete_source_row",
            )
            persist_mexc_funding(
                conn, {item.source_symbol: (item, snapshot)}, current + timedelta(seconds=90)
            )
            assert (
                conn.execute("SELECT funding_rate_raw FROM latest_market_state").fetchone()[0]
                is None
            )
            assert (
                conn.execute("SELECT " + latest_fixed + " FROM latest_market_state").fetchone()
                == before
            )
            assert (
                conn.execute("SELECT " + minute_fixed + " FROM market_state_1m").fetchone()
                == minute_before
            )
        finally:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_l1_writer_rejoins_new_cache_after_lock_and_drains_cancellation(monkeypatch, tmp_path):
    import threading
    from dataclasses import replace
    from types import SimpleNamespace

    import pytest

    from prep_watchdeck_market import service
    from prep_watchdeck_market.sources.mexc_funding import MexcFundingRuntime, funding_snapshot

    async def run():
        instance = service.MarketService("unused", tmp_path, enabled_venues=("mexc",))
        item = instrument()
        catalog = parse_mexc_catalog(envelope([item.raw_definition]), observed_at=NOW)
        instance._catalogs["mexc"] = catalog
        instance._mexc_version_ids = {item.source_symbol: 7}
        runtime = MexcFundingRuntime(None, lambda: [item])
        instance._mexc_funding = runtime
        stale = mexc_l1.parse_mexc_l1(
            envelope([ticker_row()]), {}, [item], cycle_at=NOW, observed_at=NOW
        )
        entered, finish = threading.Event(), threading.Event()
        captured = []

        def persist(*args, **kwargs):
            captured.extend(args[3])
            entered.set()
            finish.wait(2)
            return SimpleNamespace()

        monkeypatch.setattr(service, "persist_market_cycle_url", persist)
        await instance._market_write_lock.acquire()
        task = asyncio.create_task(instance._persist_l1_cycle(NOW, NOW, [stale]))
        await asyncio.sleep(0)
        current = datetime.now(UTC)
        payload = envelope(
            {
                **funding_payload(current + timedelta(hours=4))["data"],
                "timestamp": int(current.timestamp() * 1000),
            }
        )
        fresh = replace(funding_snapshot(payload, item, observed_at=current), native_version_id=7)
        runtime.snapshots[item.source_symbol] = fresh
        instance._market_write_lock.release()
        await asyncio.to_thread(entered.wait, 1)
        assert captured[0].observations[0].funding_observed_at == current
        assert captured[0].observations[0].source_at == NOW
        assert (
            captured[0].observations[0].source_payload_hash
            == stale.observations[0].source_payload_hash
        )
        task.cancel()
        await asyncio.sleep(0.01)
        assert instance._market_write_lock.locked()
        assert not task.done()
        task.cancel()  # run_forever's finally can cancel an already-cancelling writer again.
        await asyncio.sleep(0.01)
        assert instance._market_write_lock.locked()
        assert instance._catalog_update_lock.locked()
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not instance._market_write_lock.locked()
        assert not instance._catalog_update_lock.locked()

    asyncio.run(run())


def test_funding_flush_keeps_completion_during_commit_dirty_and_triggers_artifact(
    monkeypatch, tmp_path
):
    import threading
    from dataclasses import replace

    from prep_watchdeck_market import service
    from prep_watchdeck_market.sources.mexc_funding import MexcFundingRuntime, funding_snapshot

    async def run():
        instance = service.MarketService("unused", tmp_path, enabled_venues=("mexc",))
        item = instrument()
        instance._catalogs["mexc"] = parse_mexc_catalog(
            envelope([item.raw_definition]), observed_at=NOW
        )
        instance._mexc_version_ids = {item.source_symbol: 7}
        runtime = MexcFundingRuntime(None, lambda: [item])
        instance._mexc_funding = runtime
        snapshot = replace(
            funding_snapshot(funding_payload(), item, observed_at=NOW), native_version_id=7
        )
        runtime.snapshots[item.source_symbol] = snapshot
        runtime.dirty_symbols.add(item.source_symbol)
        entered, finish = threading.Event(), threading.Event()
        captured = []

        def persist(url, updates, funding_as_of):
            captured.append(updates[item.source_symbol][1])
            entered.set()
            finish.wait(2)
            return 1

        monkeypatch.setattr(service, "persist_mexc_funding_url", persist)
        flush = asyncio.create_task(instance._flush_mexc_funding())
        await asyncio.to_thread(entered.wait, 1)
        newer = replace(snapshot, error_code="funding_fetch_failed", payload=None)
        runtime.snapshots[item.source_symbol] = newer
        finish.set()
        assert await flush == 1
        assert instance._artifact_trigger.is_set()
        assert item.source_symbol in runtime.dirty_symbols
        assert await instance._flush_mexc_funding() == 1
        assert captured == [snapshot, newer]
        assert runtime.dirty_symbols == set()
        assert await instance._flush_mexc_funding() == 0

    asyncio.run(run())


def test_l1_rejoined_funding_raw_commits_before_any_flush(monkeypatch, tmp_path):
    import os
    from dataclasses import replace
    from uuid import uuid4

    import psycopg
    import pytest
    from psycopg import sql

    from prep_watchdeck_market import service
    from prep_watchdeck_market.catalog_store import persist_catalog
    from prep_watchdeck_market.database import apply_migrations
    from prep_watchdeck_market.identity import resolve_market_groups
    from prep_watchdeck_market.market_store import persist_market_cycle, persist_mexc_funding
    from prep_watchdeck_market.sources.mexc_funding import MexcFundingRuntime, funding_snapshot

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires isolated TEST_DATABASE_URL")
    schema = "funding_provenance_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        try:
            apply_migrations(conn)
            catalog = parse_mexc_catalog(envelope([instrument().raw_definition]), observed_at=NOW)
            persist_catalog(conn, catalog, resolve_market_groups(catalog.instruments))
            item = catalog.instruments[0]
            version_id = conn.execute(
                "SELECT venue_instrument_version_id FROM venue_instrument_versions"
            ).fetchone()[0]
            first = replace(
                funding_snapshot(funding_payload(), item, observed_at=NOW),
                native_version_id=version_id,
            )
            batch = mexc_l1.parse_mexc_l1(
                envelope([ticker_row()]),
                {item.source_symbol: first},
                [item],
                cycle_at=NOW,
                observed_at=NOW,
            )
            current = datetime.now(UTC)
            payload = envelope(
                {
                    **funding_payload(current + timedelta(hours=4))["data"],
                    "timestamp": int(current.timestamp() * 1000),
                    "fundingRate": "-.008",
                }
            )
            latest = replace(
                funding_snapshot(payload, item, observed_at=current), native_version_id=version_id
            )
            instance = service.MarketService("unused", tmp_path, enabled_venues=("mexc",))
            instance._catalogs["mexc"] = catalog
            instance._mexc_version_ids = {item.source_symbol: version_id}
            runtime = MexcFundingRuntime(None, lambda: [item])
            runtime.snapshots[item.source_symbol] = latest
            instance._mexc_funding = runtime

            def persist(url, cycle_at, started_at, batches, **kwargs):
                return persist_market_cycle(conn, cycle_at, started_at, batches, **kwargs)

            monkeypatch.setattr(service, "persist_market_cycle_url", persist)
            result = asyncio.run(instance._persist_l1_cycle(NOW, NOW, [batch]))
            # No independent Funding flush has run; this was the L1 transaction alone.
            assert result.raw_payloads_written == 2
            row = conn.execute(
                "SELECT funding_rate_raw,funding_source_at,funding_observed_at,"
                "source_payload_hash,source_at,observed_at FROM latest_market_state"
            ).fetchone()
            assert row[0] == Decimal("-0.008")
            assert row[1:3] == (latest.source_at, current)
            assert row[3].strip() == batch.observations[0].source_payload_hash
            assert row[4:] == (NOW, NOW)
            raw = conn.execute(
                "SELECT venue_instrument_version_id,observed_at,source_at,payload "
                "FROM raw_market_observations WHERE dataset='funding_current'"
            ).fetchone()
            assert raw[:3] == (version_id, current, latest.source_at)
            assert raw[3]["funding"] == payload
            assert raw[3]["nativeVersionId"] == version_id
            assert raw[3]["fundingObservedAt"] == current.isoformat()
            l1_raw = conn.execute(
                "SELECT payload_hash,payload FROM raw_market_observations "
                "WHERE dataset='l1_all_market'"
            ).fetchone()
            assert l1_raw[0].strip() == batch.payload_hash
            assert l1_raw[1]["funding"][item.source_symbol] == first.payload
            # Reusing the same raw snapshot in the later flush adds no duplicate raw event.
            persist_mexc_funding(conn, {item.source_symbol: (item, latest)}, current)
            assert (
                conn.execute(
                    "SELECT count(*) FROM raw_market_observations WHERE dataset='funding_current'"
                ).fetchone()[0]
                == 1
            )
        finally:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
