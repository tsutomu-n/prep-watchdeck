from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from aiohttp import ClientSession, web
from psycopg.types.json import Jsonb

from prep_watchdeck_market.bundle_files import json_bytes, sha256
from prep_watchdeck_market.candle_audit import load_snapshot
from prep_watchdeck_market.candle_audit_artifacts import AuditRequest
from prep_watchdeck_market.candle_audit_publication import execute_and_publish
from prep_watchdeck_market.candle_recovery_state import CandleRecoveryState
from prep_watchdeck_market.fixture_bundle import export_fixture, verify_fixture
from prep_watchdeck_market.reference_openmarket import (
    OpenMarketClient,
    ReferenceError,
    reference_markets,
    reference_snapshot,
    verify_reference_bundle,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.usefixtures("isolated_feature_database")


def test_openmarket_transport_auth_rate_and_secret_boundary() -> None:
    async def exercise() -> None:
        seen: list[tuple[str, dict[str, str], str | None]] = []

        async def handler(request: web.Request) -> web.Response:
            seen.append(
                (request.path, dict(request.query), request.headers.get("X-OpenMarket-Key"))
            )
            if request.path == "/unauthorized":
                return web.Response(status=401, text="provider private response")
            if request.path == "/limited":
                return web.Response(status=429, headers={"Retry-After": "61"})
            return web.json_response(
                {"symbols": []},
                headers={
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + 120),
                },
            )

        application = web.Application()
        application.router.add_get("/{tail:.*}", handler)
        runner = web.AppRunner(application)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        try:
            port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
            base = f"http://127.0.0.1:{port}"
            async with ClientSession() as session:
                client = OpenMarketClient(
                    session, "SYNTHETIC_SECRET", base_url=base, min_interval=0
                )
                data, _ = await client.get("/ok", {"pageOffset": "0"})
                assert data == b'{"symbols": []}'
                assert seen == [("/ok", {"pageOffset": "0"}, "SYNTHETIC_SECRET")]
                with pytest.raises(ReferenceError, match="reference_rate_limited") as limited:
                    await client.get("/ok", {})
                assert "SYNTHETIC_SECRET" not in str(limited.value)
                assert len(seen) == 1  # local weight guard prevents an extra request
                auth_client = OpenMarketClient(
                    session, "SYNTHETIC_SECRET", base_url=base, min_interval=0
                )
                with pytest.raises(ReferenceError, match="reference_auth_rejected") as auth:
                    await auth_client.get("/unauthorized", {})
                assert "provider private response" not in str(auth.value)
                assert "SYNTHETIC_SECRET" not in str(auth.value)
                with pytest.raises(ReferenceError, match="reference_rate_limited"):
                    await auth_client.get("/limited", {})
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


class FakeOpenMarket:
    def __init__(self, metadata: bytes, points: bytes) -> None:
        self.metadata = metadata
        self.points = points
        self.queries: list[tuple[str, dict[str, str]]] = []

    async def get(self, path: str, params: dict[str, str]) -> tuple[bytes, datetime]:
        self.queries.append((path, params))
        return (self.metadata if path == "/v1/markets" else self.points), datetime.now(UTC)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires isolated TEST_DATABASE_URL")
def test_reference_lookup_snapshot_audit_input_and_partial(tmp_path: Path) -> None:
    assert TEST_DATABASE_URL is not None
    symbol = f"PWREF{uuid4().hex[:8].upper()}USDT"
    digest = uuid4().hex * 2
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    since = now - timedelta(minutes=20)
    until = since + timedelta(minutes=6)
    payload_id: int | None = None
    version_id: int | None = None
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        try:
            row = connection.execute(
                """
                INSERT INTO raw_catalog_payloads (
                    venue, endpoint, source_kind, documentation_url,
                    payload_hash, observed_at, last_observed_at, payload
                ) VALUES ('bitget', '/catalog', 'native_rest', 'https://example.invalid',
                          %s, %s, %s, %s) RETURNING raw_catalog_payload_id
                """,
                (digest, now, now, Jsonb({"symbol": symbol})),
            ).fetchone()
            assert row is not None
            payload_id = row[0]
            row = connection.execute(
                """
                INSERT INTO venue_instrument_versions (
                    venue, source_symbol, definition_hash, valid_from, active, asset_class,
                    market_type, base_asset, quote_asset, settle_asset, quantity_unit,
                    contract_multiplier, raw_definition, raw_catalog_payload_id
                ) VALUES ('bitget', %s, %s, %s, true, 'crypto', 'linear_perpetual',
                          'PWREF', 'USDT', 'USDT', 'base', 1, '{}'::jsonb, %s)
                RETURNING venue_instrument_version_id
                """,
                (symbol, digest, since - timedelta(minutes=1), payload_id),
            ).fetchone()
            assert row is not None
            version_id = row[0]
            for index in range(6):
                connection.execute(
                    """
                    INSERT INTO candle_1m (
                        venue_instrument_version_id, bucket_at, open_price, high_price,
                        low_price, close_price, volume_base, finality, observed_at
                    ) VALUES (%s, %s, 100.125, 102.25, 99.5, 101.75, 5.125,
                              'confirmed', %s)
                    """,
                    (version_id, since + timedelta(minutes=index), now),
                )
            metadata = json_bytes(
                {
                    "symbols": [
                        {
                            "exchange": "BITGET",
                            "rawSymbol": symbol,
                            "coin": "PWREF",
                            "category": "PERPETUAL",
                            "normalizedSymbol": "PWREF-USDT",
                            "availableSince": {"s": int((since - timedelta(hours=1)).timestamp())},
                        }
                    ],
                    "nextOffset": 1,
                }
            )
            provider = {
                "exchange": "BITGET",
                "rawSymbol": symbol,
                "coin": "PWREF",
                "category": "PERPETUAL",
                "interval": "MINUTE",
                "type": "TRADE_SIDE_AGNOSTIC_AGG",
            }

            def points(count: int) -> bytes:
                return json_bytes(
                    {
                        "series": [
                            {
                                "id": provider,
                                "points": [
                                    {
                                        "Point": {
                                            "timestamp": {
                                                "s": int(
                                                    (since + timedelta(minutes=index)).timestamp()
                                                )
                                            },
                                            "open": 100.125,
                                            "high": 102.25,
                                            "low": 99.5,
                                            "close": 101.75,
                                            "volume": 5.125,
                                            "firstTimestamp": {
                                                "s": int(
                                                    (since + timedelta(minutes=index)).timestamp()
                                                )
                                                + 1
                                            },
                                            "lastTimestamp": {
                                                "s": int(
                                                    (since + timedelta(minutes=index)).timestamp()
                                                )
                                                + 58
                                            },
                                        }
                                    }
                                    for index in range(count)
                                ],
                            }
                        ]
                    }
                )

            mapping = {
                "schemaVersion": 1,
                "mappingId": uuid4().hex,
                "evidenceKind": "synthetic",
                "checkedAt": (now - timedelta(minutes=1)).isoformat(),
                "checkedBy": "isolated-test",
                "native": {
                    "venue": "bitget",
                    "source_symbol": symbol,
                    "venue_instrument_version_id": version_id,
                    "definition_sha256": digest,
                    "base_asset": "PWREF",
                    "quote_asset": "USDT",
                    "settle_asset": "USDT",
                    "price_kind": "trade",
                    "interval_seconds": 60,
                },
                "provider": provider,
                "metadataSha256": sha256(metadata),
                "rationale": "isolated synthetic exact contract",
            }
            mapping_path = tmp_path / "mapping.json"
            mapping_path.write_bytes(json_bytes(mapping))
            client = FakeOpenMarket(metadata, points(6))
            lookup_file = tmp_path / "candidates.json"
            lookup = asyncio.run(
                reference_markets(
                    TEST_DATABASE_URL,
                    cast(OpenMarketClient, client),
                    venue="bitget",
                    symbol=symbol,
                    output=lookup_file,
                )
            )
            assert lookup["metadataComplete"] is True
            assert len(lookup["candidates"]) == 1
            path, receipt = asyncio.run(
                reference_snapshot(
                    TEST_DATABASE_URL,
                    tmp_path / "state",
                    cast(OpenMarketClient, client),
                    mapping_path=mapping_path,
                    since=since,
                    until=until,
                    output_dir=tmp_path / "runs",
                )
            )
            assert receipt.execution == "completed"
            assert receipt.counts.valid_bars == 6
            assert verify_reference_bundle(path) == receipt
            snapshot = load_snapshot(
                path / "reference.snapshot.json",
                start=since,
                end=until,
                as_of=receipt.finished_at,
            )
            assert not snapshot.findings
            assert snapshot.rows[since].open_price.as_tuple().exponent == -3
            point_query = next(params for route, params in client.queries if route == "/v1/points")
            assert point_query == {
                "type": "TRADE_SIDE_AGNOSTIC_AGG",
                "exchange": "BITGET",
                "rawSymbol": symbol,
                "interval": "MINUTE",
                "from": str(int(since.timestamp())),
                "period": "360",
                "gapfill": "false",
            }
            fixture_path, fixture_manifest = export_fixture(
                TEST_DATABASE_URL,
                tmp_path / "state",
                tmp_path / "fixtures",
                instrument_id=f"bitget:{symbol}",
                version_id=version_id,
                since=since,
                until=until,
                evidence_kind="synthetic",
            )
            request = AuditRequest.model_validate(
                {
                    "schemaVersion": 1,
                    "target": {
                        "venueInstrumentId": f"bitget:{symbol}",
                        "venueInstrumentVersionId": version_id,
                    },
                    "leftPath": str(
                        (fixture_path / "candles-1m.snapshot.json").relative_to(tmp_path)
                    ),
                    "rightPath": str((path / "reference.snapshot.json").relative_to(tmp_path)),
                    "leftSource": {
                        "sourceId": "prep-db-snapshot",
                        "label": "隔離DB保存足",
                        "snapshotCreatedAt": fixture_manifest.capture.finished_at.isoformat(),
                    },
                    "rightSource": {
                        "sourceId": "openmarket-route",
                        "label": "合成OpenMarket経路",
                        "snapshotCreatedAt": receipt.finished_at.isoformat(),
                    },
                    "comparisonKind": "acquisition_routes",
                    "evidenceKind": "synthetic",
                    "windowStart": since.isoformat(),
                    "windowEnd": until.isoformat(),
                    "dataAsOf": datetime.now(UTC).isoformat(),
                    "returnMinutes": 5,
                    "compareVolumeBase": True,
                    "tolerances": {
                        "priceAbsTol": "0",
                        "priceRelTol": "0",
                        "volumeAbsTol": "0",
                        "volumeRelTol": "0",
                        "returnTolBps": "0",
                    },
                }
            )
            request_path = tmp_path / "audit-request.json"
            request_path.write_bytes(json_bytes(request.model_dump(mode="json", by_alias=True)))
            audit = execute_and_publish(
                request, request_path=request_path, state_dir=tmp_path / "state"
            )
            assert audit.execution == "completed"
            assert audit.outcome == "match"
            assert audit.comparison_kind == "acquisition_routes"
            assert (tmp_path / "state" / "artifacts" / "candle-audit-index.json").exists()
            recovery_at = datetime.now(UTC).isoformat()
            recovery = CandleRecoveryState.model_validate(
                {
                    "schemaVersion": 1,
                    "runId": uuid4().hex,
                    "generatedAt": recovery_at,
                    "startedAt": recovery_at,
                    "finishedAt": recovery_at,
                    "execution": "succeeded",
                    "trigger": "manual",
                    "window": {
                        "start": since.isoformat(),
                        "end": until.isoformat(),
                        "graceSeconds": 180,
                    },
                    "summary": {
                        "targetCount": 1,
                        "scannedTargetCount": 1,
                        "httpRequests": 0,
                        "missingBefore": 0,
                        "inserted": 0,
                        "newlyPresent": 0,
                        "remaining": 0,
                        "failedTargets": 0,
                        "deferredTargets": 0,
                    },
                    "details": [
                        {
                            "target": {
                                "venueInstrumentId": f"bitget:{symbol}",
                                "venueInstrumentVersionId": version_id,
                                "definitionHash": digest,
                            },
                            "missingBefore": 0,
                            "inserted": 0,
                            "remaining": 0,
                            "errorCode": None,
                        }
                    ],
                    "detailsTruncated": False,
                    "errorCode": None,
                }
            )
            (tmp_path / "state" / "artifacts" / "candle-recovery-state.json").write_bytes(
                json_bytes(recovery.model_dump(mode="json", by_alias=True))
            )
            attached_path, attached = export_fixture(
                TEST_DATABASE_URL,
                tmp_path / "state",
                tmp_path / "attached-fixtures",
                instrument_id=f"bitget:{symbol}",
                version_id=version_id,
                since=since,
                until=until,
                audit_run=audit.run_id,
                evidence_kind="synthetic",
            )
            assert attached.execution == "completed"
            assert [entry.availability for entry in attached.datasets[-2:]] == [
                "included",
                "included",
            ]
            assert verify_fixture(attached_path) == attached
            client.points = points(5)
            partial_path, partial = asyncio.run(
                reference_snapshot(
                    TEST_DATABASE_URL,
                    tmp_path / "state",
                    cast(OpenMarketClient, client),
                    mapping_path=mapping_path,
                    since=since,
                    until=until,
                    output_dir=tmp_path / "runs",
                )
            )
            assert partial.execution == "partial"
            assert partial.counts.missing_bars == 1
            assert verify_reference_bundle(partial_path) == partial
            client.points = points(0)
            empty_path, empty = asyncio.run(
                reference_snapshot(
                    TEST_DATABASE_URL,
                    tmp_path / "state",
                    cast(OpenMarketClient, client),
                    mapping_path=mapping_path,
                    since=since,
                    until=until,
                    output_dir=tmp_path / "runs",
                )
            )
            assert empty.execution == "partial"
            assert empty.counts.valid_bars == 0
            assert empty.counts.missing_bars == 6
            assert verify_reference_bundle(empty_path) == empty
            mapping["provider"]["exchange"] = "HYPERLIQUID"
            mapping_path.write_bytes(json_bytes(mapping))
            with pytest.raises(ReferenceError, match="reference_mapping_invalid"):
                asyncio.run(
                    reference_snapshot(
                        TEST_DATABASE_URL,
                        tmp_path / "state",
                        cast(OpenMarketClient, client),
                        mapping_path=mapping_path,
                        since=since,
                        until=until,
                        output_dir=tmp_path / "runs",
                    )
                )
        finally:
            if version_id is not None:
                connection.execute(
                    "DELETE FROM candle_1m WHERE venue_instrument_version_id = %s",
                    (version_id,),
                )
                connection.execute(
                    "DELETE FROM venue_instrument_versions WHERE venue_instrument_version_id = %s",
                    (version_id,),
                )
            if payload_id is not None:
                connection.execute(
                    "DELETE FROM raw_catalog_payloads WHERE raw_catalog_payload_id = %s",
                    (payload_id,),
                )
