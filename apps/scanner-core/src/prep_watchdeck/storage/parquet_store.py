from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from prep_watchdeck.models import CandleBar, TickerInfo


def _date_part(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, UTC).strftime("%Y-%m-%d")


def write_candles_parquet(base_dir: Path, bars_by_symbol: dict[str, list[CandleBar]]) -> None:
    rows = [
        {
            "symbol": bar.symbol,
            "ts": bar.ts,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "base_vol": float(bar.base_vol),
            "quote_vol": float(bar.quote_vol),
            "date": _date_part(bar.ts),
        }
        for bars in bars_by_symbol.values()
        for bar in bars
    ]
    if not rows:
        return
    for date, group in pl.DataFrame(rows).partition_by("date", as_dict=True).items():
        date_value = date[0] if isinstance(date, tuple) else date
        out_dir = base_dir / f"date={date_value}"
        out_dir.mkdir(parents=True, exist_ok=True)
        group.drop("date").write_parquet(out_dir / "candles.parquet")


def write_tickers_snapshot_parquet(base_dir: Path, run_id: str, tickers: list[TickerInfo]) -> None:
    if not tickers:
        return
    ts = next(
        (ticker.ts for ticker in tickers if ticker.ts is not None),
        int(datetime.now(UTC).timestamp() * 1000),
    )
    rows = [
        {
            "run_id": run_id,
            "symbol": ticker.symbol,
            "ts": ticker.ts,
            "last_price": float(ticker.last_price) if ticker.last_price is not None else None,
            "change_24h": float(ticker.change_24h) if ticker.change_24h is not None else None,
            "usdt_volume_24h": float(ticker.usdt_volume_24h)
            if ticker.usdt_volume_24h is not None
            else None,
            "funding_rate": float(ticker.funding_rate) if ticker.funding_rate is not None else None,
            "holding_amount": float(ticker.holding_amount)
            if ticker.holding_amount is not None
            else None,
        }
        for ticker in tickers
    ]
    out_dir = base_dir / f"date={_date_part(ts)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(out_dir / f"{run_id}.parquet")
