from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from prep_watchdeck_market.bundle_files import BundleError

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.usefixtures("isolated_feature_database")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:secret@127.0.0.1:5432/other",
        "postgresql://prep_watchdeck_market:secret@remote.invalid:55432/prep_watchdeck_market",
        "postgresql://prep_watchdeck_market:secret@127.0.0.1:55432/prep_watchdeck_market?options=bad",
    ],
)
def test_reader_refuses_other_database_targets_before_connect(url: str) -> None:
    from prep_watchdeck_market.research.reader import read_observation

    now = datetime.now(UTC).replace(second=0, microsecond=0)
    with pytest.raises(BundleError, match="research_database_target_invalid"):
        read_observation(
            url,
            instrument_id="bitget:TESTUSDT",
            version_id=1,
            since=now - timedelta(minutes=1),
            until=now,
        )


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="requires isolated TEST_DATABASE_URL")
def test_reader_keeps_one_read_only_snapshot_and_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prep_watchdeck_market.research import reader
    from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
    from prep_watchdeck_market.research.snapshot import verify_snapshot

    assert TEST_DATABASE_URL is not None
    symbol = f"R{uuid4().hex[:8].upper()}USDT"
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    start = now - timedelta(minutes=1)
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        raw_row = connection.execute(
            """INSERT INTO raw_catalog_payloads
               (venue,endpoint,source_kind,payload_hash,observed_at,last_observed_at,payload)
               VALUES ('bitget','/catalog','native_rest',%s,%s,%s,%s)
               RETURNING raw_catalog_payload_id""",
            (
                "b" * 64,
                start - timedelta(days=1),
                start - timedelta(days=1),
                Jsonb({"symbol": symbol}),
            ),
        ).fetchone()
        assert raw_row is not None
        raw = raw_row[0]
        version_row = connection.execute(
            """INSERT INTO venue_instrument_versions
               (venue,source_symbol,definition_hash,valid_from,active,asset_class,
                market_type,base_asset,quote_asset,settle_asset,quantity_unit,
                contract_multiplier,raw_definition,raw_catalog_payload_id)
               VALUES ('bitget',%s,%s,%s,true,'crypto','linear_perpetual',
                       'TEST','USDT','USDT','base',1,'{}',%s)
               RETURNING venue_instrument_version_id""",
            (symbol, "a" * 64, start - timedelta(days=1), raw),
        ).fetchone()
        assert version_row is not None
        version = version_row[0]
        connection.execute(
            """INSERT INTO candle_1m (venue_instrument_version_id,bucket_at,open_price,
               high_price,low_price,close_price,volume_base,volume_notional,finality,observed_at)
               VALUES (%s,%s,100,101,99,101,10,1000,'confirmed',%s)""",
            (version, start, now),
        )
        connection.execute(
            """INSERT INTO market_state_1m
               (venue_instrument_version_id,bucket_at,status,first_observed_at,last_observed_at,
                sample_count,mark_price,open_interest_raw,open_interest_raw_unit)
               VALUES (%s,%s,'ready',%s,%s,1,101,20,'base')""",
            (version, start, start, start),
        )
        connection.execute(
            """INSERT INTO market_groups (group_id,base_asset,created_at,updated_at)
               VALUES (%s,'TEST',%s,%s)""",
            (symbol, start - timedelta(days=1), start - timedelta(days=1)),
        )
        connection.execute(
            "INSERT INTO group_memberships "
            "(group_id,venue_instrument_version_id,mapping_method,valid_from) "
            "VALUES (%s,%s,'exact',%s)",
            (symbol, version, start - timedelta(days=1)),
        )
        connection.execute(
            "INSERT INTO capabilities (venue,capability,available,source_kind,observed_at) "
            "VALUES ('bitget','research_test',true,'native_rest',%s)",
            (start,),
        )

    rows_original = reader._rows
    inserted = False

    def concurrent_change(connection, query, params):
        nonlocal inserted
        if "FROM candle_1m" in query and not inserted:
            inserted = True
            with (
                pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
                connection.transaction(),
            ):
                connection.execute("UPDATE candle_1m SET close_price=100 WHERE false")
            with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as writer:
                writer.execute(
                    "UPDATE market_state_1m SET open_interest_raw=999 "
                    "WHERE venue_instrument_version_id=%s",
                    (version,),
                )
        return rows_original(connection, query, params)

    monkeypatch.setattr(reader, "_rows", concurrent_change)
    result = reader.read_observation(
        TEST_DATABASE_URL,
        instrument_id=f"bitget:{symbol}",
        version_id=version,
        since=start,
        until=now,
    )
    assert result.payload.states[0]["open_interest_raw"] == "20"
    assert result.payload.groups[0]["group_id"] == symbol
    assert result.payload.capabilities[0]["capability"] == "research_test"
    assert result.read_completed_at >= result.payload.snapshot_at
    with ObservationJournal(tmp_path / "journal") as journal:
        journal.record(
            result.payload,
            read_started_at=result.read_started_at,
            read_completed_at=result.read_completed_at,
            elapsed_seconds=result.elapsed_seconds,
        )
    snapshot = verify_snapshot(export_snapshot(tmp_path / "journal", tmp_path / "snapshots"))
    assert snapshot.replay_valid
    assert snapshot.observed_evidence
