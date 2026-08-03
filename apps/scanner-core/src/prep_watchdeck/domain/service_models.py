from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from prep_watchdeck.domain.dto import to_camel

StreamKind = Literal["ticker", "candle1m", "mixed"]
BackfillProgressStatus = Literal["running", "completed", "failed", "cancelled"]


class ServiceModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        populate_by_name=True,
    )


class InstrumentRecord(ServiceModel):
    symbol: str
    product_type: str
    symbol_type: str | None = None
    symbol_status: str | None = None
    base_coin: str | None = None
    quote_coin: str | None = None
    support_margin_coins: list[str] = Field(default_factory=list)
    max_leverage: float | None = None
    min_trade_num: float | None = None
    is_rwa: bool | None = None
    updated_at_ms: int


class TickerLatestRecord(ServiceModel):
    symbol: str
    ts_ms: int
    last_price: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    change_24h: float | None = None
    funding_rate: float | None = None
    next_funding_time_ms: int | None = None
    mark_price: float | None = None
    index_price: float | None = None
    holding_amount: float | None = None
    base_volume_24h: float | None = None
    quote_volume_24h: float | None = None
    open_utc: float | None = None
    updated_at_ms: int


class Candle1mRecord(ServiceModel):
    symbol: str
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    base_volume: float | None = None
    quote_volume: float | None = None
    usdt_volume: float | None = None
    is_closed: bool
    source: str
    updated_at_ms: int

    @field_validator("open", "high", "low", "close")
    @classmethod
    def validate_price(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("price must be positive")
        return value

    @field_validator("base_volume", "quote_volume", "usdt_volume")
    @classmethod
    def validate_volume(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("volume must be non-negative")
        return value


class StreamHealthRecord(ServiceModel):
    shard_id: str
    stream_kind: StreamKind
    channel_count: int = Field(ge=0)
    connected: bool
    last_message_at_ms: int | None = None
    last_pong_at_ms: int | None = None
    reconnect_count: int = Field(ge=0)
    gap_count: int = Field(ge=0)
    last_error: str | None = None


class ServiceDiagnostics(ServiceModel):
    schema_ready: bool
    instrument_count: int
    ticker_count: int
    candle_1m_count: int
    stream_health_count: int
    latest_candle_1m_ts_ms: int | None = None


class BackfillProgress(ServiceModel):
    status: BackfillProgressStatus
    requested_symbols: int = Field(ge=0)
    completed_symbols: int = Field(ge=0)
    saved_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    limit: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    started_at_ms: int
    updated_at_ms: int
    finished_at_ms: int | None = None
    latest_error: str | None = None


class DeepBackfillProgress(ServiceModel):
    status: BackfillProgressStatus
    target_symbols: int = Field(ge=0)
    completed_symbols: int = Field(ge=0)
    pending_symbols: int = Field(ge=0)
    saved_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    target_limit: int = Field(ge=1)
    batch_size: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    rate_limit_per_second: float = Field(gt=0)
    cooldown_seconds: float = Field(ge=0)
    retry_delay_seconds: float = Field(ge=0)
    cycle_count: int = Field(ge=0)
    started_at_ms: int
    updated_at_ms: int
    finished_at_ms: int | None = None
    current_symbols: list[str] = Field(default_factory=list)
    latest_error: str | None = None


class ServiceStateSnapshot(ServiceModel):
    schema_version: Literal[1] = 1
    generated_at_ms: int
    data_as_of_ms: int | None = None
    product_type: str
    stream_symbols: int = Field(ge=0)
    stream_channels: int = Field(ge=0)
    stream_shards: int = Field(ge=0)
    diagnostics: ServiceDiagnostics
    backfill: BackfillProgress | None = None
    reconcile: BackfillProgress | None = None
    deep_backfill: DeepBackfillProgress | None = None


class BackfillSymbolResult(ServiceModel):
    symbol: str
    fetched_count: int
    saved_count: int
    latest_ts_ms: int | None = None
    error: str | None = None


class BackfillResult(ServiceModel):
    product_type: str
    granularity: Literal["1m"]
    requested_symbols: list[str]
    saved_count: int
    symbols: list[BackfillSymbolResult]


class BootstrapResult(ServiceModel):
    product_type: str
    template: str
    fetched_contract_count: int
    fetched_ticker_count: int
    selected_symbols: list[str]
    valid_symbols: list[str] = Field(default_factory=list)
