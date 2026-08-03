from __future__ import annotations

import json

from typer.testing import CliRunner

from prep_watchdeck.adapters.duckdb.service_store import DuckDbServiceStore
from prep_watchdeck.application.service_gap_audit import audit_service_gaps
from prep_watchdeck.domain.service_models import Candle1mRecord, InstrumentRecord
from prep_watchdeck.interfaces.cli import app

runner = CliRunner()


def test_audit_service_gaps_reports_missing_ranges_and_zero_volume() -> None:
    store = MemoryGapStore(
        instruments=[
            instrument("AAAUSDT"),
            instrument("BBBUSDT"),
        ],
        candles=[
            candle("AAAUSDT", 1_800_000_000_000, 10.0),
            candle("AAAUSDT", 1_800_000_060_000, 0.0),
            candle("AAAUSDT", 1_800_000_180_000, 12.0),
            candle("BBBUSDT", 1_800_000_120_000, 20.0),
        ],
    )

    result = audit_service_gaps(
        store,
        symbols=["AAAUSDT", "BBBUSDT"],
        window_start_ms=1_800_000_000_000,
        window_end_ms=1_800_000_180_000,
    )

    assert result.expected_count == 4
    assert result.symbols[0].symbol == "AAAUSDT"
    assert result.symbols[0].status == "PARTIAL"
    assert result.symbols[0].missing_count == 1
    assert result.symbols[0].missing_ranges[0].start_ts_ms == 1_800_000_120_000
    assert result.symbols[0].missing_ranges[0].end_ts_ms == 1_800_000_120_000
    assert result.symbols[0].zero_volume_count == 1
    assert result.symbols[0].classification == "REPAIRABLE_GAP"
    assert result.symbols[1].symbol == "BBBUSDT"
    assert result.symbols[1].missing_count == 3
    assert result.symbols[1].classification == "LISTING_OR_HISTORY_SHORT"


def test_audit_service_gaps_classifies_tail_only_missing_as_tail_lag() -> None:
    start_ms = 1_800_000_000_000
    store = MemoryGapStore(
        instruments=[instrument("AAAUSDT")],
        candles=[
            *[candle("AAAUSDT", start_ms + index * 60_000, 10.0) for index in range(61)],
            candle("AAAUSDT", start_ms + 65 * 60_000, 10.0),
        ],
    )

    result = audit_service_gaps(
        store,
        symbols=["AAAUSDT"],
        window_start_ms=start_ms,
        window_end_ms=start_ms + 70 * 60_000,
    )

    assert result.symbols[0].status == "PARTIAL"
    assert result.symbols[0].missing_count == 9
    assert result.symbols[0].missing_ranges[0].start_ts_ms == start_ms + 61 * 60_000
    assert result.symbols[0].missing_ranges[0].end_ts_ms == start_ms + 64 * 60_000
    assert result.symbols[0].classification == "TAIL_LAG"


def test_audit_service_gaps_uses_normal_instruments_when_symbols_are_not_given() -> None:
    store = MemoryGapStore(
        instruments=[
            instrument("AAAUSDT", status="normal"),
            instrument("PAUSEDUSDT", status="offline"),
        ],
        candles=[
            candle("AAAUSDT", 1_800_000_000_000, 10.0),
            candle("PAUSEDUSDT", 1_800_000_000_000, 10.0),
        ],
    )

    result = audit_service_gaps(
        store,
        symbols=[],
        window_start_ms=1_800_000_000_000,
        window_end_ms=1_800_000_000_000,
    )

    assert [item.symbol for item in result.symbols] == ["AAAUSDT"]


def test_service_gap_audit_cli_writes_json_report(tmp_path, monkeypatch) -> None:
    store = DuckDbServiceStore(tmp_path / "watchdeck.duckdb")
    store.upsert_instruments([instrument("AAAUSDT")])
    store.upsert_candles_1m(
        [
            candle("AAAUSDT", 1_800_000_000_000, 10.0),
            candle("AAAUSDT", 1_800_000_120_000, 10.0),
        ]
    )
    report = tmp_path / "reports" / "gap-audit.json"
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_DB_PATH", str(tmp_path / "watchdeck.duckdb"))

    result = runner.invoke(
        app,
        [
            "service-gap",
            "audit",
            "--symbols",
            "AAAUSDT",
            "--required-1m-bars",
            "3",
            "--end-ts-ms",
            "1800000180000",
            "--output",
            str(report),
        ],
    )

    assert result.exit_code == 0
    assert "service gap audit complete" in result.output
    payload = json.loads(report.read_text())
    assert payload["expected_count"] == 3
    assert payload["symbols"][0]["missing_count"] == 1
    assert payload["symbols"][0]["missing_ranges"][0]["start_ts_ms"] == 1_800_000_060_000


class MemoryGapStore:
    def __init__(
        self,
        *,
        instruments: list[InstrumentRecord],
        candles: list[Candle1mRecord],
    ) -> None:
        self._instruments = instruments
        self._candles = candles

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
            for item in self._candles
            if item.symbol in wanted and start_ts_ms <= item.ts_ms <= end_ts_ms
        ]


def instrument(symbol: str, *, status: str = "normal") -> InstrumentRecord:
    return InstrumentRecord(
        symbol=symbol,
        product_type="USDT-FUTURES",
        symbol_status=status,
        updated_at_ms=1_800_000_000_000,
    )


def candle(symbol: str, ts_ms: int, quote_volume: float) -> Candle1mRecord:
    return Candle1mRecord(
        symbol=symbol,
        ts_ms=ts_ms,
        open=1.0,
        high=1.2,
        low=0.9,
        close=1.1,
        base_volume=quote_volume,
        quote_volume=quote_volume,
        usdt_volume=quote_volume,
        is_closed=True,
        source="test",
        updated_at_ms=ts_ms,
    )
