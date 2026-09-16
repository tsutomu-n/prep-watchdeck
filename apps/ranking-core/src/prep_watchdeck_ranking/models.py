"""Versioned mapping and public API contracts. Timestamps are UTC milliseconds."""

import hashlib
import json
import math
import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

MINUTE = 60_000
METRIC_VERSION = "trade-close-quote-turnover-analysis-v2"
MAP_SCHEMA_VERSION = "ranking-map-v2"
Provider = Literal["bybit", "binance"]
MappingStatus = Literal["verified", "unsupported", "review", "out_of_scope"]
RowState = Literal[
    "ready",
    "starting",
    "history_missing",
    "source_delayed",
    "source_unavailable",
    "mapping_review",
    "unsupported",
    "out_of_scope",
    "filtered",
    "direction_excluded",
    "invalid_data",
    "reference_invalid",
]


class Contract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        json_schema_serialization_defaults_required=True,
    )


class Reference(Contract):
    provider: Provider
    symbol: str = Field(min_length=1, max_length=80)
    base_asset: str = Field(min_length=1)
    multiplier: int = Field(gt=0)
    quote_asset: Literal["USDT"] = "USDT"
    settle_asset: Literal["USDT"] = "USDT"
    contract_type: Literal["linear_perpetual"] = "linear_perpetual"
    revision: str = Field(min_length=1)

    @field_validator("symbol")
    @classmethod
    def symbol_text(cls, value: str) -> str:
        if not re.fullmatch(r"[\w]+", value, re.UNICODE):
            raise ValueError("invalid public contract symbol")
        return value

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.symbol}:{self.revision}"


class Widget(Contract):
    status: Literal["supported", "unsupported", "review"]
    symbol: str | None
    reason: str | None
    evidence: tuple[str, ...]
    reference_key: str | None = None


class OriginalInstrument(Contract):
    venue: Literal["bitget", "hyperliquid", "aster"]
    instrument_id: str
    version_id: int
    symbol: str
    base_asset: str
    multiplier: int | None = Field(
        gt=0,
        description="Original underlying quantity per unit; null means conversion is unverified. "
        "This does not determine fixed-reference ranking eligibility.",
    )


class MappingRow(Contract):
    id: str
    asset: str
    status: MappingStatus = Field(
        description="Asset identity and fixed-reference qualification only; original quantity "
        "conversion and Widget qualification are independent."
    )
    reason: str | None
    originals: tuple[OriginalInstrument, ...]
    reference: Reference | None
    widget: Widget
    evidence: tuple[str, ...]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if not self.originals:
            raise ValueError("mapping must retain original instruments")
        if self.status == "verified":
            if self.reference is None or not self.evidence:
                raise ValueError("verified mapping requires reference and evidence")
        elif self.reference is not None:
            raise ValueError("unverified mapping cannot acquire prices")
        elif self.status in ("unsupported", "out_of_scope") and (
            not self.reason or not self.evidence
        ):
            raise ValueError("excluded mapping requires a reason and evidence")
        if self.widget.status == "supported":
            if not self.reference or not self.widget.symbol or not self.widget.evidence:
                raise ValueError("supported Widget requires independent evidence")
            prefix = f"{self.reference.provider.upper()}:"
            if (
                not self.widget.symbol.startswith(prefix)
                or not self.widget.symbol.endswith(".P")
                or self.widget.reference_key != self.reference.key
            ):
                raise ValueError("Widget contract differs from reference")
        elif self.widget.symbol is not None:
            raise ValueError("unverified Widget must not have a usable symbol")
        elif self.status == "verified" and self.widget.status == "unsupported":
            if not self.widget.reason or not self.widget.evidence:
                raise ValueError("unsupported Widget requires a reason and evidence")
        return self


class RankingMap(Contract):
    schema_version: Literal["ranking-map-v2"] = MAP_SCHEMA_VERSION
    version: str
    verified_at: int
    roster_generated_at: int
    roster_fingerprint: str
    roster_source: str
    source_instrument_count: int
    rows: tuple[MappingRow, ...]

    @model_validator(mode="after")
    def completeness(self) -> Self:
        ids = [item.instrument_id for row in self.rows for item in row.originals]
        if len(ids) != self.source_instrument_count or len(ids) != len(set(ids)):
            raise ValueError("mapping has duplicate or missing original instruments")
        if len({row.id for row in self.rows}) != len(self.rows):
            raise ValueError("duplicate row identity")
        refs = [row.reference.key for row in self.rows if row.reference]
        if len(refs) != len(set(refs)):
            raise ValueError("same reference must be represented by one row")
        return self


class MinuteBar(Contract):
    reference_key: str
    end: int
    open: float
    high: float
    low: float
    close: float
    quote_turnover: float

    @model_validator(mode="after")
    def valid_bar(self) -> Self:
        if self.end <= 0 or self.end % MINUTE:
            raise ValueError("bar end must be a UTC minute boundary")
        values = (self.open, self.high, self.low, self.close, self.quote_turnover)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("bar values must be finite")
        if min(self.open, self.high, self.low, self.close) <= 0 or self.quote_turnover < 0:
            raise ValueError("invalid price or turnover")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("OHLC is inconsistent")
        return self


class RankChange(Contract):
    status: Literal["compared", "new", "unavailable", "not_ranked"]
    previous_rank: int | None = None
    delta: int | None = None
    reason: str | None = None


class Indicator(Contract):
    value: float | None = None
    status: Literal[
        "ready",
        "history_missing",
        "no_baseline",
        "unsupported_period",
        "starting",
        "no_range",
        "invalid_data",
        "reference_unavailable",
    ]


class RankedRow(Contract):
    id: str
    asset: str
    mapping_status: MappingStatus = Field(
        description="Asset identity and fixed-reference qualification; not a claim that all "
        "original quantity conversions or Widgets are verified."
    )
    venues: tuple[str, ...]
    originals: tuple[OriginalInstrument, ...]
    reference: Reference | None
    widget: Widget
    state: RowState
    reason: str | None
    return_pct: float | None
    quote_turnover: float | None
    rank: int | None
    rank_change: RankChange = RankChange(status="unavailable", reason="no_previous_generation")
    turnover_ratio: Indicator = Indicator(status="history_missing")
    day_range_position: Indicator = Indicator(status="history_missing")


class Coverage(Contract):
    source_instruments: int
    rows: int
    crypto_rows: int
    supported: int
    widget_supported: int
    valid: int
    ranked: int
    reasons: dict[str, int]


class RankingResponse(Contract):
    schema_version: Literal["ranking-v2"] = "ranking-v2"
    generation_id: str
    map_version: str
    metric_version: Literal["trade-close-quote-turnover-analysis-v2"] = METRIC_VERSION
    cutoff: int
    generated_at: int
    roster_generated_at: int
    roster_stale: bool
    stale: bool
    status: Literal["ready", "partial", "starting", "stale"]
    period: Literal["15m", "1h", "daily"]
    daily_reference_jst: str
    anchor: int
    order: Literal["gainers", "losers", "turnover"]
    min_turnover: float
    previous_generation_id: str | None = None
    previous_cutoff: int | None = None
    coverage: Coverage
    rows: tuple[RankedRow, ...]


def content_digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()
