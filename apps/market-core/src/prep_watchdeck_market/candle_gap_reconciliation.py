"""Compare immutable legacy v1 and current v2 candle ledgers without DB or provider access.

Exit zero means the comparison was written. It never certifies historical recovery.
Legacy database identity lacks the v2 relation binding, so matching recovered entries
remain unknown until their cross-schema provenance is independently established.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from prep_watchdeck_market.candle_gap_audit import (
    MAX_BUCKETS,
    MAX_BYTES,
    MAX_GAPS,
    MAX_VERSIONS,
    MINUTE,
    AuditScope,
    Boundary,
    CandleKey,
    ContractRange,
    EvidenceModel,
    HistoryAudit,
    TrackedGap,
    UnavailableRange,
    load_evidence,
)

MAX_LEGACY_INPUTS = 32
SHA256 = r"^[0-9a-f]{64}$"


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _key(value: CandleKey) -> tuple[str, int, str, datetime]:
    return value.instrument_id, value.version_id, value.definition_hash, value.bucket


class LegacyHistoryAudit(EvidenceModel):
    """The legacy schema is validated as v1 and is never rewritten as a v2 ledger."""

    schema_version: Literal["candle-gap-audit-v1"]
    scope: AuditScope
    scope_hash: str = Field(pattern=SHA256)
    observed_at: datetime
    snapshot: str = Field(min_length=1, max_length=1024)
    database_identity: str = Field(pattern=SHA256)
    session_read_only: Literal[True]
    database_mutations: Literal[0]
    provider_requests: Literal[0]
    provider_status: Literal["not_queried"]
    contract_ranges: tuple[ContractRange, ...] = Field(max_length=MAX_VERSIONS)
    expected_minutes: int = Field(ge=0, le=MAX_BUCKETS, strict=True)
    present_minutes: int = Field(ge=0, le=MAX_BUCKETS, strict=True)
    missing: tuple[CandleKey, ...] = Field(max_length=MAX_GAPS)
    boundaries: tuple[Boundary, ...] = Field(max_length=MAX_GAPS)
    catalog_unavailable: tuple[UnavailableRange, ...] = Field(max_length=MAX_GAPS)
    tracked_gaps: tuple[TrackedGap, ...] = Field(max_length=MAX_GAPS)
    previous_evidence_hash: str | None = Field(pattern=SHA256)
    evidence_hash: str = Field(pattern=SHA256)

    @field_validator("observed_at")
    @classmethod
    def observation_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("legacy observation requires an explicit timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.scope_hash != _hash(self.scope.model_dump(mode="json", by_alias=True)):
            raise ValueError("legacy scope hash differs")
        total = len(self.scope.instrument_ids) * int(
            (self.scope.until - self.scope.since).total_seconds() // 60
        )
        if (
            self.observed_at < self.scope.until
            or not self.present_minutes <= self.expected_minutes <= total
            or self.expected_minutes - self.present_minutes != len(self.missing)
            or (
                not self.boundaries
                and not self.catalog_unavailable
                and self.expected_minutes != total
            )
        ):
            raise ValueError("inconsistent legacy observation or coverage counts")
        versions = {item.version_id: item for item in self.contract_ranges}
        if len(versions) != len(self.contract_ranges):
            raise ValueError("duplicate legacy contract versions")
        if any(item.instrument_id not in self.scope.instrument_ids for item in versions.values()):
            raise ValueError("legacy contract outside scope")
        missing = {_key(item) for item in self.missing}
        tracked = {_key(item.key): item.status for item in self.tracked_gaps}
        if len(missing) != len(self.missing) or len(tracked) != len(self.tracked_gaps):
            raise ValueError("duplicate legacy gap keys")
        if any(tracked.get(key) != "missing" for key in missing):
            raise ValueError("legacy missing key lacks unresolved tracking")
        for item in (*self.missing, *(entry.key for entry in self.tracked_gaps)):
            if item.instrument_id not in self.scope.instrument_ids or not (
                self.scope.since <= item.bucket < self.scope.until
            ):
                raise ValueError("legacy gap outside scope")
        for item in (
            *self.missing,
            *(entry.key for entry in self.tracked_gaps if entry.status == "recovered"),
        ):
            contract = versions.get(item.version_id)
            if (
                contract is None
                or contract.instrument_id != item.instrument_id
                or contract.definition_hash != item.definition_hash
                or contract.valid_from > item.bucket
                or (contract.valid_to is not None and contract.valid_to < item.bucket + MINUTE)
            ):
                raise ValueError("legacy gap has no matching contract")
        boundaries = {(item.instrument_id, item.bucket) for item in self.boundaries}
        if len(boundaries) != len(self.boundaries):
            raise ValueError("duplicate legacy boundary keys")
        for item in self.boundaries:
            if (
                item.instrument_id not in self.scope.instrument_ids
                or not self.scope.since <= item.bucket < self.scope.until
                or any(contract.instrument_id != item.instrument_id for contract in item.contracts)
            ):
                raise ValueError("legacy boundary outside scope")
        intervals = {
            (item.instrument_id, item.since, item.until) for item in self.catalog_unavailable
        }
        if len(intervals) != len(self.catalog_unavailable):
            raise ValueError("duplicate legacy catalog intervals")
        for item in self.catalog_unavailable:
            if item.instrument_id not in self.scope.instrument_ids or not (
                self.scope.since <= item.since < item.until <= self.scope.until
            ):
                raise ValueError("legacy catalog interval outside scope")
        if len(tracked) + len(boundaries) + len(intervals) > MAX_GAPS:
            raise ValueError("legacy unresolved evidence exceeds budget")
        return self


@contextmanager
def _parent_directory(path: Path) -> Iterator[int]:
    """Anchor path operations at directory descriptors and reject symlink ancestors."""
    absolute = path.absolute()
    if not absolute.name or ".." in absolute.parts:
        raise ValueError("input and output paths must not contain parent traversal")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for component in absolute.parent.parts[1:]:
            following = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        yield descriptor
    finally:
        os.close(descriptor)


def _read_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    with _parent_directory(path) as directory:
        descriptor = os.open(path.name, flags, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("ledger must be a regular file")
        if metadata.st_size > MAX_BYTES:
            raise ValueError("ledger exceeds size budget")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("ledger exceeds size budget")
    return raw


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def _invalid_constant(value: str) -> Any:
    raise ValueError("invalid JSON numeric constant")


def _payload(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("ledger must be a JSON object")
    content = dict(value)
    evidence_hash = content.pop("evidenceHash", None)
    if evidence_hash != _hash(content):
        raise ValueError("ledger content hash differs")
    return value


def _metadata(path: Path, raw: bytes, report: LegacyHistoryAudit | HistoryAudit) -> dict[str, Any]:
    return {
        "path": str(path.absolute()),
        "rawSha256": hashlib.sha256(raw).hexdigest(),
        "evidenceHash": report.evidence_hash,
        "schemaVersion": report.schema_version,
        "observedAt": report.observed_at.isoformat(),
        "databaseIdentity": report.database_identity,
    }


def reconcile_files(legacy_paths: tuple[Path, ...], baseline_path: Path) -> dict[str, Any]:
    """Retain every old unresolved key; absence from a fresh baseline is not recovery."""
    if not 0 < len(legacy_paths) <= MAX_LEGACY_INPUTS:
        raise ValueError("supply between one and 32 explicit legacy paths")
    if len({str(path.absolute()) for path in legacy_paths}) != len(legacy_paths):
        raise ValueError("duplicate legacy input paths")
    baseline_raw = _read_regular_file(baseline_path)
    baseline_payload = _payload(baseline_raw)
    # Retain the current loader as the v2 validity authority. Equality also detects
    # a changed input between the raw-hash read and the loader's independent read.
    baseline = load_evidence(baseline_path)
    if HistoryAudit.model_validate(baseline_payload) != baseline:
        raise ValueError("baseline changed while reading")
    baseline_tracking = {_key(item.key): item.status for item in baseline.tracked_gaps}
    baseline_versions = {item.version_id: item for item in baseline.contract_ranges}
    inputs: list[dict[str, Any]] = []
    gaps: dict[tuple[str, int, str, datetime], dict[str, Any]] = {}
    boundaries: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    retained_count = 0
    for path in legacy_paths:
        raw = _read_regular_file(path)
        payload = _payload(raw)
        legacy = LegacyHistoryAudit.model_validate(payload)
        if legacy.scope != baseline.scope:
            raise ValueError("legacy and baseline scopes differ")
        if legacy.observed_at > baseline.observed_at:
            raise ValueError("baseline observation precedes legacy evidence")
        metadata = _metadata(path, raw, legacy)
        metadata["provenanceStatus"] = "unknown_legacy_database_binding"
        inputs.append(metadata)
        unresolved = [item for item in legacy.tracked_gaps if item.status != "recovered"]
        retained_count += len(unresolved) + len(legacy.boundaries) + len(legacy.catalog_unavailable)
        if retained_count > MAX_GAPS:
            raise ValueError("comparison evidence exceeds budget")
        for item in unresolved:
            key = _key(item.key)
            entry = gaps.setdefault(
                key,
                {
                    "key": item.key.model_dump(mode="json", by_alias=True),
                    "sourceEvidenceHashes": [],
                    "oldStatuses": [],
                },
            )
            if legacy.evidence_hash not in entry["sourceEvidenceHashes"]:
                entry["sourceEvidenceHashes"].append(legacy.evidence_hash)
            if item.status not in entry["oldStatuses"]:
                entry["oldStatuses"].append(item.status)
        boundaries.extend(
            {
                "boundary": item,
                "sourceEvidenceHash": legacy.evidence_hash,
                "sourceRawSha256": metadata["rawSha256"],
                "status": "boundary_unresolved",
            }
            for item in payload["boundaries"]
        )
        unavailable.extend(
            {
                "interval": item,
                "sourceEvidenceHash": legacy.evidence_hash,
                "sourceRawSha256": metadata["rawSha256"],
                "status": "catalog_unavailable",
            }
            for item in payload["catalogUnavailable"]
        )
    comparisons: list[dict[str, Any]] = []
    for key, entry in sorted(gaps.items()):
        instrument_id, version_id, definition_hash, _ = key
        current = baseline_tracking.get(key)
        contract = baseline_versions.get(version_id)
        if current == "missing":
            status, reason = "still_missing", "exact_key_missing_in_saved_v2"
        elif current == "boundary_unresolved":
            status, reason = "boundary_unresolved", "exact_key_boundary_in_saved_v2"
        elif current == "definition_changed" or (
            contract is not None
            and (
                contract.instrument_id != instrument_id
                or contract.definition_hash != definition_hash
            )
        ):
            status, reason = "identity_changed", "saved_v2_contract_identity_differs"
        elif current == "recovered":
            status, reason = "unknown", "legacy_database_binding_not_established"
        else:
            status, reason = "missing_from_new_baseline", "no_exact_recovery_evidence"
        entry.update(status=status, reason=reason, baselineStatus=current)
        comparisons.append(entry)
    report = {
        "schemaVersion": "candle-gap-reconciliation-v1",
        "comparisonStatus": "comparison_complete",
        "scope": baseline.scope.model_dump(mode="json", by_alias=True),
        "legacyInputs": inputs,
        "baseline": _metadata(baseline_path, baseline_raw, baseline),
        "databaseIdentityRelationship": "unverified_cross_schema",
        "gapComparisons": comparisons,
        "preservedBoundaries": boundaries,
        "preservedCatalogUnavailable": unavailable,
        "legacyUnresolvedKeys": len(comparisons),
        "legacyUnresolvedBoundaries": len(boundaries),
        "legacyUnresolvedCatalogIntervals": len(unavailable),
        "allLegacyUnresolvedRecovered": False,
        "globalHistoryAcceptance": "not_assessed",
        "databaseMutations": 0,
        "providerRequests": 0,
    }
    report["manifestHash"] = _hash(report)
    return report


def write_manifest(path: Path, report: dict[str, Any]) -> None:
    payload = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    if len(payload) > MAX_BYTES:
        raise ValueError("comparison output exceeds size budget")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    with _parent_directory(path) as directory:
        descriptor = os.open(path.name, flags, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, action="append", required=True)
    parser.add_argument(
        "--baseline", type=Path, required=True, help="saved v2 ledger of same scope"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="new manifest; overwrite refused"
    )
    args = parser.parse_args(argv)
    try:
        report = reconcile_files(tuple(args.legacy), args.baseline)
        write_manifest(args.output, report)
        print(
            json.dumps(
                {
                    "output": str(args.output.absolute()),
                    "comparisonStatus": report["comparisonStatus"],
                    "legacyUnresolvedKeys": report["legacyUnresolvedKeys"],
                    "legacyUnresolvedBoundaries": report["legacyUnresolvedBoundaries"],
                    "legacyUnresolvedCatalogIntervals": report["legacyUnresolvedCatalogIntervals"],
                    "allLegacyUnresolvedRecovered": report["allLegacyUnresolvedRecovered"],
                    "globalHistoryAcceptance": report["globalHistoryAcceptance"],
                    "manifestHash": report["manifestHash"],
                }
            )
        )
        return 0
    except (OSError, ValueError, TypeError, RecursionError):
        print("candle reconciliation failed: invalid ledger, scope, or output", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
