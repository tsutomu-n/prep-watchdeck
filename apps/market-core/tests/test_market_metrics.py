import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.market_metrics import (
    build_market_metrics,
    candle_cutoff,
    read_market_metrics,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def row(now: datetime) -> dict[str, object]:
    cutoff = candle_cutoff(now)
    return {
        "venue_instrument_version_id": 7,
        "venue": "bitget",
        "source_symbol": "BTCUSDT",
        "quote_asset": "USDT",
        "settle_asset": "USDT",
        "price_tick": "0.1",
        "l_cycle_at": now.replace(second=0, microsecond=0),
        "l_oi_base": 120,
        "l_source_at": now - timedelta(seconds=3),
        "l_observed_at": now - timedelta(seconds=2),
        "oi_15m_base": 100,
        "oi_1h_base": 80,
        "oi_15m_source_at": now - timedelta(minutes=15),
        "oi_15m_observed_at": now - timedelta(minutes=15),
        "oi_1h_source_at": now - timedelta(hours=1),
        "oi_1h_observed_at": now - timedelta(hours=1),
        "c_end_close": 110,
        "c_end_finality": "confirmed",
        "c_end_source_at": cutoff,
        "c_end_observed_at": cutoff + timedelta(seconds=20),
        "c_15m_close": 100,
        "c_15m_finality": "confirmed",
        "c_15m_source_at": cutoff - timedelta(minutes=15),
        "c_15m_observed_at": cutoff - timedelta(minutes=15),
        "c_1h_close": 100,
        "c_1h_finality": "derived_final",
        "c_1h_source_at": cutoff - timedelta(hours=1),
        "c_1h_observed_at": cutoff - timedelta(hours=1),
        "c_24h_close": 100,
        "c_24h_finality": "confirmed",
        "c_24h_source_at": cutoff - timedelta(days=1),
        "c_24h_observed_at": cutoff - timedelta(days=1),
    }


def test_metrics_share_cutoff_and_keep_endpoint_quality_separate() -> None:
    now = datetime(2026, 9, 28, 12, 6, 30, tzinfo=UTC)
    result = build_market_metrics([row(now)], now=now)
    metric = result.rows[0]
    assert result.candle_cutoff == datetime(2026, 9, 28, 12, 3, tzinfo=UTC)
    assert metric.oi_change["15m"].value == pytest.approx(20)
    assert metric.oi_change["1h"].value == pytest.approx(50)
    assert metric.trade_change["15m"].value == pytest.approx(10)
    assert metric.trade_change["24h"].end_at == result.candle_cutoff
    assert metric.trade_change["1h"].end_finality == "confirmed"

    incomplete = row(now)
    incomplete["c_15m_close"] = None
    incomplete["l_oi_base"] = None
    changed = build_market_metrics([incomplete], now=now).rows[0]
    assert changed.trade_change["15m"].availability == "missing"
    assert changed.trade_change["1h"].availability == "available"
    assert changed.oi_change["15m"].availability == "missing"


def test_later_endpoint_correction_recomputes_without_cached_values() -> None:
    now = datetime(2026, 9, 28, 12, 6, 30, tzinfo=UTC)
    original = row(now)
    revised = dict(original, c_end_close=95, oi_15m_base=110)
    before = build_market_metrics([original], now=now).rows[0]
    after = build_market_metrics([revised], now=now).rows[0]
    assert before.trade_change["15m"].value == pytest.approx(10)
    assert after.trade_change["15m"].value == pytest.approx(-5)
    assert after.oi_change["15m"].value is not None
    assert after.oi_change["15m"].value < before.oi_change["15m"].value


def seed_metrics_database(connection, now):
    """Shared isolated SQL fixture; timestamps describe observations, not DB commits."""
    cutoff = candle_cutoff(now)
    run_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO collector_runs (run_id, run_kind, started_at, status) "
        "VALUES (%s, 'catalog', %s, 'succeeded')",
        (run_id, now),
    )
    raw_id = connection.execute(
        "INSERT INTO raw_catalog_payloads "
        "(venue, endpoint, payload_hash, observed_at, last_observed_at, "
        "source_kind, payload) "
        "VALUES ('bitget', 'isolated-test', %s, %s, %s, 'native_rest', '{}') "
        "RETURNING raw_catalog_payload_id",
        ("a" * 64, now, now),
    ).fetchone()[0]
    version_id = connection.execute(
        "INSERT INTO venue_instrument_versions "
        "(venue, source_symbol, definition_hash, valid_from, active, asset_class, "
        "market_type, base_asset, quote_asset, settle_asset, raw_catalog_payload_id, "
        "quantity_unit, raw_definition) "
        "VALUES ('bitget', 'BTCUSDT', %s, %s, true, 'crypto', 'linear_perpetual', "
        "'BTC', 'USDT', 'USDT', %s, 'base', '{}') "
        "RETURNING venue_instrument_version_id",
        ("b" * 64, now - timedelta(days=2), raw_id),
    ).fetchone()[0]
    cycle = now.replace(second=0, microsecond=0)
    connection.execute(
        "INSERT INTO latest_market_state "
        "(venue_instrument_version_id, collector_run_id, cycle_at, observed_at, "
        "source_at, status, open_interest_base, quote_asset) "
        "VALUES (%s, %s, %s, %s, %s, 'partial', 1100, 'USDT')",
        (version_id, run_id, cycle, now, now),
    )
    for minutes, quantity in ((15, 1000), (60, 800)):
        connection.execute(
            "INSERT INTO market_state_1m "
            "(venue_instrument_version_id, bucket_at, status, first_observed_at, "
            "last_observed_at, sample_count, open_interest_base) "
            "VALUES (%s, %s, 'partial', %s, %s, 1, %s)",
            (version_id, cycle - timedelta(minutes=minutes), now, now, quantity),
        )
    for minutes, close in ((0, 110), (15, 100), (60, 100), (1440, 100)):
        connection.execute(
            "INSERT INTO candle_1m (venue_instrument_version_id, bucket_at, "
            "open_price, high_price, low_price, close_price, finality, observed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'confirmed', %s)",
            (
                version_id,
                cutoff - timedelta(minutes=minutes + 1),
                close,
                close,
                close,
                close,
                cutoff - timedelta(seconds=20),
            ),
        )
    return version_id, raw_id


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="isolated PostgreSQL required")
def test_metrics_query_uses_migrated_schema_without_writing() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"market_metrics_test_{uuid.uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            now = datetime(2026, 9, 28, 12, 6, 30, tzinfo=UTC)
            cutoff = candle_cutoff(now)
            version_id, raw_id = seed_metrics_database(connection, now)
            artifact = read_market_metrics(connection, now=now)
            assert artifact.metric_version == "native-endpoints-v1"
            assert len(artifact.rows) == 1
            assert artifact.rows[0].oi_change["15m"].value == pytest.approx(10)
            assert artifact.rows[0].trade_change["15m"].value == pytest.approx(10)
            connection.execute(
                "UPDATE candle_1m SET open_price=95, high_price=95, low_price=95, "
                "close_price=95 WHERE venue_instrument_version_id=%s AND bucket_at=%s",
                (version_id, cutoff - timedelta(minutes=1)),
            )
            revised = read_market_metrics(connection, now=now)
            assert revised.rows[0].trade_change["15m"].value == pytest.approx(-5)
            connection.execute(
                "INSERT INTO venue_instrument_versions "
                "(venue, source_symbol, definition_hash, valid_from, active, asset_class, "
                "market_type, base_asset, quote_asset, settle_asset, raw_catalog_payload_id, "
                "quantity_unit, raw_definition) "
                "SELECT 'bitget', 'FIXTURE' || n || 'USDT', %s, %s, true, 'crypto', "
                "'linear_perpetual', 'FIXTURE' || n, 'USDT', 'USDT', %s, 'base', '{}' "
                "FROM generate_series(1, 1200) AS n",
                ("c" * 64, now - timedelta(days=2), raw_id),
            )
            started = time.perf_counter()
            full_universe = read_market_metrics(connection, now=now)
            elapsed = time.perf_counter() - started
            assert len(full_universe.rows) == 1201
            assert elapsed < 10
        finally:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


@pytest.mark.parametrize("broken", [b"{broken", b'{"schemaVersion":1,"rows":"invalid"}'])
def test_metrics_recover_known_corruption_preserving_exact_bytes(tmp_path, monkeypatch, broken):
    from contextlib import nullcontext

    from prep_watchdeck_market import market_metrics as metrics

    now = datetime(2026, 9, 28, 12, 6, 30, tzinfo=UTC)
    artifact = build_market_metrics([row(now)], now=now)
    path = tmp_path / "market-metrics.json"
    path.write_bytes(broken)
    monkeypatch.setattr(metrics.psycopg, "connect", lambda *a, **kw: nullcontext(None))
    monkeypatch.setattr(metrics, "read_market_metrics", lambda *a, **kw: artifact)
    assert metrics.publish_market_metrics("unused", tmp_path, now=now) == 1
    assert metrics.MarketMetricsArtifact.model_validate_json(path.read_bytes()) == artifact
    backups = list(tmp_path.glob("market-metrics.json.corrupt-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == broken
    assert metrics.publish_market_metrics("unused", tmp_path, now=now) == 1
    assert list(tmp_path.glob("market-metrics.json.corrupt-*")) == backups


@pytest.mark.parametrize(
    "original", [b'{"schemaVersion":2}', b"{}", b"null", b"[]", b'{"schemaVersion":true}']
)
def test_metrics_unknown_schema_is_never_replaced(tmp_path, monkeypatch, original):
    from contextlib import nullcontext

    from prep_watchdeck_market import market_metrics as metrics

    now = datetime(2026, 9, 28, 12, 6, 30, tzinfo=UTC)
    path = tmp_path / "market-metrics.json"
    path.write_bytes(original)
    monkeypatch.setattr(metrics.psycopg, "connect", lambda *a, **kw: nullcontext(None))
    monkeypatch.setattr(
        metrics, "read_market_metrics", lambda *a, **kw: build_market_metrics([], now=now)
    )
    with pytest.raises(ValueError):
        metrics.publish_market_metrics("unused", tmp_path, now=now)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("market-metrics.json.corrupt-*"))


@pytest.mark.parametrize("failure", ["read", "backup", "db", "changed", "writer"])
def test_metrics_recovery_stops_on_unsafe_boundaries(tmp_path, monkeypatch, failure):
    import fcntl
    from contextlib import nullcontext
    from pathlib import Path

    from prep_watchdeck_market import market_metrics as metrics

    now = datetime(2026, 9, 28, 12, 6, 30, tzinfo=UTC)
    path = tmp_path / "market-metrics.json"
    original = b"{broken"
    path.write_bytes(original)
    monkeypatch.setattr(metrics.psycopg, "connect", lambda *a, **kw: nullcontext(None))

    def project(*args, **kwargs):
        if failure == "db":
            raise psycopg.OperationalError("isolated timeout")
        if failure == "changed":
            path.write_bytes(b"another writer")
        return build_market_metrics([], now=now)

    monkeypatch.setattr(metrics, "read_market_metrics", project)
    if failure == "read":
        monkeypatch.setattr(
            metrics, "_metrics_snapshot", lambda *a: (_ for _ in ()).throw(PermissionError())
        )
    if failure == "backup":
        original_open = Path.open

        def fail_backup(self, *args, **kwargs):
            if ".corrupt-" in self.name:
                raise PermissionError("isolated preservation failure")
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_backup)
    with (tmp_path / ".market-metrics.lock").open("wb") as lock:
        if failure == "writer":
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises((OSError, ValueError, psycopg.OperationalError)):
            metrics.publish_market_metrics("unused", tmp_path, now=now)
    assert path.read_bytes() == (b"another writer" if failure == "changed" else original)
    assert not list(tmp_path.glob("*.pending"))


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("oi_15m_base", 0, "no_baseline"),
        ("l_oi_base", None, "endpoint_missing"),
        ("oi_15m_base", None, "endpoint_missing"),
        ("l_oi_base", float("nan"), "endpoint_missing"),
    ],
)
def test_oi_endpoint_failure_never_falls_back_to_notional(field, value, reason):
    now = datetime(2026, 9, 28, 12, 6, 30, tzinfo=UTC)
    source = row(now)
    source[field] = value
    source["open_interest_notional"] = 1650
    metric = build_market_metrics([source], now=now).rows[0].oi_change["15m"]
    assert metric.value is None and metric.reason_code == reason


def test_projection_deadline_kills_and_reaps_the_owner(tmp_path, monkeypatch):
    import subprocess

    from prep_watchdeck_market import market_metrics as metrics

    # A real child stalls after acquiring the publication lock. No test DB is needed.
    pid_path = tmp_path / "pid"
    script = tmp_path / "stalled-python"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import fcntl, os, pathlib, time\n"
        f'lock = open({str(tmp_path / ".market-metrics.lock")!r}, "w")\n'
        "fcntl.flock(lock, fcntl.LOCK_EX)\n"
        f"pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    script.chmod(0o700)
    original = tmp_path / "market-metrics.json"
    original.write_bytes(b"{preserve me")
    monkeypatch.setattr(metrics.sys, "executable", str(script))
    monkeypatch.setattr(metrics, "PROJECTION_TIMEOUT_SECONDS", 0.5)
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        metrics.publish_market_metrics_bounded("unused", tmp_path, now=datetime.now(UTC))
    assert time.monotonic() - started < 3
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)
    import fcntl

    with (tmp_path / ".market-metrics.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert original.read_bytes() == b"{preserve me"


@pytest.fixture
def isolated_metrics_database():
    if not TEST_DATABASE_URL:
        pytest.skip("isolated PostgreSQL required")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    target = conninfo_to_dict(TEST_DATABASE_URL)
    assert target.get("host") == "127.0.0.1"
    assert target.get("port", "5432") not in {"5432", "55432"}
    assert target.get("dbname") == "prep_watchdeck_test"
    database = "metrics_acceptance_" + uuid.uuid4().hex
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            url = make_conninfo(TEST_DATABASE_URL, dbname=database)
            with psycopg.connect(url, autocommit=True) as connection:
                apply_migrations(connection)
                yield url, connection
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def test_current_version_does_not_splice_oi_or_infer_unknown_quantity(isolated_metrics_database):
    _, connection = isolated_metrics_database
    now = datetime.now(UTC)
    version, raw = seed_metrics_database(connection, now)
    connection.execute(
        "UPDATE venue_instrument_versions SET valid_to=%s WHERE venue_instrument_version_id=%s",
        (now, version),
    )
    replacement = connection.execute(
        "INSERT INTO venue_instrument_versions "
        "(venue,source_symbol,definition_hash,valid_from,active,asset_class,market_type,"
        "base_asset,quote_asset,settle_asset,raw_catalog_payload_id,quantity_unit,raw_definition) "
        "VALUES ('bitget','BTCUSDT',%s,%s,true,'crypto','linear_perpetual',"
        "'BTC','USDT','USDT',%s,'unknown','{}') "
        "RETURNING venue_instrument_version_id",
        ("d" * 64, now, raw),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO latest_market_state "
        "(venue_instrument_version_id,collector_run_id,cycle_at,observed_at,source_at,status,"
        "open_interest_raw,open_interest_raw_unit,open_interest_notional,"
        "open_interest_base,quote_asset) "
        "SELECT %s,collector_run_id,cycle_at,observed_at,source_at,status,"
        "1100,'unknown',165000,NULL,quote_asset "
        "FROM latest_market_state WHERE venue_instrument_version_id=%s",
        (replacement, version),
    )
    result = read_market_metrics(connection, now=now)
    assert len(result.rows) == 1
    assert result.rows[0].venue_instrument_version_id == replacement
    assert result.rows[0].oi_change["15m"].value is None
    assert result.rows[0].oi_change["15m"].reason_code == "endpoint_missing"
    # A normalized current endpoint still cannot borrow the previous version's baseline.
    connection.execute(
        "UPDATE latest_market_state SET open_interest_base=1100 WHERE "
        "venue_instrument_version_id=%s",
        (replacement,),
    )
    assert read_market_metrics(connection, now=now).rows[0].oi_change["15m"].value is None


def test_real_statement_timeout_releases_projection_connection(isolated_metrics_database, tmp_path):
    import concurrent.futures

    from prep_watchdeck_market.market_metrics import publish_market_metrics_bounded

    url, writer = isolated_metrics_database
    now = datetime.now(UTC)
    seed_metrics_database(writer, now)
    path = tmp_path / "market-metrics.json"
    publish_market_metrics_bounded(url, tmp_path, now=now)
    original = path.read_bytes()
    with psycopg.connect(url) as blocker, concurrent.futures.ThreadPoolExecutor() as executor:
        blocker.execute("LOCK TABLE candle_1m IN ACCESS EXCLUSIVE MODE")
        started = time.monotonic()
        future = executor.submit(publish_market_metrics_bounded, url, tmp_path, now=now)
        observed = 0
        while not future.done():
            count = writer.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND "
                "query LIKE '%%SELECT vi.venue_instrument_version_id%%'"
            ).fetchone()[0]
            # Exclude this observing query itself.
            observed = max(observed, count - 1)
            time.sleep(0.05)
        with pytest.raises(RuntimeError, match="metrics projection failed"):
            future.result()
        assert 4.5 <= time.monotonic() - started < 10
        assert observed == 1
        assert path.read_bytes() == original
        blocker.rollback()
    publish_market_metrics_bounded(url, tmp_path, now=now)
    assert path.read_bytes() != original


def test_projection_snapshot_is_repeatable_read_only(isolated_metrics_database, monkeypatch):
    from prep_watchdeck_market import market_metrics as metrics

    _, connection = isolated_metrics_database
    original = metrics.build_market_metrics

    def inspect(rows, *, now):
        assert connection.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        assert connection.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read"
        return original(rows, now=now)

    monkeypatch.setattr(metrics, "build_market_metrics", inspect)
    metrics.read_market_metrics(connection, now=datetime.now(UTC))
