"""Offline byte, temporal and semantic validation; integrity is not PIT qualification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from prep_watchdeck_market.bundle_files import (
    BundleError,
    read_regular,
    sha256,
    strict_json,
    sums_bytes,
)
from prep_watchdeck_market.research.files import checked_files
from prep_watchdeck_market.research.models import (
    MAX_FILE_BYTES,
    MAX_OBSERVATIONS,
    ObservationReceipt,
    ResearchPayload,
    ResearchTarget,
    instant,
    payload_reasons,
)

CAUSAL_FAILURES = {
    "research_clock_invalid",
    "research_database_clock_skew",
    "research_poll_gap",
    "research_capture_window_exceeded",
    "research_future_row",
    "research_future_source_time",
    "research_future_context",
    "research_unclosed_window",
    "research_version_window_mismatch",
    "research_finality_before_close",
    "research_finality_time_unknown",
}


@dataclass(frozen=True)
class VerifiedObservation:
    receipt: ObservationReceipt
    payload: ResearchPayload


@dataclass(frozen=True)
class VerifiedSnapshot:
    path: Path
    snapshot_sha256: str
    manifest: dict[str, Any]
    target: ResearchTarget | None
    observations: tuple[VerifiedObservation, ...]
    receipts: tuple[ObservationReceipt, ...]
    reasons: tuple[str, ...]

    @property
    def replay_valid(self) -> bool:
        return bool(self.observations) and not (
            set(self.reasons) & CAUSAL_FAILURES or any(row.kind == "gap" for row in self.receipts)
        )

    @property
    def qualified_for_ab(self) -> bool:
        return self.replay_valid and not self.reasons

    @property
    def observed_evidence(self) -> bool:
        return bool(self.observations) and all(
            row.payload.evidence_kind == "observed" for row in self.observations
        )

    def rows(
        self, dataset: Literal["candles", "states", "funding"], *, cutoff: datetime | None = None
    ) -> list[dict[str, Any]]:
        cutoff = None if cutoff is None else instant(cutoff)
        latest: dict[tuple[int, datetime], dict[str, Any]] = {}
        time_key = "funding_at" if dataset == "funding" else "bucket_at"
        for observation in self.observations:
            if cutoff is not None and observation.receipt.available_at > cutoff:
                continue
            for source in getattr(observation.payload, dataset):
                key = (source["venue_instrument_version_id"], instant(source[time_key]))
                latest[key] = {
                    **source,
                    "research_available_at": observation.receipt.available_at.isoformat(),
                    "research_observation_id": observation.receipt.observation_id,
                    "research_payload_sha256": observation.receipt.payload_sha256,
                }
        return [row for _key, row in sorted(latest.items())]


def verify_snapshot(path: Path, cutoff: datetime | None = None) -> VerifiedSnapshot:
    cutoff = None if cutoff is None else instant(cutoff)
    manifest_bytes = read_regular(path / "manifest.json", MAX_FILE_BYTES)
    manifest = strict_json(manifest_bytes)
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "kind",
            "journal",
            "target",
            "receipt_count",
            "files",
            "producer_revision_complete",
            "exchange_first_available_at",
            "funding_coverage",
            "context_scope",
        }
        or manifest["schema_version"] != 1
        or manifest["kind"] != "reader_observed_snapshot"
        or manifest["producer_revision_complete"] is not False
        or manifest["exchange_first_available_at"] is not None
        or manifest["funding_coverage"] != "observed_rows_only"
        or manifest["context_scope"] != "local_validity_and_reader_observation"
        or type(manifest["receipt_count"]) is not int
        or not 1 <= manifest["receipt_count"] <= MAX_OBSERVATIONS
        or not isinstance(manifest["files"], dict)
    ):
        raise BundleError("research_manifest_invalid")
    files = checked_files(path, manifest["files"])
    all_files = {**files, "manifest.json": manifest_bytes}
    if read_regular(path / "SHA256SUMS", 1024 * 1024) != sums_bytes(all_files):
        raise BundleError("research_hash_mismatch")
    # Refuse symlinks and undeclared files as well as hash mismatches.
    actual: set[str] = set()
    for entry in path.rglob("*"):
        if entry.is_symlink():
            raise BundleError("research_path_invalid")
        if entry.is_file():
            actual.add(entry.relative_to(path).as_posix())
        if len(actual) > 4_012:
            raise BundleError("research_size_exceeded")
    if actual != set(all_files) | {"SHA256SUMS"}:
        raise BundleError("research_unexpected_file")
    try:
        target = (
            None
            if manifest["target"] is None
            else ResearchTarget.model_validate(manifest["target"])
        )
        journal = manifest["journal"]
        max_gap = journal["max_gap_seconds"]
        clock_error = float(journal["clock_error_seconds"])
        if type(max_gap) is not int or not 5 <= max_gap <= 3600 or not 0 <= clock_error <= 30:
            raise BundleError("research_policy_invalid")
        records = [
            (ObservationReceipt.model_validate(strict_json(raw)), raw)
            for name, raw in files.items()
            if name.startswith("receipts/")
        ]
        records.sort(key=lambda item: item[0].sequence)
        if len(records) != manifest["receipt_count"]:
            raise BundleError("research_receipt_chain_invalid")
        observations: list[VerifiedObservation] = []
        receipts: list[ObservationReceipt] = []
        reasons: set[str] = set()
        previous: ObservationReceipt | None = None
        previous_bytes: bytes | None = None
        used: set[str] = set()
        for index, (receipt, raw) in enumerate(records, 1):
            receipt_path = f"receipts/{receipt.observation_id}.json"
            if files.get(receipt_path) != raw or receipt_path in used:
                raise BundleError("research_receipt_identity_mismatch")
            used.add(receipt_path)
            if receipt.sequence != index or receipt.previous_receipt_sha256 != (
                None if previous_bytes is None else sha256(previous_bytes)
            ):
                raise BundleError("research_receipt_chain_invalid")
            if receipt.clock_error_seconds != clock_error:
                raise BundleError("research_policy_invalid")
            issues = set(receipt.reasons)
            if receipt.kind == "observation":
                payload_path = f"observations/{receipt.observation_id}.json"
                payload_bytes = files.get(payload_path)
                if payload_bytes is None or sha256(payload_bytes) != receipt.payload_sha256:
                    raise BundleError("research_hash_mismatch")
                used.add(payload_path)
                payload = ResearchPayload.model_validate(strict_json(payload_bytes))
                if payload.target != target:
                    raise BundleError("research_identity_mismatch")
                issues.update(payload_reasons(payload, receipt.read_completed_at))
                margin = timedelta(seconds=clock_error)
                if (
                    not receipt.read_started_at - margin
                    <= payload.snapshot_at
                    <= receipt.read_completed_at + margin
                ):
                    issues.add("research_database_clock_skew")
                if (
                    abs(
                        (receipt.read_completed_at - receipt.read_started_at).total_seconds()
                        - receipt.elapsed_seconds
                    )
                    > clock_error
                ):
                    issues.add("research_clock_invalid")
                if cutoff is None or receipt.available_at <= cutoff:
                    observations.append(VerifiedObservation(receipt, payload))
            if (
                receipt.read_completed_at < receipt.read_started_at
                or receipt.payload_readback_completed_at < receipt.read_completed_at
            ):
                issues.add("research_clock_invalid")
            if previous is not None:
                delta = (receipt.read_started_at - previous.read_started_at).total_seconds()
                if delta > max_gap:
                    issues.add("research_poll_gap")
                if delta < 0 or receipt.available_at < previous.available_at:
                    issues.add("research_clock_invalid")
            if (receipt.payload_readback_completed_at - records[0][0].read_started_at) > timedelta(
                hours=24
            ):
                issues.add("research_capture_window_exceeded")
            if cutoff is None or receipt.available_at <= cutoff:
                reasons.update(issues)
                receipts.append(receipt)
            previous, previous_bytes = receipt, raw
        if used != set(files):
            raise BundleError("research_unexpected_file")
        if not observations:
            reasons.add("research_no_observations_at_cutoff")
        return VerifiedSnapshot(
            path,
            sha256(manifest_bytes),
            manifest,
            target,
            tuple(observations),
            tuple(receipts),
            tuple(sorted(reasons)),
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        raise BundleError("research_schema_invalid") from None
