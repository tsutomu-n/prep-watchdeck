from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from prep_watchdeck.errors import ConfigError


class VpiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    enabled: bool
    benchmark_symbols: tuple[str, ...] = Field(min_length=1)
    target_symbols: tuple[str, ...] = Field(min_length=1)
    target_order_notional_usd: float = Field(gt=0)
    min_required_1m_bars: int = Field(gt=0)
    stale_after_seconds: int = Field(gt=0)
    fast_half_life_bars: float = Field(gt=0)
    slow_half_life_bars: float = Field(gt=0)
    reason_pressure_threshold: float = Field(gt=0)
    early_activity_score: float = Field(ge=0, le=100)
    active_move_score: float = Field(ge=0, le=100)
    thin_turnover_notional_multiple: float = Field(gt=0)
    single_bar_concentration_threshold: float = Field(ge=0, le=1)
    funding_overheated_abs_rate: float = Field(gt=0)

    @field_validator("benchmark_symbols", "target_symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("symbols must be an array")
        symbols: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("symbols must not contain empty values")
            symbols.append(item.strip().upper())
        if len(symbols) != len(set(symbols)):
            raise ValueError("symbols must not contain duplicates")
        return tuple(symbols)

    @model_validator(mode="after")
    def validate_relationships(self) -> VpiConfig:
        overlap = set(self.benchmark_symbols) & set(self.target_symbols)
        if overlap:
            raise ValueError(f"benchmark and target symbols overlap: {sorted(overlap)}")
        if self.fast_half_life_bars >= self.slow_half_life_bars:
            raise ValueError("fast_half_life_bars must be less than slow_half_life_bars")
        if self.early_activity_score >= self.active_move_score:
            raise ValueError("early_activity_score must be less than active_move_score")
        return self


def load_vpi_config(path: Path) -> VpiConfig:
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
        return VpiConfig.model_validate(data)
    except Exception as exc:
        raise ConfigError(f"invalid VPI config: {path}: {exc}") from exc
