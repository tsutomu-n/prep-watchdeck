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


def test_basic_fixture_computes_candidate_74h_contract() -> None:
    snapshot = FixtureProvider(Path("../../fixtures")).build_snapshot(
        template="balanced", fixture_set="basic"
    )

    candidate_rule = snapshot.summary["candidateRule74h"]
    assert candidate_rule["eligible"] == 1
    assert candidate_rule["notMatched"] == 0
    assert candidate_rule["unknown"] == 3
    assert [item["symbol"] for item in snapshot.rankings["timeframes"]["15m"]["changeUp"]] == [
        "ALTUSDT"
    ]
    assert [item["symbol"] for item in snapshot.rankings["noTrade"]] == ["THINUSDT"]
    assert snapshot.feature_version == "3"
    assert snapshot.ruleset_version == "3"
    assert snapshot.schema_version == 1


def test_fixture_provider_uses_template_ranking_top_n(tmp_path) -> None:
    config_dir = tmp_path / "scanner-filters"
    config_dir.mkdir()
    source = Path("../../config/scanner-filters/balanced.toml")
    config = source.read_text(encoding="utf-8").replace("top_n = 10", "top_n = 1")
    (config_dir / "balanced.toml").write_text(config, encoding="utf-8")

    snapshot = FixtureProvider(Path("../../fixtures"), config_dir=config_dir).build_snapshot(
        template="balanced", fixture_set="basic"
    )

    assert len(snapshot.rankings["timeframes"]["15m"]["changeUp"]) == 1
    assert snapshot.rankings["meta"]["timeframes"]["15m"]["changeUp"]["limit"] == 1


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
