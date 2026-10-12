from __future__ import annotations

import gzip
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from prep_watchdeck_market.bundle_files import BundleError, json_bytes, sha256
from tests.test_research_journal import Clock, native_payload, record


def test_gap_report_uses_actual_native_buckets_and_same_cohort(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
    from prep_watchdeck_market.research.quality import quality_report

    data = native_payload()
    data["window_start"] = "2026-10-09T00:00:00Z"
    data["states"][0]["open_interest_raw"] = None
    with ObservationJournal(tmp_path / "journal", clock=Clock()) as journal:
        record(journal, data, Clock())
    report = quality_report(export_snapshot(tmp_path / "journal", tmp_path / "snapshots"))
    assert report["counts"]["expected_minutes"] == 2
    assert report["counts"]["candles"] == 1
    assert report["counts"]["common_price_activity_oi"] == 0
    assert report["missing"]["candles"] == ["2026-10-09T00:00:00+00:00"]
    assert report["exclusions"]["oi_missing"] == 1


def test_archive_reconcile_checks_bytes_and_reports_value_conflicts(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.quality import reconcile_archives

    rows = native_payload()["candles"]
    original = tmp_path / "original.parquet"
    alternate = tmp_path / "alternate.parquet"
    pl.DataFrame(rows).write_parquet(original)
    pl.DataFrame([{**rows[0], "close_price": "102"}]).write_parquet(alternate)
    manifest = {
        "instrument_id": "bitget:TESTUSDT",
        "version_id": 1,
        "definition_hash": "a" * 64,
        "window_start": "2026-10-09T00:00:00Z",
        "window_end": "2026-10-09T00:02:00Z",
        "valid_from": "2026-10-08T00:00:00Z",
        "valid_to": None,
        "sources": [
            {
                "path": str(path),
                "sha256": sha256(path.read_bytes()),
                "dataset": "candles",
                "instrument_id": "bitget:TESTUSDT",
                "version_id": 1,
                "definition_hash": "a" * 64,
            }
            for path in (original, alternate)
        ],
    }
    before = original.read_bytes()
    result = reconcile_archives(manifest)
    assert result["conflicts"][0]["at"] == "2026-10-09T00:01:00+00:00"
    assert result["backfill_candidates"] == ["2026-10-09T00:00:00+00:00"]
    assert result["point_in_time_replay"] is False
    assert original.read_bytes() == before
    pl.DataFrame([{**rows[0], "volume_notional": "999999"}]).write_parquet(alternate)
    manifest["sources"][1]["sha256"] = sha256(alternate.read_bytes())
    changed_activity = reconcile_archives(manifest)
    assert changed_activity["conflicts"][0]["fields"] == ["volume_notional"]
    manifest["sources"][0]["sha256"] = "f" * 64
    with pytest.raises(BundleError, match="research_hash_mismatch"):
        reconcile_archives(manifest)


def funding_file(path: Path, rate: str = "0.0001") -> bytes:
    raw = (
        "venue,category,symbol,funding_time_ms,funding_rate,current_instrument_fund_interval_hours\n"
        f"bitget,USDT-FUTURES,TESTUSDT,1791504000000,{rate},8\n"
    ).encode()
    data = gzip.compress(raw)
    path.write_bytes(data)
    return data


def test_funding_import_keeps_actual_coverage_and_rejects_conflicting_rates(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.quality import inspect_funding_sources

    first, second = tmp_path / "first.csv.gz", tmp_path / "second.csv.gz"
    funding_file(first)
    funding_file(second, "0.0002")
    manifest = {
        "venue": "bitget",
        "category": "USDT-FUTURES",
        "symbol": "TESTUSDT",
        "sources": [{"path": str(first), "sha256": sha256(first.read_bytes())}],
        "window_start": datetime.fromtimestamp(1791504000, UTC).isoformat(),
        "window_end": datetime.fromtimestamp(1791504000 + 86400, UTC).isoformat(),
    }
    result = inspect_funding_sources(manifest)
    assert result["rows"] == 1
    assert result["coverage"] == "observed_rows_only"
    assert result["schedule_verified"] is False
    assert result["lineage"][0]["sha256"] == sha256(first.read_bytes())
    manifest["sources"].append({"path": str(second), "sha256": sha256(second.read_bytes())})
    with pytest.raises(BundleError, match="research_funding_conflict"):
        inspect_funding_sources(manifest)


def test_ccxt_comparison_requires_native_identity_and_does_not_repair_history(
    tmp_path: Path,
) -> None:
    from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
    from prep_watchdeck_market.research.tool_inputs import compare_ccxt

    with ObservationJournal(tmp_path / "journal", clock=Clock()) as journal:
        record(journal, native_payload(), Clock())
    snapshot = export_snapshot(tmp_path / "journal", tmp_path / "snapshots")
    reference = {
        "schema_version": 1,
        "source": "ccxt",
        "exchange_id": "bitget",
        "native_symbol": "TESTUSDT",
        "ccxt_version": "test",
        "captured_at": "2026-10-09T00:03:00Z",
        "volume_unit": "base",
        "has": {"fetchOHLCV": True, "fetchOpenInterest": False},
        "ohlcv": [[1791504060000, 100, 110, 99, 101, 10.0]],
    }
    report = compare_ccxt(snapshot, reference)
    assert report["matched_rows"] == 1
    assert report["history_repaired"] is False
    assert report["capabilities"]["fetchOpenInterest"] == "unsupported"
    from prep_watchdeck_market.bundle_files import strict_json

    assert compare_ccxt(snapshot, strict_json(json_bytes(reference)))["matched_rows"] == 1
    reference["native_symbol"] = "DIFFERENTUSDT"
    with pytest.raises(BundleError, match="research_identity_mismatch"):
        compare_ccxt(snapshot, reference)


def test_hft_gate_rejects_sparse_snapshots_and_prepares_continuous_ticks(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.tool_inputs import prepare_hft_input

    events = [
        {
            "kind": "snapshot",
            "sequence": 1,
            "exchange_ns": 100,
            "local_ns": 110,
            "bids": [["100", "2"]],
            "asks": [["101", "3"]],
        },
        {
            "kind": "depth",
            "sequence": 2,
            "exchange_ns": 200,
            "local_ns": 215,
            "side": "bid",
            "price": "100",
            "quantity": "1",
        },
        {
            "kind": "trade",
            "sequence": 3,
            "exchange_ns": 250,
            "local_ns": 270,
            "side": "buy",
            "price": "101",
            "quantity": "0.1",
        },
    ]
    source = tmp_path / "ticks.json"
    source.write_bytes(json_bytes(events))
    metadata = {
        "schema_version": 1,
        "instrument_id": "bitget:TESTUSDT",
        "version_id": 1,
        "definition_hash": "a" * 64,
        "quantity_unit": "base",
        "tick_size": "0.1",
        "lot_size": "0.1",
        "source_path": str(source),
        "source_sha256": sha256(source.read_bytes()),
        "feed_kind": "continuous_l2_and_trades",
        "sequence_scope": "combined_capture",
        "capture_complete": True,
        "aggressor_side_verified": True,
    }
    output = prepare_hft_input(metadata, tmp_path / "prepared")
    assert (output / "events.json").is_file()
    assert source.read_bytes() == json_bytes(events)
    import importlib.util

    from prep_watchdeck_market.bundle_files import strict_json, sums_bytes
    from prep_watchdeck_market.research.tool_inputs import export_hft_npz

    if importlib.util.find_spec("numpy") is not None:
        np = importlib.import_module("numpy")

        exported = export_hft_npz(output, tmp_path / "npz")
        with np.load(exported / "data.npz", allow_pickle=False) as archive:
            assert archive["data"].dtype.names == (
                "ev",
                "exch_ts",
                "local_ts",
                "px",
                "qty",
                "order_id",
                "ival",
                "fval",
            )
            assert len(archive["data"]) == 4
            assert archive["data"]["qty"][-1] == 0.1
    prepared = strict_json((output / "events.json").read_bytes())
    prepared["rows"][-1][4] = -1
    from prep_watchdeck_market.research.files import plain_json

    (output / "events.json").write_bytes(json_bytes(plain_json(prepared)))
    manifest = strict_json((output / "manifest.json").read_bytes())
    manifest["files"]["events.json"] = sha256((output / "events.json").read_bytes())
    (output / "manifest.json").write_bytes(json_bytes(manifest))
    (output / "SHA256SUMS").write_bytes(
        sums_bytes(
            {name: (output / name).read_bytes() for name in [*manifest["files"], "manifest.json"]}
        )
    )
    with pytest.raises(BundleError, match="research_hft_input_invalid"):
        export_hft_npz(output, tmp_path / "bad-npz")
    metadata["feed_kind"] = "periodic_snapshots"
    with pytest.raises(BundleError, match="research_hft_feed_ineligible"):
        prepare_hft_input(metadata, tmp_path / "rejected")
    metadata["feed_kind"] = "continuous_l2_and_trades"
    events[1]["sequence"] = 4
    source.write_bytes(json_bytes(events))
    metadata["source_sha256"] = sha256(source.read_bytes())
    with pytest.raises(BundleError, match="research_hft_sequence_gap"):
        prepare_hft_input(metadata, tmp_path / "rejected-2")


def test_hft_extreme_grid_reports_safe_error() -> None:
    from decimal import Decimal

    from prep_watchdeck_market.research.tool_inputs import _tick

    with pytest.raises(BundleError, match="research_hft_grid_invalid"):
        _tick("100", Decimal("1e-30"), positive=True)
