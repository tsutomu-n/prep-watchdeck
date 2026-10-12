import os
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.native_activity import build_native_activity, read_native_activity

NOW = datetime(2026, 10, 8, 6, 7, 30, tzinfo=UTC)
CUTOFF = datetime(2026, 10, 8, 6, 4, tzinfo=UTC)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def aggregate_rows():
    rows = []
    for minutes in (15, 60):
        for kind, indexes in (("recent", range(4)), ("baseline", range(1, 8))):
            for index in indexes:
                end = CUTOFF - (
                    timedelta(minutes=(3 - index) * minutes)
                    if kind == "recent"
                    else timedelta(days=index)
                )
                start = end - timedelta(minutes=minutes)
                turnover = (
                    (1000, 2000, 4000, 6000)[index]
                    if kind == "recent"
                    else (1000, 2000, 3000, 4000, 5000, 6000, 7000)[index - 1]
                ) * (minutes / 15)
                rows.append(
                    {
                        "venue_instrument_version_id": 7,
                        "venue": "bitget",
                        "source_symbol": "BTCUSDT",
                        "quote_asset": "USDT",
                        "minutes": minutes,
                        "sample_kind": kind,
                        "sample_index": index,
                        "start_at": start,
                        "end_at": end,
                        "candle_count": minutes,
                        "missing_volume_count": 0,
                        "invalid_candle_count": 0,
                        "turnover": turnover,
                        "start_close": 100,
                        "end_close": 110,
                        "start_finality": "confirmed",
                        "end_finality": "confirmed",
                        "start_source_at": start,
                        "end_source_at": end,
                        "start_observed_at": start,
                        "end_observed_at": end,
                    }
                )
    return rows


def test_same_time_median_preserves_four_recent_windows_and_price_direction():
    result = build_native_activity(aggregate_rows(), now=NOW)
    assert result.candle_cutoff == CUTOFF
    row = result.rows[0]
    assert row.venue_instrument_id == "bitget:BTCUSDT"
    window = row.windows["15m"]
    assert window.current.turnover.value == 6000
    assert window.current.price_change_pct.value == pytest.approx(10)
    assert [sample.turnover.value for sample in window.history] == [1000, 2000, 4000, 6000]
    assert window.current == window.history[-1]
    assert window.baseline_turnover.value == 4000
    assert window.baseline_days == 7
    assert window.baseline_end_times == tuple(CUTOFF - timedelta(days=d) for d in range(7, 0, -1))
    assert window.relative_ratio.value == 1.5
    assert window.previous_change_pct.value == 50
    assert row.windows["1h"].current.turnover.value == 24000


def test_incomplete_baseline_does_not_hide_current_or_recent_trend():
    rows = aggregate_rows()
    for row in rows:
        if row["sample_kind"] == "baseline" and row["sample_index"] > 2:
            row["candle_count"] = 0
    window = build_native_activity(rows, now=NOW).rows[0].windows["15m"]
    assert window.baseline_days == 2
    assert window.baseline_turnover.status == window.relative_ratio.status == "history_missing"
    assert window.current.turnover.value == 6000
    assert window.previous_change_pct.value == 50


@pytest.mark.parametrize("baseline,status", [(0, "no_baseline"), (999, "low_baseline")])
def test_tiny_denominators_cannot_create_misleading_activity(baseline, status):
    rows = aggregate_rows()
    for row in rows:
        if row["minutes"] == 15 and (
            row["sample_kind"] == "baseline"
            or (row["sample_kind"] == "recent" and row["sample_index"] == 2)
        ):
            row["turnover"] = baseline
    window = build_native_activity(rows, now=NOW).rows[0].windows["15m"]
    assert window.baseline_turnover.value == baseline
    assert window.relative_ratio.status == window.previous_change_pct.status == status
    assert window.relative_ratio.value is None


def test_real_zero_current_is_zero_activity_and_minus_one_hundred_percent():
    rows = aggregate_rows()
    for row in rows:
        if row["sample_kind"] == "recent" and row["sample_index"] == 3:
            row["turnover"] = 0
    window = build_native_activity(rows, now=NOW).rows[0].windows["15m"]
    assert window.current.turnover.value == window.relative_ratio.value == 0
    assert window.previous_change_pct.value == -100


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("candle_count", 14, "history_missing"),
        ("missing_volume_count", 1, "history_missing"),
        ("invalid_candle_count", 1, "invalid_data"),
        ("turnover", float("nan"), "invalid_data"),
        ("turnover", -1, "invalid_data"),
        ("end_observed_at", NOW + timedelta(seconds=1), "invalid_data"),
    ],
)
def test_bad_current_window_is_not_inferred_from_history(field, value, status):
    rows = aggregate_rows()
    next(
        row
        for row in rows
        if row["minutes"] == 15 and row["sample_kind"] == "recent" and row["sample_index"] == 3
    )[field] = value
    window = build_native_activity(rows, now=NOW).rows[0].windows["15m"]
    assert window.current.turnover.status == status
    assert window.current.turnover.value is None
    assert window.relative_ratio.value is None
    assert window.history[-2].turnover.value == 4000


def test_missing_price_anchor_does_not_discard_complete_turnover():
    rows = aggregate_rows()
    for row in rows:
        if row["sample_kind"] == "recent" and row["sample_index"] == 3:
            row["start_close"] = None
    sample = build_native_activity(rows, now=NOW).rows[0].windows["15m"].current
    assert sample.turnover.value == 6000
    assert sample.price_change_pct.value is None
    assert sample.price_change_pct.status == "history_missing"


def test_nonfinal_current_endpoint_cannot_be_reported_as_ready_turnover():
    rows = aggregate_rows()
    for row in rows:
        if row["sample_kind"] == "recent" and row["sample_index"] == 3:
            row["end_finality"] = "provisional"
    sample = build_native_activity(rows, now=NOW).rows[0].windows["15m"].current
    assert sample.turnover.status == "invalid_data"


def test_three_complete_days_use_the_median_and_keep_exact_day_evidence():
    rows = aggregate_rows()
    for row in rows:
        if row["sample_kind"] == "baseline":
            index = row["sample_index"]
            if index > 3:
                row["candle_count"] = 0
            else:
                row["turnover"] = (1000, 2000, 900000)[index - 1]
    window = build_native_activity(rows, now=NOW).rows[0].windows["15m"]
    assert window.baseline_turnover.value == 2000
    assert window.baseline_days == 3
    assert window.relative_ratio.value == 3


def test_artifact_rejects_duplicate_current_identity_and_out_of_window_history():
    from pydantic import ValidationError

    from prep_watchdeck_market.native_activity import NativeActivityArtifact

    result = build_native_activity(aggregate_rows(), now=NOW)
    data = result.model_dump(mode="python", by_alias=False)
    data["rows"] = [data["rows"][0], data["rows"][0]]
    with pytest.raises(ValidationError, match="duplicate native activity identity"):
        NativeActivityArtifact.model_validate(data)
    data = result.model_dump(mode="python", by_alias=False)
    data["rows"][0]["windows"]["15m"]["baseline_end_times"] = (
        CUTOFF - timedelta(days=8),
        *data["rows"][0]["windows"]["15m"]["baseline_end_times"][1:],
    )
    with pytest.raises(ValidationError, match="same-time historical windows"):
        NativeActivityArtifact.model_validate(data)


@pytest.fixture
def activity_database():
    if not TEST_DATABASE_URL:
        pytest.skip("isolated PostgreSQL required")
    target = conninfo_to_dict(TEST_DATABASE_URL)
    assert target.get("host") == "127.0.0.1"
    assert target.get("port", "5432") not in {"5432", "55432"}
    assert target.get("dbname") == target.get("user") == "prep_watchdeck_test"
    name = f"native_activity_test_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(name)))
        try:
            apply_migrations(connection)
            raw_row = connection.execute(
                "INSERT INTO raw_catalog_payloads (venue, endpoint, payload_hash, observed_at, "
                "last_observed_at, source_kind, payload) "
                "VALUES ('bitget', 'isolated-activity-test', %s, %s, %s, 'native_rest', '{}') "
                "RETURNING raw_catalog_payload_id",
                ("a" * 64, NOW, NOW),
            ).fetchone()
            assert raw_row is not None
            raw = raw_row[0]
            version_row = connection.execute(
                "INSERT INTO venue_instrument_versions (venue, source_symbol, definition_hash, "
                "valid_from, active, asset_class, market_type, base_asset, quote_asset, "
                "settle_asset, raw_catalog_payload_id, quantity_unit, raw_definition) "
                "VALUES ('bitget','BTCUSDT',%s,%s,true,'crypto','linear_perpetual',"
                "'BTC','USDT','USDT',%s,'base','{}') RETURNING venue_instrument_version_id",
                ("b" * 64, NOW - timedelta(days=8), raw),
            ).fetchone()
            assert version_row is not None
            version = version_row[0]
            # Independent fixture: a continuous recent four-hour strip and seven historical
            # one-hour strips include the extra close anchor, all with 100 USDT/minute.
            connection.execute(
                "INSERT INTO candle_1m (venue_instrument_version_id, bucket_at, open_price, "
                "high_price, low_price, close_price, volume_notional, finality, source_at, "
                "observed_at) SELECT %s, bucket, 100, 100, 100, 100, 100, 'confirmed', "
                "bucket + interval '1 minute', bucket + interval '61 seconds' FROM ("
                "SELECT %s::timestamptz - n * interval '1 minute' AS bucket "
                "FROM generate_series(1,241) n UNION ALL "
                "SELECT %s::timestamptz - d * interval '1 day' - n * interval '1 minute' "
                "FROM generate_series(1,7) d CROSS JOIN generate_series(1,61) n) fixture",
                (version, CUTOFF, CUTOFF),
            )
            yield connection, version
        finally:
            connection.execute("RESET search_path")
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def test_sql_checks_all_candles_exact_boundaries_and_current_version(
    activity_database, monkeypatch
):
    from prep_watchdeck_market import native_activity

    connection, version = activity_database
    original = native_activity.build_native_activity

    def inspect(rows, *, now):
        assert connection.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        assert connection.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read"
        return original(rows, now=now)

    monkeypatch.setattr(native_activity, "build_native_activity", inspect)
    connection.execute(
        "UPDATE candle_1m SET volume_notional=200 WHERE venue_instrument_version_id=%s "
        "AND bucket_at >= %s AND bucket_at < %s",
        (version, CUTOFF - timedelta(minutes=15), CUTOFF),
    )
    connection.execute(
        "UPDATE candle_1m SET close_price=110, high_price=110 "
        "WHERE venue_instrument_version_id=%s AND bucket_at=%s",
        (version, CUTOFF - timedelta(minutes=1)),
    )
    first = read_native_activity(connection, now=NOW).rows[0]
    assert first.windows["15m"].current.turnover.value == 3000
    assert first.windows["1h"].current.turnover.value == 7500
    assert first.windows["15m"].current.price_change_pct.value == pytest.approx(10)
    assert first.windows["15m"].relative_ratio.value == 2
    assert first.windows["15m"].previous_change_pct.value == 100
    assert first.windows["1h"].baseline_turnover.value == 6000

    middle = CUTOFF - timedelta(minutes=7)
    connection.execute(
        "UPDATE candle_1m SET observed_at=%s WHERE venue_instrument_version_id=%s AND bucket_at=%s",
        (NOW + timedelta(seconds=1), version, middle),
    )
    changed = read_native_activity(connection, now=NOW).rows[0].windows["15m"]
    assert changed.current.turnover.status == "invalid_data"
    connection.execute(
        "UPDATE candle_1m SET observed_at=%s, volume_notional=NULL "
        "WHERE venue_instrument_version_id=%s AND bucket_at=%s",
        (NOW, version, middle),
    )
    assert (
        read_native_activity(connection, now=NOW).rows[0].windows["15m"].current.turnover.status
        == "history_missing"
    )
    # A non-minute replacement cannot masquerade as the missing minute despite equal count.
    connection.execute(
        "UPDATE candle_1m SET volume_notional=200, bucket_at=bucket_at + interval '1 second' "
        "WHERE venue_instrument_version_id=%s AND bucket_at=%s",
        (version, middle),
    )
    assert (
        read_native_activity(connection, now=NOW).rows[0].windows["15m"].current.turnover.status
        == "invalid_data"
    )

    connection.execute(
        "UPDATE venue_instrument_versions SET valid_to=%s WHERE venue_instrument_version_id=%s",
        (NOW, version),
    )
    replacement = connection.execute(
        "INSERT INTO venue_instrument_versions (venue,source_symbol,definition_hash,valid_from,"
        "active,asset_class,market_type,base_asset,quote_asset,settle_asset,raw_catalog_payload_id,"
        "quantity_unit,raw_definition) SELECT venue,source_symbol,%s,%s,true,asset_class,"
        "market_type,base_asset,quote_asset,settle_asset,raw_catalog_payload_id,quantity_unit,"
        "raw_definition FROM venue_instrument_versions WHERE venue_instrument_version_id=%s "
        "RETURNING venue_instrument_version_id",
        ("c" * 64, NOW, version),
    ).fetchone()[0]
    current = read_native_activity(connection, now=NOW)
    assert len(current.rows) == 1
    assert current.rows[0].venue_instrument_version_id == replacement
    assert current.rows[0].windows["15m"].current.turnover.status == "history_missing"
    assert current.rows[0].windows["15m"].baseline_days == 0


def test_sql_projects_466_instruments_within_the_publication_budget(activity_database):
    connection, version = activity_database
    connection.execute(
        "INSERT INTO venue_instrument_versions (venue,source_symbol,definition_hash,valid_from,"
        "active,asset_class,market_type,base_asset,quote_asset,settle_asset,raw_catalog_payload_id,"
        "quantity_unit,raw_definition) SELECT venue,'FIXTURE' || n || 'USDT',definition_hash,"
        "valid_from,active,asset_class,market_type,base_asset,quote_asset,settle_asset,"
        "raw_catalog_payload_id,quantity_unit,raw_definition FROM venue_instrument_versions "
        "CROSS JOIN generate_series(1,465) n WHERE venue_instrument_version_id=%s",
        (version,),
    )
    connection.execute(
        "INSERT INTO candle_1m (venue_instrument_version_id,bucket_at,open_price,high_price,"
        "low_price,close_price,volume_notional,finality,source_at,observed_at) "
        "SELECT vi.venue_instrument_version_id,c.bucket_at,c.open_price,c.high_price,c.low_price,"
        "c.close_price,c.volume_notional,c.finality,c.source_at,c.observed_at FROM candle_1m c "
        "CROSS JOIN venue_instrument_versions vi WHERE c.venue_instrument_version_id=%s "
        "AND vi.venue_instrument_version_id<>%s",
        (version, version),
    )
    connection.execute("ANALYZE candle_1m")
    connection.execute("SET statement_timeout='5s'")
    started = time.perf_counter()
    result = read_native_activity(connection, now=NOW)
    elapsed = time.perf_counter() - started
    assert len(result.rows) == 466
    assert all(row.windows["15m"].relative_ratio.value == 1 for row in result.rows)
    assert elapsed < 8
    print(f"activity_projection_466_instruments_seconds={elapsed:.3f}")
