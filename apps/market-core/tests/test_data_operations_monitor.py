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

import pytest

ROOT = Path(__file__).resolve().parents[3]
UTILITY = runpy.run_path(str(ROOT / "scripts/market/check-data-operations.py"))
NOW = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "condition", ["explained", "stale", "unknown", "empty", "absent", "identity"]
)
def test_partial_cycle_is_reported_without_masking_unavailable(condition: str) -> None:
    data = inputs()
    stamp = NOW.isoformat()
    for symbol, version, quality in [("BTCUSDT", 8, "ready"), ("SXTUSDT", 9, "partial")]:
        item = copy.deepcopy(data["universe"]["items"][0])
        item.update(
            venueInstrumentId=f"aster:{symbol}",
            venueInstrumentVersionId=version,
            venue="aster",
            quality=quality,
        )
        data["universe"]["items"].append(item)
        data["mapping"]["rows"].append(
            {
                "id": f"aster-{symbol.lower()}",
                "status": "verified",
                "originals": [
                    {"venue": "aster", "instrumentId": f"aster:{symbol}", "versionId": version}
                ],
            }
        )
        metric = copy.deepcopy(data["metrics"]["rows"][0])
        metric.update(
            venueInstrumentId=f"aster:{symbol}", venueInstrumentVersionId=version, venue="aster"
        )
        data["metrics"]["rows"].append(metric)
    data["mapping"]["sourceInstrumentCount"] = 3
    data["service"]["l1"].update(status="partial", errorCode="venue_partial_failure")
    collector = next(c for c in data["service"]["collectors"] if c["runKind"] == "l1")
    collector.update(status="partial", recordsReceived=3, recordsWritten=3, cycleAt=stamp)
    collector["diagnostics"] = {
        "schemaVersion": "persisted-l1-diagnostics-v1",
        "cycleAt": stamp,
        "persistedQualityCountsByVenue": {
            "aster": {"ready": 1, "partial": 1, "unavailable": 0},
            "bitget": {"ready": 1, "partial": 0, "unavailable": 0},
        },
        "persistedReasonCountsByVenue": {"aster": {"incomplete_source_row": 1}, "bitget": {}},
        "persistedExplainedPartialCountsByVenue": {"aster": 1, "bitget": 0},
        "persistedDiagnosticExamples": {
            "aster": [
                {
                    "venueInstrumentId": "aster:SXTUSDT",
                    "venueInstrumentVersionId": 9,
                    "status": "partial",
                    "errorCode": "incomplete_source_row",
                    "missingFields": ["bestBid"],
                    "observedAt": stamp,
                    "sourceAt": stamp,
                }
            ],
            "bitget": [],
        },
    }
    if condition == "stale":
        data["service"]["l1"]["latestAt"] = (NOW - timedelta(seconds=121)).isoformat()
    elif condition == "unknown":
        collector["diagnostics"]["persistedReasonCountsByVenue"]["aster"] = {
            "unexplained_partial": 1
        }
    elif condition == "empty":
        collector["diagnostics"]["persistedQualityCountsByVenue"]["aster"].update(
            ready=0, partial=2
        )
        collector["diagnostics"]["persistedReasonCountsByVenue"]["aster"] = {
            "incomplete_source_row": 2
        }
        data["universe"]["items"][1]["quality"] = "partial"
        example = copy.deepcopy(collector["diagnostics"]["persistedDiagnosticExamples"]["aster"][0])
        example.update(venueInstrumentId="aster:BTCUSDT", venueInstrumentVersionId=8)
        collector["diagnostics"]["persistedDiagnosticExamples"]["aster"].append(example)
    elif condition == "absent":
        del collector["diagnostics"]
    elif condition == "identity":
        collector["diagnostics"]["persistedDiagnosticExamples"]["aster"][0][
            "venueInstrumentVersionId"
        ] = 10
    if "diagnostics" in collector:
        diagnostic = collector["diagnostics"]
        collector["diagnostics"] = {
            "schemaVersion": diagnostic["schemaVersion"],
            "cycleAt": diagnostic["cycleAt"],
            "venues": [
                {
                    "venue": venue,
                    "qualityCounts": counts,
                    "reasonCounts": [
                        {"errorCode": code, "count": count}
                        for code, count in diagnostic["persistedReasonCountsByVenue"][venue].items()
                    ],
                    "explainedPartialCount": diagnostic["persistedExplainedPartialCountsByVenue"][
                        venue
                    ],
                    "examples": diagnostic["persistedDiagnosticExamples"][venue],
                }
                for venue, counts in diagnostic["persistedQualityCountsByVenue"].items()
            ],
        }
    report = UTILITY["check"](**data, now=NOW)
    assert ("l1_unavailable" in report["operationalFailures"]) == (condition != "explained")
    if condition == "explained":
        assert "l1_partial" in report["warnings"]
        assert "native_l1_partial" in report["warnings"]
        assert report["collectorDiagnostics"]["persistedReasonCountsByVenue"]["aster"] == {
            "incomplete_source_row": 1
        }


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


def test_strict_recovery_preserves_native_unicode_id_version_and_definition_bindings():
    # The eight exact native identities rejected by the 1147-instrument roster audit.
    observed = [
        (
            "aster:哈基米USDT",
            9888,
            "3d66fc5011b70b6bf88c4dd17e6f13f9f1b9d84d4ff96fa05f713b37b457872b",
        ),
        (
            "aster:币安人生USDT",
            9681,
            "95946cc36c3eec2a3f8b7baeb453ded128378aae7fade6b6d610b8c61b9b0b41",
        ),
        (
            "aster:我踏马来了USDT",
            9693,
            "a956a7714de1c63f5eb5cfd14d4a746ae06bfdc7ae5742559f01cffed3702329",
        ),
        (
            "aster:牛来USDT",
            9871,
            "c1404998433db817620ca1bc6afdaad671e0e0819ec547af884352c4d44634b3",
        ),
        (
            "aster:龙虾USDT",
            9752,
            "7e592a41e7b9a39e8a1bbb428290b946657d775ce242543d5b89dfc1fa6a9c6c",
        ),
        (
            "bitget:哈基米USDT",
            3187,
            "cdba57ae7f7c28d627ade4d36ef69df5daf864d471abbc87e8afa2095d343a0c",
        ),
        (
            "bitget:牛来USDT",
            4075,
            "73720be682d58c66a2e7958a6cc47d346f5eee3aa0254e5de44af3a9b8d1338c",
        ),
        (
            "bitget:龙虾USDT",
            5756,
            "a1aa70b8ea613527ed3e7fa918b7deb3a3c817033f60091df5607a3cc9e56d59",
        ),
    ]
    document = _completed_recovery()["candleRecovery"]
    document["evidence"]["roster"] = [
        {"venueInstrumentId": key, "venueInstrumentVersionId": version, "definitionHash": digest}
        for key, version, digest in observed
    ]
    document["evidence"]["rosterDigest"] = hashlib.sha256(
        json.dumps(sorted(observed), separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    current = {key: version for key, version, _ in observed}
    before = copy.deepcopy(document)
    assert UTILITY["recovery_roster_matches"](document, "candleRecovery", current)
    assert document == before
    for change in (
        "control",
        "format_control",
        "duplicate",
        "venue",
        "empty_symbol",
        "version",
        "invalid_version",
        "hash",
        "invalid_hash",
    ):
        changed = copy.deepcopy(document)
        row = changed["evidence"]["roster"][0]
        if change == "control":
            row["venueInstrumentId"] += "\n"
        elif change == "format_control":
            row["venueInstrumentId"] += "\u200b"
        elif change == "duplicate":
            changed["evidence"]["roster"].append(copy.deepcopy(row))
        elif change == "venue":
            row["venueInstrumentId"] = "unknown:哈基米USDT"
        elif change == "empty_symbol":
            row["venueInstrumentId"] = "aster:"
        elif change == "version":
            row["venueInstrumentVersionId"] -= 1
        elif change == "invalid_version":
            row["venueInstrumentVersionId"] = 0
        elif change == "hash":
            row["definitionHash"] = "b" * 64
        else:
            row["definitionHash"] = "g" * 64
        exact_current = current
        if change not in {"version", "hash"}:
            # Malformed identities must fail even with a self-consistent digest
            # and current roster, rather than merely due to mismatched bindings.
            keys = [
                (
                    item["venueInstrumentId"],
                    item["venueInstrumentVersionId"],
                    item["definitionHash"],
                )
                for item in changed["evidence"]["roster"]
            ]
            changed["evidence"]["rosterDigest"] = hashlib.sha256(
                json.dumps(sorted(keys), separators=(",", ":"), ensure_ascii=True).encode()
            ).hexdigest()
            exact_current = {key: version for key, version, _ in keys}
        assert not UTILITY["recovery_roster_matches"](changed, "candleRecovery", exact_current), (
            change
        )


def test_running_candle_scan_keeps_direct_proof_through_grid_wait_and_bounded_run():
    data = inputs()
    completed = _completed_recovery()
    previous = completed["candleRecovery"]
    finished = NOW - timedelta(seconds=1265.898621)
    started = finished - timedelta(seconds=593.221796)
    cutoff = started.replace(second=0, microsecond=0) - timedelta(seconds=180)
    previous.update(
        startedAt=started.isoformat(),
        finishedAt=finished.isoformat(),
        generatedAt=finished.isoformat(),
    )
    previous["window"].update(
        start=(cutoff - timedelta(hours=6)).isoformat(), end=cutoff.isoformat()
    )
    data["recovery"] = copy.deepcopy(completed)
    running = data["recovery"]["candleRecovery"]
    running.update(
        runId="c" * 32,
        execution="running",
        finishedAt=None,
        startedAt=(NOW - timedelta(seconds=398.675654)).isoformat(),
        generatedAt=NOW.isoformat(),
        previousCompletedRunId="a" * 32,
        evidence=None,
    )
    report = UTILITY["check"](
        **data, now=NOW, completed_recovery=completed, require_complete_recovery=True
    )
    assert not report["operationalFailures"]
    assert report["recoveryAcceptanceEvidence"]["candleRecovery"]["runId"] == "a" * 32
    for elapsed in (398.675654, 615):
        checked_at = NOW + timedelta(seconds=elapsed - 398.675654)
        selected = UTILITY["select_recovery_evidence"](data["recovery"], completed, now=checked_at)
        blockers = UTILITY["recovery_acceptance_blockers"](
            selected,
            now=checked_at,
            current={"bitget:BTCUSDT": 7},
            active_recovery=data["recovery"],
        )
        assert "candleRecovery_acceptance_unverified" not in blockers
    for change in (
        "waiting",
        "failed",
        "partial",
        "missing",
        "missing_current",
        "timeout",
        "late_start",
        "predecessor",
        "roster",
        "startup",
    ):
        changed, latest = copy.deepcopy(data), copy.deepcopy(completed)
        active = changed["recovery"]["candleRecovery"]
        if change == "waiting":
            changed["recovery"]["candleRecovery"] = copy.deepcopy(previous)
        elif change in {"failed", "partial"}:
            active["execution"] = change
        elif change == "missing":
            latest.pop("candleRecovery")
        elif change == "missing_current":
            changed["recovery"]["candleRecovery"] = None
        elif change == "timeout":
            active["startedAt"] = (NOW - timedelta(seconds=615.001)).isoformat()
        elif change == "late_start":
            active["startedAt"] = (finished + timedelta(seconds=900.001)).isoformat()
        elif change == "predecessor":
            active["previousCompletedRunId"] = "d" * 32
        elif change == "roster":
            latest["candleRecovery"]["evidence"] = _evidence("candleRecovery", version=6)
        else:
            active["trigger"] = "startup"
        result = UTILITY["check"](
            **changed, now=NOW, completed_recovery=latest, require_complete_recovery=True
        )
        assert "candleRecovery_acceptance_unverified" in result["operationalFailures"], change


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
