"""Prospective fixed cutoffs and descriptive comparison on common input eligibility."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from statistics import fmean
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from .config import no_symlink_path
from .evaluation import BASELINES, DAY, Generation, _outcomes, _ranking
from .models import CandidatePolicy, Contract, OutcomeRow, content_digest, outcome_cutoff
from .stable_files import read_stable_regular_file


class FormalEvaluationScope(Contract):
    """The exact asset universe and reference identity fixed before outcomes exist."""

    schema_version: Literal["attention-formal-scope-v1"] = "attention-formal-scope-v1"
    family_id: str = Field(min_length=1)
    map_version: str = Field(min_length=1)
    reference_keys: dict[str, str | None]

    @model_validator(mode="after")
    def concrete_universe(self) -> Self:
        if not self.reference_keys or any(
            not key or (value is not None and not value)
            for key, value in self.reference_keys.items()
        ):
            raise ValueError("scope document requires exact assets and reference keys")
        return self


def read_scope(path: Path) -> tuple[FormalEvaluationScope, str]:
    raw = read_stable_regular_file(no_symlink_path(path), max_bytes=16 * 1024 * 1024)
    return FormalEvaluationScope.model_validate_json(raw), hashlib.sha256(raw).hexdigest()


def validate_ledger_path(path: Path, *, protocol_path: Path, scope_path: Path) -> Path:
    """Keep the durable look separate from immutable bindings and execution sources."""
    if ".." in path.parts:
        raise ValueError("formal ledger traversal is forbidden")
    path = no_symlink_path(path)
    if (
        path in (no_symlink_path(protocol_path), no_symlink_path(scope_path))
        or path.suffix != ".json"
    ):
        raise ValueError("formal ledger must be separate from protocol and scope")
    for package in ("prep_watchdeck_attention", "prep_watchdeck_market", "prep_watchdeck_ranking"):
        spec = importlib.util.find_spec(package)
        if spec is None or spec.origin is None:
            raise ValueError("formal execution source cannot be resolved")
        if path.is_relative_to(no_symlink_path(Path(spec.origin).parent)):
            raise ValueError("formal ledger cannot be inside execution source")
    return path


def execution_source_hashes() -> dict[str, str]:
    """Include the transitive project source imports used by the actual formal entrypoint."""
    pending = [
        "prep_watchdeck_attention.formal_evaluation",
        "prep_watchdeck_attention.formal_protocol",
        "prep_watchdeck_attention.cli",
    ]
    hashes: dict[str, str] = {}
    while pending:
        module = pending.pop()
        if module in hashes or not module.startswith(
            ("prep_watchdeck_attention", "prep_watchdeck_market", "prep_watchdeck_ranking")
        ):
            continue
        try:
            spec = importlib.util.find_spec(module)
        except (ImportError, ValueError):
            spec = None
        if spec is None or spec.origin is None or not spec.origin.endswith(".py"):
            raise ValueError("formal execution source cannot be resolved")
        path = Path(spec.origin)
        raw = read_stable_regular_file(path, max_bytes=8 * 1024 * 1024)
        hashes[module] = hashlib.sha256(raw).hexdigest()
        parent = module.rpartition(".")[0]
        if parent:
            pending.append(parent)
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        for node in ast.walk(ast.parse(raw)):
            if isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    name = importlib.util.resolve_name(
                        "." * node.level + (node.module or ""), package
                    )
                else:
                    name = node.module or ""
                if node.module:
                    pending.append(name)
                else:
                    pending.extend(name + "." + alias.name for alias in node.names)
    return dict(sorted(hashes.items()))


class FormalEvaluationProtocol(Contract):
    schema_version: Literal["attention-formal-protocol-v1"] = "attention-formal-protocol-v1"
    family_id: str
    policy_hashes: dict[str, str]
    source_hashes: dict[str, str]
    map_version: str
    scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    look_ledger_path: str = Field(min_length=1)
    registered_at_ms: int = Field(gt=0)
    start_ms: int = Field(gt=0)
    end_ms: int = Field(gt=0)
    formal_look_count: Literal[1] = 1
    seed: Literal[0] = 0
    bootstrap_samples: Literal[2000] = 2000
    k_values: tuple[Literal[10], Literal[20]] = (10, 20)
    horizons: tuple[Literal[15], Literal[60]] = (15, 60)
    minimum_day_blocks: Literal[30] = 30
    minimum_coverage: float = Field(default=0.8, ge=0.8, le=0.8)
    maximum_coverage_regression: float = Field(default=0.05, ge=0.05, le=0.05)
    minimum_practical_delta: float = Field(default=0.1, ge=0.1, le=0.1)
    correction_policy: Literal["separate_edition_preserve_original"] = (
        "separate_edition_preserve_original"
    )
    missing_policy: Literal["no_imputation_keep_original_coverage_guard"] = (
        "no_imputation_keep_original_coverage_guard"
    )

    @model_validator(mode="after")
    def prospective_window(self) -> Self:
        if (
            self.start_ms % DAY
            or self.end_ms != self.start_ms + 30 * DAY
            or self.registered_at_ms >= self.start_ms
            or not self.policy_hashes
        ):
            raise ValueError("protocol requires a future start and exactly 30 UTC day blocks")
        return self


def write_protocol(
    path: Path,
    policies: Sequence[CandidatePolicy],
    *,
    map_version: str,
    scope_sha256: str | None = None,
    scope_path: Path | None = None,
    ledger_path: Path | None = None,
    start_ms: int,
    registered_at_ms: int,
) -> FormalEvaluationProtocol:
    path = no_symlink_path(path)
    if scope_path is None:
        raise ValueError("a concrete scope document is required")
    scope, scope_digest = read_scope(scope_path)
    if scope_sha256 is not None and scope_sha256 != scope_digest:
        raise ValueError("scope document hash differs from the supplied binding")
    if scope.map_version != map_version:
        raise ValueError("scope document map differs from the protocol")
    proposed_ledger = validate_ledger_path(
        ledger_path or path.with_name(path.name + ".look.json"),
        protocol_path=path,
        scope_path=scope_path,
    )
    families = {p.family_id for p in policies}
    if len(families) != 1 or {p.horizon_minutes for p in policies} != {15, 60}:
        raise ValueError("one complete prospective family is required")
    if scope.family_id != next(iter(families)):
        raise ValueError("scope document family differs from the protocol")
    signals = {
        horizon: {p.signal for p in policies if p.horizon_minutes == horizon}
        for horizon in (15, 60)
    }
    if signals[15] != signals[60] or not set(BASELINES) < signals[15]:
        raise ValueError("both horizons need the same candidates and all three baselines")
    if any(
        p.frozen_at > registered_at_ms
        or p.minimum_day_blocks != 30
        or p.k_values != (10, 20)
        or p.minimum_coverage != 0.8
        or p.maximum_coverage_regression != 0.05
        or p.minimum_practical_delta != 0.1
        for p in policies
    ):
        raise ValueError("policy conditions differ from the fixed formal protocol")
    hashes = {p.id: content_digest(p.model_dump(mode="json", by_alias=True)) for p in policies}
    if len(hashes) != len(policies):
        raise ValueError("duplicate protocol policy")
    source = execution_source_hashes()
    proposed = FormalEvaluationProtocol(
        family_id=next(iter(families)),
        policy_hashes=hashes,
        source_hashes=source,
        map_version=map_version,
        scope_sha256=scope_digest,
        look_ledger_path=str(proposed_ledger),
        registered_at_ms=registered_at_ms,
        start_ms=start_ms,
        end_ms=start_ms + 30 * DAY,
    )
    if path.exists():
        existing = FormalEvaluationProtocol.model_validate_json(
            read_stable_regular_file(path, max_bytes=1024 * 1024)
        )
        if existing != proposed:
            raise ValueError("formal protocol is immutable; changed binding or cutoff refused")
        return existing
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("protocol path cannot contain symlinks")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(proposed.model_dump_json(by_alias=True, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return proposed


def common_eligible_ids(
    generation: Generation, policies: Sequence[CandidatePolicy]
) -> tuple[str, ...]:
    """Input scores define this pool; no future outcome can add or remove an asset."""
    pools = [set(_ranking(policy, generation)) for policy in policies]
    return tuple(sorted(set.intersection(*pools))) if pools else ()


def common_eligible_diagnostics(
    generations: Sequence[Generation],
    policies: Sequence[CandidatePolicy],
    outcomes: Sequence[OutcomeRow],
) -> dict[str, object]:
    latest = _outcomes(outcomes)
    records: list[dict[str, Any]] = []
    for generation in generations:
        inputs, features, _ = generation
        native_counts = Counter(
            o.venue for row in features for o in row.original_instrument_versions if o.current
        )
        for candidate in (p for p in policies if p.signal not in BASELINES):
            baselines = [
                p
                for p in policies
                if p.signal in BASELINES and p.horizon_minutes == candidate.horizon_minutes
            ]
            if {p.signal for p in baselines} != set(BASELINES):
                raise ValueError("common eligibility needs all three baseline signals")
            pool = set(common_eligible_ids(generation, (candidate, *baselines)))
            eligible_coverage = len(pool) / len(features) if features else 0.0
            for k in (10, 20):
                rankings = {
                    p.id: [a for a in _ranking(p, generation) if a in pool][:k]
                    for p in (candidate, *baselines)
                }
                values: dict[str, float | None] = {}
                for identity, assets in rankings.items():
                    rows = [
                        latest.get((inputs.generation_id, asset, candidate.horizon_minutes))
                        for asset in assets
                    ]
                    known = bool(rows) and all(
                        row is not None
                        and row.status == "ready"
                        and row.max_abs_return is not None
                        and row.cutoff == outcome_cutoff(inputs.decision_at)
                        and row.reference_key
                        == next(f.reference_key for f in features if f.asset_id == row.asset_id)
                        for row in rows
                    )
                    values[identity] = (
                        fmean(
                            row.max_abs_return
                            for row in rows
                            if row is not None and row.max_abs_return is not None
                        )
                        if known
                        else None
                    )
                records.append(
                    {
                        "generationId": inputs.generation_id,
                        "mapVersion": inputs.ranking_map_version,
                        "candidatePolicyId": candidate.id,
                        "horizonMinutes": candidate.horizon_minutes,
                        "k": k,
                        "universeAssets": len(features),
                        "commonEligibleAssets": len(pool),
                        "commonInputCoverage": eligible_coverage,
                        "nativeCountsByVenue": dict(native_counts),
                        "meanFutureMaxAbsReturn": values,
                        "selectedIds": rankings,
                        "reason": "outcome_gap_or_pending"
                        if any(v is None for v in values.values())
                        else None,
                    }
                )
    return {
        "scope": "descriptive_common_input_eligibility_no_future_selection",
        "originalWholeUniverseCoverageGuardUnchanged": True,
        "records": records,
    }
