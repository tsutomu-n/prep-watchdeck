from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from prep_watchdeck_market.artifacts import ArtifactModel

RUN_ID_PATTERN = r"^[0-9a-f]{32}$"
SHA_PATTERN = r"^[0-9a-f]{64}$"
NONNEGATIVE_DECIMAL_PATTERN = r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$"
SIGNED_DECIMAL_PATTERN = r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$"
TARGET_PATTERN = r"^(bitget|hyperliquid|aster):[^\x00-\x20\x7f]+$"
TEXT_PATTERN = r"^[^\x00-\x1f\x7f]+$"
SOURCE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
ComparisonKind = Literal["snapshot_revision", "acquisition_routes", "repeatability"]
EvidenceKind = Literal["observed", "synthetic"]
AuditExecution = Literal["completed", "invalid_input", "failed"]
AuditOutcome = Literal["match", "differences", "incomplete", "unverified"]
FindingKind = Literal[
    "value_difference",
    "return_difference",
    "missing_bar",
    "invalid_row",
    "missing_value",
    "return_unavailable",
]
FindingReason = Literal[
    "value_tolerance_exceeded",
    "return_tolerance_exceeded",
    "missing_bucket",
    "duplicate_bucket",
    "record_version_mismatch",
    "record_is_not_final",
    "observed_before_close",
    "unavailable_at_as_of",
    "invalid_timestamp",
    "invalid_numeric",
    "invalid_ohlc",
    "invalid_row",
    "missing_requested_value",
    "missing_return_endpoint",
]


def _utc(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp requires an offset")
    return None if value is None else value.astimezone(UTC)


def _time(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    result = _utc(stamp)
    assert result is not None
    return result


class AuditTarget(ArtifactModel):
    venue_instrument_id: str = Field(pattern=TARGET_PATTERN, max_length=160)
    venue_instrument_version_id: int = Field(ge=1)


class AuditSourceDeclaration(ArtifactModel):
    source_id: str = Field(pattern=SOURCE_ID_PATTERN)
    label: str = Field(min_length=1, max_length=128, pattern=TEXT_PATTERN)
    snapshot_created_at: datetime | None

    @field_validator("snapshot_created_at")
    @classmethod
    def validate_time(cls, value: datetime | None) -> datetime | None:
        return _utc(value)


class AuditTolerances(ArtifactModel):
    price_abs_tol: str = Field(pattern=NONNEGATIVE_DECIMAL_PATTERN, max_length=128)
    price_rel_tol: str = Field(pattern=NONNEGATIVE_DECIMAL_PATTERN, max_length=128)
    volume_abs_tol: str = Field(pattern=NONNEGATIVE_DECIMAL_PATTERN, max_length=128)
    volume_rel_tol: str = Field(pattern=NONNEGATIVE_DECIMAL_PATTERN, max_length=128)
    return_tol_bps: str = Field(pattern=NONNEGATIVE_DECIMAL_PATTERN, max_length=128)


class AuditRequest(ArtifactModel):
    schema_version: Literal[1]
    target: AuditTarget
    left_path: str = Field(min_length=1, max_length=4096)
    right_path: str = Field(min_length=1, max_length=4096)
    left_source: AuditSourceDeclaration
    right_source: AuditSourceDeclaration
    comparison_kind: ComparisonKind
    evidence_kind: EvidenceKind
    window_start: datetime
    window_end: datetime
    data_as_of: datetime
    return_minutes: Literal[5]
    compare_volume_base: bool
    tolerances: AuditTolerances

    @field_validator("window_start", "window_end", "data_as_of")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        result = _utc(value)
        assert result is not None
        return result


class AuditWindow(ArtifactModel):
    start: datetime
    end: datetime
    data_as_of: datetime
    source_interval_seconds: Literal[60]
    return_minutes: Literal[5]


class AuditInputEvidence(AuditSourceDeclaration):
    file_sha256: str | None = Field(pattern=SHA_PATTERN)
    source_time_missing_count: int | None = Field(ge=0)
    derived_final_count: int | None = Field(ge=0)


class AuditInputs(ArtifactModel):
    left: AuditInputEvidence
    right: AuditInputEvidence


class AuditSeries(ArtifactModel):
    venue: Literal["bitget", "hyperliquid", "aster"]
    source_symbol: str = Field(min_length=1, max_length=128, pattern=TEXT_PATTERN)
    venue_instrument_version_id: int = Field(ge=1)
    definition_sha256: str = Field(pattern=SHA_PATTERN)
    base_asset: str = Field(min_length=1, max_length=128, pattern=TEXT_PATTERN)
    quote_asset: str = Field(min_length=1, max_length=128, pattern=TEXT_PATTERN)
    settle_asset: str = Field(min_length=1, max_length=128, pattern=TEXT_PATTERN)
    price_kind: Literal["trade"]
    interval_seconds: Literal[60]


class AuditCounts(ArtifactModel):
    expected_bars: int = Field(ge=0)
    common_valid_bars: int = Field(ge=0)
    compared_price_values: int = Field(ge=0)
    compared_volume_values: int = Field(ge=0)
    expected_return_pairs: int = Field(ge=0)
    return_pairs: int = Field(ge=0)
    price_difference_values: int = Field(ge=0)
    price_difference_bars: int = Field(ge=0)
    volume_difference_values: int = Field(ge=0)
    return_difference_pairs: int = Field(ge=0)
    left_missing_bars: int = Field(ge=0)
    right_missing_bars: int = Field(ge=0)
    left_invalid_bars: int = Field(ge=0)
    right_invalid_bars: int = Field(ge=0)
    missing_value_count: int = Field(ge=0)
    return_missing_pairs: int = Field(ge=0)
    total_findings: int = Field(ge=0)
    complete_for_requested_checks: bool
    max_flagged_price_diff_bps: str | None = Field(pattern=NONNEGATIVE_DECIMAL_PATTERN)
    max_flagged_return_diff_bps: str | None = Field(pattern=NONNEGATIVE_DECIMAL_PATTERN)


class AuditFinding(ArtifactModel):
    id: str = Field(pattern=r"^f[0-9]{6}$")
    kind: FindingKind
    side: Literal["left", "right", "pair"] | None
    field: (
        Literal["open_price", "high_price", "low_price", "close_price", "volume_base", "log_return"]
        | None
    )
    bucket_at: datetime | None
    start_at: datetime | None
    end_at: datetime | None
    left: str | None = Field(pattern=SIGNED_DECIMAL_PATTERN)
    right: str | None = Field(pattern=SIGNED_DECIMAL_PATTERN)
    absolute_difference: str | None = Field(pattern=NONNEGATIVE_DECIMAL_PATTERN)
    difference_bps: str | None = Field(pattern=NONNEGATIVE_DECIMAL_PATTERN)
    reason_code: FindingReason
    row_number: int | None = Field(ge=1)

    @field_validator("bucket_at", "start_at", "end_at")
    @classmethod
    def validate_time(cls, value: datetime | None) -> datetime | None:
        return _utc(value)


class AuditReportHeader(ArtifactModel):
    schema_version: Literal[1]
    audit_version: Literal["native-candle-snapshots-v1"]
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    implementation_sha256: str = Field(pattern=SHA_PATTERN)
    target: AuditTarget
    series: AuditSeries | None
    started_at: datetime
    checked_at: datetime
    window: AuditWindow
    execution: AuditExecution
    outcome: AuditOutcome | None
    error_code: str | None = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    comparison_kind: ComparisonKind
    evidence_kind: EvidenceKind
    scope: Literal["saved_candle_snapshots"]
    independence: Literal["not_established"]
    inputs: AuditInputs
    summary: AuditCounts | None
    tolerances: AuditTolerances
    compare_volume_base: bool


class AuditReport(AuditReportHeader):
    findings: tuple[AuditFinding, ...] = Field(max_length=65000)


class AuditIndexEntry(ArtifactModel):
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    target: AuditTarget
    started_at: datetime
    checked_at: datetime
    comparison_kind: ComparisonKind
    evidence_kind: EvidenceKind
    window: AuditWindow
    execution: AuditExecution
    outcome: AuditOutcome | None
    error_code: str | None
    inputs: AuditInputs
    summary: AuditCounts | None
    last_completed_run_id: str | None = Field(pattern=RUN_ID_PATTERN)


class AuditIndex(ArtifactModel):
    schema_version: Literal[1]
    generated_at: datetime
    entries: tuple[AuditIndexEntry, ...] = Field(max_length=256)


class AuditMarkerBucket(ArtifactModel):
    bucket_at: datetime
    finding_count: int = Field(ge=1)
    kinds: tuple[FindingKind, ...]
    first_finding_offset: int = Field(ge=0)


class AuditDetailPage(ArtifactModel):
    schema_version: Literal[1]
    report: AuditReportHeader
    total_findings: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    findings: tuple[AuditFinding, ...]
    has_more: bool
    marker_buckets: tuple[AuditMarkerBucket, ...]


def implementation_fingerprint() -> str:
    root = Path(__file__).resolve().parents[4]
    stem = "apps/market-core/src/prep_watchdeck_market/"
    paths = sorted(
        stem + name
        for name in (
            "candle_audit.py",
            "candle_audit_publication.py",
            "candle_audit_artifacts.py",
            "candles.py",
            "models.py",
        )
    )
    evidence = [
        {"path": path, "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest()}
        for path in paths
    ]
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _declaration_evidence(
    source: AuditSourceDeclaration,
    diagnostic: dict[str, Any] | None,
) -> AuditInputEvidence:
    return AuditInputEvidence(
        source_id=source.source_id,
        label=source.label,
        snapshot_created_at=source.snapshot_created_at,
        file_sha256=None if diagnostic is None else diagnostic["input_sha256"],
        source_time_missing_count=(
            None if diagnostic is None else diagnostic["source_time_missing_count"]
        ),
        derived_final_count=None if diagnostic is None else diagnostic["derived_final_count"],
    )


def _reason(value: str) -> FindingReason:
    if value in {
        "duplicate_bucket",
        "record_version_mismatch",
        "record_is_not_final",
        "observed_before_close",
        "unavailable_at_as_of",
    }:
        return value
    if "timestamp" in value or "timezone" in value or "minute" in value:
        return "invalid_timestamp"
    if "OHLC" in value or "price is below" in value or "price is above" in value:
        return "invalid_ohlc"
    if any(text in value for text in ("decimal", "finite", "trade_count", "trade count")):
        return "invalid_numeric"
    return "invalid_row"


def _finding(**values: Any) -> dict[str, Any]:
    return {
        "kind": values.get("kind"),
        "side": values.get("side"),
        "field": values.get("field"),
        "bucket_at": values.get("bucket_at"),
        "start_at": values.get("start_at"),
        "end_at": values.get("end_at"),
        "left": values.get("left"),
        "right": values.get("right"),
        "absolute_difference": values.get("absolute_difference"),
        "difference_bps": values.get("difference_bps"),
        "reason_code": values.get("reason_code"),
        "row_number": values.get("row_number"),
    }


def _findings(diagnostic: dict[str, Any]) -> tuple[AuditFinding, ...]:
    rows: list[dict[str, Any]] = []
    for item in diagnostic["differences"]:
        is_return = item["field"] == "log_return"
        end_at = _time(item["end_at"]) if is_return else None
        rows.append(
            _finding(
                kind="return_difference" if is_return else "value_difference",
                field=item["field"],
                bucket_at=end_at - timedelta(minutes=1) if end_at else _time(item["bucket_at"]),
                start_at=_time(item["start_at"]) if is_return else None,
                end_at=end_at,
                left=item["left"],
                right=item["right"],
                absolute_difference=None if is_return else item["abs_diff"],
                difference_bps=item["abs_diff_bps"] if is_return else item["rel_diff_bps"],
                reason_code=(
                    "return_tolerance_exceeded" if is_return else "value_tolerance_exceeded"
                ),
            )
        )
    for side in ("left", "right"):
        source = diagnostic["sources"][side]
        for bucket in source["missing_buckets"]:
            rows.append(
                _finding(
                    kind="missing_bar",
                    side=side,
                    bucket_at=_time(bucket),
                    reason_code="missing_bucket",
                )
            )
        for finding in source["findings"]:
            rows.append(
                _finding(
                    kind="invalid_row",
                    side=side,
                    bucket_at=(
                        None if finding["bucket_at"] is None else _time(finding["bucket_at"])
                    ),
                    reason_code=_reason(str(finding["reason"])),
                    row_number=finding["row"],
                )
            )
    for item in diagnostic["missing_values"]:
        rows.append(
            _finding(
                kind="missing_value",
                side="pair",
                field=item["field"],
                bucket_at=_time(item["bucket_at"]),
                reason_code="missing_requested_value",
            )
        )
    for endpoint in diagnostic["return_missing_endpoints"]:
        end_at = _time(endpoint)
        rows.append(
            _finding(
                kind="return_unavailable",
                side="pair",
                field="log_return",
                bucket_at=end_at - timedelta(minutes=1),
                start_at=end_at - timedelta(minutes=5),
                end_at=end_at,
                reason_code="missing_return_endpoint",
            )
        )
    rows.sort(
        key=lambda row: (
            row["bucket_at"] is None,
            row["bucket_at"] or datetime.max.replace(tzinfo=UTC),
            row["kind"] or "",
            row["field"] or "",
            row["side"] or "",
            row["row_number"] or 0,
        )
    )
    if len(rows) > 65000:
        raise ValueError("audit findings exceed the report limit")
    return tuple(AuditFinding(id=f"f{number:06d}", **row) for number, row in enumerate(rows, 1))


def _series(raw: dict[str, Any]) -> AuditSeries:
    return AuditSeries(
        venue=raw["venue"],
        source_symbol=raw["source_symbol"],
        venue_instrument_version_id=raw["venue_instrument_version_id"],
        definition_sha256=raw["definition_sha256"],
        base_asset=raw["base_asset"],
        quote_asset=raw["quote_asset"],
        settle_asset=raw["settle_asset"],
        price_kind=raw["price_kind"],
        interval_seconds=raw["interval_seconds"],
    )


def _counts(diagnostic: dict[str, Any], findings: tuple[AuditFinding, ...]) -> AuditCounts:
    differences = diagnostic["differences"]
    prices = [
        item
        for item in differences
        if item["field"] in {"open_price", "high_price", "low_price", "close_price"}
    ]
    returns = [item for item in differences if item["field"] == "log_return"]
    volume = [item for item in differences if item["field"] == "volume_base"]
    left, right = diagnostic["sources"]["left"], diagnostic["sources"]["right"]
    price_max = max((Decimal(item["rel_diff_bps"]) for item in prices), default=None)
    return_max = max((Decimal(item["abs_diff_bps"]) for item in returns), default=None)
    common = diagnostic["common_valid_bars"]
    missing_values = len(diagnostic["missing_values"])
    compared_volume = (
        common - missing_values if "volume_base" in diagnostic["compared_fields"] else 0
    )
    return AuditCounts(
        expected_bars=diagnostic["expected_bars"],
        common_valid_bars=common,
        compared_price_values=common * 4,
        compared_volume_values=compared_volume,
        expected_return_pairs=diagnostic["expected_return_pairs"],
        return_pairs=diagnostic["return_pairs"],
        price_difference_values=len(prices),
        price_difference_bars=len({item["bucket_at"] for item in prices}),
        volume_difference_values=len(volume),
        return_difference_pairs=len(returns),
        left_missing_bars=len(left["missing_buckets"]),
        right_missing_bars=len(right["missing_buckets"]),
        left_invalid_bars=len(left["unusable_buckets"]) - len(left["missing_buckets"]),
        right_invalid_bars=len(right["unusable_buckets"]) - len(right["missing_buckets"]),
        missing_value_count=missing_values,
        return_missing_pairs=len(diagnostic["return_missing_endpoints"]),
        total_findings=len(findings),
        complete_for_requested_checks=diagnostic["coverage_complete"],
        max_flagged_price_diff_bps=None if price_max is None else str(price_max),
        max_flagged_return_diff_bps=None if return_max is None else str(return_max),
    )


def _common_header(
    request: AuditRequest,
    *,
    run_id: str,
    started_at: datetime,
    checked_at: datetime,
    execution: AuditExecution,
    outcome: AuditOutcome | None,
    error_code: str | None,
    series: AuditSeries | None,
    inputs: AuditInputs,
    summary: AuditCounts | None,
) -> dict[str, Any]:
    return dict(
        schema_version=1,
        audit_version="native-candle-snapshots-v1",
        run_id=run_id,
        implementation_sha256=implementation_fingerprint(),
        target=request.target,
        series=series,
        started_at=started_at,
        checked_at=checked_at,
        window=AuditWindow(
            start=request.window_start,
            end=request.window_end,
            data_as_of=request.data_as_of,
            source_interval_seconds=60,
            return_minutes=5,
        ),
        execution=execution,
        outcome=outcome,
        error_code=error_code,
        comparison_kind=request.comparison_kind,
        evidence_kind=request.evidence_kind,
        scope="saved_candle_snapshots",
        independence="not_established",
        inputs=inputs,
        summary=summary,
        tolerances=request.tolerances,
        compare_volume_base=request.compare_volume_base,
    )


def build_audit_report(
    request: AuditRequest,
    diagnostic: dict[str, Any],
    *,
    run_id: str,
    started_at: datetime,
    checked_at: datetime,
) -> AuditReport:
    series = _series(diagnostic["series"])
    if (
        f"{series.venue}:{series.source_symbol}" != request.target.venue_instrument_id
        or series.venue_instrument_version_id != request.target.venue_instrument_version_id
    ):
        raise ValueError("audit target mismatch")
    findings = _findings(diagnostic)
    counts = _counts(diagnostic, findings)
    inputs = AuditInputs(
        left=_declaration_evidence(request.left_source, diagnostic["sources"]["left"]),
        right=_declaration_evidence(request.right_source, diagnostic["sources"]["right"]),
    )
    return AuditReport(
        **_common_header(
            request,
            run_id=run_id,
            started_at=started_at,
            checked_at=checked_at,
            execution="completed",
            outcome=diagnostic["outcome"],
            error_code=None,
            series=series,
            inputs=inputs,
            summary=counts,
        ),
        findings=findings,
    )


def build_failed_report(
    request: AuditRequest,
    *,
    run_id: str,
    started_at: datetime,
    checked_at: datetime,
    execution: Literal["invalid_input", "failed"],
    error_code: str,
    left_hash: str | None = None,
    right_hash: str | None = None,
) -> AuditReport:
    inputs = AuditInputs(
        left=AuditInputEvidence(
            **request.left_source.model_dump(),
            file_sha256=left_hash,
            source_time_missing_count=None,
            derived_final_count=None,
        ),
        right=AuditInputEvidence(
            **request.right_source.model_dump(),
            file_sha256=right_hash,
            source_time_missing_count=None,
            derived_final_count=None,
        ),
    )
    return AuditReport(
        **_common_header(
            request,
            run_id=run_id,
            started_at=started_at,
            checked_at=checked_at,
            execution=execution,
            outcome=None,
            error_code=error_code,
            series=None,
            inputs=inputs,
            summary=None,
        ),
        findings=(),
    )


def index_entry_from_report(
    report: AuditReport,
    *,
    last_completed_run_id: str | None,
) -> AuditIndexEntry:
    return AuditIndexEntry(
        run_id=report.run_id,
        target=report.target,
        started_at=report.started_at,
        checked_at=report.checked_at,
        comparison_kind=report.comparison_kind,
        evidence_kind=report.evidence_kind,
        window=report.window,
        execution=report.execution,
        outcome=report.outcome,
        error_code=report.error_code,
        inputs=report.inputs,
        summary=report.summary,
        last_completed_run_id=(
            report.run_id if report.execution == "completed" else last_completed_run_id
        ),
    )


def detail_page(report: AuditReport, *, offset: int, limit: int) -> AuditDetailPage:
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("invalid audit detail page")
    grouped: dict[datetime, list[tuple[int, FindingKind]]] = defaultdict(list)
    for position, finding in enumerate(report.findings):
        bucket = finding.bucket_at
        if (
            bucket is not None
            and report.window.start <= bucket < report.window.end
            and bucket.second == 0
            and bucket.microsecond == 0
        ):
            grouped[bucket].append((position, finding.kind))
    markers = tuple(
        AuditMarkerBucket(
            bucket_at=bucket,
            finding_count=len(items),
            kinds=tuple(sorted({kind for _, kind in items})),
            first_finding_offset=min(position for position, _ in items),
        )
        for bucket, items in sorted(grouped.items())
    )
    header = AuditReportHeader.model_validate(report.model_dump(exclude={"findings"}))
    return AuditDetailPage(
        schema_version=1,
        report=header,
        total_findings=len(report.findings),
        offset=offset,
        limit=limit,
        findings=report.findings[offset : offset + limit],
        has_more=offset + limit < len(report.findings),
        marker_buckets=markers,
    )
