"""JSON-lines bridge for the isolated DB -> real metrics worker -> Browser E2E."""

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.market_metrics import candle_cutoff
from prep_watchdeck_market.service import MarketService

from .test_market_metrics import seed_metrics_database


def emit(value):
    print(json.dumps(value), flush=True)


async def main():
    source = os.environ["TEST_DATABASE_URL"]
    target = conninfo_to_dict(source)
    if (
        target.get("host") != "127.0.0.1"
        or target.get("port", "5432") in {"5432", "55432"}
        or target.get("dbname") != "prep_watchdeck_test"
        or target.get("user") != "prep_watchdeck_test"
    ):
        raise ValueError("isolated test database required")
    root = Path(sys.argv[1]).resolve()
    expected = Path(__file__).resolve().parents[3] / "var/tmp/e2e/runtime"
    if root != expected:
        raise ValueError("isolated browser state required")
    database = f"metrics_browser_{uuid4().hex}"
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        worker = None
        stop = asyncio.Event()
        try:
            url = make_conninfo(source, dbname=database)
            with psycopg.connect(url, autocommit=True) as writer:
                apply_migrations(writer)
                now = datetime.now(UTC)
                with writer.transaction():
                    version, _ = seed_metrics_database(writer, now)
                    writer.execute(
                        "DELETE FROM candle_1m WHERE venue_instrument_version_id=%s "
                        "AND bucket_at=%s",
                        (version, candle_cutoff(now) - timedelta(minutes=1)),
                    )
                    commit_requested = time.time()
                write_completed = time.time()
                service = MarketService(url, root)
                worker = asyncio.create_task(service._metrics_loop(stop))
                emit(
                    {
                        "event": "ready",
                        "commitRequestedAt": commit_requested,
                        "writeCompletedAt": write_completed,
                        "version": version,
                    }
                )
                while True:
                    command = (await asyncio.to_thread(sys.stdin.readline)).strip()
                    if command == "quit" or not command:
                        break
                    if command == "stop":
                        stop.set()
                        if worker is None:
                            raise ValueError("metrics worker is not running")
                        await worker
                        worker = None
                        emit({"event": "stopped", "at": time.time()})
                        continue
                    if command == "restart":
                        stop = asyncio.Event()
                        worker = asyncio.create_task(service._metrics_loop(stop))
                        emit({"event": "restarted", "at": time.time()})
                        continue
                    if command == "timeout":
                        before = (root / "artifacts/market-metrics.json").read_bytes()
                        started = time.monotonic()
                        maximum = 0
                        with writer.transaction():
                            writer.execute("LOCK TABLE candle_1m IN ACCESS EXCLUSIVE MODE")
                            service._metrics_trigger.set()
                            while time.monotonic() - started < 12:
                                activity = admin.execute(
                                    "SELECT count(*) FROM pg_stat_activity WHERE datname=%s "
                                    "AND query LIKE '%%SELECT vi.venue_instrument_version_id%%'",
                                    (database,),
                                ).fetchone()
                                assert activity is not None
                                count = activity[0]
                                maximum = max(maximum, count)
                                if maximum and count == 0:
                                    break
                                await asyncio.sleep(0.1)
                            else:
                                raise AssertionError("projection did not finish its DB timeout")
                            assert maximum == 1
                            assert (root / "artifacts/market-metrics.json").read_bytes() == before
                        service._metrics_trigger.set()
                        emit(
                            {
                                "event": "timeout",
                                "maximumConnections": maximum,
                                "artifactUnchanged": True,
                                "elapsedSeconds": time.monotonic() - started,
                            }
                        )
                        continue
                    close = {"late": 110, "correct": 95, "resume-write": 120}[command]
                    cutoff = candle_cutoff(datetime.now(UTC))
                    with writer.transaction():
                        # Refresh endpoints at the worker's current minute, including rollover.
                        for minutes, price in ((0, close), (15, 100), (60, 100), (1440, 100)):
                            writer.execute(
                                "INSERT INTO candle_1m (venue_instrument_version_id, bucket_at, "
                                "open_price, high_price, low_price, close_price, "
                                "finality, observed_at) "
                                "VALUES (%s,%s,%s,%s,%s,%s,'confirmed',%s) "
                                "ON CONFLICT (venue_instrument_version_id,bucket_at) DO UPDATE SET "
                                "open_price=EXCLUDED.open_price,high_price=EXCLUDED.high_price,"
                                "low_price=EXCLUDED.low_price,close_price=EXCLUDED.close_price,"
                                "observed_at=EXCLUDED.observed_at",
                                (
                                    version,
                                    cutoff - timedelta(minutes=minutes + 1),
                                    price,
                                    price,
                                    price,
                                    price,
                                    datetime.now(UTC),
                                ),
                            )
                        commit_requested = time.time()
                    write_completed = time.time()
                    service._metrics_trigger.set()
                    emit(
                        {
                            "event": command,
                            "commitRequestedAt": commit_requested,
                            "writeCompletedAt": write_completed,
                            "notifiedAt": time.time(),
                            "cutoff": cutoff.isoformat(),
                        }
                    )
        finally:
            stop.set()
            if worker:
                await worker
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


if __name__ == "__main__":
    asyncio.run(main())
