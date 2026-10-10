"""Pure, fail-closed decisions for a finite observation's acceptance evidence.

Host runners supply hashes of the bytes they actually read. This module neither reads runtime
state nor approves policy; callers must pin this source and obtain operational authorization.
"""

import math
import re
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

ACCEPTED = frozenset({"PASS", "PASS_WITH_REVIEWED_EXCEPTIONS"})
WARNING_CODES = frozenset({"native_metric_unavailable", "mapping_review_required"})
RAW_STREAMS = {
    "performance": "observer/samples.jsonl",
    "api": "observer/api-samples.jsonl",
    "funding": "funding/samples.jsonl",
}
SOURCE_NAMES = frozenset(
    {"acceptanceEvidence", "completeDriver", "observer", "funding", "dataopsChecker"}
)
NORMAL_EXIT = {"SERVICE_RESULT": "success", "EXIT_CODE": "exited", "EXIT_STATUS": "0"}


class EvidenceError(ValueError):
    """A fixed reason code, suitable for receipts without disclosing source data."""


def _need(condition: object, code: str) -> None:
    if not condition:
        raise EvidenceError(code)


def _object(value: object, code: str) -> Mapping[str, Any]:
    _need(isinstance(value, Mapping), code)
    assert isinstance(value, Mapping)
    return value


def _time(value: object) -> datetime:
    _need(isinstance(value, str), "evidence_time_invalid")
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise EvidenceError("evidence_time_invalid") from None
    _need(result.tzinfo is not None, "evidence_time_invalid")
    return result


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _seconds(value: object, minimum: float) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= minimum
    )


def _warning_key(value: Mapping[str, Any]) -> tuple[str, str, int, str, str]:
    code, instrument, version, metric, reason = (
        value.get(key) for key in ("code", "instrumentId", "versionId", "metric", "reasonCode")
    )
    _need(code in WARNING_CODES, "warning_code_unknown")
    _need(
        all(isinstance(item, str) and item.strip() for item in (instrument, metric, reason))
        and type(version) is int
        and version > 0,
        "warning_identity_incomplete",
    )
    return cast(tuple[str, str, int, str, str], (code, instrument, version, metric, reason))


def validate_warning_exceptions(
    report: Mapping[str, Any],
    exceptions: object,
    *,
    evidence_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Match every occurrence to one exact, time-bounded, reviewed permission.

    maxCount is per report, so repeated scheduled reports do not consume an exception budget.
    Distinct instruments, versions, metrics and reasons always need distinct permissions.
    """
    checked = _time(report.get("checkedAt"))
    occurrences, warnings = report.get("warningOccurrences"), report.get("warnings")
    _need(
        isinstance(occurrences, list)
        and report.get("warningOccurrencesTruncated") is False
        and type(report.get("warningOccurrenceCount")) is int
        and report.get("warningOccurrenceCount") == len(occurrences),
        "warning_occurrences_incomplete",
    )
    _need(
        isinstance(warnings, list) and all(isinstance(x, str) for x in warnings),
        "warning_codes_invalid",
    )
    assert isinstance(occurrences, list)
    assert isinstance(warnings, list)
    counts = Counter(
        _warning_key(_object(row, "warning_occurrence_invalid")) for row in occurrences
    )
    _need(set(warnings) == {key[0] for key in counts}, "warning_codes_disagree")
    _need(isinstance(exceptions, list), "warning_exception_policy_missing")
    assert isinstance(exceptions, list)
    permissions, identifiers = {}, set()
    for raw in exceptions:
        item = _object(raw, "warning_exception_invalid")
        key = _warning_key(item)
        identifier = item.get("exceptionId")
        _need(
            isinstance(identifier, str)
            and identifier.strip()
            and identifier not in identifiers
            and key not in permissions,
            "warning_exception_duplicate_or_unnamed",
        )
        _need(item.get("approved") is True, "warning_exception_unreviewed")
        _need(
            type(item.get("maxCount")) is int and item["maxCount"] > 0,
            "warning_exception_limit_invalid",
        )
        start, end = _time(item.get("validFrom")), _time(item.get("validUntil"))
        _need(start < end, "warning_exception_period_invalid")
        path, digest = item.get("reviewedEvidencePath"), item.get("reviewedEvidenceSha256")
        _need(
            isinstance(path, str)
            and path.startswith("/")
            and _digest(digest)
            and evidence_hashes.get(path) == digest,
            "warning_review_evidence_mismatch",
        )
        permissions[key] = item
        identifiers.add(identifier)
    used = []
    for key, count in counts.items():
        _need(key in permissions, "warning_occurrence_unreviewed")
        item = permissions[key]
        _need(
            _time(item["validFrom"]) <= checked < _time(item["validUntil"]),
            "warning_exception_expired_or_not_started",
        )
        _need(count <= item["maxCount"], "warning_exception_count_exceeded")
        used.append(item["exceptionId"])
    return {
        "status": "PASS_WITH_REVIEWED_EXCEPTIONS" if used else "PASS",
        "checkedAt": report["checkedAt"],
        "occurrenceCount": len(occurrences),
        "reviewedExceptions": sorted(used),
    }


def validate_observation_completion(
    receipt: Mapping[str, Any],
    service_exit: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    *,
    policy_sha256: str,
    supervisor_sha256: str,
    source_sha256: Mapping[str, str],
    acceptance_sha256: str,
    raw_sha256: Mapping[str, str],
    raw_sizes: Mapping[str, int],
    raw_progress: Mapping[str, Mapping[str, Any]],
    minimum_seconds: int = 7200,
) -> dict[str, Any]:
    """Require the original run to have succeeded under exactly the audited policy/source.

    Replaying other checks can never upgrade a failed or interrupted original run. The returned
    acceptance class is the original class, including its reviewed-exception qualification.
    """
    _need(type(minimum_seconds) is int and minimum_seconds >= 7200, "duration_policy_invalid")
    _need(
        receipt.get("schemaVersion") == 1
        and receipt.get("scope") == "mexc_stage50_reobservation"
        and receipt.get("phase") == "completed"
        and receipt.get("gatePassed") is True
        and receipt.get("fullAcceptance") in ACCEPTED
        and receipt.get("receivedSignals") == [],
        "original_run_not_accepted",
    )
    _need(
        service_exit.get("systemdExit") == NORMAL_EXIT
        and receipt.get("systemdExit") == NORMAL_EXIT,
        "original_service_exit_abnormal",
    )
    _need(
        _digest(policy_sha256) and _digest(supervisor_sha256) and _digest(acceptance_sha256),
        "original_hash_invalid",
    )
    for value in (receipt, service_exit, acceptance):
        _need(value.get("policySha256") == policy_sha256, "original_policy_mismatch")
        _need(value.get("supervisorSha256") == supervisor_sha256, "original_supervisor_mismatch")
        _need(value.get("fullAcceptance") == receipt["fullAcceptance"], "original_result_mismatch")
    _need(
        set(source_sha256) >= SOURCE_NAMES
        and all(_digest(x) for x in source_sha256.values())
        and receipt.get("sourceSha256") == source_sha256
        and acceptance.get("sourceSha256") == source_sha256,
        "original_source_mismatch",
    )
    _need(
        acceptance.get("stage") == 50
        and receipt.get("acceptanceSha256") == acceptance_sha256
        and service_exit.get("acceptanceSha256") == acceptance_sha256,
        "original_acceptance_hash_mismatch",
    )
    _need(
        (_time(receipt.get("endedAt")) - _time(receipt.get("startedAt"))).total_seconds()
        >= minimum_seconds,
        "original_run_duration_incomplete",
    )
    children = _object(receipt.get("children"), "original_children_missing")
    _need(set(children) == {"observer", "funding"}, "original_children_missing")
    for raw_child in children.values():
        child = _object(raw_child, "original_child_invalid")
        _need(
            type(child.get("returncode")) is int
            and child["returncode"] == 0
            and child.get("signals") == [],
            "original_child_exit_abnormal",
        )
        _need(
            _seconds(child.get("processElapsedSeconds"), minimum_seconds),
            "original_child_duration_incomplete",
        )
    _need(
        set(raw_sha256) == set(RAW_STREAMS.values())
        and set(raw_sizes) == set(raw_sha256)
        and all(_digest(x) for x in raw_sha256.values())
        and acceptance.get("rawSha256") == raw_sha256,
        "original_raw_hash_mismatch",
    )
    streams = _object(receipt.get("streams"), "original_streams_missing")
    _need(set(streams) == set(RAW_STREAMS), "original_streams_missing")
    _need(set(raw_progress) == set(RAW_STREAMS), "original_raw_progress_missing")
    for name, path in RAW_STREAMS.items():
        stream = _object(streams[name], "original_stream_invalid")
        actual = _object(raw_progress[name], "original_raw_progress_missing")
        fields = (
            "firstSampleAt",
            "lastSampleAt",
            "firstElapsedSeconds",
            "lastElapsedSeconds",
            "lastSampleIndex",
            "partialTailBytes",
            "completeLineBytes",
            "observedDurationSeconds",
            "maxSampleGapSeconds",
        )
        _need(
            all(key in actual and stream.get(key) == actual[key] for key in fields),
            "original_raw_progress_mismatch",
        )
        _need(
            _seconds(actual.get("maxSampleGapSeconds"), 0)
            and actual["maxSampleGapSeconds"]
            <= {"performance": 93, "api": 13.5, "funding": 6}[name]
            and _seconds(actual.get("firstElapsedSeconds"), 0)
            and _seconds(
                actual.get("lastElapsedSeconds"),
                minimum_seconds - 30 if name == "api" else minimum_seconds,
            )
            and (name == "api" or actual["firstElapsedSeconds"] == 0)
            and _time(receipt["startedAt"])
            <= _time(actual["firstSampleAt"])
            <= _time(actual["lastSampleAt"])
            <= _time(receipt["endedAt"]),
            "original_raw_clock_or_gap_invalid",
        )
        # The API sampler is asynchronous; its final sample may precede the performance sample
        # by the same 30-second freshness bound enforced while observing.
        required = minimum_seconds - 30 if name == "api" else minimum_seconds
        _need(
            type(stream.get("lastSampleIndex")) is int
            and stream["lastSampleIndex"] >= 1
            and stream.get("partialTailBytes") == 0
            and type(raw_sizes[path]) is int
            and raw_sizes[path] > 0
            and stream.get("completeLineBytes") == raw_sizes[path]
            and _seconds(stream.get("observedDurationSeconds"), required),
            "original_stream_incomplete",
        )
    summary = _object(acceptance.get("summary"), "original_summary_missing")
    _need(
        summary.get("status") == "PASS"
        and summary.get("phase") == "completed"
        and summary.get("acceptanceTimeComplete") is True
        and summary.get("clockErrors") == []
        and _seconds(summary.get("observedElapsedSeconds"), minimum_seconds)
        and _seconds(summary.get("observedWallSeconds"), minimum_seconds),
        "original_summary_incomplete",
    )
    performance = raw_progress["performance"]
    _need(
        summary.get("samples") == performance["lastSampleIndex"] + 1
        and _time(summary.get("startedAt")) == _time(performance["firstSampleAt"])
        and _time(summary.get("lastSampleAt")) == _time(performance["lastSampleAt"])
        and abs(summary["observedWallSeconds"] - performance["observedDurationSeconds"]) <= 0.000001
        and abs(summary["observedElapsedSeconds"] - performance["lastElapsedSeconds"]) <= 0.000501,
        "original_summary_raw_mismatch",
    )
    return {
        "fullAcceptance": receipt["fullAcceptance"],
        "originalAcceptanceSha256": acceptance_sha256,
        "policySha256": policy_sha256,
        "supervisorSha256": supervisor_sha256,
        "sourceSha256": dict(source_sha256),
        "rawSha256": dict(raw_sha256),
    }


def _definition_roster(value: object) -> dict[str, tuple[int, str]]:
    _need(isinstance(value, list) and value, "recovery_definition_roster_missing")
    assert isinstance(value, list)
    result = {}
    for raw in value:
        row = _object(raw, "recovery_definition_identity_invalid")
        identifier, version, digest = (
            row.get(key)
            for key in ("venueInstrumentId", "venueInstrumentVersionId", "definitionHash")
        )
        _need(
            isinstance(identifier, str)
            and identifier.strip()
            and identifier not in result
            and type(version) is int
            and version > 0
            and _digest(digest),
            "recovery_definition_identity_invalid",
        )
        result[identifier] = (version, digest)
    return result


def validate_recovery_definitions(
    report: Mapping[str, Any], database_roster: object
) -> dict[str, Any]:
    """Compare both completed proofs against an independently captured DB roster.

    The dataops checker separately validates completion and the artifact digest. A digest
    recomputed after changing an artifact's definition cannot satisfy this independent check.
    """
    expected = _definition_roster(database_roster)
    recoveries = _object(report.get("recoveryAcceptanceEvidence"), "recovery_evidence_missing")
    for name in ("candleRecovery", "endpointRecovery"):
        completed = _object(recoveries.get(name), "recovery_evidence_missing")
        evidence = _object(completed.get("evidence"), "recovery_evidence_missing")
        _need(
            _definition_roster(evidence.get("roster")) == expected,
            "recovery_definition_database_mismatch",
        )
    return {
        "accepted": True,
        "rosterCount": len(expected),
        "recoveries": ["candleRecovery", "endpointRecovery"],
    }
