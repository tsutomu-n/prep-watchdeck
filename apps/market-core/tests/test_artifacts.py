from __future__ import annotations

import json
import os
import runpy
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from prep_watchdeck_market.artifacts import (
    ARTIFACT_MODELS,
    ArtifactFileStatus,
    CandleRecord,
    CollectorRunRecord,
    UniverseRecord,
    build_market_chart,
    build_market_service_state,
    build_selected_market,
    build_universe_snapshot,
    publish_artifacts,
    publish_selected_artifact,
    read_universe_records,
    write_artifact_atomic,
)
from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.identity import resolve_market_groups
from prep_watchdeck_market.models import Venue
from prep_watchdeck_market.sources import mexc

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def test_native_only_mexc_retains_prices_and_oi_without_entering_other_venue_median(
    monkeypatch,
) -> None:
    directory = Path(__file__).resolve().parents[1] / "data/mexc-reviewed-20261010"
    registry = runpy.run_path(str(directory / "registry-100.py"))["MEXC_REVIEWED_IDENTITIES"]
    monkeypatch.setattr(mexc, "MEXC_REVIEWED_IDENTITIES", registry)
    now = datetime(2026, 10, 10, tzinfo=UTC)
    batch = mexc.parse_mexc_catalog(
        json.loads((directory / "catalog.json").read_text()), observed_at=now
    )
    native = next(item for item in batch.instruments if item.source_symbol == "ZEC_USDT")
    peers = [
        replace(
            native,
            venue=venue,
            source_symbol="ZECUSDT",
            quantity_unit="base",
            contract_multiplier=Decimal("1"),
            raw_definition={},
        )
        for venue in ("bitget", "aster")
    ]
    instruments = [*peers, native]
    groups = resolve_market_groups(instruments)
    records = [
        replace(
            _universe_record(
                venue=instrument.venue,
                symbol=instrument.source_symbol,
                base="ZEC",
                quote="USDT",
                group_id=resolution.group_id,
                cycle_at=now,
                observed_at=now,
                mark=mark,
            ),
            source_at=now,
            reference_price=Decimal(mark),
            best_bid=Decimal(mark) - 1,
            best_ask=Decimal(mark) + 1,
            open_interest_raw=Decimal("100"),
            open_interest_raw_unit="contracts" if instrument.venue == "mexc" else "base",
            open_interest_base=Decimal("1"),
            open_interest_notional=Decimal(mark),
            volume_24h_raw=Decimal("1000"),
            volume_24h_unit="quote",
        )
        for instrument, resolution, mark in zip(
            instruments, groups, ("100", "102", "900"), strict=True
        )
    ]
    items = build_universe_snapshot(records, generated_at=now).items
    for item in items:
        if item.venue == "mexc":
            assert item.group_id == "native:mexc:ZEC_USDT:linear-perp"
            assert item.mark_price == 900
            assert item.open_interest_base == 1
            assert item.open_interest_notional == 900
            assert item.reference_mark_median.status == "unavailable"
            assert item.reference_mark_median.value is None
        else:
            assert item.reference_mark_median.value == 101
            assert item.reference_mark_median.venue_count == 2
            assert set(item.reference_mark_median.venues) == {"bitget", "aster"}


def test_universe_median_is_strict_and_stale_values_are_not_published() -> None:
    now = datetime(2026, 8, 14, 12, 2, tzinfo=UTC)
    common_cycle = now - timedelta(minutes=1)
    records = (
        _universe_record(
            venue="hyperliquid",
            symbol="BTC",
            base="BTC",
            quote="USD",
            group_id="crypto:BTC:linear-perp",
            cycle_at=common_cycle,
            observed_at=now - timedelta(seconds=20),
            mark="102",
        ),
        _universe_record(
            venue="bitget",
            symbol="BTCUSDT",
            base="BTC",
            quote="USDT",
            group_id="crypto:BTC:linear-perp",
            cycle_at=common_cycle,
            observed_at=now - timedelta(seconds=10),
            mark="100",
        ),
        _universe_record(
            venue="aster",
            symbol="BTCUSDT",
            base="BTC",
            quote="USDT",
            group_id="crypto:BTC:linear-perp",
            cycle_at=common_cycle - timedelta(minutes=1),
            observed_at=now - timedelta(seconds=15),
            mark="999",
        ),
        _universe_record(
            venue="bitget",
            symbol="ETHUSDT",
            base="ETH",
            quote="USDT",
            group_id="crypto:ETH:linear-perp",
            cycle_at=common_cycle,
            observed_at=now - timedelta(seconds=121),
            mark="2000",
        ),
    )

    artifact = build_universe_snapshot(records, generated_at=now)
    payload = artifact.model_dump(mode="json", by_alias=True)

    assert [item["venueInstrumentId"] for item in payload["items"]] == [
        "aster:BTCUSDT",
        "bitget:BTCUSDT",
        "hyperliquid:BTC",
        "bitget:ETHUSDT",
    ]
    btc = next(
        item
        for item in payload["items"]
        if item["venue"] == "bitget" and item["baseAsset"] == "BTC"
    )
    assert btc["referenceMarkMedian"] == {
        "status": "ready",
        "value": 101.0,
        "venueCount": 2,
        "venues": ["bitget", "hyperliquid"],
        "cycleAt": common_cycle.isoformat().replace("+00:00", "Z"),
        "maxAgeSeconds": 20.0,
        "skewSeconds": 10.0,
        "unavailableReason": None,
        "parityAssumptionCode": "usd_usdc_usdt_reference_only",
    }
    stale = next(item for item in payload["items"] if item["baseAsset"] == "ETH")
    assert stale["quality"] == "stale"
    assert stale["markPrice"] is None
    assert "l1_older_than_120_seconds" in stale["qualityReasons"]
    assert payload["parityAssumption"]["appliedTo"] == "reference_mark_median_only"


def test_chart_selected_and_service_artifacts_are_bounded_and_explicit() -> None:
    start = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    candles = tuple(
        CandleRecord(
            venue_instrument_version_id=7,
            bucket_at=start + timedelta(minutes=index),
            open_price=Decimal("100") + index,
            high_price=Decimal("102") + index,
            low_price=Decimal("99") + index,
            close_price=Decimal("101") + index,
            volume_base=Decimal("1"),
            volume_notional=Decimal("100"),
            trade_count=10,
            finality="derived_final" if index == 4 else "confirmed",
            source_at=None,
            observed_at=start + timedelta(minutes=index + 1, seconds=5),
        )
        for index in range(5)
    )
    chart = build_market_chart(
        "bitget:BTCUSDT",
        candles,
        generated_at=start + timedelta(minutes=6),
    )
    five_minute = chart.timeframes[0]
    assert five_minute.timeframe == "5m"
    assert len(five_minute.bars) == 1
    assert five_minute.bars[0].finality == "mixed"
    assert five_minute.bars[0].complete is True
    assert five_minute.bars[0].source_bar_count == 5

    selected = build_selected_market(None, generated_at=start)
    assert selected.status == "unavailable"
    assert selected.selection is None
    assert selected.quality_reasons == ("no_active_selection",)

    runs = (
        CollectorRunRecord(
            run_kind="catalog",
            status="succeeded",
            started_at=start - timedelta(minutes=15),
            completed_at=start - timedelta(minutes=14),
            cycle_at=None,
            records_received=10,
            records_written=10,
            error_code=None,
        ),
        CollectorRunRecord(
            run_kind="l1",
            status="partial",
            started_at=start - timedelta(minutes=1),
            completed_at=start - timedelta(seconds=30),
            cycle_at=start - timedelta(minutes=1),
            records_received=10,
            records_written=9,
            error_code="venue_partial_failure",
        ),
    )
    service = build_market_service_state(
        runs,
        (
            ArtifactFileStatus(
                name="universe-snapshot.json",
                status="ready",
                generated_at=start,
                error_code=None,
            ),
        ),
        generated_at=start,
    )
    assert service.catalog.status == "ready"
    assert service.l1.status == "partial"
    assert service.l1.error_code == "venue_partial_failure"


def test_atomic_writer_replaces_and_static_schemas_match_models(tmp_path: Path) -> None:
    generated_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    target = tmp_path / "universe-snapshot.json"
    first = build_universe_snapshot((), generated_at=generated_at)
    second = build_universe_snapshot(
        (
            _universe_record(
                venue="bitget",
                symbol="BTCUSDT",
                base="BTC",
                quote="USDT",
                group_id=None,
                cycle_at=None,
                observed_at=None,
                mark=None,
            ),
        ),
        generated_at=generated_at + timedelta(seconds=1),
    )

    write_artifact_atomic(target, first)
    write_artifact_atomic(target, second)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["generatedAt"] == "2026-08-14T12:00:01Z"
    assert [path.name for path in tmp_path.iterdir()] == ["universe-snapshot.json"]

    schema_root = Path(__file__).parents[3] / "schemas"
    for filename, model in ARTIFACT_MODELS.items():
        stored = json.loads((schema_root / filename).read_text(encoding="utf-8"))
        assert stored == model.model_json_schema(by_alias=True, mode="serialization")
        _assert_objects_are_closed(stored)


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)
def test_empty_postgres_queries_publish_all_artifacts(tmp_path: Path) -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"artifact_test_{uuid.uuid4().hex}"
    generated_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            assert read_universe_records(connection) == ()
            connection.execute(
                """
                    INSERT INTO collector_runs (
                        run_id, run_kind, started_at, status,
                        records_received, records_written, metrics
                    )
                    VALUES (%s, 'catalog', %s, 'running', 0, 0, '{}')
                """,
                (uuid.uuid4(), generated_at),
            )

            result = publish_artifacts(connection, tmp_path, generated_at=generated_at)

            assert result.status == "ready"
            assert sorted(path.name for path in tmp_path.iterdir()) == [
                "market-chart.json",
                "selected-market.json",
                "service-state.json",
                "universe-snapshot.json",
            ]
            chart_path = tmp_path / "market-chart.json"
            chart_payload = json.loads(chart_path.read_text(encoding="utf-8"))
            chart_payload["venueInstrumentId"] = "bitget:BTCUSDT"
            chart_path.write_text(json.dumps(chart_payload), encoding="utf-8")
            refreshed_at = generated_at + timedelta(seconds=5)
            refreshed = publish_selected_artifact(
                connection,
                tmp_path,
                result.files,
                generated_at=refreshed_at,
            )
            assert refreshed.status == "ready"
            selected_payload = json.loads(
                (tmp_path / "selected-market.json").read_text(encoding="utf-8")
            )
            universe_payload = json.loads(
                (tmp_path / "universe-snapshot.json").read_text(encoding="utf-8")
            )
            refreshed_chart = json.loads(chart_path.read_text(encoding="utf-8"))
            assert selected_payload["generatedAt"] == "2026-08-14T12:00:05Z"
            assert refreshed_chart["venueInstrumentId"] is None
            assert refreshed_chart["generatedAt"] == "2026-08-14T12:00:05Z"
            assert universe_payload["generatedAt"] == "2026-08-14T12:00:00Z"
        finally:
            connection.execute("RESET search_path")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def _universe_record(
    *,
    venue: Venue,
    symbol: str,
    base: str,
    quote: str,
    group_id: str | None,
    cycle_at: datetime | None,
    observed_at: datetime | None,
    mark: str | None,
) -> UniverseRecord:
    return UniverseRecord(
        venue_instrument_version_id=1,
        venue=venue,
        source_symbol=symbol,
        base_asset=base,
        quote_asset=quote,
        settle_asset="USDC" if venue == "hyperliquid" else "USDT",
        collateral_asset="USDC" if venue == "hyperliquid" else "USDT",
        active=True,
        market_type="linear_perpetual",
        execution_model="clob",
        group_id=group_id,
        mapping_method="exact_base_heuristic" if group_id is not None else None,
        catalog_source_kind="native_rest",
        catalog_endpoint="/catalog",
        catalog_documentation_url="https://example.invalid/docs",
        catalog_payload_hash="a" * 64,
        catalog_observed_at=datetime(2026, 8, 14, 11, 55, tzinfo=UTC),
        catalog_source_at=None,
        collector_run_id="00000000-0000-0000-0000-000000000001" if cycle_at else None,
        cycle_at=cycle_at,
        observed_at=observed_at,
        source_at=None,
        status="ready" if cycle_at else None,
        mark_price=None if mark is None else Decimal(mark),
        reference_price=None,
        reference_price_kind="none",
        best_bid=None,
        best_ask=None,
        funding_rate_raw=None,
        funding_interval_seconds=None,
        funding_rate_per_hour=None,
        next_funding_at=None,
        open_interest_raw=None,
        open_interest_raw_unit=None,
        open_interest_base=None,
        open_interest_notional=None,
        volume_24h_raw=None,
        volume_24h_unit=None,
        l1_source_payload_hash=None,
        error_code=None,
    )


def _assert_objects_are_closed(node: object) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
        for value in node.values():
            _assert_objects_are_closed(value)
    elif isinstance(node, list):
        for value in node:
            _assert_objects_are_closed(value)


def test_mexc_funding_only_partial_joins_median_but_invalid_ticker_does_not():
    from dataclasses import replace

    now = datetime(2026, 10, 10, tzinfo=UTC)
    common = dict(
        base="BTC",
        quote="USDT",
        group_id="crypto:BTC:linear-perp",
        cycle_at=now,
        observed_at=now,
        mark="100",
    )
    mexc = replace(
        _universe_record(venue="mexc", symbol="BTC_USDT", **common),
        status="partial",
        error_code="funding_only_partial:funding_fetch_failed",
        source_at=now,
        reference_price=Decimal("101"),
        best_bid=Decimal("99"),
        best_ask=Decimal("100"),
        open_interest_raw=Decimal("10000"),
        open_interest_raw_unit="contracts",
        open_interest_base=Decimal("1"),
        open_interest_notional=Decimal("100"),
        volume_24h_raw=Decimal("4567"),
        volume_24h_unit="quote",
    )
    peer = _universe_record(venue="bitget", symbol="BTCUSDT", **common)
    items = build_universe_snapshot([mexc, peer], generated_at=now).items
    assert all(item.reference_mark_median.venue_count == 2 for item in items)
    invalid = replace(mexc, best_bid=None)
    assert all(
        item.reference_mark_median.status == "unavailable"
        for item in build_universe_snapshot([invalid, peer], generated_at=now).items
    )
    other_partial = replace(mexc, error_code="incomplete_source_row")
    assert all(
        item.reference_mark_median.status == "unavailable"
        for item in build_universe_snapshot([other_partial, peer], generated_at=now).items
    )


def test_mexc_publisher_enforces_funding_ttl_even_with_overlong_valid_until():
    from dataclasses import replace

    observed = datetime(2026, 10, 10, tzinfo=UTC)
    now = observed + timedelta(seconds=91)
    record = replace(
        _universe_record(
            venue="mexc",
            symbol="BTC_USDT",
            base="BTC",
            quote="USDT",
            group_id=None,
            cycle_at=observed,
            observed_at=now,
            mark="100",
        ),
        funding_rate_raw=Decimal("0.001"),
        funding_interval_seconds=14400,
        funding_rate_per_hour=Decimal("0.00025"),
        next_funding_at=observed + timedelta(hours=4),
        funding_source_at=observed,
        funding_observed_at=observed,
        funding_valid_until=observed + timedelta(hours=1),
    )
    item = build_universe_snapshot([record], generated_at=now).items[0]
    assert item.mark_price == 100
    assert (
        item.funding_rate_raw,
        item.funding_interval_seconds,
        item.funding_rate_per_hour,
        item.next_funding_at,
    ) == (None, None, None, None)
    assert "funding_expired" in item.quality_reasons


def test_implicit_publication_time_is_after_db_reads(monkeypatch, tmp_path):
    from dataclasses import replace

    import prep_watchdeck_market.artifacts as module

    started = datetime(2026, 10, 10, tzinfo=UTC)
    completed = started + timedelta(seconds=91)
    row = replace(
        _universe_record(
            venue="mexc",
            symbol="BTC_USDT",
            base="BTC",
            quote="USDT",
            group_id=None,
            cycle_at=started,
            observed_at=started,
            mark="100",
        ),
        funding_rate_raw=Decimal("0.001"),
        funding_interval_seconds=14400,
        funding_rate_per_hour=Decimal("0.00025"),
        next_funding_at=started + timedelta(hours=4),
        funding_source_at=started,
        funding_observed_at=started,
        funding_valid_until=started + timedelta(seconds=90),
    )
    wall_clock = started

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return wall_clock

    def records(connection):
        nonlocal wall_clock
        wall_clock = completed
        return (row,)

    monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(module, "read_selected_market", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "read_universe_records", records)
    monkeypatch.setattr(module, "read_chart_records", lambda *args, **kwargs: ())
    monkeypatch.setattr(module, "read_collector_runs", lambda *args, **kwargs: ())
    publish_artifacts(None, tmp_path)
    payload = json.loads((tmp_path / "universe-snapshot.json").read_text())
    assert payload["generatedAt"] == "2026-10-10T00:01:31Z"
    assert payload["items"][0]["fundingRateRaw"] is None
    assert payload["items"][0]["markPrice"] == 100
