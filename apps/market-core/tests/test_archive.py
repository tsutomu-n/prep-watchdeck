from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from prep_watchdeck_market.archive import archive_partition
from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.maintenance import _archive_dates
from prep_watchdeck_market.retention import (
    prune_archived_partition,
    prune_raw_market_history,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)
def test_archive_generation_readback_and_retention_are_fail_closed(tmp_path: Path) -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"archive_test_{uuid.uuid4().hex}"
    archive_root = tmp_path / "parquet"
    partition_date = date(2026, 8, 5)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            version_id = _seed_market_state(connection, partition_date)
            assert _archive_dates(
                connection,
                preferred_date=date(2026, 8, 13),
                today=now.date(),
            ) == (partition_date, date(2026, 8, 13))

            blocked = prune_archived_partition(
                connection,
                archive_root,
                dataset="market_state_1m",
                venue="bitget",
                partition_date=partition_date,
                now=now,
            )
            assert blocked.reason == "confirmed_manifest_missing"
            assert blocked.normalized_deleted == 0
            assert blocked.raw_deleted == 0

            first = archive_partition(
                connection,
                archive_root,
                dataset="market_state_1m",
                venue="bitget",
                partition_date=partition_date,
            )
            assert first.generation == 1
            assert first.status == "confirmed"
            assert first.row_count == 2
            assert first.unique_key_columns == (
                "venue_instrument_version_id",
                "bucket_at",
            )
            assert first.min_timestamp == datetime(2026, 8, 5, 0, 0, tzinfo=UTC)
            assert first.max_timestamp == datetime(2026, 8, 5, 0, 1, tzinfo=UTC)
            assert first.relative_path.startswith(
                "dataset=market_state_1m/venue=bitget/date=2026-08-05/"
            )
            first_path = archive_root / first.relative_path
            assert first_path.is_file()
            assert hashlib.sha256(first_path.read_bytes()).hexdigest() == first.sha256
            assert pl.read_parquet(first_path).height == 2
            assert len(list(first_path.parent.glob("*.parquet"))) == 1

            connection.execute(
                """
                    UPDATE market_state_1m
                    SET mark_price = 111
                    WHERE venue_instrument_version_id = %s
                      AND bucket_at = '2026-08-05 00:01:00+00'
                """,
                (version_id,),
            )
            second = archive_partition(
                connection,
                archive_root,
                dataset="market_state_1m",
                venue="bitget",
                partition_date=partition_date,
            )
            assert second.generation == 2
            assert second.status == "confirmed"
            assert second.sha256 != first.sha256
            latest = second
            for generation in range(3, 6):
                connection.execute(
                    """
                        UPDATE market_state_1m
                        SET mark_price = %s
                        WHERE venue_instrument_version_id = %s
                          AND bucket_at = '2026-08-05 00:01:00+00'
                    """,
                    (110 + generation, version_id),
                )
                latest = archive_partition(
                    connection,
                    archive_root,
                    dataset="market_state_1m",
                    venue="bitget",
                    partition_date=partition_date,
                )
                assert latest.generation == generation

            partition_root = (
                archive_root / "dataset=market_state_1m" / "venue=bitget" / "date=2026-08-05"
            )
            assert len(list(partition_root.rglob("*.parquet"))) == 4
            assert not first_path.exists()
            assert (archive_root / second.relative_path).is_file()
            assert connection.execute(
                """
                    SELECT generation, status, confirmed_at IS NOT NULL,
                           superseded_at IS NOT NULL
                    FROM archive_manifests
                    ORDER BY generation
                """
            ).fetchall() == [
                (1, "superseded", True, True),
                (2, "superseded", True, True),
                (3, "superseded", True, True),
                (4, "superseded", True, True),
                (5, "confirmed", True, False),
            ]

            late_observed_at = datetime.now(UTC)
            connection.execute(
                """
                    UPDATE market_state_1m
                    SET mark_price = 999, last_observed_at = %s
                    WHERE venue_instrument_version_id = %s
                      AND bucket_at = '2026-08-05 00:01:00+00'
                """,
                (late_observed_at, version_id),
            )
            stale_archive = prune_archived_partition(
                connection,
                archive_root,
                dataset="market_state_1m",
                venue="bitget",
                partition_date=partition_date,
                now=now,
            )
            assert stale_archive.reason == "archive_stale_late_correction"
            assert stale_archive.normalized_deleted == 0
            refreshed = archive_partition(
                connection,
                archive_root,
                dataset="market_state_1m",
                venue="bitget",
                partition_date=partition_date,
            )
            assert refreshed.generation == 6

            pruned = prune_archived_partition(
                connection,
                archive_root,
                dataset="market_state_1m",
                venue="bitget",
                partition_date=partition_date,
                now=now,
            )
            assert pruned.reason is None
            assert pruned.normalized_deleted == 2
            assert pruned.raw_deleted == 0
            assert not pruned.has_more
            assert connection.execute("SELECT count(*) FROM market_state_1m").fetchone() == (0,)
            raw_pruned = prune_raw_market_history(connection, now=now)
            assert raw_pruned.deleted == 3
            assert not raw_pruned.has_more
            raw_count = connection.execute(
                "SELECT count(*) FROM raw_market_observations"
            ).fetchone()
            assert raw_count == (0,)
        finally:
            connection.execute("RESET search_path")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def _seed_market_state(connection: psycopg.Connection[Any], partition_date: date) -> int:
    observed_at = datetime(2026, 8, 5, 0, 0, tzinfo=UTC)
    raw_definition = {"symbol": "BTCUSDT"}
    raw_catalog_id = connection.execute(
        """
            INSERT INTO raw_catalog_payloads (
                venue, endpoint, source_kind, documentation_url, payload_hash,
                observed_at, last_observed_at, payload
            )
            VALUES ('bitget', '/catalog', 'native_rest', 'https://example.invalid',
                    %s, %s, %s, %s)
            RETURNING raw_catalog_payload_id
        """,
        ("a" * 64, observed_at, observed_at, Jsonb(raw_definition)),
    ).fetchone()
    assert raw_catalog_id is not None
    version = connection.execute(
        """
            INSERT INTO venue_instrument_versions (
                venue, source_symbol, definition_hash, valid_from, active,
                asset_class, market_type, execution_model, base_asset, quote_asset,
                settle_asset, collateral_asset, quantity_unit, contract_multiplier,
                source_status, raw_definition, raw_catalog_payload_id
            )
            VALUES ('bitget', 'BTCUSDT', %s, %s, true, 'crypto', 'linear_perpetual',
                    'clob', 'BTC', 'USDT', 'USDT', 'USDT', 'base', 1, 'normal', %s, %s)
            RETURNING venue_instrument_version_id
        """,
        ("b" * 64, observed_at, Jsonb(raw_definition), int(raw_catalog_id[0])),
    ).fetchone()
    assert version is not None
    version_id = int(version[0])

    for minute, mark_price in ((0, 100), (1, 101)):
        bucket_at = datetime(2026, 8, 5, 0, minute, tzinfo=UTC)
        connection.execute(
            """
                INSERT INTO market_state_1m (
                    venue_instrument_version_id, bucket_at, status,
                    first_observed_at, last_observed_at, sample_count,
                    mark_price, reference_price_kind
                )
                VALUES (%s, %s, 'ready', %s, %s, 1, %s, 'none')
            """,
            (version_id, bucket_at, bucket_at, bucket_at, mark_price),
        )
        raw_payload = {"minute": minute, "markPrice": mark_price}
        connection.execute(
            """
                INSERT INTO raw_market_observations (
                    observed_date, venue, source_symbol, dataset, observed_at,
                    payload_hash, payload
                )
                VALUES (%s, 'bitget', 'BTCUSDT', 'l1_all_market', %s, %s, %s)
            """,
            (
                partition_date,
                bucket_at,
                hashlib.sha256(str(raw_payload).encode()).hexdigest(),
                Jsonb(raw_payload),
            ),
        )
    connection.execute(
        """
            INSERT INTO raw_market_observations (
                observed_date, venue, source_symbol, dataset, observed_at,
                payload_hash, payload
            )
            VALUES (%s, 'bitget', 'BTCUSDT', 'candle_stream', %s, %s, %s)
        """,
        (
            partition_date,
            observed_at,
            "c" * 64,
            Jsonb({"kind": "not-covered-by-market-state-archive"}),
        ),
    )
    return version_id
