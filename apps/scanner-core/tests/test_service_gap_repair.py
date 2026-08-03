from __future__ import annotations

from decimal import Decimal

from prep_watchdeck.application.service_gap_audit import audit_service_gaps
from prep_watchdeck.application.service_gap_repair import repair_service_gaps
from prep_watchdeck.domain.service_models import Candle1mRecord, InstrumentRecord
from prep_watchdeck.models import CandleBar


async def test_repair_service_gaps_dry_run_does_not_fetch_or_write() -> None:
    store = MemoryRepairStore(
        instruments=[instrument("AAAUSDT")],
        candles=[
            candle("AAAUSDT", 1_800_000_000_000),
            candle("AAAUSDT", 1_800_000_120_000),
        ],
    )
    audit = audit_service_gaps(
        store,
        symbols=["AAAUSDT"],
        window_start_ms=1_800_000_000_000,
        window_end_ms=1_800_000_120_000,
    )
    fetcher = RecordingRangeFetcher({"AAAUSDT": []})

    result = await repair_service_gaps(
        store=store,
        fetcher=fetcher,
        audit=audit,
        product_type="USDT-FUTURES",
        write=False,
    )

    assert fetcher.calls == []
    assert result.write_enabled is False
    assert result.symbols[0].classification == "DRY_RUN_REPAIRABLE"
    assert store.written == []


async def test_repair_service_gaps_writes_only_missing_bitget_candles() -> None:
    store = MemoryRepairStore(
        instruments=[instrument("AAAUSDT")],
        candles=[
            candle("AAAUSDT", 1_800_000_000_000),
            candle("AAAUSDT", 1_800_000_120_000),
        ],
    )
    audit = audit_service_gaps(
        store,
        symbols=["AAAUSDT"],
        window_start_ms=1_800_000_000_000,
        window_end_ms=1_800_000_120_000,
    )
    fetcher = RecordingRangeFetcher(
        {
            "AAAUSDT": [
                bar("AAAUSDT", 1_800_000_000_000),
                bar("AAAUSDT", 1_800_000_060_000),
                bar("AAAUSDT", 1_800_000_120_000),
            ]
        }
    )

    result = await repair_service_gaps(
        store=store,
        fetcher=fetcher,
        audit=audit,
        product_type="USDT-FUTURES",
        write=True,
    )

    assert fetcher.calls == [
        ("AAAUSDT", "USDT-FUTURES", "1m", 1_800_000_060_000, 1_800_000_060_000)
    ]
    assert result.write_enabled is True
    assert result.symbols[0].classification == "REPAIRED"
    assert result.symbols[0].fetched_count == 1
    assert result.symbols[0].upserted_count == 1
    assert [(item.symbol, item.ts_ms, item.source) for item in store.written] == [
        ("AAAUSDT", 1_800_000_060_000, "rest-history-gap-repair")
    ]


async def test_repair_service_gaps_classifies_empty_bitget_history_as_history_short() -> None:
    store = MemoryRepairStore(
        instruments=[instrument("NEWUSDT")],
        candles=[],
    )
    audit = audit_service_gaps(
        store,
        symbols=["NEWUSDT"],
        window_start_ms=1_800_000_000_000,
        window_end_ms=1_800_000_120_000,
    )
    fetcher = RecordingRangeFetcher({"NEWUSDT": []})

    result = await repair_service_gaps(
        store=store,
        fetcher=fetcher,
        audit=audit,
        product_type="USDT-FUTURES",
        write=True,
    )

    assert result.symbols[0].classification == "BITGET_HISTORY_UNAVAILABLE"
    assert result.symbols[0].upserted_count == 0
    assert store.written == []


class MemoryRepairStore:
    def __init__(
        self,
        *,
        instruments: list[InstrumentRecord],
        candles: list[Candle1mRecord],
    ) -> None:
        self._instruments = instruments
        self._candles = candles
        self.written: list[Candle1mRecord] = []

    def load_instruments(self) -> list[InstrumentRecord]:
        return self._instruments

    def load_candles_1m_range(
        self,
        symbols: list[str],
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> list[Candle1mRecord]:
        wanted = set(symbols)
        return [
            item
            for item in [*self._candles, *self.written]
            if item.symbol in wanted and start_ts_ms <= item.ts_ms <= end_ts_ms
        ]

    def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
        self.written.extend(candles)


class RecordingRangeFetcher:
    def __init__(self, bars_by_symbol: dict[str, list[CandleBar]]) -> None:
        self._bars_by_symbol = bars_by_symbol
        self.calls: list[tuple[str, str, str, int, int]] = []

    async def __call__(
        self,
        symbol: str,
        product_type: str,
        granularity: str,
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> list[CandleBar]:
        self.calls.append((symbol, product_type, granularity, start_ts_ms, end_ts_ms))
        return [
            item
            for item in self._bars_by_symbol.get(symbol, [])
            if start_ts_ms <= item.ts <= end_ts_ms
        ]


def instrument(symbol: str) -> InstrumentRecord:
    return InstrumentRecord(
        symbol=symbol,
        product_type="USDT-FUTURES",
        symbol_status="normal",
        updated_at_ms=1_800_000_000_000,
    )


def candle(symbol: str, ts_ms: int) -> Candle1mRecord:
    return Candle1mRecord(
        symbol=symbol,
        ts_ms=ts_ms,
        open=1.0,
        high=1.2,
        low=0.9,
        close=1.1,
        base_volume=10.0,
        quote_volume=11.0,
        usdt_volume=11.0,
        is_closed=True,
        source="test",
        updated_at_ms=ts_ms,
    )


def bar(symbol: str, ts_ms: int) -> CandleBar:
    return CandleBar(
        symbol=symbol,
        ts=ts_ms,
        open=Decimal("1.0"),
        high=Decimal("1.2"),
        low=Decimal("0.9"),
        close=Decimal("1.1"),
        base_vol=Decimal("10"),
        quote_vol=Decimal("11"),
    )
