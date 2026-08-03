from __future__ import annotations

import time
from collections.abc import Awaitable
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from prep_watchdeck.application.service_gap_audit import (
    ONE_MINUTE_MS,
    GapRange,
    ServiceGapAudit,
)
from prep_watchdeck.domain.service_models import Candle1mRecord
from prep_watchdeck.models import CandleBar

MAX_HISTORY_CANDLES_PER_REQUEST = 200
RepairClassification = Literal[
    "NO_GAP",
    "NO_MISSING_ZERO_VOLUME",
    "DRY_RUN_REPAIRABLE",
    "REPAIRED",
    "PARTIAL_REPAIRED",
    "BITGET_HISTORY_UNAVAILABLE",
    "BITGET_API_ERROR",
]


class ServiceGapRepairStore(Protocol):
    def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
        """Persist repaired 1m candle records."""


class CandleRangeFetcher(Protocol):
    def __call__(
        self,
        symbol: str,
        product_type: str,
        granularity: str,
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> Awaitable[list[CandleBar]]:
        """Fetch candles inside an inclusive timestamp range."""


@dataclass(frozen=True)
class SymbolGapRepair:
    symbol: str
    classification: RepairClassification
    requested_missing_count: int
    fetched_count: int
    upserted_count: int
    api_error: str | None = None


@dataclass(frozen=True)
class ServiceGapRepair:
    write_enabled: bool
    product_type: str
    symbols: list[SymbolGapRepair]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


async def repair_service_gaps(
    *,
    store: ServiceGapRepairStore,
    fetcher: CandleRangeFetcher,
    audit: ServiceGapAudit,
    product_type: str,
    write: bool,
) -> ServiceGapRepair:
    symbol_results: list[SymbolGapRepair] = []
    for item in audit.symbols:
        if item.missing_count == 0:
            symbol_results.append(
                SymbolGapRepair(
                    symbol=item.symbol,
                    classification=(
                        "NO_MISSING_ZERO_VOLUME" if item.zero_volume_count > 0 else "NO_GAP"
                    ),
                    requested_missing_count=0,
                    fetched_count=0,
                    upserted_count=0,
                )
            )
            continue
        if not write:
            symbol_results.append(
                SymbolGapRepair(
                    symbol=item.symbol,
                    classification="DRY_RUN_REPAIRABLE",
                    requested_missing_count=item.missing_count,
                    fetched_count=0,
                    upserted_count=0,
                )
            )
            continue
        symbol_results.append(
            await _repair_symbol(
                store=store,
                fetcher=fetcher,
                symbol=item.symbol,
                product_type=product_type,
                missing_ranges=item.missing_ranges,
                requested_missing_count=item.missing_count,
            )
        )
    return ServiceGapRepair(write_enabled=write, product_type=product_type, symbols=symbol_results)


async def _repair_symbol(
    *,
    store: ServiceGapRepairStore,
    fetcher: CandleRangeFetcher,
    symbol: str,
    product_type: str,
    missing_ranges: list[GapRange],
    requested_missing_count: int,
) -> SymbolGapRepair:
    missing_ts = {
        ts_ms
        for gap in missing_ranges
        for ts_ms in range(gap.start_ts_ms, gap.end_ts_ms + ONE_MINUTE_MS, ONE_MINUTE_MS)
    }
    fetched_count = 0
    records_by_ts: dict[int, Candle1mRecord] = {}
    try:
        for start_ts_ms, end_ts_ms in _chunk_missing_ranges(missing_ranges):
            bars = await fetcher(symbol, product_type, "1m", start_ts_ms, end_ts_ms)
            fetched_count += len(bars)
            for bar in bars:
                if bar.ts in missing_ts:
                    records_by_ts[bar.ts] = _record_from_bar(bar)
    except Exception as exc:
        return SymbolGapRepair(
            symbol=symbol,
            classification="BITGET_API_ERROR",
            requested_missing_count=requested_missing_count,
            fetched_count=fetched_count,
            upserted_count=0,
            api_error=f"{type(exc).__name__}: {exc}",
        )

    records = [records_by_ts[ts_ms] for ts_ms in sorted(records_by_ts)]
    if records:
        store.upsert_candles_1m(records)
    if not records:
        classification: RepairClassification = "BITGET_HISTORY_UNAVAILABLE"
    elif len(records) == requested_missing_count:
        classification = "REPAIRED"
    else:
        classification = "PARTIAL_REPAIRED"
    return SymbolGapRepair(
        symbol=symbol,
        classification=classification,
        requested_missing_count=requested_missing_count,
        fetched_count=fetched_count,
        upserted_count=len(records),
    )


def _chunk_missing_ranges(ranges: list[GapRange]) -> list[tuple[int, int]]:
    chunks: list[tuple[int, int]] = []
    for gap in ranges:
        cursor = gap.start_ts_ms
        while cursor <= gap.end_ts_ms:
            chunk_end = min(
                gap.end_ts_ms,
                cursor + (MAX_HISTORY_CANDLES_PER_REQUEST - 1) * ONE_MINUTE_MS,
            )
            chunks.append((cursor, chunk_end))
            cursor = chunk_end + ONE_MINUTE_MS
    return chunks


def _record_from_bar(bar: CandleBar) -> Candle1mRecord:
    quote_volume = float(bar.quote_vol)
    now_ms = int(time.time() * 1000)
    return Candle1mRecord(
        symbol=bar.symbol.strip().upper(),
        ts_ms=bar.ts,
        open=float(bar.open),
        high=float(bar.high),
        low=float(bar.low),
        close=float(bar.close),
        base_volume=float(bar.base_vol),
        quote_volume=quote_volume,
        usdt_volume=quote_volume,
        is_closed=True,
        source="rest-history-gap-repair",
        updated_at_ms=now_ms,
    )
