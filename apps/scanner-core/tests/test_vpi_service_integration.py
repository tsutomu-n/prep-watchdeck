from __future__ import annotations

import json
from pathlib import Path

from prep_watchdeck.adapters.fixture import FixtureProvider
from prep_watchdeck.application.service_snapshot import build_service_snapshot
from prep_watchdeck.config.templates import load_template
from prep_watchdeck.config.vpi_config import VpiConfig, load_vpi_config
from prep_watchdeck.domain.service_models import (
    Candle1mRecord,
    InstrumentRecord,
    OpenInterestSampleRecord,
    TickerLatestRecord,
)

BASE_TS_MS = 1_781_000_000_000


def test_service_snapshot_adds_canonical_vpi_summary_and_row_copy() -> None:
    store = _service_store(include_open_candle=False)
    scanner_config = load_template(Path("../../config/scanner-filters"), "balanced")
    vpi_config = _vpi_config()

    snapshot = build_service_snapshot(
        store,
        template="balanced",
        config=scanner_config,
        vpi_config=vpi_config,
        generated_at_ms=BASE_TS_MS + 130 * 60_000,
        run_id="vpi-service",
    ).snapshot

    block = snapshot.summary["vpiLitePlus"]
    assert block["schemaVersion"] == 1
    assert block["mode"] == "lite_plus_v0"
    assert block["generatedAt"] == BASE_TS_MS + 130 * 60_000
    assert [item["symbol"] for item in block["benchmarks"]] == ["BTCUSDT", "ETHUSDT"]
    assert [item["symbol"] for item in block["targets"]] == ["SOLUSDT"]
    assert {row.symbol for row in snapshot.rows} == {"SOLUSDT"}
    sol_row = snapshot.rows[0]
    assert sol_row.display["vpiLitePlus"] == block["targets"][0]
    assert "diagnostics" not in block["targets"][0]
    assert "bars" not in block["targets"][0]
    assert len(json.dumps(block, separators=(",", ":"))) < 3_000


def test_service_snapshot_omits_vpi_when_disabled_or_not_supplied() -> None:
    store = _service_store(include_open_candle=False)
    scanner_config = load_template(Path("../../config/scanner-filters"), "balanced")
    disabled = _vpi_config().model_copy(update={"enabled": False})

    without_config = build_service_snapshot(
        store,
        template="balanced",
        config=scanner_config,
        generated_at_ms=BASE_TS_MS + 130 * 60_000,
    ).snapshot
    disabled_snapshot = build_service_snapshot(
        store,
        template="balanced",
        config=scanner_config,
        vpi_config=disabled,
        generated_at_ms=BASE_TS_MS + 130 * 60_000,
    ).snapshot
    live_scan = FixtureProvider(Path("../../fixtures")).build_snapshot(
        template="balanced",
        fixture_set="basic",
    )

    assert "vpiLitePlus" not in without_config.summary
    assert "vpiLitePlus" not in disabled_snapshot.summary
    assert "vpiLitePlus" not in live_scan.summary


def test_service_snapshot_uses_closed_1m_bars_before_5m_aggregation() -> None:
    scanner_config = load_template(Path("../../config/scanner-filters"), "balanced")
    vpi_config = _vpi_config()
    generated_at_ms = BASE_TS_MS + 130 * 60_000

    closed_only = build_service_snapshot(
        _service_store(include_open_candle=False),
        template="balanced",
        config=scanner_config,
        vpi_config=vpi_config,
        generated_at_ms=generated_at_ms,
    ).snapshot
    with_open = build_service_snapshot(
        _service_store(include_open_candle=True),
        template="balanced",
        config=scanner_config,
        vpi_config=vpi_config,
        generated_at_ms=generated_at_ms,
    ).snapshot

    assert with_open.summary["vpiLitePlus"] == closed_only.summary["vpiLitePlus"]


def test_service_snapshot_isolates_one_symbol_compute_failure(monkeypatch) -> None:
    from prep_watchdeck.application import service_snapshot

    original_compute = service_snapshot.compute_vpi_lite_plus

    def fail_eth(*, symbol: str, **kwargs):
        if symbol == "ETHUSDT":
            raise RuntimeError("forced test failure")
        return original_compute(symbol=symbol, **kwargs)

    monkeypatch.setattr(service_snapshot, "compute_vpi_lite_plus", fail_eth)
    snapshot = build_service_snapshot(
        _service_store(include_open_candle=False),
        template="balanced",
        config=load_template(Path("../../config/scanner-filters"), "balanced"),
        vpi_config=_vpi_config(),
        generated_at_ms=BASE_TS_MS + 130 * 60_000,
    ).snapshot

    block = snapshot.summary["vpiLitePlus"]
    assert [item["symbol"] for item in block["benchmarks"]] == ["BTCUSDT"]
    assert [item["symbol"] for item in block["targets"]] == ["SOLUSDT"]
    assert snapshot.rows[0].display["vpiLitePlus"]["symbol"] == "SOLUSDT"


def test_vpi_sidecar_does_not_change_scanner_decisions() -> None:
    store = _service_store(include_open_candle=False)
    scanner_config = load_template(Path("../../config/scanner-filters"), "balanced")
    generated_at_ms = BASE_TS_MS + 130 * 60_000

    baseline = build_service_snapshot(
        store,
        template="balanced",
        config=scanner_config,
        generated_at_ms=generated_at_ms,
        run_id="baseline",
    ).snapshot
    with_vpi = build_service_snapshot(
        store,
        template="balanced",
        config=scanner_config,
        vpi_config=_vpi_config(),
        generated_at_ms=generated_at_ms,
        run_id="with-vpi",
    ).snapshot

    assert with_vpi.rankings == baseline.rankings
    assert [
        (row.symbol, row.category, row.attention_score, row.reason_codes, row.risk_tag_codes)
        for row in with_vpi.rows
    ] == [
        (row.symbol, row.category, row.attention_score, row.reason_codes, row.risk_tag_codes)
        for row in baseline.rows
    ]


def _vpi_config() -> VpiConfig:
    return load_vpi_config(Path("../../config/vpi-lite-plus.toml"))


def _service_store(*, include_open_candle: bool) -> MemoryServiceStore:
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    candles = [
        _candle(symbol, BASE_TS_MS + index * 60_000, index=index, is_closed=True)
        for symbol in symbols
        for index in range(130)
    ]
    if include_open_candle:
        candles.append(
            Candle1mRecord(
                symbol="SOLUSDT",
                ts_ms=BASE_TS_MS + 130 * 60_000,
                open=1_000.0,
                high=2_000.0,
                low=500.0,
                close=1_500.0,
                quote_volume=1_000_000_000.0,
                usdt_volume=1_000_000_000.0,
                is_closed=False,
                source="test",
                updated_at_ms=BASE_TS_MS + 130 * 60_000,
            )
        )
    return MemoryServiceStore(
        instruments=[_instrument("SOLUSDT")],
        tickers=[_ticker(symbol) for symbol in symbols],
        candles=candles,
    )


def _instrument(symbol: str) -> InstrumentRecord:
    return InstrumentRecord(
        symbol=symbol,
        product_type="USDT-FUTURES",
        symbol_type="perpetual",
        symbol_status="normal",
        base_coin=symbol.removesuffix("USDT"),
        quote_coin="USDT",
        max_leverage=25.0,
        updated_at_ms=BASE_TS_MS,
    )


def _ticker(symbol: str) -> TickerLatestRecord:
    return TickerLatestRecord(
        symbol=symbol,
        ts_ms=BASE_TS_MS,
        last_price=100.0,
        high_24h=110.0,
        low_24h=90.0,
        change_24h=0.05,
        funding_rate=0.0001,
        holding_amount=12_345.0,
        quote_volume_24h=1_000_000.0,
        updated_at_ms=BASE_TS_MS,
    )


def _candle(symbol: str, ts_ms: int, *, index: int, is_closed: bool) -> Candle1mRecord:
    base = 100.0 + index * 0.01
    return Candle1mRecord(
        symbol=symbol,
        ts_ms=ts_ms,
        open=base,
        high=base + 0.2,
        low=base - 0.2,
        close=base + 0.1,
        base_volume=10_000.0 + index,
        quote_volume=10_000.0 + index,
        usdt_volume=10_000.0 + index,
        is_closed=is_closed,
        source="test",
        updated_at_ms=ts_ms,
    )


class MemoryServiceStore:
    def __init__(
        self,
        *,
        instruments: list[InstrumentRecord],
        tickers: list[TickerLatestRecord],
        candles: list[Candle1mRecord],
    ) -> None:
        self.instruments = instruments
        self.tickers = tickers
        self.candles = candles
        self.oi_samples: list[OpenInterestSampleRecord] = []

    def load_instruments(self) -> list[InstrumentRecord]:
        return self.instruments

    def load_ticker_latest(self) -> list[TickerLatestRecord]:
        return self.tickers

    def load_recent_candles_1m(self, limit_per_symbol: int) -> list[Candle1mRecord]:
        return self.candles[-limit_per_symbol:]

    def load_candles_1m_since(self, start_ts_ms: int) -> list[Candle1mRecord]:
        return [candle for candle in self.candles if candle.ts_ms >= start_ts_ms]

    def load_candles_1m_range(
        self,
        symbols: list[str],
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> list[Candle1mRecord]:
        wanted = set(symbols)
        return [
            candle
            for candle in self.candles
            if candle.symbol in wanted and start_ts_ms <= candle.ts_ms <= end_ts_ms
        ]

    def upsert_open_interest_samples(self, samples: list[OpenInterestSampleRecord]) -> None:
        self.oi_samples = samples

    def load_open_interest_samples(
        self, start_ts_ms: int, end_ts_ms: int
    ) -> list[OpenInterestSampleRecord]:
        _ = (start_ts_ms, end_ts_ms)
        return []

    def delete_open_interest_samples_before(self, cutoff_ts_ms: int) -> int:
        _ = cutoff_ts_ms
        return 0
