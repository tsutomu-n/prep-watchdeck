"""One prospective formal look over fixed, streamed, immutable evaluation inputs."""

import fcntl
import hashlib
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import model_validator

from .config import no_symlink_path
from .evaluation import BASELINES, Generation, _outcomes, evaluate_candidate_family
from .formal_protocol import (
    FormalEvaluationProtocol,
    FormalEvaluationScope,
    execution_source_hashes,
    read_scope,
    validate_ledger_path,
)
from .models import (
    MINUTE,
    AttentionEvaluationReport,
    Contract,
    OutcomeRow,
    content_digest,
    outcome_cutoff,
)
from .stable_files import read_stable_regular_file
from .storage import AttentionStore, atomic_json


class _Digest(Protocol):
    def update(self, value: bytes, /) -> None: ...


class _FormalLook(Contract):
    schema_version: Literal["attention-formal-look-v1"] = "attention-formal-look-v1"
    protocol_sha256: str
    input_sha256: str
    formal_look_count: Literal[1] = 1
    status: Literal["STARTED", "COMPLETE"]
    availability_cutoff_ms: int
    report: AttentionEvaluationReport | None = None
    report_sha256: str | None = None

    @model_validator(mode="after")
    def preserved_result(self) -> Self:
        if self.status == "COMPLETE":
            if self.report is None or self.report_sha256 != content_digest(
                self.report.model_dump(mode="json", by_alias=True)
            ):
                raise ValueError("formal original result is missing or changed")
        elif self.report is not None or self.report_sha256 is not None:
            raise ValueError("unfinished formal look cannot contain a result")
        return self


def _evidence_rows(
    store: AttentionStore,
    protocol: FormalEvaluationProtocol,
    scope: FormalEvaluationScope,
    availability_ms: int,
    digest: _Digest,
) -> Iterator[tuple[Generation, tuple[OutcomeRow, ...]]]:
    # Only scalar hashes and metric sufficient data survive advancing this generator.
    for generation in store.iter_evidence_generations(
        start_ms=protocol.start_ms, end_ms=protocol.end_ms
    ):
        inputs, features, response = generation
        if not protocol.start_ms <= inputs.decision_at < protocol.end_ms:
            continue
        if inputs.ranking_cutoff > inputs.decision_at:
            raise ValueError("formal ranking cutoff cannot follow the decision")
        if inputs.ranking_map_version != protocol.map_version:
            raise ValueError("generation map differs from formal protocol")
        keys = {row.asset_id: row.reference_key for row in features}
        if len(keys) != len(features) or keys != scope.reference_keys:
            raise ValueError("generation assets or references differ from formal scope")
        if response.generation_id != inputs.generation_id or any(
            row.decision_at != inputs.decision_at for row in features
        ):
            raise ValueError("formal generation identity or decision time differs")
        rows = tuple(
            row
            for _, row in sorted(
                _outcomes(store.outcomes_for_generation(inputs.generation_id)).items()
            )
        )
        if any(
            row.generation_id != inputs.generation_id
            or row.asset_id not in scope.reference_keys
            or row.reference_key != scope.reference_keys[row.asset_id]
            or row.horizon_minutes not in protocol.horizons
            or row.cutoff != outcome_cutoff(inputs.decision_at)
            for row in rows
        ):
            raise ValueError("formal outcome identity or cutoff binding differs")
        if any(row.settled_at > availability_ms for row in rows):
            raise ValueError("different formal input: outcome after fixed availability cutoff")
        payload = {
            "inputs": inputs.model_dump(mode="json", by_alias=True),
            "features": [row.model_dump(mode="json", by_alias=True) for row in features],
            "response": response.model_dump(mode="json", by_alias=True),
            "outcomes": [row.model_dump(mode="json", by_alias=True) for row in rows],
        }
        digest.update(content_digest(payload).encode())
        yield generation, rows


def _input_digest(
    store: AttentionStore,
    protocol: FormalEvaluationProtocol,
    scope: FormalEvaluationScope,
    availability_ms: int,
) -> str:
    digest = hashlib.sha256()
    for _ in _evidence_rows(store, protocol, scope, availability_ms, digest):
        pass
    return digest.hexdigest()


def evaluate_formal_family(
    store: AttentionStore,
    *,
    protocol_path: Path,
    scope_path: Path,
    ledger_path: Path,
    now_ms: int | None = None,
    seed: int = 0,
    bootstrap_samples: int = 2000,
) -> AttentionEvaluationReport:
    """Reserve one look before computation; resume only the identical frozen input snapshot."""
    protocol_path, scope_path = no_symlink_path(protocol_path), no_symlink_path(scope_path)
    ledger_path = validate_ledger_path(
        ledger_path, protocol_path=protocol_path, scope_path=scope_path
    )
    raw = read_stable_regular_file(protocol_path, max_bytes=1024 * 1024)
    protocol = FormalEvaluationProtocol.model_validate_json(raw)
    protocol_digest = hashlib.sha256(raw).hexdigest()
    scope, scope_digest = read_scope(scope_path)
    if (
        scope_digest != protocol.scope_sha256
        or scope.map_version != protocol.map_version
        or scope.family_id != protocol.family_id
    ):
        raise ValueError("concrete scope differs from the registered formal protocol")
    if seed != protocol.seed or bootstrap_samples != protocol.bootstrap_samples:
        raise ValueError("seed or bootstrap samples differ from formal protocol")
    if str(ledger_path) != protocol.look_ledger_path:
        raise ValueError("formal ledger target differs from immutable protocol")
    if execution_source_hashes() != protocol.source_hashes:
        raise ValueError("execution sources differ from registered formal protocol")
    policies = store.policies(protocol.family_id)
    hashes = {
        policy.id: content_digest(policy.model_dump(mode="json", by_alias=True))
        for policy in policies
    }
    if hashes != protocol.policy_hashes:
        raise ValueError("family or frozen policies differ from formal protocol")
    now_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    if now_ms < protocol.end_ms + 60 * MINUTE:
        raise ValueError("formal window and final sixty-minute follow-up are not complete")
    if not ledger_path.parent.is_dir():
        raise ValueError("formal ledger parent must already exist")
    lock_path = no_symlink_path(ledger_path.with_name(ledger_path.name + ".lock"))
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "rb+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        existing = (
            _FormalLook.model_validate_json(
                read_stable_regular_file(ledger_path, max_bytes=16 * 1024 * 1024)
            )
            if ledger_path.exists()
            else None
        )
        availability_ms = existing.availability_cutoff_ms if existing is not None else now_ms
        fingerprint = _input_digest(store, protocol, scope, availability_ms)
        if existing is not None:
            if existing.protocol_sha256 != protocol_digest or existing.input_sha256 != fingerprint:
                raise ValueError("a second different formal input/look is forbidden")
            if existing.status == "COMPLETE":
                assert existing.report is not None
                return existing.report
            look = existing
        else:
            look = _FormalLook(
                protocol_sha256=protocol_digest,
                input_sha256=fingerprint,
                status="STARTED",
                availability_cutoff_ms=availability_ms,
            )
            atomic_json(ledger_path, look.model_dump(mode="json", by_alias=True))
        calculated_digest = hashlib.sha256()
        report = evaluate_candidate_family(
            store,
            policy_ids=[p.id for p in policies if p.signal not in BASELINES],
            baseline_policy_ids=[p.id for p in policies if p.signal in BASELINES],
            k_values=protocol.k_values,
            minimum_practical_delta=protocol.minimum_practical_delta,
            bootstrap_samples=protocol.bootstrap_samples,
            seed=protocol.seed,
            evidence_rows=_evidence_rows(
                store, protocol, scope, availability_ms, calculated_digest
            ),
            save=False,
            created_at_ms=availability_ms,
        )
        if (
            calculated_digest.hexdigest() != fingerprint
            or _input_digest(store, protocol, scope, availability_ms) != fingerprint
            or read_stable_regular_file(protocol_path, max_bytes=1024 * 1024) != raw
            or read_scope(scope_path)[1] != scope_digest
            or execution_source_hashes() != protocol.source_hashes
        ):
            raise ValueError("inputs changed during formal evaluation; original look reserved")
        completed = look.model_copy(
            update={
                "status": "COMPLETE",
                "report": report,
                "report_sha256": content_digest(report.model_dump(mode="json", by_alias=True)),
            }
        )
        atomic_json(ledger_path, completed.model_dump(mode="json", by_alias=True))
        return report
