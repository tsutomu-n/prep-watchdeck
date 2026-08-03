from __future__ import annotations

from decimal import Decimal

from prep_watchdeck.adapters.duckdb.snapshot_cache import DuckDbSnapshotCache
from prep_watchdeck.models import CandleBar


def test_save_candles_5m_loads_saved_bars(tmp_path) -> None:
    cache = DuckDbSnapshotCache(tmp_path / "watchdeck.duckdb")
    cache.save_candles_5m(
        {
            "ALTUSDT": [
                _bar("ALTUSDT", 1_781_000_000_000, "10.1"),
                _bar("ALTUSDT", 1_781_000_300_000, "10.2"),
            ],
            "BTCUSDT": [
                _bar("BTCUSDT", 1_781_000_000_000, "100.1"),
            ],
        }
    )

    loaded = cache.load_candles_5m(["BTCUSDT", "ALTUSDT"])

    assert [bar.ts for bar in loaded["ALTUSDT"]] == [
        1_781_000_000_000,
        1_781_000_300_000,
    ]
    assert loaded["ALTUSDT"][0].close == Decimal("10.1")
    assert loaded["ALTUSDT"][1].quote_vol == Decimal("1020.0")
    assert loaded["BTCUSDT"][0].close == Decimal("100.1")


def test_save_candles_5m_replaces_existing_rows_and_removes_temp_csv(tmp_path) -> None:
    cache = DuckDbSnapshotCache(tmp_path / "watchdeck.duckdb")
    cache.save_candles_5m({"ALTUSDT": [_bar("ALTUSDT", 1_781_000_000_000, "10.1")]})
    cache.save_candles_5m({"ALTUSDT": [_bar("ALTUSDT", 1_781_000_000_000, "11.2")]})

    loaded = cache.load_candles_5m(["ALTUSDT"])

    assert len(loaded["ALTUSDT"]) == 1
    assert loaded["ALTUSDT"][0].close == Decimal("11.2")
    assert list(tmp_path.glob("candles_5m_*.csv")) == []


def test_save_candles_5m_skips_empty_input_without_temp_csv(tmp_path) -> None:
    cache = DuckDbSnapshotCache(tmp_path / "watchdeck.duckdb")

    cache.save_candles_5m({"ALTUSDT": []})

    assert list(tmp_path.glob("candles_5m_*.csv")) == []


def test_save_candles_5m_handles_cache_path_with_single_quote(tmp_path) -> None:
    cache_dir = tmp_path / "quote'path"
    cache = DuckDbSnapshotCache(cache_dir / "watchdeck.duckdb")

    cache.save_candles_5m({"ALTUSDT": [_bar("ALTUSDT", 1_781_000_000_000, "10.1")]})

    loaded = cache.load_candles_5m(["ALTUSDT"])
    assert loaded["ALTUSDT"][0].close == Decimal("10.1")


def _bar(symbol: str, ts: int, close: str) -> CandleBar:
    close_value = Decimal(close)
    return CandleBar(
        symbol=symbol,
        ts=ts,
        open=close_value - Decimal("0.1"),
        high=close_value + Decimal("0.2"),
        low=close_value - Decimal("0.2"),
        close=close_value,
        base_vol=Decimal("100"),
        quote_vol=close_value * Decimal("100"),
    )
