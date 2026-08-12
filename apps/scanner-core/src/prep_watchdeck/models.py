from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from prep_watchdeck.domain.enums import ActivityPhase

Timeframe = Literal["5m", "15m", "1h", "4h", "24h"]
Category = Literal["WATCH", "CAUTION", "NO_TRADE", "LOW_PRIORITY"]
Direction = Literal["UP_SURGE", "UP", "FLAT", "DOWN", "DOWN_CRASH"]


class ContractInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    symbol: str
    product_type: str = Field(alias="productType")
    base_coin: str | None = Field(default=None, alias="baseCoin")
    quote_coin: str | None = Field(default=None, alias="quoteCoin")
    symbol_type: str | None = Field(default=None, alias="symbolType")
    symbol_status: str | None = Field(default=None, alias="symbolStatus")
    min_trade_usdt: Decimal | None = Field(default=None, alias="minTradeUSDT")
    max_lever: Decimal | None = Field(default=None, alias="maxLever")
    is_rwa: bool | None = Field(default=None, alias="isRwa")

    @field_validator("is_rwa", mode="before")
    @classmethod
    def validate_is_rwa(cls, value: object) -> bool | None:
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"yes", "y", "true", "1"}:
                return True
            if normalized in {"no", "n", "false", "0"}:
                return False
        return None


class TickerInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    symbol: str
    ts: int | None = None
    last_price: Decimal | None = Field(default=None, alias="lastPr")
    high_24h: Decimal | None = Field(default=None, alias="high24h")
    low_24h: Decimal | None = Field(default=None, alias="low24h")
    change_24h: Decimal | None = Field(default=None, alias="change24h")
    usdt_volume_24h: Decimal | None = Field(default=None, alias="usdtVolume")
    funding_rate: Decimal | None = Field(default=None, alias="fundingRate")
    holding_amount: Decimal | None = Field(default=None, alias="holdingAmount")


class CandleBar(BaseModel):
    symbol: str
    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    base_vol: Decimal
    quote_vol: Decimal

    @field_validator("ts")
    @classmethod
    def validate_ts(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("ts must be positive")
        return value

    @field_validator("open", "high", "low", "close")
    @classmethod
    def validate_positive_price(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("price must be positive")
        return value

    @field_validator("base_vol", "quote_vol")
    @classmethod
    def validate_non_negative_volume(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("volume must be non-negative")
        return value


class ScannerRow(BaseModel):
    symbol: str
    ts: int
    close: Decimal
    category: Category
    direction: Direction
    label: str
    priority_score: float
    change_pct_by_tf: dict[str, float | None]
    turnover_usdt_by_tf: dict[str, float | None]
    volume_ratio_by_tf: dict[str, float | None]
    activity_phase: ActivityPhase = ActivityPhase.UNKNOWN
    roughness_15m: str
    btc_relative_15m: str
    funding_bias: str
    open_interest_state: str
    reason: str
    risk_tags: list[str]
    data_quality: str
