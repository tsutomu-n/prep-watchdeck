from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from prep_watchdeck_market.models import Venue
from prep_watchdeck_market.selected_market import (
    DepthLevel,
    SelectedDepth,
    SelectedEvent,
    SelectedTrade,
    TradeSide,
)
from prep_watchdeck_market.selection import (
    SELECTION_TTL,
    BookWalkEstimate,
    estimate_book_walks,
    unavailable_book_walks,
)

_SELECTION_LOCK_ID = 7_838_492_731_104_448_091
_CLEANUP_DEADLINE = timedelta(seconds=10)
_TRADE_LIMIT = 100


class SelectedStoreError(RuntimeError):
    """Selected market data could not be persisted without exposing credentials."""


class InvalidSelectionError(SelectedStoreError):
    """The selection is inactive, expired, or not backed by an eligible current group."""


@dataclass(frozen=True, slots=True)
class SelectionLease:
    selection_id: UUID
    group_id: str
    primary_venue_instrument_version_id: int
    activated_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    superseded_at: datetime | None
    cleanup_deadline_at: datetime | None
    cleaned_at: datetime | None


@dataclass(frozen=True, slots=True)
class SelectionTransition:
    current: SelectionLease
    previous: SelectionLease | None


@dataclass(frozen=True, slots=True)
class SelectedStoreResult:
    depth_snapshots: int
    trades_received: int
    trades_stored: int
    trades_retained: int
    raw_observations_stored: int


@dataclass(frozen=True, slots=True)
class SelectedTradeView:
    venue_instrument_version_id: int
    venue: Venue
    source_symbol: str
    trade_id: str
    side: TradeSide
    price: Decimal
    size_base: Decimal
    source_at: datetime | None
    received_at: datetime


@dataclass(frozen=True, slots=True)
class SelectedInstrumentView:
    venue_instrument_version_id: int
    venue: Venue
    source_symbol: str
    quote_asset: str
    depth_received_at: datetime | None
    bids: tuple[DepthLevel, ...]
    asks: tuple[DepthLevel, ...]
    book_walks: tuple[BookWalkEstimate, ...]


@dataclass(frozen=True, slots=True)
class SelectedMarketView:
    selection_id: UUID
    group_id: str
    primary_venue_instrument_id: str
    expires_at: datetime
    instruments: tuple[SelectedInstrumentView, ...]
    trades: tuple[SelectedTradeView, ...]


def activate_selection(
    connection: Connection[Any],
    *,
    selection_id: UUID,
    group_id: str,
    primary_venue_instrument_id: str,
    activated_at: datetime,
) -> SelectionTransition:
    _require_utc(activated_at, "activated_at")
    if not group_id.strip():
        raise ValueError("selected group_id must not be empty")
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (_SELECTION_LOCK_ID,))
            primary_version_id = _selected_primary_version(
                cursor,
                group_id,
                primary_venue_instrument_id,
            )
            active_row = cursor.execute(
                """
                    SELECT selection_id, group_id, primary_venue_instrument_version_id,
                           activated_at, heartbeat_at, expires_at, superseded_at,
                           cleanup_deadline_at, cleaned_at
                    FROM selected_group_leases
                    WHERE superseded_at IS NULL
                    FOR UPDATE
                """
            ).fetchone()
            if active_row is not None and UUID(str(active_row[0])) == selection_id:
                current = _lease_from_row(active_row)
                if (
                    current.group_id != group_id
                    or current.primary_venue_instrument_version_id != primary_version_id
                ):
                    raise InvalidSelectionError("selection_id cannot change its selected identity")
                cursor.execute(
                    """
                        UPDATE selected_group_leases
                        SET heartbeat_at = %s, expires_at = %s
                        WHERE selection_id = %s
                    """,
                    (activated_at, activated_at + SELECTION_TTL, selection_id),
                )
                return SelectionTransition(
                    current=_active_lease(
                        selection_id,
                        group_id,
                        primary_version_id,
                        activated_at,
                    ),
                    previous=None,
                )

            previous: SelectionLease | None = None
            if active_row is not None:
                previous_active = _lease_from_row(active_row)
                cleanup_deadline = activated_at + _CLEANUP_DEADLINE
                cursor.execute(
                    """
                        UPDATE selected_group_leases
                        SET superseded_at = %s, cleanup_deadline_at = %s
                        WHERE selection_id = %s
                    """,
                    (activated_at, cleanup_deadline, previous_active.selection_id),
                )
                previous = SelectionLease(
                    selection_id=previous_active.selection_id,
                    group_id=previous_active.group_id,
                    primary_venue_instrument_version_id=(
                        previous_active.primary_venue_instrument_version_id
                    ),
                    activated_at=previous_active.activated_at,
                    heartbeat_at=previous_active.heartbeat_at,
                    expires_at=previous_active.expires_at,
                    superseded_at=activated_at,
                    cleanup_deadline_at=cleanup_deadline,
                    cleaned_at=None,
                )

            current = _active_lease(
                selection_id,
                group_id,
                primary_version_id,
                activated_at,
            )
            cursor.execute(
                """
                    INSERT INTO selected_group_leases (
                        selection_id, group_id, primary_venue_instrument_version_id,
                        activated_at, heartbeat_at, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    current.selection_id,
                    current.group_id,
                    current.primary_venue_instrument_version_id,
                    current.activated_at,
                    current.heartbeat_at,
                    current.expires_at,
                ),
            )
        return SelectionTransition(current=current, previous=previous)
    except (InvalidSelectionError, ValueError):
        raise
    except psycopg.Error:
        raise SelectedStoreError("selection activation failed") from None


def heartbeat_selection(
    connection: Connection[Any],
    selection_id: UUID,
    heartbeat_at: datetime,
) -> bool:
    _require_utc(heartbeat_at, "heartbeat_at")
    try:
        with connection.transaction():
            result = connection.execute(
                """
                    UPDATE selected_group_leases
                    SET heartbeat_at = %s, expires_at = %s
                    WHERE selection_id = %s AND superseded_at IS NULL
                      AND heartbeat_at <= %s
                """,
                (heartbeat_at, heartbeat_at + SELECTION_TTL, selection_id, heartbeat_at),
            )
        return result.rowcount == 1
    except psycopg.Error:
        raise SelectedStoreError("selection heartbeat failed") from None


def close_selection(
    connection: Connection[Any],
    selection_id: UUID,
    cleaned_at: datetime,
) -> bool:
    """Close one active lease after its subscription and queued writes have stopped."""

    _require_utc(cleaned_at, "cleaned_at")
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (_SELECTION_LOCK_ID,))
            cursor.execute(
                """
                    UPDATE selected_group_leases
                    SET superseded_at = %s, cleanup_deadline_at = %s, cleaned_at = %s
                    WHERE selection_id = %s AND superseded_at IS NULL
                """,
                (
                    cleaned_at,
                    cleaned_at + _CLEANUP_DEADLINE,
                    cleaned_at,
                    selection_id,
                ),
            )
            selection_closed = cursor.rowcount == 1
        return selection_closed
    except psycopg.Error:
        raise SelectedStoreError("selection close failed") from None


def mark_selection_cleaned(
    connection: Connection[Any],
    selection_id: UUID,
    cleaned_at: datetime,
) -> bool:
    _require_utc(cleaned_at, "cleaned_at")
    try:
        with connection.transaction():
            result = connection.execute(
                """
                    UPDATE selected_group_leases
                    SET cleaned_at = %s
                    WHERE selection_id = %s AND superseded_at IS NOT NULL
                      AND cleaned_at IS NULL AND superseded_at <= %s
                """,
                (cleaned_at, selection_id, cleaned_at),
            )
        return result.rowcount == 1
    except psycopg.Error:
        raise SelectedStoreError("selection cleanup acknowledgement failed") from None


def store_selected_events(
    connection: Connection[Any],
    selection_id: UUID,
    events: Sequence[SelectedEvent],
) -> SelectedStoreResult:
    if not events:
        return SelectedStoreResult(0, 0, 0, 0, 0)
    try:
        with connection.transaction(), connection.cursor() as cursor:
            lease = _active_selection(cursor, selection_id)
            versions = _selected_versions(cursor, lease.group_id, events)
            depth_snapshots = 0
            trades_received = 0
            trades_stored = 0
            raw_stored = 0
            for event in events:
                if event.received_at < lease.activated_at or event.received_at >= lease.expires_at:
                    raise InvalidSelectionError("selected event is outside the active lease")
                version_id = versions.get((event.venue, event.source_symbol))
                if version_id is None:
                    raise InvalidSelectionError(
                        "selected event does not belong to an eligible current group member"
                    )
                _insert_raw_event(cursor, selection_id, lease.group_id, version_id, event)
                raw_stored += 1
                if isinstance(event, SelectedDepth):
                    _replace_depth(cursor, selection_id, version_id, event)
                    depth_snapshots += 1
                else:
                    trades_received += 1
                    trades_stored += _insert_trade(cursor, selection_id, version_id, event)
            if trades_received:
                _prune_trades(cursor, selection_id)
            retained_row = cursor.execute(
                "SELECT count(*) FROM selected_trades WHERE selection_id = %s",
                (selection_id,),
            ).fetchone()
            trades_retained = int(retained_row[0]) if retained_row is not None else 0
        return SelectedStoreResult(
            depth_snapshots=depth_snapshots,
            trades_received=trades_received,
            trades_stored=trades_stored,
            trades_retained=trades_retained,
            raw_observations_stored=raw_stored,
        )
    except (InvalidSelectionError, ValueError):
        raise
    except psycopg.Error:
        raise SelectedStoreError("selected event persistence failed") from None


def read_selected_market(
    connection: Connection[Any],
    *,
    now: datetime,
) -> SelectedMarketView | None:
    _require_utc(now, "now")
    try:
        with connection.transaction(), connection.cursor() as cursor:
            row = cursor.execute(
                """
                    SELECT lease.selection_id, lease.group_id, lease.expires_at,
                           instrument.venue, instrument.source_symbol
                    FROM selected_group_leases AS lease
                    JOIN venue_instrument_versions AS instrument
                      ON instrument.venue_instrument_version_id =
                         lease.primary_venue_instrument_version_id
                    WHERE lease.superseded_at IS NULL AND lease.expires_at > %s
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            selection_id = UUID(str(row[0]))
            group_id = str(row[1])
            expires_at = _datetime(row[2])
            primary_venue_instrument_id = f"{row[3]}:{row[4]}"
            instrument_rows = cursor.execute(
                """
                    SELECT instrument.venue_instrument_version_id, instrument.venue,
                           instrument.source_symbol, instrument.quote_asset
                    FROM group_memberships AS membership
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE membership.group_id = %s AND membership.valid_to IS NULL
                      AND instrument.valid_to IS NULL AND instrument.active = true
                    ORDER BY instrument.venue, instrument.source_symbol
                """,
                (group_id,),
            ).fetchall()
            depth_rows = cursor.execute(
                """
                    SELECT venue_instrument_version_id, side, level_index, price,
                           size_base, received_at
                    FROM selected_depth_levels
                    WHERE selection_id = %s
                    ORDER BY venue_instrument_version_id, side, level_index
                """,
                (selection_id,),
            ).fetchall()
            trade_rows = cursor.execute(
                """
                    SELECT trade.venue_instrument_version_id, instrument.venue,
                           instrument.source_symbol, trade.source_trade_id, trade.side,
                           trade.price, trade.size_base, trade.source_at, trade.received_at
                    FROM selected_trades AS trade
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE trade.selection_id = %s
                    ORDER BY trade.source_at DESC NULLS LAST,
                             trade.received_at DESC, trade.selected_trade_id DESC
                    LIMIT 100
                """,
                (selection_id,),
            ).fetchall()
    except psycopg.Error:
        raise SelectedStoreError("selected market read failed") from None

    depths: dict[int, dict[str, Any]] = {}
    for depth_row in depth_rows:
        version_id = int(depth_row[0])
        entry = depths.setdefault(version_id, {"bid": [], "ask": [], "received_at": None})
        side = str(depth_row[1])
        levels = entry[side]
        if isinstance(levels, list):
            levels.append(DepthLevel(Decimal(depth_row[3]), Decimal(depth_row[4])))
        received_at = _datetime(depth_row[5])
        previous_received = entry["received_at"]
        if previous_received is None or received_at > previous_received:
            entry["received_at"] = received_at

    instruments: list[SelectedInstrumentView] = []
    for instrument_row in instrument_rows:
        version_id = int(instrument_row[0])
        venue = _venue(instrument_row[1])
        source_symbol = str(instrument_row[2])
        quote_asset = str(instrument_row[3])
        depth = depths.get(version_id)
        if depth is None or depth["received_at"] is None:
            bids: tuple[DepthLevel, ...] = ()
            asks: tuple[DepthLevel, ...] = ()
            depth_received_at = None
            walks = unavailable_book_walks("depth_unavailable")
        else:
            bids = tuple(depth["bid"])
            asks = tuple(depth["ask"])
            depth_received_at = _datetime(depth["received_at"])
            walks = estimate_book_walks(
                bids,
                asks,
                quote_asset=quote_asset,
                received_at=depth_received_at,
                now=now,
            )
        instruments.append(
            SelectedInstrumentView(
                venue_instrument_version_id=version_id,
                venue=venue,
                source_symbol=source_symbol,
                quote_asset=quote_asset,
                depth_received_at=depth_received_at,
                bids=bids,
                asks=asks,
                book_walks=walks,
            )
        )
    trades = tuple(
        SelectedTradeView(
            venue_instrument_version_id=int(trade_row[0]),
            venue=_venue(trade_row[1]),
            source_symbol=str(trade_row[2]),
            trade_id=str(trade_row[3]),
            side=_trade_side(trade_row[4]),
            price=Decimal(trade_row[5]),
            size_base=Decimal(trade_row[6]),
            source_at=None if trade_row[7] is None else _datetime(trade_row[7]),
            received_at=_datetime(trade_row[8]),
        )
        for trade_row in trade_rows
    )
    return SelectedMarketView(
        selection_id=selection_id,
        group_id=group_id,
        primary_venue_instrument_id=primary_venue_instrument_id,
        expires_at=expires_at,
        instruments=tuple(instruments),
        trades=trades,
    )


def _active_selection(cursor: Any, selection_id: UUID) -> SelectionLease:
    row = cursor.execute(
        """
            SELECT selection_id, group_id, primary_venue_instrument_version_id,
                   activated_at, heartbeat_at, expires_at, superseded_at,
                   cleanup_deadline_at, cleaned_at
            FROM selected_group_leases
            WHERE selection_id = %s AND superseded_at IS NULL
            FOR SHARE
        """,
        (selection_id,),
    ).fetchone()
    if row is None:
        raise InvalidSelectionError("selection is not active")
    return _lease_from_row(row)


def _selected_versions(
    cursor: Any,
    group_id: str,
    events: Sequence[SelectedEvent],
) -> dict[tuple[Venue, str], int]:
    requested = sorted({(event.venue, event.source_symbol) for event in events})
    venues = [venue for venue, _ in requested]
    symbols = [symbol for _, symbol in requested]
    rows = cursor.execute(
        """
            WITH requested (venue, source_symbol) AS (
                SELECT * FROM unnest(%s::text[], %s::text[])
            )
            SELECT instrument.venue, instrument.source_symbol,
                   instrument.venue_instrument_version_id
            FROM requested
            JOIN venue_instrument_versions AS instrument
              USING (venue, source_symbol)
            JOIN group_memberships AS membership
              USING (venue_instrument_version_id)
            WHERE membership.group_id = %s AND membership.valid_to IS NULL
              AND instrument.valid_to IS NULL AND instrument.active = true
              AND instrument.execution_model = 'clob'
              AND instrument.market_type = 'linear_perpetual'
              AND upper(instrument.quote_asset) = ANY(%s)
              AND upper(instrument.settle_asset) = ANY(%s)
              AND upper(instrument.collateral_asset) = ANY(%s)
              AND instrument.quantity_unit = 'base'
              AND instrument.contract_multiplier = 1
            FOR SHARE OF instrument, membership
        """,
        (
            venues,
            symbols,
            group_id,
            ["USD", "USDC", "USDT"],
            ["USD", "USDC", "USDT"],
            ["USD", "USDC", "USDT"],
        ),
    ).fetchall()
    return {(_venue(row[0]), str(row[1])): int(row[2]) for row in rows}


def _selected_primary_version(
    cursor: Any,
    group_id: str,
    venue_instrument_id: str,
) -> int:
    venue_text, separator, source_symbol = venue_instrument_id.partition(":")
    if (
        separator != ":"
        or not source_symbol
        or venue_text
        not in {
            "bitget",
            "hyperliquid",
            "aster",
        }
    ):
        raise InvalidSelectionError("primary venue_instrument_id is invalid")
    row = cursor.execute(
        """
            SELECT instrument.venue_instrument_version_id
            FROM group_memberships AS membership
            JOIN venue_instrument_versions AS instrument
              USING (venue_instrument_version_id)
            WHERE membership.group_id = %s AND membership.valid_to IS NULL
              AND instrument.venue = %s AND instrument.source_symbol = %s
              AND instrument.valid_to IS NULL AND instrument.active = true
              AND instrument.execution_model = 'clob'
              AND instrument.market_type = 'linear_perpetual'
              AND upper(instrument.quote_asset) = ANY(%s)
              AND upper(instrument.settle_asset) = ANY(%s)
              AND upper(instrument.collateral_asset) = ANY(%s)
              AND instrument.quantity_unit = 'base'
              AND instrument.contract_multiplier = 1
            LIMIT 1
        """,
        (
            group_id,
            venue_text,
            source_symbol,
            ["USD", "USDC", "USDT"],
            ["USD", "USDC", "USDT"],
            ["USD", "USDC", "USDT"],
        ),
    ).fetchone()
    if row is None:
        raise InvalidSelectionError(
            "primary instrument is not an eligible current member of the selected group"
        )
    return int(row[0])


def _insert_raw_event(
    cursor: Any,
    selection_id: UUID,
    group_id: str,
    version_id: int,
    event: SelectedEvent,
) -> None:
    cursor.execute(
        """
            INSERT INTO selected_raw_observations (
                observed_date, selection_id, group_id, venue_instrument_version_id,
                observation_kind, observed_at, source_at, payload_hash, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            event.received_at.date(),
            selection_id,
            group_id,
            version_id,
            "depth" if isinstance(event, SelectedDepth) else "trade",
            event.received_at,
            event.source_at,
            event.payload_hash,
            Jsonb(event.raw_payload),
        ),
    )


def _replace_depth(
    cursor: Any,
    selection_id: UUID,
    version_id: int,
    depth: SelectedDepth,
) -> None:
    cursor.execute(
        """
            DELETE FROM selected_depth_levels
            WHERE selection_id = %s AND venue_instrument_version_id = %s
        """,
        (selection_id, version_id),
    )
    for side, levels in (("bid", depth.bids), ("ask", depth.asks)):
        for level_index, level in enumerate(levels):
            cursor.execute(
                """
                    INSERT INTO selected_depth_levels (
                        selection_id, venue_instrument_version_id, side, level_index,
                        price, size_base, source_at, received_at, source_channel,
                        source_payload_hash
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    selection_id,
                    version_id,
                    side,
                    level_index,
                    level.price,
                    level.size_base,
                    depth.source_at,
                    depth.received_at,
                    depth.source_channel,
                    depth.payload_hash,
                ),
            )


def _insert_trade(
    cursor: Any,
    selection_id: UUID,
    version_id: int,
    trade: SelectedTrade,
) -> int:
    cursor.execute(
        """
            INSERT INTO selected_trades (
                selection_id, venue_instrument_version_id, source_trade_id, side,
                price, size_base, source_at, received_at, source_channel,
                source_payload_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (selection_id, venue_instrument_version_id, source_trade_id)
            DO NOTHING
        """,
        (
            selection_id,
            version_id,
            trade.trade_id,
            trade.side,
            trade.price,
            trade.size_base,
            trade.source_at,
            trade.received_at,
            trade.source_channel,
            trade.payload_hash,
        ),
    )
    return int(cursor.rowcount)


def _prune_trades(cursor: Any, selection_id: UUID) -> None:
    cursor.execute(
        """
            DELETE FROM selected_trades
            WHERE selected_trade_id IN (
                SELECT selected_trade_id
                FROM selected_trades
                WHERE selection_id = %s
                ORDER BY source_at DESC NULLS LAST,
                         received_at DESC, selected_trade_id DESC
                OFFSET 100
            )
        """,
        (selection_id,),
    )


def _active_lease(
    selection_id: UUID,
    group_id: str,
    primary_version_id: int,
    activated_at: datetime,
) -> SelectionLease:
    return SelectionLease(
        selection_id=selection_id,
        group_id=group_id,
        primary_venue_instrument_version_id=primary_version_id,
        activated_at=activated_at,
        heartbeat_at=activated_at,
        expires_at=activated_at + SELECTION_TTL,
        superseded_at=None,
        cleanup_deadline_at=None,
        cleaned_at=None,
    )


def _lease_from_row(row: Sequence[Any]) -> SelectionLease:
    return SelectionLease(
        selection_id=UUID(str(row[0])),
        group_id=str(row[1]),
        primary_venue_instrument_version_id=int(row[2]),
        activated_at=_datetime(row[3]),
        heartbeat_at=_datetime(row[4]),
        expires_at=_datetime(row[5]),
        superseded_at=None if row[6] is None else _datetime(row[6]),
        cleanup_deadline_at=None if row[7] is None else _datetime(row[7]),
        cleaned_at=None if row[8] is None else _datetime(row[8]),
    )


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SelectedStoreError("selected timestamp has an invalid database type")
    return value


def _venue(value: object) -> Venue:
    text = str(value)
    if text not in {"bitget", "hyperliquid", "aster"}:
        raise SelectedStoreError("selected Venue has an invalid database value")
    return text  # type: ignore[return-value]


def _trade_side(value: object) -> TradeSide:
    text = str(value)
    if text == "buy":
        return "buy"
    if text == "sell":
        return "sell"
    raise SelectedStoreError("selected trade side has an invalid database value")


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
