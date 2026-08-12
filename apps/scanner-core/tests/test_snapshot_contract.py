from __future__ import annotations

import json
from pathlib import Path

from prep_watchdeck.adapters.cache import DuckDbCacheProvider
from prep_watchdeck.adapters.duckdb import DuckDbSnapshotCache
from prep_watchdeck.adapters.fixture import FixtureProvider
from prep_watchdeck.adapters.local_snapshot import AtomicSnapshotWriter
from prep_watchdeck.domain.dto import SnapshotDTO


def test_fixture_snapshot_validates() -> None:
    snapshot = FixtureProvider(Path("../../fixtures")).build_snapshot(
        template="balanced", fixture_set="thin-spike"
    )

    assert isinstance(snapshot, SnapshotDTO)
    assert snapshot.source.data_source.value == "fixture"
    assert any(row.category.value == "NO_TRADE" for row in snapshot.rows)


def test_basic_fixture_publishes_short_horizon_contract() -> None:
    snapshot = FixtureProvider(Path("../../fixtures")).build_snapshot(
        template="balanced", fixture_set="basic"
    )

    assert "candidateRule74h" not in snapshot.summary
    assert [item["symbol"] for item in snapshot.rankings["noTrade"]] == ["THINUSDT"]
    assert set(snapshot.rankings) == {"noTrade"}
    assert snapshot.feature_version == "5"
    assert snapshot.ruleset_version == "4"
    assert snapshot.schema_version == 1
    assert {row.symbol: row.activity_phase for row in snapshot.rows} == {
        "ALTUSDT": "SUSTAINED",
        "DUMPUSDT": "NORMAL",
        "NEWALTUSDT": "EXPANDING",
        "THINUSDT": "BURST",
        "SLEEPUSDT": "COOLING",
    }
    assert snapshot.summary["volumeRatio15m"] == {
        "windowMinutes": 15,
        "sampleStepMinutes": 5,
        "baselineSampleCount": 288,
        "approxBaselineSpanMinutes": 1440,
        "statistic": "median",
        "floorUsdt": 1000.0,
    }


def test_fixture_volume_ratio_metadata_follows_active_config(tmp_path) -> None:
    config_dir = tmp_path / "scanner-filters"
    config_dir.mkdir()
    source = Path("../../config/scanner-filters/balanced.toml")
    config = (
        source.read_text(encoding="utf-8")
        .replace("min_required_bars = 383", "min_required_bars = 289")
        .replace("baseline_window_bars = 288", "baseline_window_bars = 96")
        .replace("volume_ratio_floor_usdt = 1000", "volume_ratio_floor_usdt = 2500")
    )
    (config_dir / "balanced.toml").write_text(config, encoding="utf-8")

    snapshot = FixtureProvider(Path("../../fixtures"), config_dir=config_dir).build_snapshot(
        template="balanced", fixture_set="basic"
    )

    assert snapshot.summary["volumeRatio15m"] == {
        "windowMinutes": 15,
        "sampleStepMinutes": 5,
        "baselineSampleCount": 96,
        "approxBaselineSpanMinutes": 480,
        "statistic": "median",
        "floorUsdt": 2500.0,
    }


def test_fixture_sparkline_shape_survives_duckdb_cache_round_trip(tmp_path) -> None:
    snapshot = FixtureProvider(Path("../../fixtures")).build_snapshot(
        template="balanced", fixture_set="basic"
    )
    expected = {row.symbol: row.sparkline for row in snapshot.rows}
    cache = DuckDbSnapshotCache(tmp_path / "watchdeck.duckdb")
    cache.save(snapshot)

    loaded = DuckDbCacheProvider(cache).build_snapshot(template="balanced")

    assert {row.symbol: row.sparkline for row in loaded.rows} == expected


def test_atomic_writer_uses_replace_and_archive(tmp_path) -> None:
    snapshot = FixtureProvider(Path("../../fixtures")).build_snapshot(
        template="balanced", fixture_set="basic"
    )
    latest = tmp_path / "snapshots" / "latest.json"
    AtomicSnapshotWriter(latest).write(snapshot)

    payload = json.loads(latest.read_text())
    assert payload["runId"] == snapshot.run_id
    archive_files = list((tmp_path / "snapshots" / "archive").glob("*/*.json"))
    assert len(archive_files) == 1


def test_atomic_writer_can_skip_archive_for_service_publish(tmp_path) -> None:
    snapshot = FixtureProvider(Path("../../fixtures")).build_snapshot(
        template="balanced", fixture_set="basic"
    )
    latest = tmp_path / "snapshots" / "latest.json"
    AtomicSnapshotWriter(latest, archive=False).write(snapshot)

    payload = json.loads(latest.read_text())
    assert payload["runId"] == snapshot.run_id
    assert not (tmp_path / "snapshots" / "archive").exists()


def test_schema_required_fields_match_rev5_contract() -> None:
    schema = json.loads(Path("../../schemas/scanner-snapshot.schema.json").read_text())

    assert set(schema["required"]) == {
        "schemaVersion",
        "engineVersion",
        "featureVersion",
        "rulesetVersion",
        "configHash",
        "runId",
        "generatedAt",
        "dataAsOf",
        "snapshotStatus",
        "source",
        "summary",
        "rankings",
        "rows",
    }
    assert schema["additionalProperties"] is False
    assert set(schema["$defs"]["SnapshotSourceDTO"]["required"]) == {
        "exchange",
        "productType",
        "templateName",
        "dataSource",
    }
    assert {
        "symbol",
        "ts",
        "category",
        "label",
        "attentionScore",
        "changePctByTf",
        "turnoverUsdtByTf",
        "reasonCodes",
        "riskTagCodes",
        "dataQuality",
    }.issubset(set(schema["$defs"]["ScannerRowDTO"]["required"]))


def test_schema_limits_embedded_sparkline_arrays_to_16_items() -> None:
    schema = json.loads(Path("../../schemas/scanner-snapshot.schema.json").read_text())

    sparkline_property = schema["$defs"]["ScannerRowDTO"]["properties"]["sparkline"]
    assert sparkline_property["anyOf"][0] == {"$ref": "#/$defs/SparklineDTO"}

    properties = schema["$defs"]["SparklineDTO"]["properties"]
    assert properties["points"]["maxItems"] == 16
    assert properties["bars"]["maxItems"] == 16
    assert properties["timeframes"]["additionalProperties"]["maxItems"] == 16


def test_schema_exposes_optional_activity_phase_enum() -> None:
    schema = json.loads(Path("../../schemas/scanner-snapshot.schema.json").read_text())

    row_schema = schema["$defs"]["ScannerRowDTO"]
    activity = row_schema["properties"]["activityPhase"]
    enum_ref = activity["anyOf"][0]["$ref"]

    assert enum_ref == "#/$defs/ActivityPhase"
    assert schema["$defs"]["ActivityPhase"]["enum"] == [
        "BURST",
        "EXPANDING",
        "SUSTAINED",
        "COOLING",
        "NORMAL",
        "UNKNOWN",
    ]
    assert "activityPhase" not in row_schema["required"]


def test_schema_omits_retired_74h_properties_and_keeps_legacy_extension_points() -> None:
    schema = json.loads(Path("../../schemas/scanner-snapshot.schema.json").read_text())
    row_schema = schema["$defs"]["ScannerRowDTO"]

    assert row_schema["additionalProperties"] is True
    assert {
        "priceChange74hPct",
        "turnoverCurrent24hUsdt",
        "turnover24hEnding74hAgoUsdt",
        "volumeChange74h24hPct",
        "userRule74hMatched",
    }.isdisjoint(row_schema["properties"])
    assert schema["properties"]["summary"]["additionalProperties"] is True
    assert schema["properties"]["rankings"]["additionalProperties"] is True


def test_snapshot_reader_accepts_retired_74h_fields_as_legacy_extensions() -> None:
    payload = json.loads(Path("../../fixtures/snapshots/basic.json").read_text())
    payload["summary"]["candidateRule74h"] = {"eligible": 1}
    payload["rankings"]["timeframes"] = {"74h": {}}
    payload["rows"][0]["userRule74hMatched"] = True

    snapshot = SnapshotDTO.model_validate(payload)
    serialized = snapshot.model_dump(mode="json", by_alias=True)

    assert serialized["summary"]["candidateRule74h"] == {"eligible": 1}
    assert serialized["rankings"]["timeframes"] == {"74h": {}}
    assert serialized["rows"][0]["userRule74hMatched"] is True
