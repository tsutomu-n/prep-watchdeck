import sqlite3

import pytest
from helpers import feature, generation

from prep_watchdeck_attention.models import (
    AttentionCoverage,
    AttentionResponse,
    InputReference,
)
from prep_watchdeck_attention.storage import AttentionStore


def empty_generation(cutoff=1_800_000_000_000, generation_id="test-generation"):
    inputs = InputReference(
        generation_id=generation_id,
        decision_at=cutoff + 10_000,
        ranking_cutoff=cutoff,
        ranking_generated_at=cutoff + 8_000,
        ranking_generation_id="ranking",
        ranking_map_version="map",
        ranking_metric_version="v1",
        universe_generated_at=cutoff,
        service_generated_at=cutoff,
        market_metrics_generation_id=None,
        market_metrics_generated_at=None,
        market_metrics_candle_cutoff=None,
        input_skew_seconds=8,
    )
    response = AttentionResponse(
        generation_id=generation_id,
        decision_at=inputs.decision_at,
        status="partial",
        reason="no_rows",
        policy_version="attention-components-v1",
        inputs=inputs,
        coverage=AttentionCoverage(rows=0, eligible=0, confluence_ready=0, component_ready={}),
        rows=(),
    )
    return inputs, response


def test_transaction_readback_immutability_and_single_writer(tmp_path):
    inputs, response = empty_generation()
    store = AttentionStore(tmp_path / "attention")
    try:
        assert store.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert store.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(RuntimeError, match="writer"):
            AttentionStore(tmp_path / "attention")
        assert store.save_generation(inputs, (), response, evidence=True)
        assert not store.save_generation(inputs, (), response, evidence=True)
        assert store.latest_response() == response
        altered = response.model_copy(update={"reason": "other"})
        with pytest.raises(ValueError, match="conflict"):
            store.save_generation(inputs, (), altered, evidence=True)
        with pytest.raises(ValueError, match="boundary"):
            i, r = empty_generation(inputs.ranking_cutoff + 60_000, "off-boundary")
            store.save_generation(i, (), r, evidence=True)
        assert store.connection.execute("SELECT COUNT(*) FROM input_generations").fetchone()[0] == 1
    finally:
        store.close()
    reopened = AttentionStore(tmp_path / "attention")
    assert reopened.latest_response() == response
    reopened.close()


def test_transaction_failure_does_not_publish_and_non_evidence_stays_separate(tmp_path):
    store = AttentionStore(tmp_path / "attention")
    try:
        store.connection.execute("""CREATE TRIGGER reject_insert BEFORE INSERT ON input_generations
          BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
        inputs, response = empty_generation()
        with pytest.raises(sqlite3.IntegrityError):
            store.save_generation(inputs, (), response, evidence=True)
        assert store.latest_response() is None
        assert not (tmp_path / "attention/artifacts/current.json").exists()
        store.connection.execute("DROP TRIGGER reject_insert")
        assert store.save_generation(inputs, (), response, evidence=False)
        assert store.evidence_generations() == []
        assert store.connection.execute("SELECT COUNT(*) FROM feature_rows").fetchone()[0] == 0
    finally:
        store.close()


def test_latest_response_breaks_same_decision_time_ties_by_descending_id(tmp_path):
    store = AttentionStore(tmp_path / "attention")
    try:
        for generation_id in ("z-generation", "a-generation"):
            inputs, response = empty_generation(generation_id=generation_id)
            store.save_generation(inputs, (), response, evidence=False)
        latest = store.latest_response()
        assert latest is not None
        assert latest.generation_id == "z-generation"
    finally:
        store.close()


def test_existing_database_gets_latest_order_index_without_changing_readback(tmp_path):
    state = tmp_path / "attention"
    store = AttentionStore(state)
    inputs, response = empty_generation()
    try:
        store.save_generation(inputs, (), response, evidence=False)
        # Reproduce the existing schema before the latest-order index was introduced.
        store.connection.execute("DROP INDEX IF EXISTS input_latest_order")
        original = store.connection.execute("SELECT * FROM input_generations").fetchall()
    finally:
        store.close()

    reopened = AttentionStore(state)
    try:
        statements = []
        reopened.connection.set_trace_callback(statements.append)
        assert reopened.latest_response() == response
        reopened.connection.set_trace_callback(None)
        latest_query = statements[-1]
        plan = reopened.connection.execute("EXPLAIN QUERY PLAN " + latest_query).fetchall()
        assert not any("TEMP B-TREE" in row[3] for row in plan)
        assert any("USING INDEX input_latest_order" in row[3] for row in plan)
        indexes = reopened.connection.execute("PRAGMA index_list(input_generations)").fetchall()
        assert "input_time" in {row[1] for row in indexes}
        assert reopened.connection.execute("SELECT * FROM input_generations").fetchall() == original
        reader = sqlite3.connect(f"file:{state / 'attention.sqlite3'}?mode=ro", uri=True)
        try:
            assert reader.execute("SELECT value FROM metadata WHERE key='schema'").fetchone() == (
                "1",
            )
            assert (
                AttentionResponse.model_validate_json(reader.execute(latest_query).fetchone()[0])
                == response
            )
        finally:
            reader.close()
    finally:
        reopened.close()


def test_database_symlink_rejected_before_any_write(tmp_path):
    target = tmp_path / "original"
    target.write_text("unchanged")
    root = tmp_path / "attention"
    root.mkdir()
    (root / "attention.sqlite3").symlink_to(target)
    with pytest.raises(ValueError):
        AttentionStore(root)
    assert target.read_text() == "unchanged"


def test_evidence_child_readback_must_match_before_publication(tmp_path):
    store = AttentionStore(tmp_path / "attention")
    try:
        store.connection.execute("""CREATE TRIGGER corrupt_feature AFTER INSERT ON feature_rows
          BEGIN UPDATE feature_rows SET payload='{}' WHERE generation_id=NEW.generation_id; END""")
        f = feature()
        inputs, response = generation((f,))
        with pytest.raises(RuntimeError, match="readback"):
            store.save_generation(inputs, (f,), response, evidence=True)
        assert not (tmp_path / "attention/artifacts/current.json").exists()
    finally:
        store.close()
