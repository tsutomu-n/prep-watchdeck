from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from prep_watchdeck_market.database import (
    MigrationError,
    apply_migrations,
    discover_migrations,
    migration_digest,
)


def test_builtin_migration_has_required_tables_and_stable_hash() -> None:
    migrations = discover_migrations()

    assert [migration.version for migration in migrations] == [1, 2, 3, 4]
    migration = migrations[0]
    assert migration.name == "initial_schema"
    assert migrations[1].name == "catalog_identity"
    assert migrations[2].name == "market_cycle_guards"
    assert migrations[3].name == "selected_market"
    assert migration.checksum == hashlib.sha256(migration.path.read_bytes()).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", migration.checksum)
    assert re.fullmatch(r"[0-9a-f]{64}", migration_digest(migrations))

    required_tables = {
        "collector_runs",
        "raw_catalog_payloads",
        "venue_instrument_versions",
        "capabilities",
        "market_groups",
        "group_memberships",
        "latest_market_state",
        "raw_market_observations",
        "market_state_1m",
        "candle_1m",
        "funding_events",
        "archive_manifests",
        "selected_raw_observations",
        "catalog_exclusions",
        "identity_resolutions",
        "selected_group_leases",
        "selected_depth_levels",
        "selected_trades",
    }
    normalized_sql = " ".join("\n".join(item.sql for item in migrations).lower().split())
    for table in required_tables:
        assert f"create table {table}" in normalized_sql


def test_discover_migrations_orders_files_and_rejects_changed_history(tmp_path: Path) -> None:
    first_path = tmp_path / "0001_first.sql"
    second_path = tmp_path / "0002_second.sql"
    second_path.write_text("SELECT 2;\n", encoding="utf-8")
    first_path.write_text("SELECT 1;\n", encoding="utf-8")

    migrations = discover_migrations(tmp_path)

    assert [migration.version for migration in migrations] == [1, 2]
    initial_digest = migration_digest(migrations)
    second_path.write_text("SELECT 3;\n", encoding="utf-8")
    assert migration_digest(discover_migrations(tmp_path)) != initial_digest

    (tmp_path / "0002_duplicate.sql").write_text("SELECT 4;\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="duplicate migration version 2"):
        discover_migrations(tmp_path)


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)
def test_migration_is_idempotent_and_enforces_catalog_scd2_contract() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"market_core_test_{uuid.uuid4().hex}"

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            first = apply_migrations(connection)
            second = apply_migrations(connection)

            assert first.applied == (1, 2, 3, 4)
            assert first.current_version == 4
            assert first.pending == 0
            assert second.applied == ()
            assert second.current_version == 4
            assert second.pending == 0
            assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone() == (4,)

            catalog_observed_at = datetime.now(UTC)
            payload_id = connection.execute(
                """
                INSERT INTO raw_catalog_payloads (
                    venue, endpoint, source_kind, documentation_url,
                    payload_hash, observed_at, last_observed_at, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING raw_catalog_payload_id
                """,
                (
                    "bitget",
                    "/catalog",
                    "native_rest",
                    "https://example.invalid/catalog",
                    "a" * 64,
                    catalog_observed_at,
                    catalog_observed_at,
                    Jsonb({"symbol": "BTCUSDT"}),
                ),
            ).fetchone()
            assert payload_id is not None

            with pytest.raises(UniqueViolation):
                connection.execute(
                    """
                    INSERT INTO raw_catalog_payloads (
                        venue, endpoint, source_kind, documentation_url,
                        payload_hash, observed_at, last_observed_at, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        "bitget",
                        "/catalog",
                        "native_rest",
                        "https://example.invalid/catalog",
                        "a" * 64,
                        catalog_observed_at,
                        catalog_observed_at,
                        Jsonb({"symbol": "BTCUSDT"}),
                    ),
                )

            valid_from = datetime.now(UTC)
            version_id = connection.execute(
                """
                INSERT INTO venue_instrument_versions (
                    venue, source_symbol, definition_hash, valid_from,
                    active, asset_class, market_type, base_asset,
                    quote_asset, settle_asset, quantity_unit, contract_multiplier,
                    raw_definition, raw_catalog_payload_id
                )
                VALUES (
                    %s, %s, %s, %s, true, 'crypto', 'linear_perpetual',
                    'BTC', 'USDT', 'USDT', 'base', 1, '{}'::jsonb, %s
                )
                RETURNING venue_instrument_version_id
                """,
                ("bitget", "BTCUSDT", "b" * 64, valid_from, payload_id[0]),
            ).fetchone()
            assert version_id is not None

            with pytest.raises(UniqueViolation):
                connection.execute(
                    """
                    INSERT INTO venue_instrument_versions (
                        venue, source_symbol, definition_hash, valid_from,
                        active, asset_class, market_type, base_asset,
                        quote_asset, settle_asset, quantity_unit, contract_multiplier,
                        raw_definition, raw_catalog_payload_id
                    )
                    VALUES (
                        %s, %s, %s, %s, true, 'crypto', 'linear_perpetual',
                        'BTC', 'USDT', 'USDT', 'base', 1, '{}'::jsonb, %s
                    )
                    """,
                    (
                        "bitget",
                        "BTCUSDT",
                        "c" * 64,
                        valid_from + timedelta(seconds=1),
                        payload_id[0],
                    ),
                )

            connection.execute(
                """
                UPDATE venue_instrument_versions
                SET valid_to = %s
                WHERE venue_instrument_version_id = %s
                """,
                (valid_from + timedelta(seconds=1), version_id[0]),
            )
            connection.execute(
                """
                INSERT INTO venue_instrument_versions (
                    venue, source_symbol, definition_hash, valid_from,
                    active, asset_class, market_type, base_asset,
                    quote_asset, settle_asset, quantity_unit, contract_multiplier,
                    raw_definition, raw_catalog_payload_id
                )
                VALUES (
                    %s, %s, %s, %s, true, 'crypto', 'linear_perpetual',
                    'BTC', 'USDT', 'USDT', 'base', 1, '{}'::jsonb, %s
                )
                """,
                (
                    "bitget",
                    "BTCUSDT",
                    "c" * 64,
                    valid_from + timedelta(seconds=1),
                    payload_id[0],
                ),
            )
        finally:
            connection.execute("RESET search_path")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
