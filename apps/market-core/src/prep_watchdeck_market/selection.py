from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from prep_watchdeck_market.selected_market import USD_LIKE_ASSETS, DepthLevel

SELECTION_DEBOUNCE = timedelta(milliseconds=500)
SELECTION_TTL = timedelta(minutes=15)
SELECTION_HEARTBEAT = timedelta(minutes=5)
SUBSCRIPTION_CLEANUP_TIMEOUT_SECONDS = 10.0
BOOK_DEPTH_MAX_AGE = timedelta(seconds=10)
BOOK_WALK_NOTIONALS = (Decimal("100"), Decimal("500"), Decimal("1000"))


class SelectionError(RuntimeError):
    """A local selected-group transition could not be completed safely."""


class SelectionCleanupError(SelectionError):
    """An old selected-group subscription did not stop within its deadline."""


@dataclass(frozen=True, slots=True)
class ActiveSelection:
    selection_id: UUID
    group_id: str
    primary_venue_instrument_id: str
    subscription: object
    activated_at: datetime
    heartbeat_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class _PendingSelection:
    revision: int
    group_id: str
    primary_venue_instrument_id: str
    requested_at: datetime
    activate_at: datetime


Subscribe = Callable[[UUID, str, str], Awaitable[object]]
Unsubscribe = Callable[[ActiveSelection], Awaitable[None]]


class SelectionController:
    """Deterministic local single-selection controller driven by an explicit service tick."""

    def __init__(
        self,
        subscribe: Subscribe,
        unsubscribe: Unsubscribe,
        *,
        debounce: timedelta = SELECTION_DEBOUNCE,
        ttl: timedelta = SELECTION_TTL,
        heartbeat_interval: timedelta = SELECTION_HEARTBEAT,
        cleanup_timeout_seconds: float = SUBSCRIPTION_CLEANUP_TIMEOUT_SECONDS,
    ) -> None:
        if debounce.total_seconds() < 0:
            raise ValueError("selection debounce cannot be negative")
        if ttl <= timedelta(0) or heartbeat_interval <= timedelta(0):
            raise ValueError("selection TTL and heartbeat interval must be positive")
        if heartbeat_interval >= ttl:
            raise ValueError("selection heartbeat interval must be below TTL")
        if cleanup_timeout_seconds <= 0 or cleanup_timeout_seconds > 10:
            raise ValueError("subscription cleanup timeout must be between 0 and 10 seconds")
        self._subscribe = subscribe
        self._unsubscribe = unsubscribe
        self._debounce = debounce
        self._ttl = ttl
        self._heartbeat_interval = heartbeat_interval
        self._cleanup_timeout_seconds = cleanup_timeout_seconds
        self._pending: _PendingSelection | None = None
        self._active: ActiveSelection | None = None
        self._revision = 0
        self._transition_lock = asyncio.Lock()

    @property
    def active(self) -> ActiveSelection | None:
        return self._active

    @property
    def active_groups(self) -> tuple[str, ...]:
        return () if self._active is None else (self._active.group_id,)

    @property
    def heartbeat_due_at(self) -> datetime | None:
        if self._active is None:
            return None
        return self._active.heartbeat_at + self._heartbeat_interval

    def request(
        self,
        group_id: str,
        primary_venue_instrument_id: str,
        requested_at: datetime,
    ) -> int:
        _require_utc(requested_at, "requested_at")
        if not group_id.strip():
            raise ValueError("selected group_id must not be empty")
        if not primary_venue_instrument_id.strip():
            raise ValueError("primary venue_instrument_id must not be empty")
        self._revision += 1
        self._pending = _PendingSelection(
            revision=self._revision,
            group_id=group_id,
            primary_venue_instrument_id=primary_venue_instrument_id,
            requested_at=requested_at,
            activate_at=requested_at + self._debounce,
        )
        return self._revision

    def heartbeat(self, selection_id: UUID, heartbeat_at: datetime) -> bool:
        _require_utc(heartbeat_at, "heartbeat_at")
        active = self._active
        if active is None or active.selection_id != selection_id:
            return False
        if heartbeat_at < active.heartbeat_at:
            raise ValueError("selection heartbeat cannot move backwards")
        self._active = replace(
            active,
            heartbeat_at=heartbeat_at,
            expires_at=heartbeat_at + self._ttl,
        )
        return True

    async def reconcile(self, now: datetime) -> ActiveSelection | None:
        _require_utc(now, "now")
        async with self._transition_lock:
            if self._active is not None and self._active.expires_at <= now:
                await self._cleanup_active()

            pending = self._pending
            if pending is None or pending.activate_at > now:
                return self._active
            if (
                self._active is not None
                and self._active.group_id == pending.group_id
                and self._active.primary_venue_instrument_id == pending.primary_venue_instrument_id
            ):
                self._active = replace(
                    self._active,
                    heartbeat_at=now,
                    expires_at=now + self._ttl,
                )
                if self._pending is not None and self._pending.revision == pending.revision:
                    self._pending = None
                return self._active

            if self._active is not None:
                await self._cleanup_active()
            if self._pending is None or self._pending.revision != pending.revision:
                return self._active

            selection_id = uuid4()
            subscription = await self._subscribe(
                selection_id,
                pending.group_id,
                pending.primary_venue_instrument_id,
            )
            if self._pending is None or self._pending.revision != pending.revision:
                stale = ActiveSelection(
                    selection_id=selection_id,
                    group_id=pending.group_id,
                    primary_venue_instrument_id=pending.primary_venue_instrument_id,
                    subscription=subscription,
                    activated_at=now,
                    heartbeat_at=now,
                    expires_at=now + self._ttl,
                )
                await self._cleanup(stale)
                return self._active
            self._active = ActiveSelection(
                selection_id=selection_id,
                group_id=pending.group_id,
                primary_venue_instrument_id=pending.primary_venue_instrument_id,
                subscription=subscription,
                activated_at=now,
                heartbeat_at=now,
                expires_at=now + self._ttl,
            )
            self._pending = None
            return self._active

    async def stop(self) -> None:
        async with self._transition_lock:
            self._pending = None
            if self._active is not None:
                await self._cleanup_active()

    async def _cleanup_active(self) -> None:
        active = self._active
        if active is None:
            return
        await self._cleanup(active)
        if self._active is active:
            self._active = None

    async def _cleanup(self, active: ActiveSelection) -> None:
        try:
            await asyncio.wait_for(
                self._unsubscribe(active),
                timeout=self._cleanup_timeout_seconds,
            )
        except TimeoutError:
            raise SelectionCleanupError(
                "old selected-group subscription exceeded the 10-second cleanup deadline"
            ) from None


@dataclass(frozen=True, slots=True)
class BookWalkFill:
    base_size: Decimal
    average_price: Decimal
    top_price_impact_bps: Decimal


@dataclass(frozen=True, slots=True)
class BookWalkEstimate:
    notional_quote: Decimal
    buy: BookWalkFill | None
    sell: BookWalkFill | None
    buy_unavailable_reason: str | None
    sell_unavailable_reason: str | None
    includes_fees: bool = False
    predicts_future_impact: bool = False
    confirms_order_availability: bool = False


def estimate_book_walks(
    bids: Sequence[DepthLevel],
    asks: Sequence[DepthLevel],
    *,
    quote_asset: str,
    received_at: datetime,
    now: datetime,
) -> tuple[BookWalkEstimate, ...]:
    _require_utc(received_at, "depth received_at")
    _require_utc(now, "now")
    unavailable_reason: str | None = None
    if quote_asset.upper() not in USD_LIKE_ASSETS:
        unavailable_reason = "non_usd_like_quote"
    elif received_at > now:
        unavailable_reason = "invalid_depth_time"
    elif now - received_at > BOOK_DEPTH_MAX_AGE:
        unavailable_reason = "stale_depth"

    estimates: list[BookWalkEstimate] = []
    for notional in BOOK_WALK_NOTIONALS:
        if unavailable_reason is not None:
            estimates.append(
                BookWalkEstimate(
                    notional_quote=notional,
                    buy=None,
                    sell=None,
                    buy_unavailable_reason=unavailable_reason,
                    sell_unavailable_reason=unavailable_reason,
                )
            )
            continue
        buy = _walk_levels(asks, notional, is_buy=True)
        sell = _walk_levels(bids, notional, is_buy=False)
        estimates.append(
            BookWalkEstimate(
                notional_quote=notional,
                buy=buy,
                sell=sell,
                buy_unavailable_reason=None if buy is not None else "insufficient_depth",
                sell_unavailable_reason=None if sell is not None else "insufficient_depth",
            )
        )
    return tuple(estimates)


def unavailable_book_walks(reason: str) -> tuple[BookWalkEstimate, ...]:
    if not reason.strip():
        raise ValueError("book-walk unavailable reason must not be empty")
    return tuple(
        BookWalkEstimate(
            notional_quote=notional,
            buy=None,
            sell=None,
            buy_unavailable_reason=reason,
            sell_unavailable_reason=reason,
        )
        for notional in BOOK_WALK_NOTIONALS
    )


def _walk_levels(
    levels: Sequence[DepthLevel],
    notional_quote: Decimal,
    *,
    is_buy: bool,
) -> BookWalkFill | None:
    if not levels:
        return None
    remaining = notional_quote
    base_size = Decimal(0)
    for level in levels:
        available_quote = level.price * level.size_base
        consumed_quote = min(remaining, available_quote)
        base_size += consumed_quote / level.price
        remaining -= consumed_quote
        if remaining <= 0:
            break
    if remaining > 0 or base_size <= 0:
        return None
    average_price = notional_quote / base_size
    top_price = levels[0].price
    if is_buy:
        impact_bps = (average_price / top_price - 1) * Decimal(10_000)
    else:
        impact_bps = (1 - average_price / top_price) * Decimal(10_000)
    return BookWalkFill(
        base_size=base_size,
        average_price=average_price,
        top_price_impact_bps=max(Decimal(0), impact_bps),
    )


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
