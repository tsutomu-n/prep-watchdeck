from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prep_watchdeck.adapters.duckdb import DuckDbServiceStore, DuckDbSnapshotCache
from prep_watchdeck.adapters.local_snapshot import AtomicSnapshotWriter
from prep_watchdeck.application.service_snapshot import (
    CHART_SOURCE_1M_BARS,
    CHART_SOURCE_5M_BARS,
    aggregate_1m_to_5m,
    build_service_snapshot,
    publish_service_snapshot_once,
    required_analysis_5m_bars,
    snapshot_from_service_store,
)
from prep_watchdeck.config.templates import load_template
from prep_watchdeck.domain.enums import DataSource
from prep_watchdeck.domain.service_models import (
    Candle1mRecord,
    InstrumentRecord,
    OpenInterestSampleRecord,
    TickerLatestRecord,
)
from prep_watchdeck.interfaces.cli import app
from prep_watchdeck.models import CandleBar

runner = CliRunner()


def test_aggregate_1m_to_5m_builds_ohlcv_buckets() -> None:
    candles = [
        candle("ALTUSDT", 1_781_000_000_000, 1.0, 1.2, 0.9, 1.1, 100.0),
        candle("ALTUSDT", 1_781_000_060_000, 1.1, 1.3, 1.0, 1.2, 110.0),
        candle("ALTUSDT", 1_781_000_300_000, 1.2, 1.5, 1.1, 1.4, 120.0),
    ]

    bars_by_symbol = aggregate_1m_to_5m(candles)

    assert len(bars_by_symbol["ALTUSDT"]) == 2
    first = bars_by_symbol["ALTUSDT"][0]
    assert first.ts == 1_780_999_800_000
    assert float(first.open) == 1.0
    assert float(first.high) == 1.3
    assert float(first.low) == 0.9
    assert float(first.close) == 1.2
    assert float(first.quote_vol) == 210.0


def test_snapshot_from_service_store_reuses_scanner_contract(tmp_path) -> None:
    store = service_store_with_market_data(tmp_path)
    config = load_template(Path("../../config/scanner-filters"), "balanced")

    snapshot = snapshot_from_service_store(
        store,
        template="balanced",
        config=config,
        generated_at_ms=1_781_000_900_000,
        run_id="service-test",
    )

    assert snapshot.run_id == "service-test"
    assert snapshot.source.data_source == DataSource.LIVE
    assert snapshot.source.is_fallback is False
    assert snapshot.summary["serviceSource"] == "duckdb-service"
    assert snapshot.summary["counts"]["NO_TRADE"] == 1
    assert snapshot.rows[0].symbol == "ALTUSDT"
    assert snapshot.rows[0].data_quality == "MISSING"
    assert snapshot.rows[0].sparkline is not None
    assert snapshot.rows[0].sparkline == {
        "tf": "5m",
        "points": [1.11, 1.16, 1.21, 1.26, 1.29],
    }


def test_snapshot_from_service_store_includes_optional_market_comparison(tmp_path) -> None:
    store = service_store_with_market_data(tmp_path)
    config = load_template(Path("../../config/scanner-filters"), "balanced")
    comparison: dict[str, object] = {
        "schemaVersion": 1,
        "mode": "mark_price_pilot_v1",
        "symbols": [],
    }
    venue_comparison: dict[str, object] = {
        "schemaVersion": 1,
        "mode": "perp_venue_comparison_v1",
        "items": [],
    }

    snapshot = snapshot_from_service_store(
        store,
        template="balanced",
        config=config,
        market_comparison=comparison,
        perp_venue_comparison=venue_comparison,
        generated_at_ms=1_781_000_900_000,
        run_id="service-market-comparison-test",
    )

    assert snapshot.summary["marketComparison"] == comparison
    assert snapshot.summary["perpVenueComparison"] == venue_comparison


def test_snapshot_from_service_store_excludes_unsupported_symbols(tmp_path) -> None:
    store = service_store_with_market_data(tmp_path)
    store.upsert_instruments([instrument("龙虾USDT", "龙虾")])
    store.upsert_ticker_latest([ticker("龙虾USDT")])
    store.upsert_candles_1m(
        [
            candle(
                "龙虾USDT",
                1_781_000_000_000 + index * 60_000,
                1.0,
                1.2,
                0.9,
                1.1,
                1000.0,
            )
            for index in range(30)
        ]
    )
    config = load_template(Path("../../config/scanner-filters"), "balanced")

    snapshot = snapshot_from_service_store(
        store,
        template="balanced",
        config=config,
        generated_at_ms=1_781_000_900_000,
        run_id="service-safe-symbol-test",
    )

    assert {row.symbol for row in snapshot.rows} == {"ALTUSDT"}


def test_snapshot_from_service_store_does_not_mark_stale_history_ok(tmp_path) -> None:
    old_start_ms = 1_780_000_000_000
    one_minute_ms = 60_000
    required_1m_bars = 1915
    candles: list[Candle1mRecord] = []
    for index in range(required_1m_bars):
        ts_ms = old_start_ms + index * one_minute_ms
        candles.append(candle("ALTUSDT", ts_ms, 1.0, 1.2, 0.9, 1.0 + index * 0.0001, 1000.0))
        candles.append(candle("BTCUSDT", ts_ms, 100.0, 101.0, 99.0, 100.0, 1000.0))
    store = MemoryServiceStore(
        instruments=[
            instrument("ALTUSDT", "ALT"),
            instrument("BTCUSDT", "BTC"),
        ],
        tickers=[
            ticker("ALTUSDT"),
            ticker("BTCUSDT"),
        ],
        candles=candles,
    )
    config = load_template(Path("../../config/scanner-filters"), "balanced")

    snapshot = snapshot_from_service_store(
        store,
        template="balanced",
        config=config,
        generated_at_ms=old_start_ms + 10 * 24 * 60 * one_minute_ms,
        run_id="service-stale-history-test",
    )

    assert all(row.data_quality != "OK" for row in snapshot.rows)


def test_snapshot_from_service_store_surfaces_repairable_gap_risk_tag(tmp_path) -> None:
    window_end_ms = 1_781_000_700_000
    latest_candle_ts_ms = window_end_ms + 5 * 60_000
    required_1m_bars = 1915
    window_start_ms = window_end_ms - (required_1m_bars - 1) * 60_000
    missing_ts_ms = window_start_ms + 123 * 60_000
    candles: list[Candle1mRecord] = []
    for index in range(required_1m_bars + 5):
        ts_ms = window_start_ms + index * 60_000
        if ts_ms != missing_ts_ms:
            candles.append(candle("ALTUSDT", ts_ms, 1.0, 1.2, 0.9, 1.1, 1000.0))
        candles.append(candle("BTCUSDT", ts_ms, 100.0, 101.0, 99.0, 100.0, 1000.0))
    store = MemoryServiceStore(
        instruments=[
            instrument("ALTUSDT", "ALT"),
            instrument("BTCUSDT", "BTC"),
        ],
        tickers=[
            ticker("ALTUSDT"),
            ticker("BTCUSDT"),
        ],
        candles=candles,
    )
    config = load_template(Path("../../config/scanner-filters"), "balanced")

    snapshot = snapshot_from_service_store(
        store,
        template="balanced",
        config=config,
        generated_at_ms=latest_candle_ts_ms,
        run_id="service-gap-tag-test",
    )

    row = next(item for item in snapshot.rows if item.symbol == "ALTUSDT")
    assert "DATA_GAP_REPAIRABLE" in row.risk_tag_codes


def test_snapshot_from_service_store_does_not_flag_publish_lag_as_gap(tmp_path) -> None:
    window_end_ms = 1_781_000_700_000
    latest_candle_ts_ms = window_end_ms + 5 * 60_000
    generated_at_ms = latest_candle_ts_ms + 3 * 60_000
    required_1m_bars = 1915
    window_start_ms = window_end_ms - (required_1m_bars - 1) * 60_000
    candles: list[Candle1mRecord] = []
    for index in range(required_1m_bars + 5):
        ts_ms = window_start_ms + index * 60_000
        candles.append(candle("ALTUSDT", ts_ms, 1.0, 1.2, 0.9, 1.1, 1000.0))
        candles.append(candle("BTCUSDT", ts_ms, 100.0, 101.0, 99.0, 100.0, 1000.0))
    store = MemoryServiceStore(
        instruments=[
            instrument("ALTUSDT", "ALT"),
            instrument("BTCUSDT", "BTC"),
        ],
        tickers=[
            ticker("ALTUSDT"),
            ticker("BTCUSDT"),
        ],
        candles=candles,
    )
    config = load_template(Path("../../config/scanner-filters"), "balanced")

    snapshot = snapshot_from_service_store(
        store,
        template="balanced",
        config=config,
        generated_at_ms=generated_at_ms,
        run_id="service-publish-lag-test",
    )

    row = next(item for item in snapshot.rows if item.symbol == "ALTUSDT")
    assert "DATA_GAP_REPAIRABLE" not in row.risk_tag_codes
    assert "DATA_HISTORY_SHORT" not in row.risk_tag_codes


def test_snapshot_from_service_store_marks_tail_lag_as_stale_not_repairable(tmp_path) -> None:
    window_end_ms = 1_781_000_700_000
    latest_candle_ts_ms = window_end_ms + 5 * 60_000
    required_1m_bars = 1915
    window_start_ms = window_end_ms - (required_1m_bars - 1) * 60_000
    candles: list[Candle1mRecord] = []
    for index in range(required_1m_bars + 5):
        ts_ms = window_start_ms + index * 60_000
        if ts_ms <= window_end_ms - 2 * 60_000:
            candles.append(candle("ALTUSDT", ts_ms, 1.0, 1.2, 0.9, 1.1, 1000.0))
        candles.append(candle("BTCUSDT", ts_ms, 100.0, 101.0, 99.0, 100.0, 1000.0))
    store = MemoryServiceStore(
        instruments=[
            instrument("ALTUSDT", "ALT"),
            instrument("BTCUSDT", "BTC"),
        ],
        tickers=[
            ticker("ALTUSDT"),
            ticker("BTCUSDT"),
        ],
        candles=candles,
    )
    config = load_template(Path("../../config/scanner-filters"), "balanced")

    snapshot = snapshot_from_service_store(
        store,
        template="balanced",
        config=config,
        generated_at_ms=latest_candle_ts_ms,
        run_id="service-tail-lag-test",
    )

    row = next(item for item in snapshot.rows if item.symbol == "ALTUSDT")
    assert row.category == "NO_TRADE"
    assert row.data_quality == "STALE"
    assert row.attention_score == 0.0
    assert "DATA_NOT_OK" in row.risk_tag_codes
    assert "DATA_GAP_REPAIRABLE" not in row.risk_tag_codes
    assert "DATA_STALE" in row.risk_tag_codes


def test_snapshot_from_service_store_surfaces_history_short_and_zero_volume_tags(tmp_path) -> None:
    window_end_ms = 1_781_000_700_000
    required_1m_bars = 1915
    window_start_ms = window_end_ms - (required_1m_bars - 1) * 60_000
    candles: list[Candle1mRecord] = []
    for index in range(30):
        ts_ms = window_start_ms + (required_1m_bars - 30 + index) * 60_000
        candles.append(candle("NEWUSDT", ts_ms, 1.0, 1.2, 0.9, 1.1, 1000.0))
        zero_volume = 0.0 if index == 5 else 1000.0
        candles.append(
            candle("ZEROUSDT", window_start_ms + index * 60_000, 2.0, 2.2, 1.9, 2.1, zero_volume)
        )
        candles.append(
            candle("BTCUSDT", window_start_ms + index * 60_000, 100.0, 101.0, 99.0, 100.0, 1000.0)
        )
    store = MemoryServiceStore(
        instruments=[
            instrument("NEWUSDT", "NEW"),
            instrument("ZEROUSDT", "ZERO"),
            instrument("BTCUSDT", "BTC"),
        ],
        tickers=[
            ticker("NEWUSDT"),
            ticker("ZEROUSDT"),
            ticker("BTCUSDT"),
        ],
        candles=candles,
    )
    config = load_template(Path("../../config/scanner-filters"), "balanced")

    snapshot = snapshot_from_service_store(
        store,
        template="balanced",
        config=config,
        generated_at_ms=window_end_ms,
        run_id="service-gap-short-tag-test",
    )

    by_symbol = {row.symbol: row for row in snapshot.rows}
    assert "DATA_HISTORY_SHORT" in by_symbol["NEWUSDT"].risk_tag_codes
    assert "DATA_ZERO_VOLUME" in by_symbol["ZEROUSDT"].risk_tag_codes


def test_duckdb_service_store_load_candles_1m_since_filters_by_timestamp(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    store.upsert_candles_1m(
        [
            candle("ALTUSDT", 1_781_000_000_000, 1.0, 1.1, 0.9, 1.0, 100.0),
            candle("ALTUSDT", 1_781_000_060_000, 1.0, 1.2, 0.9, 1.1, 120.0),
        ]
    )

    rows = store.load_candles_1m_since(1_781_000_060_000)

    assert [row.ts_ms for row in rows] == [1_781_000_060_000]


def test_duckdb_service_store_loads_compact_snapshot_candle_window(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    bucket_start_ms = 1_781_000_100_000
    store.upsert_candles_1m(
        [
            candle("ALTUSDT", bucket_start_ms, 1.0, 1.2, 0.9, 1.1, 100.0),
            candle("ALTUSDT", bucket_start_ms + 60_000, 1.1, 1.4, 1.0, 1.3, 120.0),
            candle("ALTUSDT", bucket_start_ms + 300_000, 1.3, 1.5, 1.2, 1.4, 140.0),
            candle("BTCUSDT", bucket_start_ms, 100.0, 102.0, 99.0, 101.0, 200.0),
        ]
    )

    bars_by_symbol = store.load_candles_5m_since(bucket_start_ms)

    assert store.count_candles_1m_since(bucket_start_ms) == 4
    assert store.latest_candle_1m_ts_since(bucket_start_ms) == bucket_start_ms + 300_000
    assert [bar.ts for bar in bars_by_symbol["ALTUSDT"]] == [
        bucket_start_ms,
        bucket_start_ms + 300_000,
    ]
    first = bars_by_symbol["ALTUSDT"][0]
    assert (float(first.open), float(first.high), float(first.low), float(first.close)) == (
        1.0,
        1.4,
        0.9,
        1.3,
    )
    assert float(first.base_vol) == 220.0
    assert float(first.quote_vol) == 220.0


def test_duckdb_service_store_limits_compact_candles_to_requested_symbols(tmp_path) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    bucket_start_ms = 1_781_000_100_000
    store.upsert_candles_1m(
        [
            candle("ALTUSDT", bucket_start_ms, 1.0, 1.2, 0.9, 1.1, 100.0),
            candle("BTCUSDT", bucket_start_ms, 100.0, 102.0, 99.0, 101.0, 200.0),
            candle("OTHERUSDT", bucket_start_ms, 2.0, 2.2, 1.9, 2.1, 300.0),
        ]
    )

    bars_by_symbol = store.load_candles_5m_since(
        bucket_start_ms,
        ["ALTUSDT", "BTCUSDT"],
    )

    assert sorted(bars_by_symbol) == ["ALTUSDT", "BTCUSDT"]


def test_service_snapshot_separates_analysis_gap_and_chart_windows(monkeypatch) -> None:
    generated_at_ms = 1_800_000_000_000
    config = load_template(Path("../../config/scanner-filters"), "balanced")
    store = RecordingCompactServiceStore(generated_at_ms=generated_at_ms)
    captured_bar_counts: dict[str, int] = {}

    from prep_watchdeck.application import service_snapshot as service_snapshot_module

    original_build_scanner_rows = service_snapshot_module.build_scanner_rows

    def recording_build_scanner_rows(**kwargs):
        captured_bar_counts.update(
            {symbol: len(bars) for symbol, bars in kwargs["candles_by_symbol"].items()}
        )
        return original_build_scanner_rows(**kwargs)

    monkeypatch.setattr(
        service_snapshot_module,
        "build_scanner_rows",
        recording_build_scanner_rows,
    )

    build = build_service_snapshot(
        store,
        template="balanced",
        config=config,
        generated_at_ms=generated_at_ms,
        run_id="window-separation-test",
    )

    analysis_5m_bars = required_analysis_5m_bars(config)
    gap_end_ms = generated_at_ms - 5 * 60_000
    gap_start_ms = gap_end_ms - (analysis_5m_bars * 5 - 1) * 60_000
    chart_start_ms = gap_end_ms - (CHART_SOURCE_1M_BARS - 1) * 60_000

    assert analysis_5m_bars == 383
    assert captured_bar_counts == {"ALTUSDT": 383, "BTCUSDT": 383}
    assert len(build.chart_candles_by_symbol["ALTUSDT"]) == CHART_SOURCE_5M_BARS
    assert store.five_minute_starts[-1] == chart_start_ms
    assert store.five_minute_symbols[-1] == ["ALTUSDT", "BTCUSDT"]
    assert store.count_starts[-1] == chart_start_ms
    assert store.range_calls == [(["ALTUSDT", "BTCUSDT"], gap_start_ms, gap_end_ms)]
    assert gap_end_ms - gap_start_ms == (1915 - 1) * 60_000
    assert build.snapshot.summary["serviceCandles1m"] == CHART_SOURCE_1M_BARS * 2


def test_publish_service_snapshot_once_writes_latest_json(tmp_path) -> None:
    store = service_store_with_market_data(tmp_path)
    config = load_template(Path("../../config/scanner-filters"), "balanced")
    latest = tmp_path / "snapshots" / "latest.json"
    stale_chart = latest.parent / "charts" / "latest" / "STALEUSDT.json"
    non_json_chart_artifact = latest.parent / "charts" / "latest" / "README.txt"
    stale_chart.parent.mkdir(parents=True, exist_ok=True)
    stale_chart.write_text("{}\n", encoding="utf-8")
    non_json_chart_artifact.write_text("local note\n", encoding="utf-8")

    snapshot = publish_service_snapshot_once(
        store,
        AtomicSnapshotWriter(latest),
        DuckDbSnapshotCache(store.path),
        template="balanced",
        config=config,
        generated_at_ms=1_781_000_900_000,
        run_id="service-test",
    )

    payload = json.loads(latest.read_text())
    assert payload["runId"] == snapshot.run_id
    assert payload["source"]["dataSource"] == "live"
    assert payload["summary"]["serviceSource"] == "duckdb-service"
    assert payload["rows"][0]["sparkline"]["points"]
    assert "bars" not in payload["rows"][0]["sparkline"]
    assert "timeframes" not in payload["rows"][0]["sparkline"]
    chart = json.loads((latest.parent / "charts" / "latest" / "ALTUSDT.json").read_text())
    assert set(chart) == {
        "schemaVersion",
        "snapshotRunId",
        "symbol",
        "generatedAt",
        "dataAsOf",
        "timeframes",
    }
    assert chart["schemaVersion"] == 2
    assert chart["snapshotRunId"] == snapshot.run_id
    assert chart["symbol"] == "ALTUSDT"
    assert chart["timeframes"]["5m"]
    assert chart["timeframes"]["15m"]
    assert not stale_chart.exists()
    assert non_json_chart_artifact.exists()


def test_publish_service_chart_failure_keeps_previous_latest(tmp_path) -> None:
    store = service_store_with_market_data(tmp_path)
    config = load_template(Path("../../config/scanner-filters"), "balanced")
    latest = tmp_path / "snapshots" / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text('{"runId":"previous"}\n', encoding="utf-8")
    blocking_chart_path = latest.parent / "charts" / "latest"
    blocking_chart_path.parent.mkdir()
    blocking_chart_path.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(OSError):
        publish_service_snapshot_once(
            store,
            AtomicSnapshotWriter(latest, archive=False),
            DuckDbSnapshotCache(store.path),
            template="balanced",
            config=config,
            generated_at_ms=1_781_000_900_000,
            run_id="service-chart-failure",
        )

    assert json.loads(latest.read_text())["runId"] == "previous"


def test_publish_service_snapshot_rejects_stale_candles_and_keeps_previous_latest(
    tmp_path,
) -> None:
    store = service_store_with_market_data(tmp_path)
    config = load_template(Path("../../config/scanner-filters"), "balanced")
    latest = tmp_path / "snapshots" / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text('{"runId":"previous","rows":[{"symbol":"LIVEUSDT"}]}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="service candle data is stale"):
        publish_service_snapshot_once(
            store,
            AtomicSnapshotWriter(latest, archive=False),
            DuckDbSnapshotCache(store.path),
            template="balanced",
            config=config,
            generated_at_ms=1_781_002_000_000,
            run_id="stale-service-test",
            max_data_lag_ms=120_000,
        )

    assert json.loads(latest.read_text()) == {
        "runId": "previous",
        "rows": [{"symbol": "LIVEUSDT"}],
    }


def test_publish_service_snapshot_accepts_the_existing_120_second_boundary(
    tmp_path,
) -> None:
    store = service_store_with_market_data(tmp_path)
    config = load_template(Path("../../config/scanner-filters"), "balanced")
    latest = tmp_path / "snapshots" / "latest.json"

    snapshot = publish_service_snapshot_once(
        store,
        AtomicSnapshotWriter(latest, archive=False),
        DuckDbSnapshotCache(store.path),
        template="balanced",
        config=config,
        generated_at_ms=1_781_001_860_999,
        run_id="service-boundary-test",
        max_data_lag_ms=120_000,
    )

    assert snapshot.run_id == "service-boundary-test"
    assert json.loads(latest.read_text())["runId"] == "service-boundary-test"


def test_publish_service_cli_rejects_unavailable_recent_candles_and_keeps_latest(
    tmp_path,
    monkeypatch,
) -> None:
    service_store_with_market_data(tmp_path)
    out_dir = tmp_path / "snapshots"
    out_dir.mkdir()
    latest = out_dir / "latest.json"
    latest.write_text('{"runId":"previous","rows":[{"symbol":"LIVEUSDT"}]}\n', encoding="utf-8")
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_DB_PATH", str(tmp_path / "watchdeck.duckdb"))
    monkeypatch.setenv("PREP_WATCHDECK_OUT_DIR", str(out_dir))
    monkeypatch.setenv("PREP_WATCHDECK_SERVICE_STATE_PATH", str(out_dir / "service-state.json"))
    monkeypatch.setenv("PREP_WATCHDECK_CONFIG_DIR", str(Path("../../config/scanner-filters")))
    monkeypatch.setattr(
        "prep_watchdeck.application.service_snapshot.time.time",
        lambda: 1_781_900_000.0,
    )
    monkeypatch.setattr(
        "prep_watchdeck.interfaces.cli.collect_market_comparison_once",
        lambda: None,
    )
    monkeypatch.setattr(
        "prep_watchdeck.interfaces.cli.collect_perp_venue_comparison_once",
        lambda: None,
    )

    result = runner.invoke(app, ["publish-service", "--template", "balanced"])

    assert result.exit_code == 2
    assert "service unavailable service candle data is unavailable" in result.output
    assert json.loads(latest.read_text()) == {
        "runId": "previous",
        "rows": [{"symbol": "LIVEUSDT"}],
    }


def test_publish_service_cli_writes_state_and_latest_json(tmp_path, monkeypatch) -> None:
    service_store_with_market_data(tmp_path)
    out_dir = tmp_path / "snapshots"
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_DB_PATH", str(tmp_path / "watchdeck.duckdb"))
    monkeypatch.setenv("PREP_WATCHDECK_OUT_DIR", str(out_dir))
    monkeypatch.setenv("PREP_WATCHDECK_SERVICE_STATE_PATH", str(out_dir / "service-state.json"))
    monkeypatch.setenv("PREP_WATCHDECK_CONFIG_DIR", str(Path("../../config/scanner-filters")))
    monkeypatch.setattr(
        "prep_watchdeck.application.service_snapshot.time.time",
        lambda: 1_781_001_800.0,
    )
    comparison = {"schemaVersion": 1, "mode": "mark_price_pilot_v1", "symbols": []}
    venue_comparison = {
        "schemaVersion": 1,
        "mode": "perp_venue_comparison_v1",
        "items": [],
    }
    monkeypatch.setattr(
        "prep_watchdeck.interfaces.cli.collect_market_comparison_once",
        lambda: comparison,
    )
    monkeypatch.setattr(
        "prep_watchdeck.interfaces.cli.collect_perp_venue_comparison_once",
        lambda: venue_comparison,
    )

    result = runner.invoke(app, ["publish-service", "--template", "balanced"])

    assert result.exit_code == 0
    assert "service snapshot published" in result.output
    latest = json.loads((out_dir / "latest.json").read_text())
    state = json.loads((out_dir / "service-state.json").read_text())
    assert latest["summary"]["serviceSource"] == "duckdb-service"
    assert latest["summary"]["marketComparison"] == comparison
    assert latest["summary"]["perpVenueComparison"] == venue_comparison
    assert state["diagnostics"]["tickerCount"] == 2


def service_store_with_market_data(tmp_path) -> DuckDbServiceStore:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    store.upsert_instruments(
        [
            instrument("ALTUSDT", "ALT"),
            instrument("BTCUSDT", "BTC"),
        ]
    )
    store.upsert_ticker_latest(
        [
            ticker("ALTUSDT"),
            ticker("BTCUSDT"),
        ]
    )
    candles: list[Candle1mRecord] = []
    for index in range(30):
        ts_ms = 1_781_000_000_000 + index * 60_000
        candles.append(candle("ALTUSDT", ts_ms, 1.0, 1.2, 0.9, 1.0 + index * 0.01, 1000.0))
        candles.append(candle("BTCUSDT", ts_ms, 100.0, 101.0, 99.0, 100.0, 1000.0))
    store.upsert_candles_1m(candles)
    return store


def instrument(symbol: str, base_coin: str) -> InstrumentRecord:
    return InstrumentRecord(
        symbol=symbol,
        product_type="USDT-FUTURES",
        symbol_type="perpetual",
        symbol_status="normal",
        base_coin=base_coin,
        quote_coin="USDT",
        max_leverage=25.0,
        is_rwa=False,
        updated_at_ms=1_781_000_000_000,
    )


def ticker(symbol: str) -> TickerLatestRecord:
    return TickerLatestRecord(
        symbol=symbol,
        ts_ms=1_781_000_000_000,
        last_price=1.0 if symbol == "ALTUSDT" else 100.0,
        high_24h=1.4 if symbol == "ALTUSDT" else 110.0,
        low_24h=0.8 if symbol == "ALTUSDT" else 90.0,
        change_24h=0.05,
        funding_rate=0.0001,
        holding_amount=12345.0,
        quote_volume_24h=1_000_000.0,
        updated_at_ms=1_781_000_000_000,
    )


def candle(
    symbol: str,
    ts_ms: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    quote_volume: float,
) -> Candle1mRecord:
    return Candle1mRecord(
        symbol=symbol,
        ts_ms=ts_ms,
        open=open_,
        high=high,
        low=low,
        close=close,
        base_volume=quote_volume,
        quote_volume=quote_volume,
        usdt_volume=quote_volume,
        is_closed=False,
        source="test",
        updated_at_ms=ts_ms,
    )


class MemoryServiceStore:
    def __init__(
        self,
        *,
        instruments: list[InstrumentRecord],
        tickers: list[TickerLatestRecord],
        candles: list[Candle1mRecord],
    ) -> None:
        self.instruments = instruments
        self.tickers = tickers
        self.candles = candles
        self.oi_samples: list[OpenInterestSampleRecord] = []

    def load_instruments(self) -> list[InstrumentRecord]:
        return self.instruments

    def load_ticker_latest(self) -> list[TickerLatestRecord]:
        return self.tickers

    def load_recent_candles_1m(self, limit_per_symbol: int) -> list[Candle1mRecord]:
        if limit_per_symbol < 1:
            raise ValueError("limit_per_symbol must be positive")
        rows: list[Candle1mRecord] = []
        for symbol in sorted({candle.symbol for candle in self.candles}):
            symbol_rows = [candle for candle in self.candles if candle.symbol == symbol]
            rows.extend(sorted(symbol_rows, key=lambda item: item.ts_ms)[-limit_per_symbol:])
        return rows

    def load_candles_1m_since(self, start_ts_ms: int) -> list[Candle1mRecord]:
        return sorted(
            [candle for candle in self.candles if candle.ts_ms >= start_ts_ms],
            key=lambda item: (item.symbol, item.ts_ms),
        )

    def load_candles_1m_range(
        self,
        symbols: list[str],
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> list[Candle1mRecord]:
        wanted = set(symbols)
        return sorted(
            [
                candle
                for candle in self.candles
                if candle.symbol in wanted and start_ts_ms <= candle.ts_ms <= end_ts_ms
            ],
            key=lambda item: (item.symbol, item.ts_ms),
        )

    def upsert_open_interest_samples(self, samples: list[OpenInterestSampleRecord]) -> None:
        by_key = {(sample.symbol, sample.bucket_ts_ms): sample for sample in self.oi_samples}
        for sample in samples:
            key = (sample.symbol, sample.bucket_ts_ms)
            current = by_key.get(key)
            if current is None or sample.source_ts_ms > current.source_ts_ms:
                by_key[key] = sample
        self.oi_samples = list(by_key.values())

    def load_open_interest_samples(
        self, start_ts_ms: int, end_ts_ms: int
    ) -> list[OpenInterestSampleRecord]:
        return sorted(
            [
                sample
                for sample in self.oi_samples
                if start_ts_ms <= sample.bucket_ts_ms <= end_ts_ms
            ],
            key=lambda sample: (sample.symbol, sample.bucket_ts_ms),
        )

    def delete_open_interest_samples_before(self, cutoff_ts_ms: int) -> int:
        before = len(self.oi_samples)
        self.oi_samples = [
            sample for sample in self.oi_samples if sample.bucket_ts_ms >= cutoff_ts_ms
        ]
        return before - len(self.oi_samples)


class RecordingCompactServiceStore(MemoryServiceStore):
    def __init__(self, *, generated_at_ms: int) -> None:
        super().__init__(
            instruments=[instrument("ALTUSDT", "ALT"), instrument("BTCUSDT", "BTC")],
            tickers=[ticker("ALTUSDT"), ticker("BTCUSDT")],
            candles=[],
        )
        self.generated_at_ms = generated_at_ms
        self.five_minute_starts: list[int] = []
        self.five_minute_symbols: list[list[str]] = []
        self.count_starts: list[int] = []
        self.range_calls: list[tuple[list[str], int, int]] = []

    def load_candles_5m_since(
        self,
        start_ts_ms: int,
        symbols: list[str],
    ) -> dict[str, list[CandleBar]]:
        self.five_minute_starts.append(start_ts_ms)
        self.five_minute_symbols.append(symbols)
        return {
            symbol: [
                CandleBar(
                    symbol=symbol,
                    ts=self.generated_at_ms - (CHART_SOURCE_5M_BARS - index) * 300_000,
                    open=Decimal("1"),
                    high=Decimal("1.1"),
                    low=Decimal("0.9"),
                    close=Decimal("1"),
                    base_vol=Decimal("100"),
                    quote_vol=Decimal("1000"),
                )
                for index in range(CHART_SOURCE_5M_BARS)
            ]
            for symbol in ("ALTUSDT", "BTCUSDT")
        }

    def count_candles_1m_since(self, start_ts_ms: int) -> int:
        self.count_starts.append(start_ts_ms)
        return CHART_SOURCE_1M_BARS * 2

    def latest_candle_1m_ts_since(self, start_ts_ms: int) -> int | None:
        _ = start_ts_ms
        return self.generated_at_ms

    def load_candles_1m_range(
        self,
        symbols: list[str],
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> list[Candle1mRecord]:
        self.range_calls.append((symbols, start_ts_ms, end_ts_ms))
        return []


class FailingOiMemoryServiceStore(MemoryServiceStore):
    def upsert_open_interest_samples(self, samples: list[OpenInterestSampleRecord]) -> None:
        _ = samples
        raise RuntimeError("oi write failed")


def test_service_snapshot_uses_exact_seeded_60m_oi_and_restart_state(tmp_path) -> None:
    generated_at_ms = 1_781_001_800_000
    source_ts_ms = generated_at_ms - 30_000
    current_bucket_ts_ms = source_ts_ms - (source_ts_ms % 300_000)
    target_bucket_ts_ms = current_bucket_ts_ms - 60 * 60 * 1000
    db_path = tmp_path / "watchdeck.duckdb"
    store = service_store_with_market_data(tmp_path)
    store.upsert_ticker_latest(
        [
            ticker("ALTUSDT").model_copy(
                update={
                    "ts_ms": source_ts_ms,
                    "updated_at_ms": source_ts_ms + 1_000,
                    "holding_amount": 120.0,
                }
            ),
            ticker("BTCUSDT").model_copy(
                update={
                    "ts_ms": source_ts_ms,
                    "updated_at_ms": source_ts_ms + 1_000,
                    "holding_amount": 200.0,
                }
            ),
        ]
    )
    store.upsert_open_interest_samples(
        [
            OpenInterestSampleRecord(
                symbol="ALTUSDT",
                bucket_ts_ms=target_bucket_ts_ms,
                holding_amount=100.0,
                source_ts_ms=target_bucket_ts_ms + 1_000,
                updated_at_ms=generated_at_ms,
            )
        ]
    )
    config = load_template(Path("../../config/scanner-filters"), "balanced")

    first = snapshot_from_service_store(
        store,
        template="balanced",
        config=config,
        generated_at_ms=generated_at_ms,
        run_id="oi-first",
    )
    restarted_store = DuckDbServiceStore(db_path)
    second = snapshot_from_service_store(
        restarted_store,
        template="balanced",
        config=config,
        generated_at_ms=generated_at_ms,
        run_id="oi-restart",
    )
    samples = restarted_store.load_open_interest_samples(target_bucket_ts_ms, current_bucket_ts_ms)

    assert next(row for row in first.rows if row.symbol == "ALTUSDT").open_interest_state == (
        "INCREASING"
    )
    assert next(row for row in second.rows if row.symbol == "ALTUSDT").open_interest_state == (
        "INCREASING"
    )
    assert first.summary["oiDiagnostics"]["status"] == "ok"
    assert {(sample.symbol, sample.bucket_ts_ms) for sample in samples} == {
        ("ALTUSDT", target_bucket_ts_ms),
        ("ALTUSDT", current_bucket_ts_ms),
        ("BTCUSDT", current_bucket_ts_ms),
    }


def test_service_snapshot_requires_exact_oi_bucket(tmp_path) -> None:
    generated_at_ms = 1_781_001_800_000
    source_ts_ms = generated_at_ms - 30_000
    current_bucket_ts_ms = source_ts_ms - (source_ts_ms % 300_000)
    target_bucket_ts_ms = current_bucket_ts_ms - 60 * 60 * 1000
    store = service_store_with_market_data(tmp_path)
    store.upsert_ticker_latest(
        [
            ticker("ALTUSDT").model_copy(
                update={
                    "ts_ms": source_ts_ms,
                    "updated_at_ms": source_ts_ms,
                    "holding_amount": 120.0,
                }
            )
        ]
    )
    store.upsert_open_interest_samples(
        [
            OpenInterestSampleRecord(
                symbol="ALTUSDT",
                bucket_ts_ms=target_bucket_ts_ms + 300_000,
                holding_amount=100.0,
                source_ts_ms=target_bucket_ts_ms + 301_000,
                updated_at_ms=generated_at_ms,
            )
        ]
    )

    snapshot = snapshot_from_service_store(
        store,
        template="balanced",
        config=load_template(Path("../../config/scanner-filters"), "balanced"),
        generated_at_ms=generated_at_ms,
        run_id="oi-exact-missing",
    )

    assert next(row for row in snapshot.rows if row.symbol == "ALTUSDT").open_interest_state == (
        "UNKNOWN"
    )


def test_service_snapshot_continues_with_diagnostic_when_oi_cycle_fails() -> None:
    generated_at_ms = 1_781_001_800_000
    candles = [
        candle(
            "ALTUSDT",
            1_781_000_000_000 + index * 60_000,
            1.0,
            1.2,
            0.9,
            1.0,
            1000.0,
        )
        for index in range(30)
    ]
    store = FailingOiMemoryServiceStore(
        instruments=[instrument("ALTUSDT", "ALT")],
        tickers=[
            ticker("ALTUSDT").model_copy(
                update={
                    "ts_ms": generated_at_ms - 30_000,
                    "updated_at_ms": generated_at_ms - 20_000,
                    "holding_amount": 120.0,
                }
            )
        ],
        candles=candles,
    )

    snapshot = snapshot_from_service_store(
        store,
        template="balanced",
        config=load_template(Path("../../config/scanner-filters"), "balanced"),
        generated_at_ms=generated_at_ms,
        run_id="oi-degraded",
    )

    assert snapshot.summary["oiDiagnostics"] == {
        "status": "degraded",
        "code": "OI_HISTORY_UNAVAILABLE",
        "errorType": "RuntimeError",
    }
    assert all(row.open_interest_state == "UNKNOWN" for row in snapshot.rows)
