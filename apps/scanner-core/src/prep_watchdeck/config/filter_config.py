from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from prep_watchdeck.constants import TEMPLATES
from prep_watchdeck.errors import ConfigError


class UniverseConfig(BaseModel):
    product_type: Literal["USDT-FUTURES"]
    exclude_symbols: list[str]
    benchmark_symbol: str
    exclude_rwa: bool = True
    min_24h_usdt_volume: float
    max_24h_usdt_volume: float
    max_btc_volume_ratio_pct: float

    @model_validator(mode="after")
    def validate_universe(self) -> UniverseConfig:
        if self.min_24h_usdt_volume >= self.max_24h_usdt_volume:
            raise ValueError("min_24h_usdt_volume must be less than max_24h_usdt_volume")
        if not 0 <= self.max_btc_volume_ratio_pct <= 100:
            raise ValueError("max_btc_volume_ratio_pct must be between 0 and 100")
        return self


class CandlesConfig(BaseModel):
    granularity: Literal["5m"]
    min_required_bars: int = Field(ge=1177)
    exclude_open_candle: bool = True
    bootstrap_days: int = Field(ge=1)


class UserRuleConfig(BaseModel):
    volume_74h_mode: Literal["current_24h_vs_74h_ago_24h"]
    price_74h_abs_pct: float = Field(ge=0)
    volume_74h_min_increase_pct: float = Field(ge=0)


class PriceChangeConfig(BaseModel):
    surge_5m_pct: float
    surge_15m_pct: float
    surge_1h_pct: float
    surge_4h_pct: float
    surge_24h_pct: float
    surge_74h_pct: float
    move_5m_pct: float
    move_15m_pct: float
    move_1h_pct: float
    move_4h_pct: float
    move_24h_pct: float
    move_74h_pct: float


class VolumeConfig(BaseModel):
    baseline_window_bars: int
    min_volume_ratio: float
    strong_volume_ratio: float
    volume_leading_ratio: float
    volume_ratio_floor_usdt: float


class TurnoverConfig(BaseModel):
    min_turnover_5m_usdt: float
    min_turnover_15m_usdt: float
    min_turnover_1h_usdt: float

    @model_validator(mode="after")
    def validate_turnover(self) -> TurnoverConfig:
        if self.min_turnover_15m_usdt > self.min_turnover_1h_usdt:
            raise ValueError("min_turnover_15m_usdt must be <= min_turnover_1h_usdt")
        return self


class RoughnessConfig(BaseModel):
    warn_move_concentration_15m: float
    avoid_move_concentration_15m: float

    @model_validator(mode="after")
    def validate_roughness(self) -> RoughnessConfig:
        if self.warn_move_concentration_15m >= self.avoid_move_concentration_15m:
            raise ValueError("warn_move_concentration_15m must be < avoid_move_concentration_15m")
        return self


class DataQualityConfig(BaseModel):
    min_coverage_ratio: float = Field(ge=0, le=1)
    max_missing_bar_count: int = Field(ge=0)
    warn_zero_volume_bar_ratio: float = Field(ge=0, le=1)


class BtcRelativeConfig(BaseModel):
    linked_threshold_15m_pct: float
    individual_threshold_15m_pct: float
    individual_threshold_1h_pct: float


class FundingConfig(BaseModel):
    warn_abs_funding_rate_pct: float
    avoid_abs_funding_rate_pct: float


class OpenInterestConfig(BaseModel):
    change_lookback_minutes: Literal[60]
    increase_threshold_pct: float
    decrease_threshold_pct: float


class CategoryConfig(BaseModel):
    max_risk_tags_for_watch: int
    risk_tags_for_no_trade: int
    min_attention_score_for_display: float

    @property
    def min_priority_score_for_watch(self) -> float:
        return self.min_attention_score_for_display

    @property
    def min_priority_score_for_caution(self) -> float:
        return self.min_attention_score_for_display


class RankingConfig(BaseModel):
    exclude_no_trade_from_main_rankings: bool = True
    top_n: int = Field(ge=1, le=50)


class FilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    version: int
    universe: UniverseConfig
    candles: CandlesConfig
    user_rule: UserRuleConfig
    price_change: PriceChangeConfig
    volume: VolumeConfig
    turnover: TurnoverConfig
    roughness: RoughnessConfig
    data_quality: DataQualityConfig
    btc_relative: BtcRelativeConfig
    funding: FundingConfig
    open_interest: OpenInterestConfig
    category: CategoryConfig
    ranking: RankingConfig

    @model_validator(mode="after")
    def validate_template_name(self) -> FilterConfig:
        if self.name not in TEMPLATES:
            raise ValueError(f"template name must be one of {sorted(TEMPLATES)}")
        return self


def load_filter_config(path: Path) -> FilterConfig:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
        return FilterConfig.model_validate(data)
    except Exception as exc:
        raise ConfigError(f"invalid filter config: {path}: {exc}") from exc
