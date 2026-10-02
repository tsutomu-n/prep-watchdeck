"""Operational alerts distinguish honest data gaps from broken identities and collectors."""

import copy
import json
import runpy
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
UTILITY = runpy.run_path(str(ROOT / "scripts/market/check-data-operations.py"))
NOW = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)


def inputs() -> dict:
    stamp = NOW.isoformat()
    original = {"venue": "bitget", "instrumentId": "bitget:BTCUSDT", "versionId": 7}
    missing = {"availability": "missing", "reasonCode": "endpoint_missing", "value": None}
    available = {"availability": "available", "reasonCode": None, "value": 92123.456}
    return {
        "universe": {
            "schemaVersion": 1,
            "generatedAt": stamp,
            "status": "ready",
            "items": [
                {
                    "venueInstrumentId": original["instrumentId"],
                    "venueInstrumentVersionId": original["versionId"],
                    "venue": original["venue"],
                    "active": True,
                    "marketType": "linear_perpetual",
                    "quality": "ready",
                    # This is definition provenance, not the latest successful catalog refresh.
                    "catalog": {"observedAt": (NOW - timedelta(days=28)).isoformat()},
                }
            ],
        },
        "service": {
            "schemaVersion": 1,
            "generatedAt": stamp,
            "status": "ready",
            "catalog": {"status": "ready", "latestAt": stamp, "maxAgeSeconds": 1800},
            "l1": {"status": "ready", "latestAt": stamp, "maxAgeSeconds": 120},
            "collectors": [
                {"runKind": kind, "status": "succeeded", "recordsReceived": 1, "recordsWritten": 1}
                for kind in ("catalog", "l1")
            ],
            "artifacts": [
                {"name": "universe-snapshot.json", "status": "ready", "generatedAt": stamp}
            ],
        },
        "metrics": {
            "schemaVersion": 1,
            "generatedAt": stamp,
            "metricVersion": "native-endpoints-v1",
            "candleCutoff": (NOW - timedelta(seconds=180)).isoformat(),
            "rows": [
                {
                    "venueInstrumentId": original["instrumentId"],
                    "venueInstrumentVersionId": original["versionId"],
                    "venue": original["venue"],
                    "tradeChange": {"15m": missing, "1h": available, "24h": available},
                    "oiChange": {"15m": missing, "1h": missing},
                }
            ],
        },
        "mapping": {
            "schemaVersion": "ranking-map-v2",
            "version": "map-reviewed-v2",
            "rosterGeneratedAt": int((NOW - timedelta(days=2)).timestamp() * 1000),
            "sourceInstrumentCount": 1,
            "rows": [{"id": "btc", "status": "verified", "originals": [original]}],
        },
        "ranking": {
            "status": "running",
            "cutoff": int((NOW - timedelta(seconds=60)).timestamp() * 1000),
            "mapVersion": "map-reviewed-v2",
            "lastError": None,
            "invalidContracts": [],
            "providers": {
                provider: {
                    "subscriptions": 1,
                    "connections": 1,
                    "backfill_pending": 0,
                    "last_error": None,
                    "last_closed_at": int(NOW.timestamp() * 1000),
                }
                for provider in ("bybit", "binance")
            },
        },
        "recovery": {
            "candleRecovery": None,
            "endpointRecovery": {
                "schemaVersion": 1,
                "generatedAt": stamp,
                "execution": "partial",
                "summary": {
                    "targetCount": 1,
                    "scannedTargetCount": 1,
                    "httpRequests": 2,
                    "missingBefore": 2,
                    "inserted": 1,
                    "newlyPresent": 1,
                    "remaining": 1,
                    "failedTargets": 0,
                    "deferredTargets": 1,
                },
            },
        },
    }


def test_honest_gaps_old_roster_and_deferred_recovery_are_warnings() -> None:
    data = inputs()
    before = copy.deepcopy(data)
    report = UTILITY["check"](**data, now=NOW)
    assert not report["operationalFailures"]
    assert {
        "roster_older_than_24h",
        "native_metric_unavailable",
        "endpointRecovery_incomplete",
    } <= set(report["warnings"])
    assert report["rankingMap"]["connections"] == {
        "matched": 1,
        "versionMismatch": 0,
        "removed": 0,
        "unmapped": 0,
    }
    assert report["metricCounts"]["bitget"]["tradeChange.15m"]["reasons"] == {"endpoint_missing": 1}
    assert report["recovery"]["endpointRecovery"]["fresh"] is True
    assert "92123.456" not in json.dumps(report)
    assert data == before

    requests = []
    payload = json.dumps(data["ranking"]).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *_args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = UTILITY["health_url"](f"http://127.0.0.1:{server.server_port}")
        assert UTILITY["get_health"](url) == data["ranking"]
        assert requests == ["/health"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_stale_data_broken_identity_and_provider_error_fail_without_disclosing_error() -> None:
    data = inputs()
    data["service"]["collectors"][1]["status"] = "failed"
    data["universe"]["generatedAt"] = (NOW - timedelta(minutes=5)).isoformat()
    data["mapping"]["rows"][0]["originals"][0]["versionId"] = 6
    data["ranking"]["providers"]["bybit"]["last_error"] = "private-secret-sentinel"
    report = UTILITY["check"](**data, now=NOW)
    assert {
        "universe_stale",
        "collector_l1_failed",
        "ranking_original_identity_mismatch",
        "ranking_bybit_provider_error",
    } <= set(report["operationalFailures"])
    assert report["rankingMap"]["connections"]["versionMismatch"] == 1
    assert "private-secret-sentinel" not in json.dumps(report)


def test_cli_rejects_duplicate_payload_and_unsafe_files_or_urls(
    tmp_path, monkeypatch, capsys
) -> None:
    state = tmp_path / "market"
    artifacts = state / "artifacts"
    artifacts.mkdir(parents=True)
    mapping = tmp_path / "map.json"
    mapping.write_text("{}")
    universe = artifacts / "universe-snapshot.json"
    universe.write_text('{"schemaVersion":1,"schemaVersion":1}')
    calls = []
    monkeypatch.setitem(UTILITY["main"].__globals__, "get_health", lambda url: calls.append(url))
    args = ["--market-state-dir", str(state), "--mapping", str(mapping), "--json"]
    assert UTILITY["main"](args) == 2
    assert json.loads(capsys.readouterr().out)["inputErrors"] == ["duplicate_json_key"]
    assert not calls
    universe.unlink()
    universe.symlink_to(mapping)
    assert UTILITY["main"](args) == 2
    assert json.loads(capsys.readouterr().out)["inputErrors"] == ["file_unavailable"]
    assert not calls
    assert UTILITY["main"]([*args, "--ranking-url", "http://example.com:8769"]) == 2
    assert json.loads(capsys.readouterr().out)["inputErrors"] == [
        "ranking_url_must_be_loopback_http"
    ]
    assert not calls
