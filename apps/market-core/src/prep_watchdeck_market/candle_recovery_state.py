from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from prep_watchdeck_market.artifacts import ArtifactModel

RecoveryExecution = Literal["running", "succeeded", "partial", "failed"]
RecoveryTrigger = Literal["startup", "periodic", "manual"]


class RecoveryWindow(ArtifactModel):
    start: datetime
    end: datetime
    grace_seconds: Literal[180] = 180


class RecoverySummary(ArtifactModel):
    target_count: int = Field(ge=0)
    scanned_target_count: int = Field(ge=0)
    http_requests: int = Field(ge=0)
    missing_before: int | None = Field(ge=0)
    inserted: int = Field(ge=0)
    newly_present: int | None = Field(ge=0)
    remaining: int | None = Field(ge=0)
    failed_targets: int = Field(ge=0)
    deferred_targets: int = Field(ge=0)


class RecoveryTargetIdentity(ArtifactModel):
    venue_instrument_id: str = Field(min_length=1, max_length=200)
    venue_instrument_version_id: int = Field(ge=1)
    definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecoveryTargetDetail(ArtifactModel):
    target: RecoveryTargetIdentity
    missing_before: int | None = Field(ge=0)
    inserted: int = Field(ge=0)
    remaining: int | None = Field(ge=0)
    error_code: str | None = Field(default=None, max_length=100)


class CandleRecoveryState(ArtifactModel):
    schema_version: Literal[1] = 1
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    generated_at: datetime
    started_at: datetime
    finished_at: datetime | None
    execution: RecoveryExecution
    trigger: RecoveryTrigger
    window: RecoveryWindow
    summary: RecoverySummary
    details: tuple[RecoveryTargetDetail, ...] = Field(max_length=128)
    details_truncated: bool
    error_code: str | None = Field(default=None, max_length=100)
