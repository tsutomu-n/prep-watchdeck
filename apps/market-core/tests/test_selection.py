from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from prep_watchdeck_market.database import apply_migrations
from prep_watchdeck_market.retention import prune_selected_history
from prep_watchdeck_market.selected_market import DepthLevel, SelectedDepth, SelectedTrade
from prep_watchdeck_market.selected_store import (
    InvalidSelectionError,
    activate_selection,
    close_selection,
    read_selected_market,
    store_selected_events,
)
from prep_watchdeck_market.selection import (
    ActiveSelection,
    SelectionController,
    estimate_book_walks,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def test_selection_controller_debounces_last_write_and_cleans_before_switch() -> None:
    async def scenario() -> None:
        events: list[str] = []

        async def subscribe(
            selection_id: uuid.UUID,
            group_id: str,
            primary_venue_instrument_id: str,
        ) -> object:
            events.append(f"start:{group_id}:{primary_venue_instrument_id}:{selection_id}")
            return f"token:{group_id}"

        async def unsubscribe(active: ActiveSelection) -> None:
            events.append(f"stop:{active.group_id}")

        controller = SelectionController(subscribe, unsubscribe)
        started_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        controller.request("group:BTC", "bitget:BTCUSDT", started_at)
        controller.request(
            "group:BTC",
            "hyperliquid:BTC",
            started_at + timedelta(milliseconds=100),
        )

        assert await controller.reconcile(started_at + timedelta(milliseconds=599)) is None
        first = await controller.reconcile(started_at + timedelta(milliseconds=600))
        assert first is not None
        assert first.group_id == "group:BTC"
        assert first.primary_venue_instrument_id == "hyperliquid:BTC"
        assert len(controller.active_groups) == 1

        controller.heartbeat(first.selection_id, started_at + timedelta(minutes=5))
        controller.request(
            "group:BTC",
            "bitget:BTCUSDT",
            started_at + timedelta(minutes=5, milliseconds=1),
        )
        second = await controller.reconcile(started_at + timedelta(minutes=5, milliseconds=501))
        assert second is not None
        assert second.group_id == "group:BTC"
        assert second.primary_venue_instrument_id == "bitget:BTCUSDT"
        assert [event.split(":", maxsplit=2)[0:2] for event in events] == [
            ["start", "group"],
            ["stop", "group"],
            ["start", "group"],
        ]
        assert events[1] == "stop:group:BTC"

        assert await controller.reconcile(second.expires_at) is None
        assert events[-1] == "stop:group:BTC"
        assert controller.active_groups == ()

    asyncio.run(scenario())


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run the isolated PostgreSQL integration test",
)
def test_selected_store_limits_rows_and_book_walk_fails_closed() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"selected_store_test_{uuid.uuid4().hex}"
    observed_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    selection_id = uuid.uuid4()

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        try:
            apply_migrations(connection)
            _seed_group(connection, observed_at)
            with pytest.raises(InvalidSelectionError, match="primary"):
                activate_selection(
                    connection,
                    selection_id=uuid.uuid4(),
                    group_id="crypto:BTC",
                    primary_venue_instrument_id="hyperliquid:BTC",
                    activated_at=observed_at,
                )
            active = activate_selection(
                connection,
                selection_id=selection_id,
                group_id="crypto:BTC",
                primary_venue_instrument_id="bitget:BTCUSDT",
                activated_at=observed_at,
            )
            assert active.current.selection_id == selection_id
            assert active.previous is None

            depth = SelectedDepth(
                venue="bitget",
                source_symbol="BTCUSDT",
                bids=(
                    DepthLevel(Decimal("100"), Decimal("3")),
                    DepthLevel(Decimal("99"), Decimal("3")),
                    DepthLevel(Decimal("98"), Decimal("4")),
                ),
                asks=(
                    DepthLevel(Decimal("101"), Decimal("3")),
                    DepthLevel(Decimal("102"), Decimal("3")),
                    DepthLevel(Decimal("103"), Decimal("4")),
                ),
                source_at=observed_at,
                received_at=observed_at,
                source_channel="books15",
                raw_payload={"kind": "depth"},
            )
            trades = tuple(
                SelectedTrade(
                    venue="bitget",
                    source_symbol="BTCUSDT",
                    trade_id=f"trade-{index:03d}",
                    side="buy" if index % 2 == 0 else "sell",
                    price=Decimal("100") + Decimal(index) / 100,
                    size_base=Decimal("0.01"),
                    source_at=observed_at + timedelta(milliseconds=index),
                    received_at=observed_at + timedelta(milliseconds=index),
                    source_channel="trades",
                    raw_payload={"index": index},
                )
                for index in range(105)
            )
            stored = store_selected_events(connection, selection_id, (depth, *trades))
            assert stored.depth_snapshots == 1
            assert stored.trades_stored == 105
            assert stored.trades_retained == 100

            selected = read_selected_market(
                connection,
                now=observed_at + timedelta(seconds=5),
            )
            assert selected is not None
            assert selected.group_id == "crypto:BTC"
            assert selected.primary_venue_instrument_id == "bitget:BTCUSDT"
            assert len(selected.instruments) == 1
            assert len(selected.trades) == 100
            assert selected.trades[0].trade_id == "trade-104"
            instrument = selected.instruments[0]
            assert len(instrument.bids) == 3
            assert len(instrument.asks) == 3
            estimates = {item.notional_quote: item for item in instrument.book_walks}
            assert estimates[Decimal("100")].buy is not None
            assert estimates[Decimal("500")].sell is not None
            assert estimates[Decimal("1000")].buy is not None
            assert estimates[Decimal("1000")].sell is None
            assert estimates[Decimal("1000")].sell_unavailable_reason == "insufficient_depth"
            assert all(not item.includes_fees for item in instrument.book_walks)
            assert all(not item.predicts_future_impact for item in instrument.book_walks)
            assert all(not item.confirms_order_availability for item in instrument.book_walks)

            stale = read_selected_market(
                connection,
                now=observed_at + timedelta(seconds=11),
            )
            assert stale is not None
            assert all(
                item.buy is None and item.sell is None for item in stale.instruments[0].book_walks
            )
            assert all(
                item.buy_unavailable_reason == "stale_depth"
                and item.sell_unavailable_reason == "stale_depth"
                for item in stale.instruments[0].book_walks
            )
            non_usd = estimate_book_walks(
                depth.bids,
                depth.asks,
                quote_asset="BTC",
                received_at=observed_at,
                now=observed_at,
            )
            assert all(item.buy is None and item.sell is None for item in non_usd)
            assert all(item.buy_unavailable_reason == "non_usd_like_quote" for item in non_usd)

            assert connection.execute("SELECT count(*) FROM selected_depth_levels").fetchone() == (
                6,
            )
            assert connection.execute("SELECT count(*) FROM selected_trades").fetchone() == (100,)
            assert connection.execute(
                "SELECT count(*) FROM selected_raw_observations"
            ).fetchone() == (106,)
            assert connection.execute(
                "SELECT count(*) FROM selected_group_leases WHERE superseded_at IS NULL"
            ).fetchone() == (1,)

            closed_at = observed_at + timedelta(seconds=1)
            assert close_selection(connection, selection_id, closed_at)
            closed_lease = connection.execute(
                """
                    SELECT superseded_at, cleanup_deadline_at, cleaned_at
                    FROM selected_group_leases
                    WHERE selection_id = %s
                """,
                (selection_id,),
            ).fetchone()
            assert closed_lease == (
                closed_at,
                closed_at + timedelta(seconds=10),
                closed_at,
            )

            replacement_id = uuid.uuid4()
            activate_selection(
                connection,
                selection_id=replacement_id,
                group_id="crypto:BTC",
                primary_venue_instrument_id="bitget:BTCUSDT",
                activated_at=observed_at + timedelta(seconds=2),
            )
            retained = prune_selected_history(
                connection,
                now=observed_at + timedelta(days=10),
            )
            assert retained.raw_deleted == 106
            assert retained.depth_deleted == 6
            assert retained.trades_deleted == 100
            assert retained.leases_deleted == 1
            assert not retained.has_more
            raw_count = connection.execute(
                "SELECT count(*) FROM selected_raw_observations"
            ).fetchone()
            assert raw_count == (0,)
            assert connection.execute("SELECT count(*) FROM selected_group_leases").fetchone() == (
                1,
            )
        finally:
            connection.execute("RESET search_path")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def _seed_group(connection: psycopg.Connection[Any], observed_at: datetime) -> None:
    raw_definition = {"symbol": "BTCUSDT"}
    raw_id = connection.execute(
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
    assert raw_id is not None
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
        ("b" * 64, observed_at, Jsonb(raw_definition), int(raw_id[0])),
    ).fetchone()
    assert version is not None
    connection.execute(
        """
            INSERT INTO market_groups (
                group_id, base_asset, asset_class, market_type, created_at, updated_at
            )
            VALUES ('crypto:BTC', 'BTC', 'crypto', 'linear_perpetual', %s, %s)
        """,
        (observed_at, observed_at),
    )
    connection.execute(
        """
            INSERT INTO group_memberships (
                group_id, venue_instrument_version_id, mapping_method, valid_from
            )
            VALUES ('crypto:BTC', %s, 'exact_base', %s)
        """,
        (int(version[0]), observed_at),
    )
