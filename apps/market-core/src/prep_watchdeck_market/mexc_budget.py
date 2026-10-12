from __future__ import annotations

import asyncio
import math
import os
import sqlite3
import time
from pathlib import Path
from typing import Literal

BudgetLane = Literal["funding", "foreground", "recovery"]
LANE_LIMITS: dict[BudgetLane, int] = {"funding": 4, "foreground": 2, "recovery": 2}
WINDOW_MS = 2_000
APPLICATION_ID = 1_296_390_211  # Dedicated admission DB; refuse business SQLite databases.


class MexcBudgetUnavailable(RuntimeError):
    """No HTTP request may start when shared admission cannot be established."""

    def __init__(self) -> None:
        super().__init__("MEXC shared budget unavailable")


def budget_path(value: str | Path | None) -> Path:
    if not value:
        raise MexcBudgetUnavailable()
    try:
        path = Path(value)
        if not path.is_absolute() or path.resolve() != path or not path.parent.is_dir():
            raise MexcBudgetUnavailable()
        return path
    except (OSError, ValueError, TypeError):
        raise MexcBudgetUnavailable() from None


class MexcHttpBudget:
    """Cross-process fixed lanes, reserved atomically before every HTTP attempt.

    Wall-clock milliseconds are shared with Bun. Clock rollback fails closed until
    the previously recorded clock catches up; elapsed wait deadlines use monotonic time.
    Only admission metadata lives here, never provider payloads or business data.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = budget_path(path)

    @classmethod
    def from_env(cls) -> MexcHttpBudget:
        return cls(budget_path(os.environ.get("PREP_WATCHDECK_MEXC_BUDGET_DB")))

    def _transaction(self, lane: BudgetLane | None, cooldown_ms: int = 0) -> int:
        budget_path(self.path)
        connection = sqlite3.connect(self.path, timeout=0.025, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
            if application_id == 0:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                if tables:
                    raise MexcBudgetUnavailable()
                connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                connection.execute(
                    "CREATE TABLE mexc_budget_meta (id INTEGER PRIMARY KEY CHECK(id=1), "
                    "version INTEGER NOT NULL, cooldown_until_ms INTEGER NOT NULL, "
                    "last_clock_ms INTEGER NOT NULL)"
                )
                connection.execute("INSERT INTO mexc_budget_meta VALUES (1,1,0,0)")
                connection.execute(
                    "CREATE TABLE mexc_budget_attempts (at_ms INTEGER NOT NULL, "
                    "lane TEXT NOT NULL CHECK(lane IN ('funding','foreground','recovery')))"
                )
                connection.execute(
                    "CREATE INDEX mexc_budget_attempt_time ON mexc_budget_attempts(at_ms)"
                )
            elif application_id != APPLICATION_ID:
                raise MexcBudgetUnavailable()
            version, cooldown_until, last_clock = connection.execute(
                "SELECT version,cooldown_until_ms,last_clock_ms FROM mexc_budget_meta WHERE id=1"
            ).fetchone()
            if version != 1:
                raise MexcBudgetUnavailable()
            now = time.time_ns() // 1_000_000
            if now < last_clock:
                raise MexcBudgetUnavailable()
            connection.execute("UPDATE mexc_budget_meta SET last_clock_ms=? WHERE id=1", (now,))
            if lane is None:
                connection.execute(
                    "UPDATE mexc_budget_meta SET cooldown_until_ms=max(cooldown_until_ms,?) "
                    "WHERE id=1",
                    (now + cooldown_ms,),
                )
                connection.execute("COMMIT")
                return 0
            connection.execute(
                "DELETE FROM mexc_budget_attempts WHERE at_ms<=?", (now - WINDOW_MS,)
            )
            rows = connection.execute(
                "SELECT at_ms,lane FROM mexc_budget_attempts ORDER BY at_ms"
            ).fetchall()
            waits = [cooldown_until - now]
            if len(rows) >= 8:
                waits.append(rows[-8][0] + WINDOW_MS - now)
            lane_rows = [at for at, row_lane in rows if row_lane == lane]
            if len(lane_rows) >= LANE_LIMITS[lane]:
                waits.append(lane_rows[-LANE_LIMITS[lane]] + WINDOW_MS - now)
            delay = max(0, *waits)
            if delay == 0:
                connection.execute(
                    "INSERT INTO mexc_budget_attempts(at_ms,lane) VALUES (?,?)", (now, lane)
                )
            connection.execute("COMMIT")
            return delay
        finally:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            connection.close()

    async def acquire(
        self, lane: BudgetLane = "foreground", *, timeout_seconds: float = 20.0
    ) -> None:
        if lane not in LANE_LIMITS or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise MexcBudgetUnavailable()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                delay_ms = await asyncio.to_thread(self._transaction, lane)
                if delay_ms == 0 and time.monotonic() < deadline:
                    return
            except (sqlite3.Error, OSError, MexcBudgetUnavailable, TypeError, ValueError):
                delay_ms = 50
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(min(remaining, max(0.001, delay_ms / 1_000), 0.25))
        raise MexcBudgetUnavailable()

    async def cooldown(self, seconds: float = 2.0, *, timeout_seconds: float = 2.0) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            seconds = 2.0
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                await asyncio.to_thread(self._transaction, None, math.ceil(max(2, seconds) * 1_000))
                return
            except (sqlite3.Error, OSError, MexcBudgetUnavailable, TypeError, ValueError):
                await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))
        raise MexcBudgetUnavailable()
