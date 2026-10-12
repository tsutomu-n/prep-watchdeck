from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

import prep_watchdeck_market.fixture_bundle as fixture_module
from prep_watchdeck_market.bundle_files import BundleError
from prep_watchdeck_market.candle_audit import load_snapshot
from prep_watchdeck_market.fixture_bundle import export_fixture, verify_fixture

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.usefixtures("isolated_feature_database")


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires isolated TEST_DATABASE_URL")
def test_fixture_export_round_trip_and_tamper_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert TEST_DATABASE_URL is not None
    symbol = f"PWTEST{uuid4().hex[:8].upper()}USDT"
    instrument_id = f"bitget:{symbol}"
    digest = uuid4().hex * 2
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    since = now - timedelta(minutes=15)
    until = now - timedelta(minutes=8)
    version_id: int | None = None
    payload_id: int | None = None
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        try:
            payload_row = connection.execute(
                """
                INSERT INTO raw_catalog_payloads (
                    venue, endpoint, source_kind, documentation_url,
                    payload_hash, observed_at, last_observed_at, payload
                ) VALUES ('bitget', '/catalog', 'native_rest', 'https://example.invalid/catalog',
                          %s, %s, %s, %s)
                RETURNING raw_catalog_payload_id
                """,
                (digest, now, now, Jsonb({"symbol": symbol})),
            ).fetchone()
            assert payload_row is not None
            payload_id = payload_row[0]
            version_row = connection.execute(
                """
                INSERT INTO venue_instrument_versions (
                    venue, source_symbol, definition_hash, valid_from, active,
                    asset_class, market_type, base_asset, quote_asset, settle_asset,
                    quantity_unit, contract_multiplier, raw_definition, raw_catalog_payload_id
                ) VALUES ('bitget', %s, %s, %s, true, 'crypto', 'linear_perpetual',
                          'PWTEST', 'USDT', 'USDT', 'base', 1, '{}'::jsonb, %s)
                RETURNING venue_instrument_version_id
                """,
                (symbol, digest, since - timedelta(minutes=1), payload_id),
            ).fetchone()
            assert version_row is not None
            version_id = version_row[0]
            for index in (0, 2):
                connection.execute(
                    """
                    INSERT INTO candle_1m (
                        venue_instrument_version_id, bucket_at, open_price, high_price,
                        low_price, close_price, volume_base, volume_notional,
                        trade_count, finality, observed_at
                    ) VALUES (%s, %s, 100.125, 102.25, 99.5, 101.75,
                              5.125, NULL, NULL, 'confirmed', %s)
                    """,
                    (version_id, since + timedelta(minutes=index), now),
                )
            connection.execute(
                """
                INSERT INTO market_state_1m (
                    venue_instrument_version_id, bucket_at, status, first_observed_at,
                    last_observed_at, sample_count, mark_price, open_interest_raw,
                    open_interest_raw_unit, open_interest_base, open_interest_notional
                ) VALUES (%s, %s, 'partial', %s, %s, 1, 100.5, 12.25, 'base', 12.25, 1231.125)
                """,
                (version_id, since, now, now),
            )
            connection.execute(
                """
                INSERT INTO funding_events (
                    venue_instrument_version_id, funding_at, funding_rate_raw, observed_at
                ) VALUES (%s, %s, 0.0001, %s)
                """,
                (version_id, since + timedelta(minutes=2), now),
            )

            path, manifest = export_fixture(
                TEST_DATABASE_URL,
                tmp_path / "state",
                tmp_path / "bundles",
                instrument_id=instrument_id,
                version_id=version_id,
                since=since,
                until=until,
                evidence_kind="synthetic",
            )
            assert manifest.execution == "completed"
            assert verify_fixture(path) == manifest
            assert [(item.name, item.availability, item.rows) for item in manifest.datasets] == [
                ("instrument", "included", 1),
                ("market-state", "included", 1),
                ("candles-1m", "included", 2),
                ("funding", "included", 1),
                ("recovery", "unavailable", None),
                ("audit", "not_requested", None),
            ]
            snapshot = load_snapshot(
                path / "candles-1m.snapshot.json", start=since, end=until, as_of=now
            )
            assert snapshot.findings == ()
            assert (
                snapshot.rows[since].open_price
                == snapshot.rows[since + timedelta(minutes=2)].open_price
            )
            cli_env = os.environ.copy()
            cli_env["PREP_WATCHDECK_MARKET_DATABASE_URL"] = TEST_DATABASE_URL
            cli_env["PREP_WATCHDECK_MARKET_STATE_DIR"] = str(tmp_path / "state")
            command = str(Path(sys.executable).with_name("watchdeck-market"))
            exported = subprocess.run(
                [
                    command,
                    "export-fixture",
                    "--instrument",
                    instrument_id,
                    "--version",
                    str(version_id),
                    "--since",
                    since.isoformat(),
                    "--until",
                    until.isoformat(),
                    "--output-dir",
                    str(tmp_path / "cli-bundles"),
                    "--evidence-kind",
                    "synthetic",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=cli_env,
                timeout=30,
            )
            assert exported.returncode == 0, exported.stdout
            cli_paths = list((tmp_path / "cli-bundles").iterdir())
            assert len(cli_paths) == 1
            verified = subprocess.run(
                [command, "verify-fixture", "--bundle", str(cli_paths[0])],
                check=False,
                capture_output=True,
                text=True,
                env=cli_env,
                timeout=30,
            )
            assert verified.returncode == 0, verified.stdout
            original_query = fixture_module._optional_query_rows

            injected = False

            def concurrent_funding_insert(read_connection, query, params):
                nonlocal injected
                if "FROM market_state_1m" in query and not injected:
                    injected = True
                    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as writer:
                        writer.execute(
                            "INSERT INTO funding_events "
                            "(venue_instrument_version_id, funding_at, "
                            "funding_rate_raw, observed_at) "
                            "VALUES (%s, %s, 0.0002, %s)",
                            (version_id, since + timedelta(minutes=3), now),
                        )
                return original_query(read_connection, query, params)

            with monkeypatch.context() as patch:
                patch.setattr(fixture_module, "_optional_query_rows", concurrent_funding_insert)
                consistent_path, consistent = export_fixture(
                    TEST_DATABASE_URL,
                    tmp_path / "state",
                    tmp_path / "concurrent-bundles",
                    instrument_id=instrument_id,
                    version_id=version_id,
                    since=since,
                    until=until,
                    evidence_kind="synthetic",
                )
            assert injected
            assert consistent.datasets[3].rows == 1
            assert verify_fixture(consistent_path) == consistent
            assert connection.execute(
                "SELECT count(*) FROM funding_events WHERE venue_instrument_version_id=%s",
                (version_id,),
            ).fetchone() == (2,)

            def fail_funding_query(connection, query, params):
                if "FROM funding_events" in query:
                    return original_query(connection, "SELECT * FROM missing_fixture_table", ())
                return original_query(connection, query, params)

            with monkeypatch.context() as patch:
                patch.setattr(fixture_module, "_optional_query_rows", fail_funding_query)
                partial_path, partial = export_fixture(
                    TEST_DATABASE_URL,
                    tmp_path / "state",
                    tmp_path / "partial-bundles",
                    instrument_id=instrument_id,
                    version_id=version_id,
                    since=since,
                    until=until,
                    evidence_kind="synthetic",
                )
            assert partial.execution == "partial"
            assert partial.datasets[3].name == "funding"
            assert partial.datasets[3].availability == "unavailable"
            assert verify_fixture(partial_path) == partial
            candle_path = path / "candles-1m.snapshot.json"
            candle_path.write_bytes(candle_path.read_bytes().replace(b"100.125", b"100.126", 1))
            with pytest.raises(BundleError, match="fixture_hash_mismatch"):
                verify_fixture(path)
        finally:
            if version_id is not None:
                connection.execute(
                    "DELETE FROM funding_events WHERE venue_instrument_version_id = %s",
                    (version_id,),
                )
                connection.execute(
                    "DELETE FROM market_state_1m WHERE venue_instrument_version_id = %s",
                    (version_id,),
                )
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


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires isolated TEST_DATABASE_URL")
def test_hyperliquid_fixture_export_retains_finalization_for_audit_and_legacy_unknown(
    tmp_path: Path,
) -> None:
    import json
    from dataclasses import replace

    from prep_watchdeck_market.candle_store import upsert_candles
    from prep_watchdeck_market.sources.hyperliquid_candles import HyperliquidCandleFinalizer

    assert TEST_DATABASE_URL is not None
    since = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=10)
    until = since + timedelta(minutes=3)
    symbol = f"PWTEST{uuid4().hex[:8].upper()}"
    digest = uuid4().hex * 2
    finalizer = HyperliquidCandleFinalizer()
    finalizer.ingest(
        {
            "channel": "candle",
            "data": {
                "s": symbol,
                "i": "1m",
                "t": int(since.timestamp() * 1000),
                "T": int((since + timedelta(minutes=1)).timestamp() * 1000) - 1,
                "o": "100",
                "h": "102",
                "l": "99",
                "c": "101",
                "v": "5",
                "n": 3,
            },
        },
        observed_at=since + timedelta(seconds=30),
    )
    early = finalizer.finalize(now=since + timedelta(minutes=1, seconds=9))[0]
    late = replace(
        early,
        bucket_start=since + timedelta(minutes=1),
        source_at=since + timedelta(minutes=2),
        observed_at=since + timedelta(minutes=1, seconds=30),
        finalized_at=until + timedelta(seconds=1),
    )
    unknown = replace(
        early,
        bucket_start=since + timedelta(minutes=2),
        source_at=until,
        observed_at=since + timedelta(minutes=2, seconds=30),
        finalized_at=None,
    )
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        payload_row = connection.execute(
            """
            INSERT INTO raw_catalog_payloads (
                venue, endpoint, source_kind, documentation_url,
                payload_hash, observed_at, last_observed_at, payload
            ) VALUES ('hyperliquid', '/info', 'native_rest',
                      'https://example.invalid/catalog', %s, %s, %s, '{}')
            RETURNING raw_catalog_payload_id
            """,
            (digest, since, since),
        ).fetchone()
        assert payload_row is not None
        version_row = connection.execute(
            """
            INSERT INTO venue_instrument_versions (
                venue, source_symbol, definition_hash, valid_from, active,
                asset_class, market_type, base_asset, quote_asset, settle_asset,
                quantity_unit, contract_multiplier, raw_definition, raw_catalog_payload_id
            ) VALUES ('hyperliquid', %s, %s, %s, true, 'crypto', 'linear_perpetual',
                      'PWTEST', 'USDC', 'USDC', 'base', 1, '{}', %s)
            RETURNING venue_instrument_version_id
            """,
            (symbol, digest, since - timedelta(minutes=1), payload_row[0]),
        ).fetchone()
        assert version_row is not None
        assert upsert_candles(connection, (early, late, unknown)).stored == 3

    path, manifest = export_fixture(
        TEST_DATABASE_URL,
        tmp_path / "state",
        tmp_path / "exports",
        instrument_id=f"hyperliquid:{symbol}",
        version_id=version_row[0],
        since=since,
        until=until,
        evidence_kind="synthetic",
    )
    assert manifest.capture.point_in_time_replay is False
    assert verify_fixture(path) == manifest
    snapshot_path = path / "candles-1m.snapshot.json"
    payload = json.loads(snapshot_path.read_bytes())
    assert early.finalized_at is not None
    assert late.finalized_at is not None
    assert payload["records"][0]["finalized_at"] == fixture_module._iso(early.finalized_at)
    assert payload["records"][1]["finalized_at"] == fixture_module._iso(late.finalized_at)
    assert payload["records"][2]["finalized_at"] is None
    audited = load_snapshot(snapshot_path, start=since, end=until, as_of=until)
    assert audited.rows[since].observed_at == early.observed_at
    assert audited.rows[since].finalized_at == early.finalized_at
    assert [finding["reason"] for finding in audited.findings] == [
        "unavailable_at_as_of",
        "observed_before_close",
    ]
    # Old fixture bytes stay untouched. An isolated old-format copy remains unknown.
    payload["records"][0].pop("finalized_at")
    legacy_path = tmp_path / "legacy-without-finalization.json"
    legacy_path.write_text(json.dumps(payload))
    legacy = load_snapshot(legacy_path, start=since, end=until, as_of=until)
    assert since not in legacy.rows
    assert legacy.findings[0]["reason"] == "observed_before_close"
    assert verify_fixture(path) == manifest
