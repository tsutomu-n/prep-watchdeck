from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator

from prep_watchdeck_market.artifacts import ArtifactModel
from prep_watchdeck_market.fixture_models import FixtureTarget, FixtureWindow


class ReferenceNative(ArtifactModel):
    venue: Literal["bitget", "hyperliquid", "aster", "mexc"]
    source_symbol: str = Field(min_length=1, max_length=120)
    venue_instrument_version_id: int = Field(ge=1)
    definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_asset: str = Field(min_length=1, max_length=120)
    quote_asset: str = Field(min_length=1, max_length=120)
    settle_asset: str = Field(min_length=1, max_length=120)
    price_kind: Literal["trade"]
    interval_seconds: Literal[60]

    model_config = ArtifactModel.model_config | {"alias_generator": None}


class ReferenceProvider(ArtifactModel):
    exchange: str = Field(min_length=1, max_length=100)
    raw_symbol: str = Field(alias="rawSymbol", min_length=1, max_length=120)
    coin: str = Field(min_length=1)
    category: Literal["PERPETUAL"]
    interval: Literal["MINUTE"]
    type: Literal["TRADE_SIDE_AGNOSTIC_AGG"]


class ReferenceMapping(ArtifactModel):
    schema_version: Literal[1]
    mapping_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    evidence_kind: Literal["synthetic", "observed"]
    checked_at: datetime
    checked_by: str = Field(min_length=1, max_length=100)
    native: ReferenceNative
    provider: ReferenceProvider
    metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("checked_at")
    @classmethod
    def require_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("offset required")
        return value.astimezone(UTC)


class ReferenceRequest(ArtifactModel):
    exchange: str
    raw_symbol: str = Field(alias="rawSymbol")
    interval: Literal["MINUTE"]
    type: Literal["TRADE_SIDE_AGNOSTIC_AGG"]
    gapfill: Literal[False]


class ReferenceCounts(ArtifactModel):
    expected_bars: int = Field(ge=0)
    received_points: int = Field(ge=0)
    valid_bars: int = Field(ge=0)
    missing_bars: int = Field(ge=0)
    invalid_points: int = Field(ge=0)


class ReferenceFile(ArtifactModel):
    path: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)


class ReferenceAcquisition(ArtifactModel):
    schema_version: Literal[1]
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    evidence_kind: Literal["synthetic", "observed"]
    provider: Literal["openmarket"]
    execution: Literal["completed", "partial", "failed"]
    started_at: datetime
    finished_at: datetime
    target: FixtureTarget
    window: FixtureWindow
    mapping_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request: ReferenceRequest
    counts: ReferenceCounts
    files: tuple[ReferenceFile, ...] = Field(max_length=10)
    error_code: str | None = Field(default=None, max_length=100)
    limitations: tuple[str, ...] = Field(max_length=20)

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("offset required")
        return value.astimezone(UTC)
