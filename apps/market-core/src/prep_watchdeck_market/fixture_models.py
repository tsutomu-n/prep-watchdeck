from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from prep_watchdeck_market.artifacts import ArtifactModel

DatasetName = Literal["instrument", "market-state", "candles-1m", "funding", "recovery", "audit"]


class FixtureTarget(ArtifactModel):
    venue_instrument_id: str = Field(min_length=1, max_length=200)
    venue_instrument_version_id: int = Field(ge=1)
    definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FixtureWindow(ArtifactModel):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def offset_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTC offset required")
        return value


class FixtureCapture(ArtifactModel):
    started_at: datetime
    finished_at: datetime
    database_snapshot_at: datetime
    method: Literal["read_only_repeatable_read"]
    point_in_time_replay: Literal[False]


class FixtureDataset(ArtifactModel):
    name: DatasetName
    availability: Literal["included", "empty", "unavailable", "not_requested"]
    path: str | None = Field(default=None, max_length=200)
    rows: int | None = Field(default=None, ge=0)
    bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    range: FixtureWindow | None = None
    captured_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=100)


class FixtureManifest(ArtifactModel):
    schema_version: Literal[1]
    bundle_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    evidence_kind: Literal["synthetic", "observed"]
    execution: Literal["completed", "partial"]
    target: FixtureTarget
    window: FixtureWindow
    capture: FixtureCapture
    datasets: tuple[FixtureDataset, ...] = Field(min_length=4, max_length=8)
    limitations: tuple[str, ...] = Field(max_length=20)
