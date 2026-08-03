from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VpiState(StrEnum):
    CALM = "CALM"
    EARLY_ACTIVITY = "EARLY_ACTIVITY"
    ACTIVE_MOVE = "ACTIVE_MOVE"
    THIN_VOLATILITY = "THIN_VOLATILITY"
    SINGLE_BAR_SUSPECT = "SINGLE_BAR_SUSPECT"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
    DATA_STALE = "DATA_STALE"
    UNKNOWN = "UNKNOWN"


class FundingState(StrEnum):
    UNKNOWN = "UNKNOWN"
    NORMAL = "NORMAL"
    OVERHEATED = "OVERHEATED"


class OpenInterestState(StrEnum):
    UNKNOWN = "UNKNOWN"
    AVAILABLE = "AVAILABLE"


class VpiDataQuality(StrEnum):
    OK = "OK"
    INSUFFICIENT = "INSUFFICIENT"
    STALE = "STALE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class VpiSourceBar:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    usdt_volume: float | None
    quote_volume: float | None
    is_closed: bool
    updated_at_ms: int


@dataclass(frozen=True)
class VpiInputBar:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    quote_turnover: float


@dataclass(frozen=True)
class VpiDiagnostics:
    abs_return_pressure: float
    turnover_pressure: float
    range_pressure: float
    used_bar_count: int
    turnover_1h: float
    single_bar_concentration: float


@dataclass(frozen=True)
class VpiLitePlusResult:
    symbol: str
    state: VpiState
    score: float
    reason_codes: tuple[str, ...]
    risk_tag_codes: tuple[str, ...]
    funding_state: FundingState
    open_interest_state: OpenInterestState
    data_quality: VpiDataQuality
    data_as_of: int | None
    diagnostics: VpiDiagnostics
