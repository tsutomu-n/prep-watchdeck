from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from psycopg import sql

from prep_watchdeck_market.catalog_store import persist_catalog
from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.identity import resolve_market_groups
from prep_watchdeck_market.models import (
    CatalogBatch,
    CatalogExclusion,
    CatalogInstrument,
    CatalogProvenance,
    SourceCapability,
    canonical_json_sha256,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)
def test_catalog_persistence_deduplicates_raw_and_versions_identity_changes() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"market_catalog_test_{uuid.uuid4().hex}"
    first_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            first_batch = _catalog_batch(first_at)
            first = persist_catalog(
                connection,
                first_batch,
                resolve_market_groups(first_batch.instruments),
            )
            repeated_batch = replace(
                first_batch,
                provenance=replace(
                    first_batch.provenance,
                    observed_at=first_at + timedelta(minutes=1),
                ),
            )
            repeated = persist_catalog(
                connection,
                repeated_batch,
                resolve_market_groups(repeated_batch.instruments),
            )

            changed_btc = replace(
                first_batch.instruments[0],
                price_tick=Decimal("0.10"),
                raw_definition={"symbol": "BTCUSDT", "pricePlace": "1"},
            )
            changed_payload: dict[str, object] = {
                "data": [changed_btc.raw_definition, {"symbol": "1000PEPEUSDT"}]
            }
            changed_batch = replace(
                first_batch,
                provenance=replace(
                    first_batch.provenance,
                    observed_at=first_at + timedelta(minutes=2),
                    payload_hash=canonical_json_sha256(changed_payload),
                ),
                instruments=(changed_btc, first_batch.instruments[1]),
                raw_payload=changed_payload,
            )
            changed = persist_catalog(
                connection,
                changed_batch,
                resolve_market_groups(changed_batch.instruments),
            )

            assert first.raw_payload_inserted is True
            assert first.instrument_versions_created == 2
            assert first.exclusions_inserted == 1
            assert repeated.raw_payload_inserted is False
            assert repeated.instrument_versions_created == 0
            assert repeated.instrument_versions_unchanged == 2
            assert repeated.exclusions_inserted == 0
            assert changed.raw_payload_inserted is True
            assert changed.instrument_versions_created == 1
            assert changed.instrument_versions_closed == 1

            assert connection.execute("SELECT count(*) FROM raw_catalog_payloads").fetchone() == (
                2,
            )
            assert connection.execute(
                "SELECT count(*) FROM venue_instrument_versions"
            ).fetchone() == (3,)
            assert connection.execute(
                "SELECT count(*) FROM venue_instrument_versions WHERE valid_to IS NULL"
            ).fetchone() == (2,)
            assert connection.execute(
                "SELECT count(*) FROM group_memberships WHERE valid_to IS NULL"
            ).fetchone() == (1,)
            assert connection.execute(
                """
                    SELECT unmapped_reason
                    FROM identity_resolutions ir
                    JOIN venue_instrument_versions vi USING (venue_instrument_version_id)
                    WHERE vi.source_symbol = '1000PEPEUSDT' AND ir.valid_to IS NULL
                """
            ).fetchone() == ("contract_multiplier_not_one",)
            assert connection.execute(
                """
                    SELECT available
                    FROM capabilities
                    WHERE venue = 'bitget' AND capability = 'catalog'
                """
            ).fetchone() == (True,)
        finally:
            connection.execute("RESET search_path")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def _catalog_batch(observed_at: datetime) -> CatalogBatch:
    raw_payload: dict[str, object] = {
        "data": [
            {"symbol": "BTCUSDT", "pricePlace": "2"},
            {"symbol": "1000PEPEUSDT"},
        ]
    }
    instruments = (
        CatalogInstrument(
            venue="bitget",
            source_symbol="BTCUSDT",
            active=True,
            source_status="normal",
            asset_class="crypto",
            market_type="linear_perpetual",
            execution_model="clob",
            base_asset="BTC",
            quote_asset="USDT",
            settle_asset="USDT",
            collateral_asset="USDT",
            quantity_unit="base",
            contract_multiplier=Decimal("1"),
            price_tick=Decimal("0.01"),
            amount_step=Decimal("0.001"),
            funding_interval_seconds=28_800,
            raw_definition={"symbol": "BTCUSDT", "pricePlace": "2"},
        ),
        CatalogInstrument(
            venue="bitget",
            source_symbol="1000PEPEUSDT",
            active=True,
            source_status="normal",
            asset_class="crypto",
            market_type="linear_perpetual",
            execution_model="clob",
            base_asset="PEPE",
            quote_asset="USDT",
            settle_asset="USDT",
            collateral_asset="USDT",
            quantity_unit="base",
            contract_multiplier=Decimal("1000"),
            price_tick=Decimal("0.000001"),
            amount_step=Decimal("1"),
            funding_interval_seconds=28_800,
            raw_definition={"symbol": "1000PEPEUSDT"},
        ),
    )
    return CatalogBatch(
        provenance=CatalogProvenance(
            venue="bitget",
            source_kind="native_rest",
            endpoint="/api/v2/mix/market/contracts",
            documentation_url="https://www.bitget.com/api-doc/contract/market/Get-All-Symbols-Contracts",
            observed_at=observed_at,
            source_at=None,
            payload_hash=canonical_json_sha256(raw_payload),
        ),
        instruments=instruments,
        exclusions=(
            CatalogExclusion(
                venue="bitget",
                source_symbol="BTCRWAUSDT",
                reason="asset_class_not_crypto",
                raw_definition={"symbol": "BTCRWAUSDT"},
            ),
        ),
        capabilities=(
            SourceCapability(
                venue="bitget",
                capability="catalog",
                available=True,
                source_kind="native_rest",
                endpoint_or_channel="/api/v2/mix/market/contracts",
                documentation_url="https://www.bitget.com/api-doc/contract/market/Get-All-Symbols-Contracts",
                details={"productType": "USDT-FUTURES"},
            ),
        ),
        raw_payload=raw_payload,
    )
