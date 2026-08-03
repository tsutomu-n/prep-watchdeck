from __future__ import annotations

import csv
import json
import tempfile
import time
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

import duckdb

from prep_watchdeck.domain.dto import SnapshotDTO
from prep_watchdeck.models import CandleBar


class DuckDbSnapshotCacheLockError(RuntimeError):
    pass


class DuckDbSnapshotCache:
    def __init__(
        self,
        path: Path,
        *,
        lock_timeout_seconds: float = 5.0,
        lock_retry_interval_seconds: float = 0.25,
    ) -> None:
        self.path = path
        self.lock_timeout_seconds = lock_timeout_seconds
        self.lock_retry_interval_seconds = lock_retry_interval_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: SnapshotDTO) -> None:
        payload = snapshot.model_dump_json(by_alias=True)
        with self._connect() as con:
            con.execute("DELETE FROM snapshots WHERE run_id = ?", [snapshot.run_id])
            con.execute(
                """
                INSERT INTO snapshots VALUES (?, ?, ?, ?)
                """,
                [snapshot.run_id, snapshot.generated_at, snapshot.data_as_of, payload],
            )

    def save_candles_5m(self, candles_by_symbol: dict[str, list[CandleBar]]) -> None:
        if not any(candles_by_symbol.values()):
            return

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="",
                prefix="candles_5m_",
                suffix=".csv",
                dir=self.path.parent,
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                writer = csv.writer(temp_file)
                writer.writerow(
                    [
                        "symbol",
                        "ts",
                        "open_price",
                        "high_price",
                        "low_price",
                        "close_price",
                        "base_vol",
                        "quote_vol",
                    ]
                )
                record_count = 0
                for symbol, bars in candles_by_symbol.items():
                    for bar in bars:
                        writer.writerow(
                            [
                                symbol,
                                bar.ts,
                                float(bar.open),
                                float(bar.high),
                                float(bar.low),
                                float(bar.close),
                                float(bar.base_vol),
                                float(bar.quote_vol),
                            ]
                        )
                        record_count += 1

            if record_count == 0:
                return

            path_literal = _sql_string_literal(str(temp_path))
            with self._connect() as con:
                con.execute(
                    f"""
                    CREATE TEMP TABLE incoming_candles_5m AS
                    SELECT *
                    FROM read_csv(
                        {path_literal},
                        header = true,
                        columns = {{
                            'symbol': 'VARCHAR',
                            'ts': 'BIGINT',
                            'open_price': 'DOUBLE',
                            'high_price': 'DOUBLE',
                            'low_price': 'DOUBLE',
                            'close_price': 'DOUBLE',
                            'base_vol': 'DOUBLE',
                            'quote_vol': 'DOUBLE'
                        }}
                    )
                    """
                )
                con.execute(
                    """
                    INSERT OR REPLACE INTO candles_5m
                    SELECT
                        symbol,
                        ts,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        base_vol,
                        quote_vol
                    FROM incoming_candles_5m
                    """
                )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def load_candles_5m(
        self,
        symbols: Iterable[str],
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict[str, list[CandleBar]]:
        normalized_symbols = sorted({symbol.upper() for symbol in symbols if symbol})
        if not normalized_symbols:
            return {}

        placeholders = ", ".join("?" for _ in normalized_symbols)
        where = [f"symbol IN ({placeholders})"]
        params: list[object] = list(normalized_symbols)
        if start_ms is not None:
            where.append("ts >= ?")
            params.append(start_ms)
        if end_ms is not None:
            where.append("ts <= ?")
            params.append(end_ms)

        columns = ", ".join(
            [
                "symbol",
                "ts",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "base_vol",
                "quote_vol",
            ]
        )
        with self._connect() as con:
            rows = con.execute(
                f"""
                SELECT {columns}
                FROM candles_5m
                WHERE {" AND ".join(where)}
                ORDER BY symbol, ts
                """,
                params,
            ).fetchall()

        candles_by_symbol: dict[str, list[CandleBar]] = {
            symbol: [] for symbol in normalized_symbols
        }
        for row in rows:
            bar = CandleBar(
                symbol=str(row[0]),
                ts=int(row[1]),
                open=Decimal(str(row[2])),
                high=Decimal(str(row[3])),
                low=Decimal(str(row[4])),
                close=Decimal(str(row[5])),
                base_vol=Decimal(str(row[6])),
                quote_vol=Decimal(str(row[7])),
            )
            candles_by_symbol.setdefault(bar.symbol, []).append(bar)
        return candles_by_symbol

    def latest(self) -> SnapshotDTO | None:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT snapshot_json::VARCHAR
                FROM snapshots
                ORDER BY generated_at DESC, run_id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return SnapshotDTO.model_validate(json.loads(str(row[0])))

    def _connect(self) -> duckdb.DuckDBPyConnection:
        deadline = time.monotonic() + max(0.0, self.lock_timeout_seconds)
        while True:
            try:
                con = duckdb.connect(str(self.path))
                self._ensure_schema(con)
                return con
            except duckdb.IOException as exc:
                if not _is_lock_error(exc) or time.monotonic() >= deadline:
                    if _is_lock_error(exc):
                        raise DuckDbSnapshotCacheLockError(
                            f"DuckDB cache is locked by another watchdeck process: {self.path}. "
                            "Wait for the running scan to finish, or stop it "
                            "before starting another scan/detect command."
                        ) from exc
                    raise
                time.sleep(max(0.01, self.lock_retry_interval_seconds))

    def _ensure_schema(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
              run_id TEXT PRIMARY KEY,
              generated_at BIGINT,
              data_as_of BIGINT,
              snapshot_json JSON
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS candles_5m (
              symbol TEXT NOT NULL,
              ts BIGINT NOT NULL,
              open_price DOUBLE NOT NULL,
              high_price DOUBLE NOT NULL,
              low_price DOUBLE NOT NULL,
              close_price DOUBLE NOT NULL,
              base_vol DOUBLE NOT NULL,
              quote_vol DOUBLE NOT NULL,
              PRIMARY KEY (symbol, ts)
            )
            """
        )


def _is_lock_error(exc: duckdb.IOException) -> bool:
    return "Could not set lock on file" in str(exc)


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
