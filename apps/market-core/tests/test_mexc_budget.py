import asyncio
import socket
import sqlite3
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import aiohttp
import pytest

from prep_watchdeck_market.mexc_budget import MexcBudgetUnavailable, MexcHttpBudget
from prep_watchdeck_market.sources.candle_history import (
    HistoryBudgetExceeded,
    HistoryRateLimited,
    NativeCandleHistoryClient,
)


@pytest.mark.parametrize("route", ["central", "recovery", "recovery_limit"])
def test_transport_disconnect_requires_an_admission_for_every_http_attempt(
    monkeypatch, tmp_path, route
):
    from prep_watchdeck_market.sources.mexc import fetch_mexc_json

    path = tmp_path / "budget.sqlite3"
    monkeypatch.setenv("PREP_WATCHDECK_MEXC_BUDGET_DB", str(path))
    requests = []

    class LoopbackResolver(aiohttp.abc.AbstractResolver):
        async def resolve(
            self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
        ) -> list[aiohttp.abc.ResolveResult]:
            return [
                {
                    "hostname": host,
                    "host": "127.0.0.1",
                    "port": port,
                    "family": socket.AF_INET,
                    "proto": 0,
                    "flags": 0,
                }
            ]

        async def close(self):
            pass

    async def run():
        async def handle(reader, writer):
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                requests.append(header.split(b"\r\n", 1)[0])
                if len(requests) > 1:
                    body = b'{"success":true,"code":0,"data":[]}'
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        b"Connection: close\r\nContent-Length: "
                        + str(len(body)).encode()
                        + b"\r\n\r\n"
                        + body
                    )
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        url = f"http://api.mexc.com:{port}"
        monkeypatch.setattr("prep_watchdeck_market.sources.mexc.MEXC_BASE_URL", url)
        try:
            connector = aiohttp.TCPConnector(resolver=LoopbackResolver())
            async with aiohttp.ClientSession(connector=connector) as session:
                if route == "central":
                    await fetch_mexc_json(session, "/test")
                else:
                    client = NativeCandleHistoryClient(
                        session,
                        max_requests=1 if route == "recovery_limit" else 3,
                        deadline_seconds=5,
                        min_interval_seconds=0,
                    )
                    if route == "recovery_limit":
                        with pytest.raises(HistoryBudgetExceeded):
                            await client._request_json("GET", url + "/test")
                    else:
                        await client._request_json("GET", url + "/test")
                    assert client.request_count == len(requests)
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())
    expected = 1 if route == "recovery_limit" else 2
    assert len(requests) == expected
    with sqlite3.connect(path) as connection:
        admissions = connection.execute("SELECT lane FROM mexc_budget_attempts").fetchall()
    assert admissions == [("foreground" if route == "central" else "recovery",)] * expected


def test_python_and_bun_processes_share_fixed_lanes_and_cooldown(monkeypatch, tmp_path):
    path = tmp_path / "budget.sqlite3"
    budget = MexcHttpBudget(path)
    asyncio.run(budget.acquire())
    # A test-only trigger retains admission timestamps after normal rolling-window pruning.
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM mexc_budget_attempts")
        connection.execute("CREATE TABLE proof_admissions(at_ms INTEGER,lane TEXT)")
        connection.execute(
            "CREATE TRIGGER retain_proof AFTER INSERT ON mexc_budget_attempts BEGIN "
            "INSERT INTO proof_admissions VALUES (NEW.at_ms,NEW.lane); END"
        )
    monkeypatch.setenv("PREP_WATCHDECK_MEXC_BUDGET_DB", str(path))

    class Session:
        @asynccontextmanager
        async def request(self, *args, **kwargs):
            assert kwargs["allow_redirects"] is False

            async def send(_request):
                return SimpleNamespace(status=429, headers={"Retry-After": "2"})

            yield await kwargs["middlewares"][0](None, send)

    async def rate_limit():
        client = NativeCandleHistoryClient(
            cast(Any, Session()), max_requests=1, deadline_seconds=5, min_interval_seconds=0
        )
        with pytest.raises(HistoryRateLimited):
            await client._request_json("GET", "https://api.mexc.com/api/v1/contract/kline/BTC_USDT")

    asyncio.run(rate_limit())
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM proof_admissions")
    with sqlite3.connect(path) as connection:
        cooldown_until = connection.execute(
            "SELECT cooldown_until_ms FROM mexc_budget_meta"
        ).fetchone()[0]
    module = (Path(__file__).resolve().parents[2] / "web/src/lib/server/mexc-budget.ts").as_posix()
    worker = tmp_path / "budget-worker.ts"
    worker.write_text(
        f'import {{ SharedMexcBudget }} from "{module}";\n'
        "process.env.PREP_WATCHDECK_MEXC_BUDGET_DB = process.argv[2];\n"
        "const budget = new SharedMexcBudget();\n"
        'for (let i=0;i<4;i++) await budget.acquire("foreground",new AbortController().signal);\n'
    )
    python_worker = (
        "import asyncio,sys; from prep_watchdeck_market.mexc_budget import MexcHttpBudget; "
        "budget=MexcHttpBudget(sys.argv[1]); "
        "asyncio.run(run())"
    )
    python_worker = python_worker.replace(
        "asyncio.run(run())",
        "\nasync def run():\n for _ in range(4): await budget.acquire(sys.argv[2])\n"
        "asyncio.run(run())",
    )
    commands = [
        [sys.executable, "-c", python_worker, str(path), "funding"],
        [sys.executable, "-c", python_worker, str(path), "funding"],
        [sys.executable, "-c", python_worker, str(path), "recovery"],
        ["bun", str(worker), str(path)],
    ]
    processes = [
        subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for cmd in commands
    ]
    try:
        for process in processes:
            _, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr.decode()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    with sqlite3.connect(path) as connection:
        admissions = connection.execute(
            "SELECT at_ms,lane FROM proof_admissions ORDER BY at_ms"
        ).fetchall()
    assert len(admissions) == 16
    assert admissions[0][0] >= cooldown_until  # Python 429 cooldown is observed by Bun too.
    for at_ms, _ in admissions:
        window = [(at, lane) for at, lane in admissions if at_ms <= at < at_ms + 2_000]
        assert len(window) <= 8
        for lane, limit in {"funding": 4, "foreground": 2, "recovery": 2}.items():
            assert sum(row_lane == lane for _, row_lane in window) <= limit


@pytest.mark.parametrize("failure", ["corrupt", "busy", "business"])
def test_shared_budget_database_failure_is_bounded_and_never_admits(tmp_path, failure):
    path = tmp_path / "budget.sqlite3"
    holder = None
    if failure == "corrupt":
        path.write_bytes(b"not a SQLite database")
    elif failure == "business":
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE business(value TEXT)")
    else:
        asyncio.run(MexcHttpBudget(path).acquire())
        holder = sqlite3.connect(path)
        holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(MexcBudgetUnavailable, match=r"^MEXC shared budget unavailable$"):
            asyncio.run(MexcHttpBudget(path).acquire(timeout_seconds=0.1))
    finally:
        if holder is not None:
            holder.close()
    if failure == "business":
        with sqlite3.connect(path) as connection:
            assert connection.execute("PRAGMA application_id").fetchone()[0] == 0
            assert connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall() == [("business",)]


def test_missing_relative_and_symlink_budget_paths_fail_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("PREP_WATCHDECK_MEXC_BUDGET_DB", raising=False)
    with pytest.raises(MexcBudgetUnavailable):
        MexcHttpBudget.from_env()
    with pytest.raises(MexcBudgetUnavailable):
        MexcHttpBudget("relative.sqlite3")
    actual = tmp_path / "actual.sqlite3"
    link = tmp_path / "link.sqlite3"
    link.symlink_to(actual)
    with pytest.raises(MexcBudgetUnavailable):
        MexcHttpBudget(link)


def test_central_http_429_retry_requires_another_lane_admission():
    from prep_watchdeck_market.sources.mexc import fetch_mexc_json

    events = []

    class Budget:
        async def acquire(self, lane, **kwargs):
            events.append(("acquire", lane))

        async def cooldown(self, seconds):
            events.append(("cooldown", seconds))

    class Response:
        def __init__(self, status):
            self.status = status
            self.headers = {"Retry-After": "7"}

        def raise_for_status(self):
            assert self.status == 200

        async def json(self, **kwargs):
            return {"success": True, "code": 0, "data": []}

    class Session:
        attempts = 0

        @asynccontextmanager
        async def get(self, *args, **kwargs):
            assert kwargs["allow_redirects"] is False

            async def send(_request):
                self.attempts += 1
                return Response(429 if self.attempts == 1 else 200)

            yield await kwargs["middlewares"][0](None, send)

    asyncio.run(
        fetch_mexc_json(
            cast(Any, Session()),
            "/api/v1/contract/ticker",
            lane="funding",
            budget=cast(Any, Budget()),
        )
    )
    assert events == [("acquire", "funding"), ("cooldown", 7), ("acquire", "funding")]


def test_central_http_budget_failure_does_not_attempt_fetch():
    from prep_watchdeck_market.sources.common import CatalogSourceError
    from prep_watchdeck_market.sources.mexc import fetch_mexc_json

    class Budget:
        async def acquire(self, **kwargs):
            raise MexcBudgetUnavailable()

    class Session:
        @asynccontextmanager
        async def get(self, *args, **kwargs):
            async def send(_request):
                raise AssertionError("HTTP started without shared admission")

            yield await kwargs["middlewares"][0](None, send)

    with pytest.raises(CatalogSourceError, match="MEXC public fetch failed"):
        asyncio.run(
            fetch_mexc_json(
                cast(Any, Session()), "/api/v1/contract/ticker", budget=cast(Any, Budget())
            )
        )
