from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol, cast

from prep_watchdeck.application.service_backfill import normalize_symbols
from prep_watchdeck.domain.service_models import Candle1mRecord, InstrumentRecord

ONE_MINUTE_MS = 60_000
TAIL_LAG_GRACE_MS = 60 * ONE_MINUTE_MS
TAIL_LAG_MIN_PREFIX_MS = 60 * ONE_MINUTE_MS
GapClassification = Literal[
    "OK",
    "REPAIRABLE_GAP",
    "LISTING_OR_HISTORY_SHORT",
    "ZERO_VOLUME_ONLY",
    "TAIL_LAG",
]
GapStatus = Literal["OK", "MISSING", "PARTIAL"]


class ServiceGapAuditStore(Protocol):
    def load_instruments(self) -> list[InstrumentRecord]:
        """Load instrument metadata."""

    def load_candles_1m_range(
        self,
        symbols: list[str],
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> list[Candle1mRecord]:
        """Load persisted 1m candles inside an inclusive timestamp window."""


@dataclass(frozen=True)
class GapRange:
    start_ts_ms: int
    end_ts_ms: int
    expected_count: int


@dataclass(frozen=True)
class SymbolGapAudit:
    symbol: str
    status: GapStatus
    classification: GapClassification
    expected_count: int
    present_count: int
    missing_count: int
    zero_volume_count: int
    first_present_ts_ms: int | None
    latest_present_ts_ms: int | None
    missing_ranges: list[GapRange]


@dataclass(frozen=True)
class ServiceGapAudit:
    window_start_ms: int
    window_end_ms: int
    expected_count: int
    symbols: list[SymbolGapAudit]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def service_gap_audit_from_dict(payload: dict[str, Any]) -> ServiceGapAudit:
    symbol_payloads = cast(list[dict[str, Any]], payload["symbols"])
    return ServiceGapAudit(
        window_start_ms=int(payload["window_start_ms"]),
        window_end_ms=int(payload["window_end_ms"]),
        expected_count=int(payload["expected_count"]),
        symbols=[
            SymbolGapAudit(
                symbol=str(item["symbol"]),
                status=item["status"],
                classification=item["classification"],
                expected_count=int(item["expected_count"]),
                present_count=int(item["present_count"]),
                missing_count=int(item["missing_count"]),
                zero_volume_count=int(item["zero_volume_count"]),
                first_present_ts_ms=_optional_int(item.get("first_present_ts_ms")),
                latest_present_ts_ms=_optional_int(item.get("latest_present_ts_ms")),
                missing_ranges=[
                    GapRange(
                        start_ts_ms=int(gap["start_ts_ms"]),
                        end_ts_ms=int(gap["end_ts_ms"]),
                        expected_count=int(gap["expected_count"]),
                    )
                    for gap in item["missing_ranges"]
                ],
            )
            for item in symbol_payloads
        ],
    )


def audit_service_gaps(
    store: ServiceGapAuditStore,
    *,
    symbols: Iterable[str],
    window_start_ms: int,
    window_end_ms: int,
) -> ServiceGapAudit:
    if window_start_ms > window_end_ms:
        raise ValueError("window_start_ms must be <= window_end_ms")
    if window_start_ms % ONE_MINUTE_MS != 0 or window_end_ms % ONE_MINUTE_MS != 0:
        raise ValueError("window bounds must be aligned to 1m")

    target_symbols = normalize_symbols(symbols)
    if not target_symbols:
        target_symbols = _normal_service_symbols(store.load_instruments())
    expected_ts = list(range(window_start_ms, window_end_ms + ONE_MINUTE_MS, ONE_MINUTE_MS))
    expected_count = len(expected_ts)
    candles = store.load_candles_1m_range(target_symbols, window_start_ms, window_end_ms)
    candles_by_symbol: dict[str, list[Candle1mRecord]] = {symbol: [] for symbol in target_symbols}
    for candle in candles:
        if candle.symbol in candles_by_symbol:
            candles_by_symbol[candle.symbol].append(candle)

    return ServiceGapAudit(
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
        expected_count=expected_count,
        symbols=[
            _audit_symbol(symbol, candles_by_symbol.get(symbol, []), expected_ts)
            for symbol in target_symbols
        ],
    )


def _normal_service_symbols(instruments: list[InstrumentRecord]) -> list[str]:
    return normalize_symbols(
        item.symbol
        for item in instruments
        if item.symbol_status is None or item.symbol_status.lower() == "normal"
    )


def _audit_symbol(
    symbol: str,
    candles: list[Candle1mRecord],
    expected_ts: list[int],
) -> SymbolGapAudit:
    by_ts = {item.ts_ms: item for item in candles}
    expected_ts_set = set(expected_ts)
    present_ts = sorted(ts for ts in by_ts if ts in expected_ts_set)
    missing_ts = [ts for ts in expected_ts if ts not in by_ts]
    missing_ranges = _missing_ranges(missing_ts)
    zero_volume_count = sum(1 for item in by_ts.values() if _is_zero_volume(item))
    missing_count = len(missing_ts)
    present_count = len(present_ts)
    first_present = present_ts[0] if present_ts else None
    latest_present = present_ts[-1] if present_ts else None
    return SymbolGapAudit(
        symbol=symbol,
        status=_status(
            expected_count=len(expected_ts),
            present_count=present_count,
            missing_count=missing_count,
        ),
        classification=_classification(
            missing_count=missing_count,
            zero_volume_count=zero_volume_count,
            first_present_ts_ms=first_present,
            window_start_ms=expected_ts[0] if expected_ts else None,
            window_end_ms=expected_ts[-1] if expected_ts else None,
            missing_ranges=missing_ranges,
        ),
        expected_count=len(expected_ts),
        present_count=present_count,
        missing_count=missing_count,
        zero_volume_count=zero_volume_count,
        first_present_ts_ms=first_present,
        latest_present_ts_ms=latest_present,
        missing_ranges=missing_ranges,
    )


def _status(*, expected_count: int, present_count: int, missing_count: int) -> GapStatus:
    if present_count == 0 and expected_count > 0:
        return "MISSING"
    if missing_count > 0:
        return "PARTIAL"
    return "OK"


def _classification(
    *,
    missing_count: int,
    zero_volume_count: int,
    first_present_ts_ms: int | None,
    window_start_ms: int | None,
    window_end_ms: int | None,
    missing_ranges: list[GapRange],
) -> GapClassification:
    if missing_count == 0:
        return "ZERO_VOLUME_ONLY" if zero_volume_count > 0 else "OK"
    if first_present_ts_ms is None:
        return "LISTING_OR_HISTORY_SHORT"
    if window_start_ms is not None and first_present_ts_ms > window_start_ms:
        return "LISTING_OR_HISTORY_SHORT"
    if _is_tail_lag_missing(missing_ranges, window_start_ms, window_end_ms):
        return "TAIL_LAG"
    return "REPAIRABLE_GAP"


def _is_tail_lag_missing(
    missing_ranges: list[GapRange],
    window_start_ms: int | None,
    window_end_ms: int | None,
) -> bool:
    if not missing_ranges or window_start_ms is None or window_end_ms is None:
        return False
    first_missing_ts_ms = missing_ranges[0].start_ts_ms
    return (
        first_missing_ts_ms >= window_end_ms - TAIL_LAG_GRACE_MS
        and first_missing_ts_ms - window_start_ms >= TAIL_LAG_MIN_PREFIX_MS
    )


def _missing_ranges(missing_ts: list[int]) -> list[GapRange]:
    if not missing_ts:
        return []
    ranges: list[GapRange] = []
    start = previous = missing_ts[0]
    for ts_ms in missing_ts[1:]:
        if ts_ms == previous + ONE_MINUTE_MS:
            previous = ts_ms
            continue
        ranges.append(_gap_range(start, previous))
        start = previous = ts_ms
    ranges.append(_gap_range(start, previous))
    return ranges


def _gap_range(start_ts_ms: int, end_ts_ms: int) -> GapRange:
    return GapRange(
        start_ts_ms=start_ts_ms,
        end_ts_ms=end_ts_ms,
        expected_count=(end_ts_ms - start_ts_ms) // ONE_MINUTE_MS + 1,
    )


def _is_zero_volume(candle: Candle1mRecord) -> bool:
    volumes = [candle.usdt_volume, candle.quote_volume, candle.base_volume]
    return any(value == 0 for value in volumes if value is not None)


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None
