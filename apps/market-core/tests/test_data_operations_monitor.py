"""Operational alerts distinguish honest data gaps from broken identities and collectors."""

import copy
import hashlib
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


def test_future_metric_diagnostics_keep_field_and_timestamp_with_bounded_output() -> None:
    data = inputs()
    fields = (
        "startAt",
        "endAt",
        "startSourceAt",
        "endSourceAt",
        "startObservedAt",
        "endObservedAt",
    )
    future = (NOW + timedelta(seconds=1)).isoformat()
    for windows in ("tradeChange", "oiChange"):
        for window in data["metrics"]["rows"][0][windows]:
            data["metrics"]["rows"][0][windows][window] = {
                "value": None,
                "availability": "missing",
                "reasonCode": "future_timestamp",
                **dict.fromkeys(fields, future),
            }
    report = UTILITY["check"](**data, now=NOW + timedelta(seconds=2))
    diagnostics = report["metricTimestampDiagnostics"]
    assert "metric_future_timestamp" in report["operationalFailures"]
    assert len(diagnostics) == UTILITY["MAX_METRIC_TIMESTAMP_DIAGNOSTICS"]
    assert report["metricTimestampDiagnosticsTruncated"] is True
    assert diagnostics[0] == {
        "instrumentId": "bitget:BTCUSDT",
        "versionId": 7,
        "metric": "tradeChange.15m",
        "field": "startAt",
        "timestamp": future,
        "validationAt": NOW.isoformat(),
    }


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


def test_monitor_identifies_both_map_versions_and_each_identity_mismatch() -> None:
    data = inputs()
    data["ranking"]["mapVersion"] = "other-running-map"
    data["mapping"]["rows"][0]["originals"][0]["versionId"] = 6
    data["mapping"]["rows"][0]["originals"].append(
        {"venue": "aster", "instrumentId": "aster:REMOVEDUSDT", "versionId": 8}
    )
    data["mapping"]["sourceInstrumentCount"] = 2
    item = copy.deepcopy(data["universe"]["items"][0])
    item["venueInstrumentId"] = "bitget:NEWUSDT"
    data["universe"]["items"].append(item)
    report = UTILITY["check"](**data, now=NOW)
    mapping = report["rankingMap"]
    assert mapping["version"] == "map-reviewed-v2"
    assert mapping["runningVersion"] == "other-running-map"
    assert mapping["versionMatches"] is False
    assert mapping["identityDiagnostics"] == [
        {
            "instrumentId": "aster:REMOVEDUSDT",
            "mappedVersionId": 8,
            "currentVersionId": None,
            "reason": "removed",
        },
        {
            "instrumentId": "bitget:BTCUSDT",
            "mappedVersionId": 6,
            "currentVersionId": 7,
            "reason": "versionMismatch",
        },
        {
            "instrumentId": "bitget:NEWUSDT",
            "mappedVersionId": None,
            "currentVersionId": 7,
            "reason": "unmapped",
        },
    ]
    assert not mapping["identityDiagnosticsTruncated"]
    assert {"ranking_map_version_mismatch", "ranking_original_identity_mismatch"} <= set(
        report["operationalFailures"]
    )
    data["ranking"].pop("mapVersion")
    missing = UTILITY["check"](**data, now=NOW)
    assert missing["rankingMap"]["runningVersion"] is None
    assert "ranking_map_version_mismatch" in missing["operationalFailures"]


def test_monitor_identity_diagnostics_are_bounded_without_hiding_failure() -> None:
    data = inputs()
    original = data["universe"]["items"][0]
    for index in range(25):
        item = copy.deepcopy(original)
        item["venueInstrumentId"] = f"bitget:NEW{index:02}USDT"
        data["universe"]["items"].append(item)
    report = UTILITY["check"](**data, now=NOW)
    assert report["rankingMap"]["connections"]["unmapped"] == 25
    assert len(report["rankingMap"]["identityDiagnostics"]) == 20
    assert report["rankingMap"]["identityDiagnosticsTruncated"]
    assert "ranking_original_identity_mismatch" in report["operationalFailures"]


def test_monitor_missing_mapping_file_is_explicit_and_does_not_call_ranking(
    tmp_path, monkeypatch, capsys
) -> None:
    data = inputs()
    root = tmp_path / "market" / "artifacts"
    root.mkdir(parents=True)
    for name, key in (
        ("universe-snapshot.json", "universe"),
        ("service-state.json", "service"),
        ("market-metrics.json", "metrics"),
    ):
        (root / name).write_text(json.dumps(data[key]))
    calls = []
    monkeypatch.setitem(UTILITY["main"].__globals__, "get_health", lambda url: calls.append(url))
    result = UTILITY["main"](
        [
            "--market-state-dir",
            str(root.parent),
            "--mapping",
            str(tmp_path / "missing-map.json"),
            "--json",
        ]
    )
    assert result == 2
    assert json.loads(capsys.readouterr().out)["inputErrors"] == ["mapping_file_unavailable"]
    assert not calls


def test_acceptance_rejects_unproved_recovery_even_when_operational_exit_would_be_zero() -> None:
    """A succeeded label, null count, or incomplete scan must not authorize collectors."""
    data = inputs()
    complete = {
        "schemaVersion": 1,
        "runId": "a" * 32,
        "generatedAt": NOW.isoformat(),
        "startedAt": (NOW - timedelta(seconds=30)).isoformat(),
        "finishedAt": NOW.isoformat(),
        "execution": "succeeded",
        "trigger": "periodic",
        "window": {
            "start": (NOW - timedelta(hours=6, minutes=4)).isoformat(),
            "end": (NOW - timedelta(minutes=4)).isoformat(),
            "graceSeconds": 180,
        },
        "summary": {
            "targetCount": 1,
            "scannedTargetCount": 1,
            "httpRequests": 0,
            "missingBefore": 0,
            "inserted": 0,
            "newlyPresent": 0,
            "remaining": 0,
            "failedTargets": 0,
            "deferredTargets": 0,
        },
        "errorCode": None,
    }
    data["recovery"] = {"candleRecovery": complete, "endpointRecovery": copy.deepcopy(complete)}
    data["recovery"]["endpointRecovery"]["window"]["start"] = (
        NOW - timedelta(minutes=1445)
    ).isoformat()
    for name, document in data["recovery"].items():
        document["evidence"] = _evidence(name)
    assert UTILITY["check"](**data, now=NOW)["recoveryAcceptanceBlockers"] == []
    cases = [
        ("execution", "running"),
        ("finishedAt", None),
        ("generatedAt", (NOW - timedelta(hours=2)).isoformat()),
        ("summary.remaining", None),
        ("summary.remaining", 1),
        ("summary.scannedTargetCount", 0),
        ("summary.failedTargets", 1),
        ("summary.deferredTargets", 1),
        ("summary.targetCount", 0),
        ("window.start", (NOW - timedelta(minutes=5)).isoformat()),
    ]
    for key, value in cases:
        changed = copy.deepcopy(data)
        obj = changed["recovery"]["candleRecovery"]
        fields = key.split(".")
        for field in fields[:-1]:
            obj = obj[field]
        obj[fields[-1]] = value
        report = UTILITY["check"](**changed, now=NOW)
        assert report["recoveryAcceptanceBlockers"], (key, value)
        strict = UTILITY["check"](**changed, now=NOW, require_complete_recovery=True)
        assert set(report["recoveryAcceptanceBlockers"]) <= set(strict["operationalFailures"])


def _evidence(name, *, version=7):
    roster = [["bitget:BTCUSDT", version, "a" * 64]]
    return {
        "schemaVersion": 1,
        "scope": "full-candle-window" if name == "candleRecovery" else "metric-endpoints",
        "rosterUnchanged": True,
        "rosterDigest": hashlib.sha256(
            json.dumps(roster, separators=(",", ":")).encode()
        ).hexdigest(),
        "roster": [
            {
                "venueInstrumentId": roster[0][0],
                "venueInstrumentVersionId": roster[0][1],
                "definitionHash": roster[0][2],
            }
        ],
    }


def _completed_recovery():
    documents = {}
    for name in ("candleRecovery", "endpointRecovery"):
        documents[name] = {
            "schemaVersion": 1,
            "runId": ("a" if name == "candleRecovery" else "b") * 32,
            "generatedAt": (NOW - timedelta(seconds=5)).isoformat(),
            "startedAt": (NOW - timedelta(seconds=30)).isoformat(),
            "finishedAt": (NOW - timedelta(seconds=5)).isoformat(),
            "execution": "succeeded",
            "trigger": "periodic",
            "errorCode": None,
            "window": {
                "start": (
                    NOW - timedelta(minutes=364 if name == "candleRecovery" else 1445)
                ).isoformat(),
                "end": (NOW - timedelta(minutes=4)).isoformat(),
                "graceSeconds": 180,
            },
            "summary": {
                "targetCount": 1,
                "scannedTargetCount": 1,
                "httpRequests": 0,
                "missingBefore": 0,
                "inserted": 0,
                "newlyPresent": 0,
                "remaining": 0,
                "failedTargets": 0,
                "deferredTargets": 0,
            },
            "evidence": _evidence(name),
        }
    return documents


def test_strict_recovery_requires_exact_roster_and_verified_digest():
    data = inputs()
    data["recovery"] = _completed_recovery()
    assert not UTILITY["check"](**data, now=NOW, require_complete_recovery=True)[
        "operationalFailures"
    ]
    for name in data["recovery"]:
        for change in ("old_version", "digest", "missing", "roster_changed"):
            changed = copy.deepcopy(data)
            document = changed["recovery"][name]
            if change == "old_version":
                document["evidence"] = _evidence(name, version=6)
            elif change == "digest":
                document["evidence"]["roster"][0]["definitionHash"] = "c" * 64
            elif change == "missing":
                document.pop("evidence")
            else:
                document["evidence"]["rosterUnchanged"] = False
            report = UTILITY["check"](**changed, now=NOW, require_complete_recovery=True)
            assert f"{name}_acceptance_unverified" in report["operationalFailures"], change
            assert not UTILITY["check"](**changed, now=NOW)["operationalFailures"]


def test_running_recovery_uses_only_its_direct_completed_predecessor():
    data = inputs()
    completed = _completed_recovery()
    data["recovery"] = copy.deepcopy(completed)
    current = data["recovery"]["endpointRecovery"]
    current.update(
        {
            "runId": "c" * 32,
            "execution": "running",
            "finishedAt": None,
            "startedAt": (NOW - timedelta(seconds=1)).isoformat(),
            "generatedAt": NOW.isoformat(),
            "previousCompletedRunId": "b" * 32,
        }
    )
    report = UTILITY["check"](
        **data, now=NOW, completed_recovery=completed, require_complete_recovery=True
    )
    assert not report["operationalFailures"]
    assert report["recovery"]["endpointRecovery"]["execution"] == "running"
    assert report["recoveryAcceptanceEvidence"]["endpointRecovery"]["runId"] == "b" * 32
    for change in ("failed", "partial", "different_predecessor", "stale_running"):
        changed, latest = copy.deepcopy(data), copy.deepcopy(completed)
        if change in {"failed", "partial"}:
            latest["endpointRecovery"]["execution"] = change
        elif change == "different_predecessor":
            changed["recovery"]["endpointRecovery"]["previousCompletedRunId"] = "d" * 32
        else:
            changed["recovery"]["endpointRecovery"]["startedAt"] = (
                NOW - timedelta(minutes=2)
            ).isoformat()
        result = UTILITY["check"](
            **changed, now=NOW, completed_recovery=latest, require_complete_recovery=True
        )
        assert "endpointRecovery_acceptance_unverified" in result["operationalFailures"], change


def test_warning_occurrences_preserve_exact_metric_and_review_targets(monkeypatch):
    data = inputs()
    data["mapping"]["rows"][0]["status"] = "review"
    report = UTILITY["check"](**data, now=NOW)
    occurrences = report.get("warningOccurrences")
    assert occurrences is not None
    assert {tuple(item.values()) for item in occurrences} == {
        ("mapping_review_required", "bitget:BTCUSDT", 7, "mapping", "review_required"),
        ("native_metric_unavailable", "bitget:BTCUSDT", 7, "tradeChange.15m", "endpoint_missing"),
        ("native_metric_unavailable", "bitget:BTCUSDT", 7, "oiChange.15m", "endpoint_missing"),
        ("native_metric_unavailable", "bitget:BTCUSDT", 7, "oiChange.1h", "endpoint_missing"),
    }
    assert report["warningOccurrenceCount"] == 4
    assert not report["warningOccurrencesTruncated"]
    monkeypatch.setitem(UTILITY["check"].__globals__, "MAX_WARNING_OCCURRENCES", 2)
    limited = UTILITY["check"](**data, now=NOW)
    assert len(limited["warningOccurrences"]) == 2
    assert limited["warningOccurrenceCount"] == 4
    assert limited["warningOccurrencesTruncated"]


def test_completed_failure_cannot_be_hidden_by_current_success():
    data = inputs()
    data["recovery"] = _completed_recovery()
    completed = copy.deepcopy(data["recovery"])
    completed["endpointRecovery"]["execution"] = "partial"
    report = UTILITY["check"](
        **data, now=NOW, completed_recovery=completed, require_complete_recovery=True
    )
    assert "endpointRecovery_acceptance_unverified" in report["operationalFailures"]


def test_acceptance_evidence_does_not_echo_unvalidated_recovery_fields():
    data = inputs()
    data["recovery"] = _completed_recovery()
    data["recovery"]["candleRecovery"]["privateDebug"] = "private-secret-sentinel"
    data["recovery"]["candleRecovery"]["evidence"]["privateDebug"] = "private-secret-sentinel"
    report = UTILITY["check"](**data, now=NOW, require_complete_recovery=True)
    assert not report["operationalFailures"]
    assert "private-secret-sentinel" not in json.dumps(report)


def test_invalid_completed_file_blocks_strict_without_changing_ordinary_monitor(
    tmp_path, monkeypatch, capsys
):
    data = inputs()
    data["recovery"] = _completed_recovery()
    root = tmp_path / "artifacts"
    root.mkdir()
    for filename, document in (
        ("universe-snapshot.json", data["universe"]),
        ("service-state.json", data["service"]),
        ("market-metrics.json", data["metrics"]),
        ("candle-recovery-state.json", data["recovery"]["candleRecovery"]),
        ("candle-endpoint-recovery-state.json", data["recovery"]["endpointRecovery"]),
    ):
        (root / filename).write_text(json.dumps(document))
    (root / "candle-endpoint-recovery-latest-completed.json").write_text("invalid json")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(data["mapping"]))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setitem(UTILITY["main"].__globals__, "datetime", Clock)
    monkeypatch.setitem(UTILITY["main"].__globals__, "get_health", lambda _url: data["ranking"])
    args = ["--market-state-dir", str(tmp_path), "--mapping", str(mapping), "--json"]
    assert UTILITY["main"](args) == 0
    capsys.readouterr()
    assert UTILITY["main"]([*args, "--require-complete-recovery"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert "endpointRecovery_acceptance_unverified" in report["operationalFailures"]


def test_metric_future_at_generation_does_not_become_valid_when_checked_later():
    data = inputs()
    data["recovery"] = _completed_recovery()
    data["metrics"]["rows"][0]["tradeChange"]["1h"]["endSourceAt"] = (
        NOW + timedelta(seconds=1)
    ).isoformat()
    result = UTILITY["check"](
        **data, now=NOW + timedelta(seconds=2), require_complete_recovery=True
    )
    assert "metric_future_timestamp" in result["operationalFailures"]
    assert result["metricTimestampDiagnostics"][0]["validationAt"] == NOW.isoformat()


def test_strict_accepts_completed_publication_before_running_state_is_replaced():
    data = inputs()
    completed = _completed_recovery()
    data["recovery"] = copy.deepcopy(completed)
    current = data["recovery"]["endpointRecovery"]
    current.update(execution="running", finishedAt=None)
    for execution, rejected in (("succeeded", False), ("partial", True), ("failed", True)):
        latest = copy.deepcopy(completed)
        latest["endpointRecovery"]["execution"] = execution
        result = UTILITY["check"](
            **data, now=NOW, completed_recovery=latest, require_complete_recovery=True
        )
        assert (
            "endpointRecovery_acceptance_unverified" in result["operationalFailures"]
        ) is rejected
    completed["endpointRecovery"]["startedAt"] = (NOW - timedelta(seconds=29)).isoformat()
    result = UTILITY["check"](
        **data, now=NOW, completed_recovery=completed, require_complete_recovery=True
    )
    assert "endpointRecovery_acceptance_unverified" in result["operationalFailures"]


def test_inconsistent_terminal_artifacts_cannot_ignore_older_failed_completion():
    data = inputs()
    data["recovery"] = _completed_recovery()
    completed = copy.deepcopy(data["recovery"])
    completed["endpointRecovery"].update(
        runId="d" * 32,
        execution="failed",
        finishedAt=(NOW - timedelta(minutes=2)).isoformat(),
    )
    result = UTILITY["check"](
        **data, now=NOW, completed_recovery=completed, require_complete_recovery=True
    )
    assert "endpointRecovery_acceptance_unverified" in result["operationalFailures"]
