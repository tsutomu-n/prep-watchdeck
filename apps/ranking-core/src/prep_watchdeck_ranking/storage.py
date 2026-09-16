"""A single writer, bounded history and fixed input generations in a dedicated state root."""

import json
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .models import MINUTE, MinuteBar, RankingMap


def isolated_state(state: Path, original_state: Path) -> Path:
    state, original = state.expanduser().resolve(), original_state.expanduser().resolve()
    if state == original or state.is_relative_to(original) or original.is_relative_to(state):
        raise ValueError("ranking state must not overlap Market Core state")
    if state == Path(state.anchor) or state == Path.home().resolve():
        raise ValueError("ranking state must be a dedicated directory")
    return state


def atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class Store:
    def __init__(self, state: Path, original_state: Path) -> None:
        self.state = isolated_state(state, original_state)
        self.state.mkdir(parents=True, exist_ok=True)
        database = self.state / "ranking.sqlite3"
        for suffix in ("", "-wal", "-shm", "-journal"):
            target = self.state / (database.name + suffix)
            if target.is_symlink() or target.resolve().parent != self.state:
                raise ValueError("ranking database cannot escape dedicated state")
        self.connection = sqlite3.connect(database)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS minute_bars (
                reference_key TEXT NOT NULL, end INTEGER NOT NULL,
                open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
                quote_turnover REAL NOT NULL,
                PRIMARY KEY(reference_key, end)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def set_map(self, mapping: RankingMap) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO metadata VALUES ('map', ?)",
                (mapping.model_dump_json(by_alias=True),),
            )
        atomic_json(self.state / "mapping.json", mapping.model_dump(mode="json", by_alias=True))

    def get_map(self) -> RankingMap | None:
        row = self.connection.execute("SELECT value FROM metadata WHERE key='map'").fetchone()
        return RankingMap.model_validate_json(row[0]) if row else None

    def put(self, bars: Iterable[MinuteBar], now: int) -> int:
        records = []
        for bar in bars:
            if bar.end > now // MINUTE * MINUTE:
                raise ValueError("unclosed or future minute bar")
            records.append(
                (
                    bar.reference_key,
                    bar.end,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.quote_turnover,
                )
            )
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO minute_bars VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reference_key,end) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, quote_turnover=excluded.quote_turnover
            """,
                records,
            )
        return len(records)

    def window(
        self, reference_key: str, first: int, last: int
    ) -> list[tuple[int, float, float, float, float]]:
        return self.connection.execute(
            """
            SELECT end,close,quote_turnover,high,low FROM minute_bars
            WHERE reference_key=? AND end>=? AND end<=? ORDER BY end
        """,
            (reference_key, first, last),
        ).fetchall()

    def latest(self, reference_key: str) -> int | None:
        row = self.connection.execute(
            "SELECT MAX(end) FROM minute_bars WHERE reference_key=?", (reference_key,)
        ).fetchone()
        return row[0]

    def prune(self, cutoff: int, keys: set[str]) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM minute_bars WHERE end<?", (cutoff - 2881 * MINUTE,)
            )
            existing = self.connection.execute("SELECT DISTINCT reference_key FROM minute_bars")
            for (key,) in list(existing):
                if key not in keys:
                    self.connection.execute("DELETE FROM minute_bars WHERE reference_key=?", (key,))

    def close(self) -> None:
        self.connection.close()
