from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired, Required, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from prep_watchdeck.domain.enums import Category, DataQuality, DataSource, SnapshotStatus


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="allow",
    )


class SnapshotSourceDTO(CamelModel):
    exchange: str
    product_type: str
    template_name: str
    data_source: DataSource
    is_fallback: bool = False
    fixture_set: str | None = None


class RankingItemDTO(CamelModel):
    symbol: str
    value: float


class ChartBarDTO(TypedDict):
    ts: int
    open: float
    high: float
    low: float
    close: float
    quoteVolume: float


MiniPoints = Annotated[list[float], Field(max_length=16)]
MiniBars = Annotated[list[ChartBarDTO], Field(max_length=16)]


class SparklineDTO(TypedDict, total=False):
    __pydantic_config__ = ConfigDict(  # type: ignore[bad-class-definition]
        json_schema_extra={
            "tsType": (
                "{ tf?: string; points?: unknown[]; bars?: unknown[]; "
                "timeframes?: Record<string, unknown[]>; [key: string]: unknown }"
            )
        }
    )

    tf: Required[str]
    points: Required[MiniPoints]
    bars: NotRequired[MiniBars]
    timeframes: NotRequired[dict[str, MiniBars]]


class ScannerRowDTO(CamelModel):
    symbol: str
    ts: int
    last_price: float | None = None
    analysis_price: float | None = None
    max_leverage: float | None = None
    min_trade_usdt: float | None = None
    category: Category
    label: str
    direction: str = "FLAT"
    attention_score: float
    change_pct_by_tf: dict[str, float | None]
    turnover_usdt_by_tf: dict[str, float | None]
    volume_ratio_by_tf: dict[str, float | None] = Field(default_factory=dict)
    range_24h_high: float | None = None
    range_24h_low: float | None = None
    range_24h_position_pct: float | None = None
    range_24h_pct: float | None = None
    price_change_74h_pct: float | None = None
    turnover_current_24h_usdt: float | None = None
    turnover_24h_ending_74h_ago_usdt: float | None = None
    volume_change_74h_24h_pct: float | None = None
    user_rule_74h_matched: bool | None = None
    roughness_15m: str | None = None
    btc_relative_15m: str | None = None
    funding_bias: str | None = None
    open_interest_state: str | None = None
    data_quality: DataQuality
    coverage_ratio: float | None = None
    missing_bar_count: int | None = None
    zero_volume_bar_ratio: float | None = None
    reason_codes: list[str]
    risk_tag_codes: list[str]
    display: dict[str, Any] = Field(default_factory=dict)
    sparkline: SparklineDTO | None = None


class SnapshotDTO(CamelModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )

    schema_version: Literal[1]
    engine_version: str
    feature_version: str
    ruleset_version: str
    config_hash: str
    run_id: str
    generated_at: int
    data_as_of: int
    snapshot_status: SnapshotStatus
    source: SnapshotSourceDTO
    summary: dict[str, Any]
    rankings: dict[str, Any]
    rows: list[ScannerRowDTO]
