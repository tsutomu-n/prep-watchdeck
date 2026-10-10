import asyncio
from datetime import UTC, datetime, timedelta
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
