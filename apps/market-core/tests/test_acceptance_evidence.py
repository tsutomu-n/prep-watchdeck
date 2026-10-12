"""Acceptance decisions retain exact exceptions and the original run's terminal proof."""

from copy import deepcopy

import pytest

SHA = "a" * 64
STAMP = "2026-10-10T01:00:00+00:00"


def warning_fixture():
    occurrence = {
        "code": "native_metric_unavailable",
        "instrumentId": "hyperliquid:TNSR",
        "versionId": 41,
        "metric": "tradeChange.15m",
        "reasonCode": "history_missing",
    }
    report = {
        "checkedAt": STAMP,
        "warnings": ["native_metric_unavailable"],
        "warningOccurrences": [occurrence],
        "warningOccurrenceCount": 1,
        "warningOccurrencesTruncated": False,
    }
    exception = {
        **occurrence,
        "exceptionId": "review-tnsr-15m-41",
        "approved": True,
        "validFrom": "2026-10-10T00:00:00+00:00",
        "validUntil": "2026-10-10T03:00:00+00:00",
        "maxCount": 1,
        "reviewedEvidencePath": "/review/tnsr.json",
        "reviewedEvidenceSha256": SHA,
    }
    return report, [exception], {"/review/tnsr.json": SHA}


def test_exact_reviewed_warning_is_visible_and_no_warning_is_clean():
    from prep_watchdeck_market.acceptance_evidence import validate_warning_exceptions

    report, exceptions, hashes = warning_fixture()
    result = validate_warning_exceptions(report, exceptions, evidence_hashes=hashes)
    assert result["status"] == "PASS_WITH_REVIEWED_EXCEPTIONS"
    assert result["reviewedExceptions"] == ["review-tnsr-15m-41"]
    report.update(warnings=[], warningOccurrences=[], warningOccurrenceCount=0)
    assert validate_warning_exceptions(report, [], evidence_hashes={})["status"] == "PASS"


@pytest.mark.parametrize(
    "change",
    [
        "unknown",
        "target",
        "version",
        "metric",
        "reason",
        "increase",
        "expired",
        "unreviewed",
        "changed-review",
        "truncated",
        "missing-occurrences",
        "missing-count",
        "unlisted-warning",
    ],
)
def test_warning_name_alone_never_authorizes_changed_or_unproved_occurrences(change):
    from prep_watchdeck_market.acceptance_evidence import validate_warning_exceptions

    report, exceptions, hashes = warning_fixture()
    occurrence = report["warningOccurrences"][0]
    if change == "unknown":
        occurrence["code"] = "new_warning"
        report["warnings"] = ["new_warning"]
    elif change in {"target", "version", "metric", "reason"}:
        key = {
            "target": "instrumentId",
            "version": "versionId",
            "metric": "metric",
            "reason": "reasonCode",
        }[change]
        occurrence[key] = 42 if key == "versionId" else "new"
    elif change == "increase":
        report["warningOccurrences"].append(deepcopy(occurrence))
        report["warningOccurrenceCount"] = 2
    elif change == "expired":
        report["checkedAt"] = "2026-10-10T03:00:00+00:00"
    elif change == "unreviewed":
        exceptions[0]["approved"] = False
    elif change == "changed-review":
        hashes["/review/tnsr.json"] = "b" * 64
    elif change == "truncated":
        report["warningOccurrencesTruncated"] = True
    elif change == "missing-occurrences":
        report.pop("warningOccurrences")
    elif change == "missing-count":
        report.pop("warningOccurrenceCount")
    else:
        report["warnings"] = []
    with pytest.raises(ValueError):
        validate_warning_exceptions(report, exceptions, evidence_hashes=hashes)


def completion_fixture():
    sources = {
        name: SHA
        for name in (
            "acceptanceEvidence",
            "completeDriver",
            "observer",
            "funding",
            "dataopsChecker",
        )
    }
    raw = {
        name: SHA
        for name in (
            "observer/samples.jsonl",
            "observer/api-samples.jsonl",
            "funding/samples.jsonl",
        )
    }
    summary = {
        "status": "PASS",
        "phase": "completed",
        "acceptanceTimeComplete": True,
        "clockErrors": [],
        "observedElapsedSeconds": 7200,
        "observedWallSeconds": 7200,
        "samples": 121,
        "startedAt": "2026-10-10T00:00:00+00:00",
        "lastSampleAt": "2026-10-10T02:00:00+00:00",
    }
    acceptance = {
        "stage": 50,
        "fullAcceptance": "PASS",
        "policySha256": SHA,
        "supervisorSha256": SHA,
        "sourceSha256": sources,
        "rawSha256": raw,
        "summary": summary,
    }
    receipt = {
        "schemaVersion": 1,
        "scope": "mexc_stage50_reobservation",
        "phase": "completed",
        "gatePassed": True,
        "fullAcceptance": "PASS",
        "acceptanceSha256": SHA,
        "policySha256": SHA,
        "supervisorSha256": SHA,
        "sourceSha256": sources,
        "startedAt": "2026-10-10T00:00:00+00:00",
        "endedAt": "2026-10-10T02:01:00+00:00",
        "receivedSignals": [],
        "children": {
            name: {"returncode": 0, "signals": [], "processElapsedSeconds": 7201}
            for name in ("observer", "funding")
        },
        "streams": {
            name: {
                "path": path,
                "lastSampleIndex": {"performance": 120, "api": 1029, "funding": 2400}[name],
                "firstSampleAt": "2026-10-10T00:00:00+00:00",
                "lastSampleAt": "2026-10-10T02:00:00+00:00",
                "firstElapsedSeconds": 0,
                "lastElapsedSeconds": 7200,
                "maxSampleGapSeconds": {"performance": 60, "api": 7, "funding": 3}[name],
                "partialTailBytes": 0,
                "completeLineBytes": 100,
                "observedDurationSeconds": 7200,
            }
            for name, path in zip(("performance", "api", "funding"), raw, strict=True)
        },
    }
    service = {
        "systemdExit": {"SERVICE_RESULT": "success", "EXIT_CODE": "exited", "EXIT_STATUS": "0"},
        "fullAcceptance": "PASS",
        "policySha256": SHA,
        "supervisorSha256": SHA,
        "acceptanceSha256": SHA,
    }
    receipt["systemdExit"] = service["systemdExit"]
    kwargs = dict(
        policy_sha256=SHA,
        supervisor_sha256=SHA,
        source_sha256=sources,
        acceptance_sha256=SHA,
        raw_sha256=raw,
        raw_sizes=dict.fromkeys(raw, 100),
        raw_progress=deepcopy(receipt["streams"]),
    )
    return receipt, service, acceptance, kwargs


def test_normal_completed_run_retains_original_acceptance():
    from prep_watchdeck_market.acceptance_evidence import validate_observation_completion

    receipt, service, acceptance, kwargs = completion_fixture()
    assert (
        validate_observation_completion(receipt, service, acceptance, **kwargs)["fullAcceptance"]
        == "PASS"
    )
    for value in (receipt, service, acceptance):
        value["fullAcceptance"] = "PASS_WITH_REVIEWED_EXCEPTIONS"
    assert (
        validate_observation_completion(receipt, service, acceptance, **kwargs)["fullAcceptance"]
        == "PASS_WITH_REVIEWED_EXCEPTIONS"
    )


@pytest.mark.parametrize(
    "change",
    [
        "abnormal",
        "signal",
        "policy",
        "supervisor",
        "source",
        "acceptance-hash",
        "acceptance-result",
        "raw-hash",
        "raw-size",
        "child-failed",
        "child-missing",
        "child-early",
        "short-stream",
        "partial-tail",
        "summary-incomplete",
    ],
)
def test_independent_audit_cannot_upgrade_broken_original_run(change):
    from prep_watchdeck_market.acceptance_evidence import validate_observation_completion

    receipt, service, acceptance, kwargs = completion_fixture()
    if change == "abnormal":
        receipt.update(phase="abnormal_exit", gatePassed=False, fullAcceptance="NOT_ACCEPTED")
    elif change == "signal":
        service["systemdExit"] = {
            "SERVICE_RESULT": "signal",
            "EXIT_CODE": "killed",
            "EXIT_STATUS": "9",
        }
    elif change == "policy":
        kwargs["policy_sha256"] = "b" * 64
    elif change == "supervisor":
        receipt["supervisorSha256"] = "b" * 64
    elif change == "source":
        kwargs["source_sha256"] = dict(kwargs["source_sha256"], observer="b" * 64)
    elif change == "acceptance-hash":
        kwargs["acceptance_sha256"] = "b" * 64
    elif change == "acceptance-result":
        acceptance["fullAcceptance"] = "NOT_ACCEPTED"
    elif change == "raw-hash":
        kwargs["raw_sha256"] = dict(kwargs["raw_sha256"], **{"funding/samples.jsonl": "b" * 64})
    elif change == "raw-size":
        kwargs["raw_sizes"]["funding/samples.jsonl"] = 101
    elif change == "child-failed":
        receipt["children"]["funding"]["returncode"] = -9
    elif change == "child-missing":
        receipt["children"].pop("funding")
    elif change == "child-early":
        receipt["children"]["funding"]["processElapsedSeconds"] = 7199
    elif change == "short-stream":
        receipt["streams"]["funding"]["observedDurationSeconds"] = 7199
    elif change == "partial-tail":
        receipt["streams"]["api"]["partialTailBytes"] = 1
    else:
        acceptance["summary"]["acceptanceTimeComplete"] = False
    with pytest.raises(ValueError):
        validate_observation_completion(receipt, service, acceptance, **kwargs)


def test_recovery_roster_hashes_must_match_independent_database_snapshot():
    import hashlib
    import json

    from prep_watchdeck_market import acceptance_evidence

    current = [
        {
            "venueInstrumentId": "aster:PEARLUSDT",
            "venueInstrumentVersionId": 9981,
            "definitionHash": SHA,
        }
    ]
    report = {
        "recoveryAcceptanceEvidence": {
            name: {"evidence": {"roster": deepcopy(current)}}
            for name in ("candleRecovery", "endpointRecovery")
        }
    }
    assert hasattr(acceptance_evidence, "validate_recovery_definitions")
    assert acceptance_evidence.validate_recovery_definitions(report, current)["accepted"] is True
    for name in ("candleRecovery", "endpointRecovery"):
        changed = deepcopy(report)
        evidence = changed["recoveryAcceptanceEvidence"][name]["evidence"]
        evidence["roster"][0]["definitionHash"] = "b" * 64
        # The artifact has a self-consistent digest, but it is not the stored DB definition.
        evidence["rosterDigest"] = hashlib.sha256(
            json.dumps([["aster:PEARLUSDT", 9981, "b" * 64]], separators=(",", ":")).encode()
        ).hexdigest()
        with pytest.raises(ValueError, match="recovery_definition_database_mismatch"):
            acceptance_evidence.validate_recovery_definitions(changed, current)


@pytest.mark.parametrize("change", ["duration", "index", "tail", "gap", "summary"])
def test_raw_progress_must_independently_match_receipt_and_summary(change):
    from prep_watchdeck_market.acceptance_evidence import validate_observation_completion

    receipt, service, acceptance, kwargs = completion_fixture()
    progress = kwargs["raw_progress"]["performance"]
    if change == "duration":
        progress["observedDurationSeconds"] = 1
    elif change == "index":
        progress["lastSampleIndex"] = 1
    elif change == "tail":
        progress["partialTailBytes"] = 1
    elif change == "gap":
        progress["maxSampleGapSeconds"] = 7200
        receipt["streams"]["performance"]["maxSampleGapSeconds"] = 7200
    else:
        acceptance["summary"]["samples"] = 120
    with pytest.raises(ValueError):
        validate_observation_completion(receipt, service, acceptance, **kwargs)


def test_api_terminal_sample_retains_existing_thirty_second_allowance():
    from prep_watchdeck_market.acceptance_evidence import validate_observation_completion

    receipt, service, acceptance, kwargs = completion_fixture()
    for stream in (receipt["streams"]["api"], kwargs["raw_progress"]["api"]):
        stream.update(
            lastSampleAt="2026-10-10T01:59:30+00:00",
            lastElapsedSeconds=7170,
            observedDurationSeconds=7170,
        )
    assert (
        validate_observation_completion(receipt, service, acceptance, **kwargs)["fullAcceptance"]
        == "PASS"
    )
    for stream in (receipt["streams"]["api"], kwargs["raw_progress"]["api"]):
        stream["observedDurationSeconds"] = 7169
    with pytest.raises(ValueError):
        validate_observation_completion(receipt, service, acceptance, **kwargs)
