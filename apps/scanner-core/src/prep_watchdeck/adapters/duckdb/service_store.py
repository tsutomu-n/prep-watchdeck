from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from threading import RLock

import duckdb

from prep_watchdeck.domain.service_models import (
    Candle1mRecord,
    InstrumentRecord,
    OpenInterestSampleRecord,
    ServiceDiagnostics,
    StreamHealthRecord,
    TickerLatestRecord,
)
from prep_watchdeck.models import CandleBar


class DuckDbServiceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._schema_initialized = False

    def initialize(self) -> None:
        with self._lock, self._connect():
            return

    def upsert_instruments(self, instruments: list[InstrumentRecord]) -> None:
        if not instruments:
            return

        with self._lock, self._connect() as con:
            con.executemany(
                """
                INSERT OR REPLACE INTO instruments VALUES (
                  ?, ?, ?, ?, ?, ?, ?::JSON, ?, ?, ?, ?
                )
                """,
                [
                    (
                        item.symbol,
                        item.product_type,
                        item.symbol_type,
                        item.symbol_status,
                        item.base_coin,
                        item.quote_coin,
                        json.dumps(item.support_margin_coins),
                        item.max_leverage,
                        item.min_trade_num,
                        item.is_rwa,
                        item.updated_at_ms,
                    )
                    for item in instruments
                ],
            )

    def upsert_ticker_latest(self, tickers: list[TickerLatestRecord]) -> None:
        if not tickers:
            return

        with self._lock, self._connect() as con:
            con.executemany(
                """
                INSERT OR REPLACE INTO ticker_latest VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    (
                        item.symbol,
                        item.ts_ms,
                        item.last_price,
                        item.bid_price,
                        item.ask_price,
                        item.high_24h,
                        item.low_24h,
                        item.change_24h,
                        item.funding_rate,
                        item.next_funding_time_ms,
                        item.mark_price,
                        item.index_price,
                        item.holding_amount,
                        item.base_volume_24h,
                        item.quote_volume_24h,
                        item.open_utc,
                        item.updated_at_ms,
                    )
                    for item in tickers
                ],
            )

    def upsert_open_interest_samples(self, samples: list[OpenInterestSampleRecord]) -> None:
        if not samples:
            return

        with self._lock, self._connect() as con:
            con.executemany(
                """
                INSERT INTO open_interest_samples VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (symbol, bucket_ts_ms) DO UPDATE SET
                  holding_amount = excluded.holding_amount,
                  source_ts_ms = excluded.source_ts_ms,
                  updated_at_ms = excluded.updated_at_ms
                WHERE excluded.source_ts_ms > open_interest_samples.source_ts_ms
                """,
                [
                    (
                        item.symbol,
                        item.bucket_ts_ms,
                        item.holding_amount,
                        item.source_ts_ms,
                        item.updated_at_ms,
                    )
                    for item in samples
                ],
            )

    def load_open_interest_samples(
        self, start_ts_ms: int, end_ts_ms: int
    ) -> list[OpenInterestSampleRecord]:
        if end_ts_ms < start_ts_ms:
            raise ValueError("end_ts_ms must be >= start_ts_ms")
        with self._lock, self._connect() as con:
            rows = con.execute(
                """
                SELECT symbol, bucket_ts_ms, holding_amount, source_ts_ms, updated_at_ms
                FROM open_interest_samples
                WHERE bucket_ts_ms >= ? AND bucket_ts_ms <= ?
                ORDER BY symbol, bucket_ts_ms
                """,
                [start_ts_ms, end_ts_ms],
            ).fetchall()
        return [
            OpenInterestSampleRecord(
                symbol=str(row[0]),
                bucket_ts_ms=int(row[1]),
                holding_amount=float(row[2]),
                source_ts_ms=int(row[3]),
                updated_at_ms=int(row[4]),
            )
            for row in rows
        ]

    def delete_open_interest_samples_before(self, cutoff_ts_ms: int) -> int:
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) FROM open_interest_samples WHERE bucket_ts_ms < ?",
                [cutoff_ts_ms],
            ).fetchone()
            deleted = int(row[0]) if row is not None else 0
            con.execute(
                "DELETE FROM open_interest_samples WHERE bucket_ts_ms < ?",
                [cutoff_ts_ms],
            )
        return deleted

    def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
        if not candles:
            return

        with self._lock, self._connect() as con:
            con.executemany(
                """
                INSERT OR REPLACE INTO candles_1m VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    (
                        item.symbol,
                        item.ts_ms,
                        item.open,
                        item.high,
                        item.low,
                        item.close,
                        item.base_volume,
                        item.quote_volume,
                        item.usdt_volume,
                        item.is_closed,
                        item.source,
                        item.updated_at_ms,
                    )
                    for item in candles
                ],
            )

    def upsert_stream_health(self, health: list[StreamHealthRecord]) -> None:
        if not health:
            return

        with self._lock, self._connect() as con:
            con.executemany(
                """
                INSERT OR REPLACE INTO stream_health VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    (
                        item.shard_id,
                        item.stream_kind,
                        item.channel_count,
                        item.connected,
                        item.last_message_at_ms,
                        item.last_pong_at_ms,
                        item.reconnect_count,
                        item.gap_count,
                        item.last_error,
                    )
                    for item in health
                ],
            )

    def latest_candle_1m_ts_by_symbol(self, symbols: Iterable[str]) -> dict[str, int | None]:
        normalized_symbols = sorted(
            {symbol.strip().upper() for symbol in symbols if symbol.strip()}
        )
        if not normalized_symbols:
            return {}

        placeholders = ", ".join("?" for _ in normalized_symbols)
        result: dict[str, int | None] = {symbol: None for symbol in normalized_symbols}
        with self._lock, self._connect() as con:
            rows = con.execute(
                f"""
                SELECT symbol, MAX(ts_ms)
                FROM candles_1m
                WHERE symbol IN ({placeholders})
                GROUP BY symbol
                """,
                normalized_symbols,
            ).fetchall()
        for symbol, ts_ms in rows:
            result[str(symbol)] = int(ts_ms) if ts_ms is not None else None
        return result

    def candle_1m_count_by_symbol(self, symbols: Iterable[str]) -> dict[str, int]:
        normalized_symbols = sorted(
            {symbol.strip().upper() for symbol in symbols if symbol.strip()}
        )
        if not normalized_symbols:
            return {}

        placeholders = ", ".join("?" for _ in normalized_symbols)
        result: dict[str, int] = {symbol: 0 for symbol in normalized_symbols}
        with self._lock, self._connect() as con:
            rows = con.execute(
                f"""
                SELECT symbol, COUNT(*)
                FROM candles_1m
                WHERE symbol IN ({placeholders})
                GROUP BY symbol
                """,
                normalized_symbols,
            ).fetchall()
        for symbol, count in rows:
            result[str(symbol)] = int(count)
        return result

    def candle_1m_count_since_by_symbol(
        self,
        symbols: Iterable[str],
        start_ts_ms: int,
    ) -> dict[str, int]:
        normalized_symbols = sorted(
            {symbol.strip().upper() for symbol in symbols if symbol.strip()}
        )
        if not normalized_symbols:
            return {}

        placeholders = ", ".join("?" for _ in normalized_symbols)
        result: dict[str, int] = {symbol: 0 for symbol in normalized_symbols}
        with self._lock, self._connect() as con:
            rows = con.execute(
                f"""
                SELECT symbol, COUNT(*)
                FROM candles_1m
                WHERE symbol IN ({placeholders})
                  AND ts_ms >= ?
                GROUP BY symbol
                """,
                [*normalized_symbols, start_ts_ms],
            ).fetchall()
        for symbol, count in rows:
            result[str(symbol)] = int(count)
        return result

    def load_instruments(self) -> list[InstrumentRecord]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                """
                SELECT symbol, product_type, symbol_type, symbol_status, base_coin, quote_coin,
                       support_margin_coins, max_leverage, min_trade_num, is_rwa, updated_at_ms
                FROM instruments
                ORDER BY symbol
                """
            ).fetchall()
        return [
            InstrumentRecord(
                symbol=str(row[0]),
                product_type=str(row[1]),
                symbol_type=str(row[2]) if row[2] is not None else None,
                symbol_status=str(row[3]) if row[3] is not None else None,
                base_coin=str(row[4]) if row[4] is not None else None,
                quote_coin=str(row[5]) if row[5] is not None else None,
                support_margin_coins=json.loads(str(row[6])) if row[6] is not None else [],
                max_leverage=float(row[7]) if row[7] is not None else None,
                min_trade_num=float(row[8]) if row[8] is not None else None,
                is_rwa=bool(row[9]) if row[9] is not None else None,
                updated_at_ms=int(row[10]),
            )
            for row in rows
        ]

    def load_ticker_latest(self) -> list[TickerLatestRecord]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                """
                SELECT symbol, ts_ms, last_price, bid_price, ask_price, high_24h, low_24h,
                       change_24h, funding_rate, next_funding_time_ms, mark_price, index_price,
                       holding_amount, base_volume_24h, quote_volume_24h, open_utc, updated_at_ms
                FROM ticker_latest
                ORDER BY symbol
                """
            ).fetchall()
        return [
            TickerLatestRecord(
                symbol=str(row[0]),
                ts_ms=int(row[1]),
                last_price=float(row[2]) if row[2] is not None else None,
                bid_price=float(row[3]) if row[3] is not None else None,
                ask_price=float(row[4]) if row[4] is not None else None,
                high_24h=float(row[5]) if row[5] is not None else None,
                low_24h=float(row[6]) if row[6] is not None else None,
                change_24h=float(row[7]) if row[7] is not None else None,
                funding_rate=float(row[8]) if row[8] is not None else None,
                next_funding_time_ms=int(row[9]) if row[9] is not None else None,
                mark_price=float(row[10]) if row[10] is not None else None,
                index_price=float(row[11]) if row[11] is not None else None,
                holding_amount=float(row[12]) if row[12] is not None else None,
                base_volume_24h=float(row[13]) if row[13] is not None else None,
                quote_volume_24h=float(row[14]) if row[14] is not None else None,
                open_utc=float(row[15]) if row[15] is not None else None,
                updated_at_ms=int(row[16]),
            )
            for row in rows
        ]

    def load_recent_candles_1m(self, limit_per_symbol: int) -> list[Candle1mRecord]:
        if limit_per_symbol < 1:
            raise ValueError("limit_per_symbol must be positive")
        with self._lock, self._connect() as con:
            rows = con.execute(
                """
                SELECT symbol, ts_ms, open, high, low, close, base_volume, quote_volume,
                       usdt_volume, is_closed, source, updated_at_ms
                FROM (
                  SELECT *,
                         ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY ts_ms DESC) AS rn
                  FROM candles_1m
                )
                WHERE rn <= ?
                ORDER BY symbol, ts_ms
                """,
                [limit_per_symbol],
            ).fetchall()
        return [
            Candle1mRecord(
                symbol=str(row[0]),
                ts_ms=int(row[1]),
                open=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                close=float(row[5]),
                base_volume=float(row[6]) if row[6] is not None else None,
                quote_volume=float(row[7]) if row[7] is not None else None,
                usdt_volume=float(row[8]) if row[8] is not None else None,
                is_closed=bool(row[9]),
                source=str(row[10]),
                updated_at_ms=int(row[11]),
            )
            for row in rows
        ]

    def load_candles_1m_since(self, start_ts_ms: int) -> list[Candle1mRecord]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                """
                SELECT symbol, ts_ms, open, high, low, close, base_volume, quote_volume,
                       usdt_volume, is_closed, source, updated_at_ms
                FROM candles_1m
                WHERE ts_ms >= ?
                ORDER BY symbol, ts_ms
                """,
                [start_ts_ms],
            ).fetchall()
        return [
            Candle1mRecord(
                symbol=str(row[0]),
                ts_ms=int(row[1]),
                open=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                close=float(row[5]),
                base_volume=float(row[6]) if row[6] is not None else None,
                quote_volume=float(row[7]) if row[7] is not None else None,
                usdt_volume=float(row[8]) if row[8] is not None else None,
                is_closed=bool(row[9]),
                source=str(row[10]),
                updated_at_ms=int(row[11]),
            )
            for row in rows
        ]

    def load_candles_5m_since(self, start_ts_ms: int) -> dict[str, list[CandleBar]]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                """
                SELECT
                  symbol,
                  ts_ms - (ts_ms % 300000) AS bucket_ts_ms,
                  ARG_MIN(open, ts_ms),
                  MAX(high),
                  MIN(low),
                  ARG_MAX(close, ts_ms),
                  SUM(COALESCE(base_volume, 0)),
                  SUM(COALESCE(usdt_volume, quote_volume, 0))
                FROM candles_1m
                WHERE ts_ms >= ?
                GROUP BY symbol, bucket_ts_ms
                ORDER BY symbol, bucket_ts_ms
                """,
                [start_ts_ms],
            ).fetchall()
        bars_by_symbol: dict[str, list[CandleBar]] = {}
        for row in rows:
            symbol = str(row[0])
            bars_by_symbol.setdefault(symbol, []).append(
                CandleBar(
                    symbol=symbol,
                    ts=int(row[1]),
                    open=Decimal(str(row[2])),
                    high=Decimal(str(row[3])),
                    low=Decimal(str(row[4])),
                    close=Decimal(str(row[5])),
                    base_vol=Decimal(str(row[6])),
                    quote_vol=Decimal(str(row[7])),
                )
            )
        return bars_by_symbol

    def count_candles_1m_since(self, start_ts_ms: int) -> int:
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) FROM candles_1m WHERE ts_ms >= ?",
                [start_ts_ms],
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def latest_candle_1m_ts_since(self, start_ts_ms: int) -> int | None:
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT MAX(ts_ms) FROM candles_1m WHERE ts_ms >= ?",
                [start_ts_ms],
            ).fetchone()
        return int(row[0]) if row is not None and row[0] is not None else None

    def load_candles_1m_range(
        self,
        symbols: list[str],
        start_ts_ms: int,
        end_ts_ms: int,
    ) -> list[Candle1mRecord]:
        normalized_symbols = sorted(
            {symbol.strip().upper() for symbol in symbols if symbol.strip()}
        )
        if not normalized_symbols:
            return []
        placeholders = ", ".join("?" for _ in normalized_symbols)
        with self._lock, self._connect() as con:
            rows = con.execute(
                f"""
                SELECT symbol, ts_ms, open, high, low, close, base_volume, quote_volume,
                       usdt_volume, is_closed, source, updated_at_ms
                FROM candles_1m
                WHERE symbol IN ({placeholders})
                  AND ts_ms >= ?
                  AND ts_ms <= ?
                ORDER BY symbol, ts_ms
                """,
                [*normalized_symbols, start_ts_ms, end_ts_ms],
            ).fetchall()
        return [
            Candle1mRecord(
                symbol=str(row[0]),
                ts_ms=int(row[1]),
                open=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                close=float(row[5]),
                base_volume=float(row[6]) if row[6] is not None else None,
                quote_volume=float(row[7]) if row[7] is not None else None,
                usdt_volume=float(row[8]) if row[8] is not None else None,
                is_closed=bool(row[9]),
                source=str(row[10]),
                updated_at_ms=int(row[11]),
            )
            for row in rows
        ]

    def diagnostics(self) -> ServiceDiagnostics:
        with self._lock, self._connect() as con:
            return ServiceDiagnostics(
                schema_ready=self._schema_ready(con),
                instrument_count=self._count(con, "instruments"),
                ticker_count=self._count(con, "ticker_latest"),
                candle_1m_count=self._count(con, "candles_1m"),
                stream_health_count=self._count(con, "stream_health"),
                latest_candle_1m_ts_ms=self._latest_ts(con, "candles_1m"),
            )

    def _connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(str(self.path))
        if not self._schema_initialized:
            self._ensure_schema(con)
            self._schema_initialized = True
        return con

    def _ensure_schema(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS instruments (
              symbol TEXT PRIMARY KEY,
              product_type TEXT NOT NULL,
              symbol_type TEXT,
              symbol_status TEXT,
              base_coin TEXT,
              quote_coin TEXT,
              support_margin_coins JSON,
              max_leverage DOUBLE,
              min_trade_num DOUBLE,
              is_rwa BOOLEAN,
              updated_at_ms BIGINT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ticker_latest (
              symbol TEXT PRIMARY KEY,
              ts_ms BIGINT NOT NULL,
              last_price DOUBLE,
              bid_price DOUBLE,
              ask_price DOUBLE,
              high_24h DOUBLE,
              low_24h DOUBLE,
              change_24h DOUBLE,
              funding_rate DOUBLE,
              next_funding_time_ms BIGINT,
              mark_price DOUBLE,
              index_price DOUBLE,
              holding_amount DOUBLE,
              base_volume_24h DOUBLE,
              quote_volume_24h DOUBLE,
              open_utc DOUBLE,
              updated_at_ms BIGINT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS open_interest_samples (
              symbol TEXT NOT NULL,
              bucket_ts_ms BIGINT NOT NULL,
              holding_amount DOUBLE NOT NULL,
              source_ts_ms BIGINT NOT NULL,
              updated_at_ms BIGINT NOT NULL,
              PRIMARY KEY (symbol, bucket_ts_ms)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS candles_1m (
              symbol TEXT NOT NULL,
              ts_ms BIGINT NOT NULL,
              open DOUBLE NOT NULL,
              high DOUBLE NOT NULL,
              low DOUBLE NOT NULL,
              close DOUBLE NOT NULL,
              base_volume DOUBLE,
              quote_volume DOUBLE,
              usdt_volume DOUBLE,
              is_closed BOOLEAN NOT NULL,
              source TEXT NOT NULL,
              updated_at_ms BIGINT NOT NULL,
              PRIMARY KEY (symbol, ts_ms)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS stream_health (
              shard_id TEXT PRIMARY KEY,
              stream_kind TEXT NOT NULL,
              channel_count INTEGER NOT NULL,
              connected BOOLEAN NOT NULL,
              last_message_at_ms BIGINT,
              last_pong_at_ms BIGINT,
              reconnect_count BIGINT NOT NULL,
              gap_count BIGINT NOT NULL,
              last_error TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot_runs (
              run_id TEXT PRIMARY KEY,
              generated_at_ms BIGINT NOT NULL,
              data_as_of_ms BIGINT NOT NULL,
              symbol_count INTEGER NOT NULL,
              row_count INTEGER NOT NULL,
              status TEXT NOT NULL
            )
            """
        )

    def _schema_ready(self, con: duckdb.DuckDBPyConnection) -> bool:
        tables = {
            str(row[0])
            for row in con.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }
        return {
            "instruments",
            "ticker_latest",
            "open_interest_samples",
            "candles_1m",
            "stream_health",
            "snapshot_runs",
        }.issubset(tables)

    def _count(self, con: duckdb.DuckDBPyConnection, table_name: str) -> int:
        row = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        return int(row[0]) if row is not None else 0

    def _latest_ts(self, con: duckdb.DuckDBPyConnection, table_name: str) -> int | None:
        row = con.execute(f"SELECT MAX(ts_ms) FROM {table_name}").fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])
