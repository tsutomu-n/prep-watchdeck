from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from prep_watchdeck_market.artifacts import write_artifact_atomic
from prep_watchdeck_market.candle_recovery_state import (
    CandleRecoveryState,
    RecoveryEvidence,
    RecoveryTargetIdentity,
)
from prep_watchdeck_market.candle_recovery_store import RecoveryTarget


def roster_evidence(
    targets: Sequence[RecoveryTarget],
    *,
    scope: Literal["full-candle-window", "metric-endpoints"],
    unchanged: bool,
) -> RecoveryEvidence:
    """Preserve every exact identity separately from bounded presentation details."""
    keys = sorted(
        (target.instrument_id, target.version_id, target.definition_hash) for target in targets
    )
    return RecoveryEvidence(
        scope=scope,
        roster=tuple(
            RecoveryTargetIdentity(
                venue_instrument_id=identifier,
                venue_instrument_version_id=version,
                definition_hash=definition_hash,
            )
            for identifier, version, definition_hash in keys
        ),
        roster_digest=hashlib.sha256(
            json.dumps(keys, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest(),
        roster_unchanged=unchanged,
    )


def completed_state_path(state_path: Path) -> Path:
    return state_path.with_name(
        state_path.name.removesuffix("-state.json") + "-latest-completed.json"
    )


def previous_completed_run_id(state_path: Path) -> str | None:
    """A running state names its direct predecessor, including a failed predecessor."""
    try:
        completed = CandleRecoveryState.model_validate_json(
            completed_state_path(state_path).read_bytes()
        )
    except (OSError, ValueError):
        return None
    if completed.execution == "running" or completed.finished_at is None:
        return None
    return completed.run_id


def write_recovery_state(state_path: Path, state: CandleRecoveryState) -> None:
    # Publish every terminal result first: partial/failed must invalidate an older success.
    # The runtime lock serializes runs; each JSON replacement remains atomic.
    if state.execution != "running":
        write_artifact_atomic(completed_state_path(state_path), state)
    write_artifact_atomic(state_path, state)
