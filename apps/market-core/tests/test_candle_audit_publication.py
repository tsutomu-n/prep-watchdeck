from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from prep_watchdeck_market.candle_audit_artifacts import AuditRequest
from prep_watchdeck_market.candle_audit_publication import (
    AuditPublicationError,
    execute_and_publish,
    load_audit_request,
)
from prep_watchdeck_market.runtime_lock import exclusive_runtime_lock


def _input(tmp_path: Path) -> tuple[AuditRequest, Path, Path]:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    start = now - timedelta(minutes=30)
    end = start + timedelta(minutes=10)
    series = {
        "venue": "bitget",
        "source_symbol": "BTCUSDT",
        "venue_instrument_version_id": 1,
        "definition_sha256": "a" * 64,
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "settle_asset": "USDT",
        "price_kind": "trade",
        "interval_seconds": 60,
    }
    rows = []
    for index in range(10):
        bucket = start + timedelta(minutes=index)
        rows.append(
            {
                "venue_instrument_version_id": 1,
                "bucket_at": bucket.isoformat(),
                "open_price": "100",
                "high_price": "102",
                "low_price": "99",
                "close_price": "101",
                "volume_base": "0",
                "volume_notional": None,
                "trade_count": 0,
                "finality": "derived_final",
                "source_at": bucket.isoformat(),
                "observed_at": (bucket + timedelta(minutes=1)).isoformat(),
            }
        )
    snapshot = {"schema_version": 1, "source_label": "synthetic", "series": series, "records": rows}
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text(json.dumps(snapshot), encoding="utf-8")
    right.write_text(json.dumps(snapshot), encoding="utf-8")
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "target": {"venueInstrumentId": "bitget:BTCUSDT", "venueInstrumentVersionId": 1},
                "leftPath": left.name,
                "rightPath": right.name,
                "leftSource": {
                    "sourceId": "snapshot-a",
                    "label": "保存A",
                    "snapshotCreatedAt": now.isoformat(),
                },
                "rightSource": {
                    "sourceId": "snapshot-b",
                    "label": "保存B",
                    "snapshotCreatedAt": now.isoformat(),
                },
                "comparisonKind": "snapshot_revision",
                "evidenceKind": "synthetic",
                "windowStart": start.isoformat(),
                "windowEnd": end.isoformat(),
                "dataAsOf": (end + timedelta(minutes=2)).isoformat(),
                "returnMinutes": 5,
                "compareVolumeBase": True,
                "tolerances": {
                    "priceAbsTol": "0",
                    "priceRelTol": "0",
                    "volumeAbsTol": "0",
                    "volumeRelTol": "0",
                    "returnTolBps": "0",
                },
            }
        ),
        encoding="utf-8",
    )
    return load_audit_request(request_path), request_path, right


def test_publication_is_immutable_and_failure_keeps_previous_completed(tmp_path: Path) -> None:
    request, request_path, right = _input(tmp_path)
    state_dir = tmp_path / "state"
    first = execute_and_publish(request, request_path=request_path, state_dir=state_dir)
    assert first.execution == "completed" and first.outcome == "match"
    first_path = state_dir / "candle-audits" / "runs" / first.run_id / "report.json"
    first_hash = hashlib.sha256(first_path.read_bytes()).hexdigest()
    right.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    failed = execute_and_publish(request, request_path=request_path, state_dir=state_dir)
    assert failed.execution == "invalid_input"
    assert hashlib.sha256(first_path.read_bytes()).hexdigest() == first_hash
    failed_path = state_dir / "candle-audits" / "runs" / failed.run_id / "report.json"
    assert failed_path.exists()
    index = json.loads((state_dir / "artifacts" / "candle-audit-index.json").read_text())
    assert index["entries"][0]["runId"] == failed.run_id
    assert index["entries"][0]["lastCompletedRunId"] == first.run_id
    assert not list((state_dir / "candle-audits").glob(".staging-*"))


def test_audit_summary_counts_values_bars_and_returns_separately(tmp_path: Path) -> None:
    request, request_path, right = _input(tmp_path)
    before = datetime.now(UTC)
    matched = execute_and_publish(request, request_path=request_path, state_dir=tmp_path / "state")
    after = datetime.now(UTC)
    assert before <= matched.started_at <= matched.checked_at <= after
    assert matched.summary is not None
    assert matched.summary.compared_price_values == 40
    assert matched.summary.max_flagged_price_diff_bps is None
    snapshot = json.loads(right.read_text(encoding="utf-8"))
    row = snapshot["records"][5]
    row.update(open_price="101", high_price="103", low_price="100", close_price="102")
    right.write_text(json.dumps(snapshot), encoding="utf-8")
    changed = execute_and_publish(request, request_path=request_path, state_dir=tmp_path / "state")
    assert changed.outcome == "differences"
    assert changed.summary is not None
    assert changed.summary.price_difference_values == 4
    assert changed.summary.price_difference_bars == 1
    assert changed.summary.return_difference_pairs == 1


def test_request_rejects_duplicate_keys_and_input_symlink(tmp_path: Path) -> None:
    request, request_path, right = _input(tmp_path)
    request_path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
    with pytest.raises(AuditPublicationError, match="audit_request_invalid"):
        load_audit_request(request_path)
    request_path.unlink()
    right.rename(tmp_path / "real-right.json")
    right.symlink_to(tmp_path / "real-right.json")
    failed = execute_and_publish(request, request_path=request_path, state_dir=tmp_path / "state")
    assert failed.execution == "invalid_input"
    assert failed.error_code == "audit_input_invalid"


def test_corrupt_index_stops_publication_without_replacing_it(tmp_path: Path) -> None:
    request, request_path, _right = _input(tmp_path)
    state_dir = tmp_path / "state"
    first = execute_and_publish(request, request_path=request_path, state_dir=state_dir)
    index_path = state_dir / "artifacts" / "candle-audit-index.json"
    index_path.write_text('{"schemaVersion":99}', encoding="utf-8")
    before = index_path.read_bytes()
    with pytest.raises(AuditPublicationError, match="audit_index_invalid"):
        execute_and_publish(request, request_path=request_path, state_dir=state_dir)
    assert index_path.read_bytes() == before
    assert (state_dir / "candle-audits" / "runs" / first.run_id / "report.json").exists()


def test_parallel_publications_keep_both_runs_and_one_valid_index(tmp_path: Path) -> None:
    request, request_path, _right = _input(tmp_path)
    state_dir = tmp_path / "state"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                execute_and_publish, request, request_path=request_path, state_dir=state_dir
            )
            for _ in range(2)
        ]
        reports = [future.result() for future in futures]
    assert reports[0].run_id != reports[1].run_id
    assert all(report.execution == "completed" for report in reports)
    runs = state_dir / "candle-audits" / "runs"
    assert all((runs / report.run_id / "report.json").exists() for report in reports)
    index = json.loads((state_dir / "artifacts" / "candle-audit-index.json").read_text())
    assert len(index["entries"]) == 1
    assert index["entries"][0]["runId"] in {report.run_id for report in reports}
    assert not list((state_dir / "candle-audits").glob(".staging-*"))


def test_capacity_and_held_lock_preserve_completed_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, request_path, _right = _input(tmp_path)
    state_dir = tmp_path / "state"
    first = execute_and_publish(request, request_path=request_path, state_dir=state_dir)
    index_path = state_dir / "artifacts" / "candle-audit-index.json"
    original = index_path.read_bytes()
    monkeypatch.setattr("prep_watchdeck_market.candle_audit_publication.MAX_AUDIT_AREA_BYTES", 1)
    with pytest.raises(AuditPublicationError, match="audit_capacity_exceeded"):
        execute_and_publish(request, request_path=request_path, state_dir=state_dir)
    assert index_path.read_bytes() == original
    monkeypatch.setattr(
        "prep_watchdeck_market.candle_audit_publication.time.monotonic",
        iter((0.0, 6.0)).__next__,
    )
    with (
        exclusive_runtime_lock(state_dir / "candle-audits" / "publish.lock"),
        pytest.raises(AuditPublicationError, match="audit_lock_unavailable"),
    ):
        execute_and_publish(request, request_path=request_path, state_dir=state_dir)
    assert index_path.read_bytes() == original
    assert (state_dir / "candle-audits" / "runs" / first.run_id / "report.json").exists()
