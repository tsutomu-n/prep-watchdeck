"""Isolated native HTTP -> DB -> recovery artifact bridge for Browser E2E."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import aiohttp
import psycopg
from aiohttp import web
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from prep_watchdeck_market.candle_recovery import CandleRecovery, RecoveryWindowRequest
from prep_watchdeck_market.candle_recovery_state import CandleRecoveryState
from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.sources import candle_history


async def main() -> None:
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
    database = f"recovery_browser_{uuid4().hex}"
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            url = make_conninfo(source, dbname=database)
            now = datetime.now(UTC).replace(second=0, microsecond=0)
            start = now - timedelta(minutes=12)
            missing = start + timedelta(minutes=1)
            with psycopg.connect(url, autocommit=True) as connection:
                apply_migrations(connection)
                payload = connection.execute(
                    """
                    INSERT INTO raw_catalog_payloads (
                        venue, endpoint, source_kind, documentation_url, payload_hash,
                        observed_at, last_observed_at, payload
                    ) VALUES ('bitget', '/e2e/catalog', 'native_rest', NULL,
                              %s, %s, %s, %s) RETURNING raw_catalog_payload_id
                    """,
                    ("a" * 64, now, now, Jsonb({"symbol": "BTCUSDT"})),
                ).fetchone()
                assert payload is not None
                version = connection.execute(
                    """
                    INSERT INTO venue_instrument_versions (
                        venue, source_symbol, definition_hash, valid_from, active,
                        asset_class, market_type, base_asset, quote_asset, settle_asset,
                        quantity_unit, contract_multiplier, raw_definition,
                        raw_catalog_payload_id
                    ) VALUES ('bitget', 'BTCUSDT', %s, %s, true, 'crypto',
                              'linear_perpetual', 'BTC', 'USDT', 'USDT', 'base', 1,
                              '{}'::jsonb, %s) RETURNING venue_instrument_version_id
                    """,
                    ("b" * 64, start - timedelta(minutes=1), payload[0]),
                ).fetchone()
                assert version is not None and version[0] == 1
                for bucket in (start, start + timedelta(minutes=2)):
                    connection.execute(
                        """
                        INSERT INTO candle_1m (
                            venue_instrument_version_id, bucket_at, open_price,
                            high_price, low_price, close_price, finality, observed_at
                        ) VALUES (1, %s, 100, 102, 99, 101, 'confirmed', %s)
                        """,
                        (bucket, now),
                    )

                requests: list[dict[str, str]] = []

                async def history(request: web.Request) -> web.Response:
                    requests.append(dict(request.query))
                    return web.json_response(
                        {
                            "code": "00000",
                            "data": [
                                [
                                    str(int(missing.timestamp() * 1000)),
                                    "100",
                                    "102",
                                    "99",
                                    "101",
                                    "1",
                                    "101",
                                ]
                            ],
                        }
                    )

                application = web.Application()
                application.router.add_get("/history", history)
                runner = web.AppRunner(application)
                await runner.setup()
                site = web.TCPSite(runner, "127.0.0.1", 0)
                await site.start()
                try:
                    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
                    candle_history.BITGET_HISTORY_URL = f"http://127.0.0.1:{port}/history"  # type: ignore[bad-assignment]
                    candle_history.MIN_REQUEST_INTERVAL_SECONDS = 0.0
                    async with aiohttp.ClientSession() as session:
                        state = await CandleRecovery(url, root).run(
                            session,
                            RecoveryWindowRequest(start, start + timedelta(minutes=3)),
                            apply=True,
                            instrument_id="bitget:BTCUSDT",
                        )
                finally:
                    await runner.cleanup()
                assert state.execution == "succeeded"
                assert state.summary.missing_before == 1
                assert state.summary.inserted == 1
                assert state.summary.remaining == 0
                assert len(requests) == 1
                assert connection.execute(
                    "SELECT count(*) FROM candle_1m WHERE venue_instrument_version_id=1"
                ).fetchone() == (3,)
                artifact = root / "artifacts/candle-recovery-state.json"
                readback = CandleRecoveryState.model_validate_json(artifact.read_bytes())
                assert readback == state
                print(
                    json.dumps(
                        {
                            "runId": state.run_id,
                            "instrumentId": "bitget:BTCUSDT",
                            "versionId": 1,
                            "missingBefore": 1,
                            "inserted": 1,
                            "remaining": 0,
                        }
                    )
                )
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


if __name__ == "__main__":
    asyncio.run(main())
