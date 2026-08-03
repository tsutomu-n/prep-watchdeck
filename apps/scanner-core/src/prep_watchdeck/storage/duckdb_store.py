from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from prep_watchdeck.models import CandleBar, ContractInfo, ScannerRow, TickerInfo


class DuckDBStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(str(self.path))
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS contracts (
              symbol TEXT,
              product_type TEXT,
              base_coin TEXT,
              quote_coin TEXT,
              symbol_type TEXT,
              symbol_status TEXT,
              min_trade_usdt DOUBLE,
              max_lever DOUBLE,
              is_rwa BOOLEAN,
              updated_at_ms BIGINT,
              PRIMARY KEY(symbol, product_type)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS tickers_snapshot (
              run_id TEXT,
              symbol TEXT,
              ts BIGINT,
              last_price DOUBLE,
              change_24h DOUBLE,
              usdt_volume_24h DOUBLE,
              funding_rate DOUBLE,
              holding_amount DOUBLE
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS candles_5m (
              symbol TEXT,
              ts BIGINT,
              open DOUBLE,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE,
              base_vol DOUBLE,
              quote_vol DOUBLE,
              PRIMARY KEY(symbol, ts)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS scanner_rows (
              run_id TEXT,
              symbol TEXT,
              ts BIGINT,
              category TEXT,
              direction TEXT,
              label TEXT,
              priority_score DOUBLE,
              row_json JSON
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS run_log (
              run_id TEXT,
              started_at_ms BIGINT,
              finished_at_ms BIGINT,
              template_name TEXT,
              status TEXT,
              message TEXT
            )
            """
        )
        return con

    def initialize(self) -> None:
        self._connect().close()

    def save_contracts(self, contracts: list[ContractInfo], updated_at_ms: int) -> None:
        rows = [
            {
                "symbol": contract.symbol,
                "product_type": contract.product_type,
                "base_coin": contract.base_coin,
                "quote_coin": contract.quote_coin,
                "symbol_type": contract.symbol_type,
                "symbol_status": contract.symbol_status,
                "min_trade_usdt": float(contract.min_trade_usdt)
                if contract.min_trade_usdt is not None
                else None,
                "max_lever": float(contract.max_lever) if contract.max_lever is not None else None,
                "is_rwa": contract.is_rwa,
                "updated_at_ms": updated_at_ms,
            }
            for contract in contracts
        ]
        if not rows:
            return
        with self._connect() as con:
            con.executemany(
                """
                INSERT OR REPLACE INTO contracts VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    (
                        row["symbol"],
                        row["product_type"],
                        row["base_coin"],
                        row["quote_coin"],
                        row["symbol_type"],
                        row["symbol_status"],
                        row["min_trade_usdt"],
                        row["max_lever"],
                        row["is_rwa"],
                        row["updated_at_ms"],
                    )
                    for row in rows
                ],
            )

    def save_tickers(self, run_id: str, tickers: list[TickerInfo]) -> None:
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
                "funding_rate": float(ticker.funding_rate)
                if ticker.funding_rate is not None
                else None,
                "holding_amount": float(ticker.holding_amount)
                if ticker.holding_amount is not None
                else None,
            }
            for ticker in tickers
        ]
        with self._connect() as con:
            con.execute("DELETE FROM tickers_snapshot WHERE run_id = ?", [run_id])
            if rows:
                con.executemany(
                    "INSERT INTO tickers_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            row["run_id"],
                            row["symbol"],
                            row["ts"],
                            row["last_price"],
                            row["change_24h"],
                            row["usdt_volume_24h"],
                            row["funding_rate"],
                            row["holding_amount"],
                        )
                        for row in rows
                    ],
                )

    def save_candles(self, bars_by_symbol: dict[str, list[CandleBar]]) -> None:
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
            }
            for bars in bars_by_symbol.values()
            for bar in bars
        ]
        if not rows:
            return
        with self._connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO candles_5m VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        row["symbol"],
                        row["ts"],
                        row["open"],
                        row["high"],
                        row["low"],
                        row["close"],
                        row["base_vol"],
                        row["quote_vol"],
                    )
                    for row in rows
                ],
            )

    def save_scanner_rows(self, run_id: str, rows: list[ScannerRow]) -> None:
        row_dicts = [
            {
                "run_id": run_id,
                "symbol": row.symbol,
                "ts": row.ts,
                "category": row.category,
                "direction": row.direction,
                "label": row.label,
                "priority_score": row.priority_score,
                "row_json": row.model_dump_json(),
            }
            for row in rows
        ]
        with self._connect() as con:
            con.execute("DELETE FROM scanner_rows WHERE run_id = ?", [run_id])
            if row_dicts:
                con.executemany(
                    "INSERT INTO scanner_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?::JSON)",
                    [
                        (
                            row["run_id"],
                            row["symbol"],
                            row["ts"],
                            row["category"],
                            row["direction"],
                            row["label"],
                            row["priority_score"],
                            row["row_json"],
                        )
                        for row in row_dicts
                    ],
                )

    def save_run_log(
        self,
        *,
        run_id: str,
        started_at_ms: int,
        finished_at_ms: int,
        template_name: str,
        status: str,
        message: str,
    ) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO run_log VALUES (?, ?, ?, ?, ?, ?)",
                [run_id, started_at_ms, finished_at_ms, template_name, status, message],
            )

    def latest_rows(self) -> list[dict[str, Any]]:
        run = self.latest_run()
        if run is None:
            return []
        run_id, _finished_at_ms = run
        with self._connect() as con:
            result = con.execute(
                """
                SELECT row_json::VARCHAR
                FROM scanner_rows
                WHERE run_id = ?
                ORDER BY priority_score DESC
                """,
                [run_id],
            ).fetchall()
        import json

        return [json.loads(row[0]) for row in result]

    def latest_run(self) -> tuple[str, int] | None:
        with self._connect() as con:
            run = con.execute(
                """
                SELECT run_id, finished_at_ms
                FROM run_log
                WHERE status = 'success'
                ORDER BY finished_at_ms DESC
                LIMIT 1
                """
            ).fetchone()
        if run is None:
            return None
        return str(run[0]), int(run[1])

    def previous_open_interest_by_symbol(
        self,
        *,
        reference_ms: int,
        lookback_minutes: int,
    ) -> dict[str, float]:
        cutoff_ms = reference_ms - lookback_minutes * 60_000
        with self._connect() as con:
            run = con.execute(
                """
                SELECT run_id
                FROM run_log
                WHERE status = 'success'
                  AND finished_at_ms <= ?
                ORDER BY finished_at_ms DESC
                LIMIT 1
                """,
                [cutoff_ms],
            ).fetchone()
            if run is None:
                return {}
            rows = con.execute(
                """
                SELECT symbol, holding_amount
                FROM tickers_snapshot
                WHERE run_id = ?
                  AND holding_amount IS NOT NULL
                """,
                [str(run[0])],
            ).fetchall()
        return {str(symbol): float(holding_amount) for symbol, holding_amount in rows}
