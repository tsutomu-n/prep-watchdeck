from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast
from uuid import UUID

import aiohttp
import psycopg
from psycopg import Connection

from prep_watchdeck_market.models import CatalogInstrument, QuantityUnit, Venue
from prep_watchdeck_market.selected_market import SelectedEvent, validate_selected_instrument
from prep_watchdeck_market.selected_store import (
    InvalidSelectionError,
    SelectionTransition,
    activate_selection,
    close_selection,
    heartbeat_selection,
    mark_selection_cleaned,
    store_selected_events,
)
from prep_watchdeck_market.selection import SELECTION_TTL, ActiveSelection, SelectionController
from prep_watchdeck_market.sources.selected_streams import (
    SelectedEmitter,
    SelectedStreamController,
)

SELECTION_COMMAND_RELATIVE_PATH = Path("control") / "selection.json"
SELECTION_COMMAND_MAX_BYTES = 16 * 1024
SELECTION_POLL_SECONDS = 0.1
SELECTED_EVENT_QUEUE_SIZE = 2_000
SELECTED_EVENT_BATCH_SIZE = 100
SELECTED_EVENT_BATCH_WAIT_SECONDS = 0.05
ACTIVE_MEMBERSHIP_REFRESH_SECONDS = 5.0

_T = TypeVar("_T")


class SelectionRuntimeError(RuntimeError):
    """Selected-data runtime failed without exposing local credentials or command payloads."""


class InvalidSelectionCommandError(SelectionRuntimeError):
    """A requested group is not currently safe to subscribe."""


@dataclass(frozen=True, slots=True)
class SelectionCommand:
    group_id: str
    venue_instrument_id: str
    requested_at: datetime
    heartbeat_at: datetime


@dataclass(frozen=True, slots=True)
class _RuntimeSubscription:
    selection_id: UUID


@dataclass(frozen=True, slots=True)
class _QueuedEvent:
    selection_id: UUID
    event: SelectedEvent


class _StreamManager(Protocol):
    async def replace_selection(self, instruments: Sequence[CatalogInstrument]) -> None: ...

    async def close(self) -> None: ...


ConnectionFactory = Callable[[str], Connection[Any]]
StreamFactory = Callable[
    [aiohttp.ClientSession | None, SelectedEmitter],
    _StreamManager,
]


def read_selection_command(path: Path, *, now: datetime) -> SelectionCommand | None:
    """Read one atomic local command; invalid input leaves the caller's safe state unchanged."""

    _require_utc(now, "now")
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, OSError):
        return None
    if not raw or len(raw) > SELECTION_COMMAND_MAX_BYTES:
        return None
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or set(payload) != {
        "schemaVersion",
        "groupId",
        "venueInstrumentId",
        "requestedAt",
        "heartbeatAt",
    }:
        return None
    schema_version = payload.get("schemaVersion")
    if isinstance(schema_version, bool) or schema_version != 1:
        return None
    group_id = payload.get("groupId")
    venue_instrument_id = payload.get("venueInstrumentId")
    requested_text = payload.get("requestedAt")
    heartbeat_text = payload.get("heartbeatAt")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (group_id, venue_instrument_id, requested_text, heartbeat_text)
    ):
        return None
    try:
        requested_at = _parse_utc_timestamp(cast(str, requested_text))
        heartbeat_at = _parse_utc_timestamp(cast(str, heartbeat_text))
    except ValueError:
        return None
    if requested_at > heartbeat_at or heartbeat_at > now:
        return None
    if heartbeat_at + SELECTION_TTL <= now:
        return None
    return SelectionCommand(
        group_id=cast(str, group_id).strip(),
        venue_instrument_id=cast(str, venue_instrument_id).strip(),
        requested_at=requested_at,
        heartbeat_at=heartbeat_at,
    )


class SelectionRuntime:
    """Connect one local selection command to bounded selected streams and one DB writer."""

    def __init__(
        self,
        database_url: str,
        state_dir: Path,
        session: aiohttp.ClientSession | None,
        *,
        connection_factory: ConnectionFactory | None = None,
        stream_factory: StreamFactory | None = None,
        poll_seconds: float = SELECTION_POLL_SECONDS,
        queue_size: int = SELECTED_EVENT_QUEUE_SIZE,
        batch_size: int = SELECTED_EVENT_BATCH_SIZE,
        batch_wait_seconds: float = SELECTED_EVENT_BATCH_WAIT_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if poll_seconds <= 0 or queue_size <= 0 or batch_size <= 0 or batch_wait_seconds < 0:
            raise ValueError("selection runtime bounds must be positive")
        self._database_url = database_url
        self._state_dir = state_dir
        self._session = session
        self._connection_factory = connection_factory or _connect
        self._stream_factory = stream_factory or _selected_stream_factory
        self._poll_seconds = poll_seconds
        self._batch_size = batch_size
        self._batch_wait_seconds = batch_wait_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._queue: asyncio.Queue[_QueuedEvent | None] = asyncio.Queue(maxsize=queue_size)
        self._db_lock = asyncio.Lock()
        self._connection: Connection[Any] | None = None
        self._streams: _StreamManager | None = None
        self._controller: SelectionController | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._emitting_selection_id: UUID | None = None
        self._last_requested_at: datetime | None = None
        self._last_identity: tuple[str, str] | None = None
        self._last_heartbeat_at: datetime | None = None
        self._reconcile_at: datetime | None = None
        self._active_instrument_fingerprint: tuple[tuple[str, str], ...] = ()
        self._next_membership_check: datetime | None = None

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        if self._connection is not None:
            raise SelectionRuntimeError("selection runtime is already running")
        control_dir = self._state_dir / SELECTION_COMMAND_RELATIVE_PATH.parent
        await asyncio.to_thread(control_dir.mkdir, parents=True, exist_ok=True)
        try:
            connection = await asyncio.to_thread(self._connection_factory, self._database_url)
        except (psycopg.Error, OSError):
            raise SelectionRuntimeError("selection database connection failed") from None
        self._connection = connection
        self._streams = self._stream_factory(self._session, self._emit)
        self._controller = SelectionController(self._subscribe, self._unsubscribe)
        self._writer_task = asyncio.create_task(
            self._writer_loop(),
            name="market-selected-writer",
        )
        try:
            await self._command_loop(stop_event)
        finally:
            cleanup_task = asyncio.create_task(
                self._shutdown(),
                name="market-selection-shutdown",
            )
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
                raise

    async def _command_loop(self, stop_event: asyncio.Event) -> None:
        command_path = self._state_dir / SELECTION_COMMAND_RELATIVE_PATH
        while not stop_event.is_set():
            await self._raise_writer_failure()
            now = self._clock()
            command = await asyncio.to_thread(read_selection_command, command_path, now=now)
            if command is not None:
                await self._accept_command(command, now=now)
            controller = self._require_controller()
            self._reconcile_at = now
            try:
                try:
                    await controller.reconcile(now)
                except InvalidSelectionCommandError:
                    await controller.stop()
            finally:
                self._reconcile_at = None
            await self._refresh_active_membership(now)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_seconds)

    async def _accept_command(self, command: SelectionCommand, *, now: datetime) -> None:
        identity = (command.group_id, command.venue_instrument_id)
        last_requested = self._last_requested_at
        if last_requested is not None and command.requested_at < last_requested:
            return
        if last_requested == command.requested_at:
            if identity != self._last_identity:
                return
            if (
                self._last_heartbeat_at is not None
                and command.heartbeat_at <= self._last_heartbeat_at
            ):
                return
            controller = self._require_controller()
            active = controller.active
            if active is None or active.expires_at <= now:
                try:
                    await self._run_db(
                        lambda: _load_group_instruments(
                            self._require_connection(),
                            command.group_id,
                            command.venue_instrument_id,
                        )
                    )
                except InvalidSelectionCommandError:
                    self._last_heartbeat_at = command.heartbeat_at
                    return
                self._last_heartbeat_at = command.heartbeat_at
                controller.request(
                    command.group_id,
                    command.venue_instrument_id,
                    command.requested_at,
                )
                return
            await self._heartbeat_active(command)
            self._last_heartbeat_at = command.heartbeat_at
            return

        controller = self._require_controller()
        active = controller.active
        if active is None or (
            active.group_id != command.group_id
            or active.primary_venue_instrument_id != command.venue_instrument_id
        ):
            try:
                await self._run_db(
                    lambda: _load_group_instruments(
                        self._require_connection(),
                        command.group_id,
                        command.venue_instrument_id,
                    )
                )
            except InvalidSelectionCommandError:
                self._last_requested_at = command.requested_at
                self._last_identity = identity
                self._last_heartbeat_at = command.heartbeat_at
                return
        self._last_requested_at = command.requested_at
        self._last_identity = identity
        self._last_heartbeat_at = command.heartbeat_at
        if (
            active is not None
            and active.group_id == command.group_id
            and active.primary_venue_instrument_id == command.venue_instrument_id
        ):
            await self._heartbeat_active(command)
            return
        controller.request(
            command.group_id,
            command.venue_instrument_id,
            command.requested_at,
        )

    async def _heartbeat_active(self, command: SelectionCommand) -> None:
        controller = self._require_controller()
        active = controller.active
        if active is None:
            return
        if (
            active.group_id != command.group_id
            or active.primary_venue_instrument_id != command.venue_instrument_id
            or command.heartbeat_at <= active.heartbeat_at
        ):
            return
        updated = await self._run_db(
            lambda: heartbeat_selection(
                self._require_connection(),
                active.selection_id,
                command.heartbeat_at,
            )
        )
        if not updated or not controller.heartbeat(active.selection_id, command.heartbeat_at):
            raise SelectionRuntimeError("selection heartbeat did not match the active lease")

    async def _subscribe(
        self,
        selection_id: UUID,
        group_id: str,
        primary_venue_instrument_id: str,
    ) -> object:
        reconcile_at = self._reconcile_at
        if reconcile_at is None:
            raise SelectionRuntimeError("selection activation occurred outside reconciliation")
        activated_at = max(reconcile_at, self._clock())
        instruments = await self._run_db(
            lambda: _load_group_instruments(
                self._require_connection(),
                group_id,
                primary_venue_instrument_id,
            )
        )
        transition = await self._run_db(
            lambda: activate_selection(
                self._require_connection(),
                selection_id=selection_id,
                group_id=group_id,
                primary_venue_instrument_id=primary_venue_instrument_id,
                activated_at=activated_at,
            )
        )
        await self._acknowledge_previous(transition, activated_at)
        self._emitting_selection_id = selection_id
        try:
            await self._require_streams().replace_selection(instruments)
        except BaseException:
            try:
                await self._require_streams().close()
                await self._flush_events()
                cleaned_at = self._clock()
                cleaned = await self._run_db(
                    lambda: close_selection(
                        self._require_connection(),
                        selection_id,
                        cleaned_at,
                    )
                )
                if not cleaned:
                    raise SelectionRuntimeError("failed selection activation was not cleaned")
            finally:
                self._emitting_selection_id = None
                self._active_instrument_fingerprint = ()
                self._next_membership_check = None
            raise
        self._active_instrument_fingerprint = _instrument_fingerprint(instruments)
        self._next_membership_check = activated_at + timedelta(
            seconds=ACTIVE_MEMBERSHIP_REFRESH_SECONDS
        )
        return _RuntimeSubscription(selection_id)

    async def _acknowledge_previous(
        self,
        transition: SelectionTransition,
        cleaned_at: datetime,
    ) -> None:
        previous = transition.previous
        if previous is None:
            return
        cleaned = await self._run_db(
            lambda: mark_selection_cleaned(
                self._require_connection(),
                previous.selection_id,
                cleaned_at,
            )
        )
        if not cleaned:
            raise SelectionRuntimeError("previous selection cleanup was not acknowledged")

    async def _unsubscribe(self, active: ActiveSelection) -> None:
        subscription = active.subscription
        if (
            not isinstance(subscription, _RuntimeSubscription)
            or subscription.selection_id != active.selection_id
        ):
            raise SelectionRuntimeError("selection subscription token is invalid")
        await self._require_streams().replace_selection(())
        await self._flush_events()
        cleaned_at = self._clock()
        cleaned = await self._run_db(
            lambda: close_selection(
                self._require_connection(),
                active.selection_id,
                cleaned_at,
            )
        )
        if not cleaned:
            raise SelectionRuntimeError("selection cleanup was not recorded")
        self._active_instrument_fingerprint = ()
        self._next_membership_check = None
        if self._emitting_selection_id == active.selection_id:
            self._emitting_selection_id = None

    async def _refresh_active_membership(self, now: datetime) -> None:
        controller = self._require_controller()
        active = controller.active
        due_at = self._next_membership_check
        if active is None or (due_at is not None and now < due_at):
            return
        self._next_membership_check = now + timedelta(seconds=ACTIVE_MEMBERSHIP_REFRESH_SECONDS)
        try:
            instruments = await self._run_db(
                lambda: _load_group_instruments(
                    self._require_connection(),
                    active.group_id,
                    active.primary_venue_instrument_id,
                )
            )
        except InvalidSelectionCommandError:
            await controller.stop()
            return
        fingerprint = _instrument_fingerprint(instruments)
        if fingerprint == self._active_instrument_fingerprint:
            return
        await controller.stop()
        controller.request(
            active.group_id,
            active.primary_venue_instrument_id,
            now,
        )

    async def _emit(self, event: SelectedEvent) -> None:
        await self._raise_writer_failure()
        selection_id = self._emitting_selection_id
        if selection_id is None:
            raise SelectionRuntimeError("selected event arrived without an active selection")
        await self._queue.put(_QueuedEvent(selection_id, event))

    async def _writer_loop(self) -> None:
        stop_after_batch = False
        while True:
            queued = await self._queue.get()
            if queued is None:
                self._queue.task_done()
                return
            batch = [queued]
            if self._batch_wait_seconds:
                await asyncio.sleep(self._batch_wait_seconds)
            while len(batch) < self._batch_size:
                try:
                    next_item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if next_item is None:
                    self._queue.task_done()
                    stop_after_batch = True
                    break
                batch.append(next_item)
            try:
                grouped: dict[UUID, list[SelectedEvent]] = {}
                for item in batch:
                    grouped.setdefault(item.selection_id, []).append(item.event)
                for selection_id, events in grouped.items():
                    try:
                        await self._run_db(
                            lambda selection_id=selection_id, events=events: store_selected_events(
                                self._require_connection(),
                                selection_id,
                                events,
                            )
                        )
                    except InvalidSelectionError:
                        continue
            finally:
                for _item in batch:
                    self._queue.task_done()
            if stop_after_batch:
                return

    async def _flush_events(self) -> None:
        writer = self._writer_task
        if writer is None:
            return
        join_task = asyncio.create_task(self._queue.join(), name="selected-event-flush")
        done, _pending = await asyncio.wait(
            (join_task, writer),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if writer in done:
            join_task.cancel()
            await asyncio.gather(join_task, return_exceptions=True)
            await writer
        await join_task
        if writer.done():
            await writer

    async def _raise_writer_failure(self) -> None:
        writer = self._writer_task
        if writer is not None and writer.done():
            await writer

    async def _shutdown(self) -> None:
        failures: list[BaseException] = []
        controller = self._controller
        streams = self._streams
        writer = self._writer_task
        if controller is not None:
            try:
                await controller.stop()
            except BaseException as error:
                failures.append(error)
        if streams is not None:
            try:
                await streams.close()
            except BaseException as error:
                failures.append(error)
        if writer is not None:
            try:
                if not writer.done():
                    await self._flush_events()
                    await self._queue.put(None)
                await writer
            except BaseException as error:
                failures.append(error)
            if not writer.done():
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
        connection = self._connection
        if connection is not None:
            try:
                await asyncio.to_thread(connection.close)
            except (psycopg.Error, OSError) as error:
                failures.append(error)
        self._connection = None
        self._streams = None
        self._controller = None
        self._writer_task = None
        self._emitting_selection_id = None
        self._active_instrument_fingerprint = ()
        self._next_membership_check = None
        if failures:
            raise BaseExceptionGroup("selection runtime shutdown failed", failures)

    async def _run_db(self, operation: Callable[[], _T]) -> _T:
        async with self._db_lock:
            return await asyncio.to_thread(operation)

    def _require_connection(self) -> Connection[Any]:
        if self._connection is None:
            raise SelectionRuntimeError("selection database connection is not available")
        return self._connection

    def _require_streams(self) -> _StreamManager:
        if self._streams is None:
            raise SelectionRuntimeError("selection stream manager is not available")
        return self._streams

    def _require_controller(self) -> SelectionController:
        if self._controller is None:
            raise SelectionRuntimeError("selection controller is not available")
        return self._controller


def _load_group_instruments(
    connection: Connection[Any],
    group_id: str,
    primary_venue_instrument_id: str,
) -> tuple[CatalogInstrument, ...]:
    try:
        rows = connection.execute(
            """
                SELECT instrument.venue, instrument.source_symbol, instrument.active,
                       instrument.source_status, instrument.asset_class,
                       instrument.market_type, instrument.execution_model,
                       instrument.base_asset, instrument.quote_asset,
                       instrument.settle_asset, instrument.collateral_asset,
                       instrument.quantity_unit, instrument.contract_multiplier,
                       instrument.price_tick, instrument.amount_step,
                       instrument.funding_interval_seconds, instrument.raw_definition
                FROM group_memberships AS membership
                JOIN venue_instrument_versions AS instrument
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
                ORDER BY instrument.venue, instrument.source_symbol
            """,
            (
                group_id,
                ["USD", "USDC", "USDT"],
                ["USD", "USDC", "USDT"],
                ["USD", "USDC", "USDT"],
            ),
        ).fetchall()
    except psycopg.Error:
        raise SelectionRuntimeError("selected group lookup failed") from None
    instruments = tuple(_instrument_from_row(row) for row in rows)
    if not instruments:
        raise InvalidSelectionCommandError("selected group has no eligible current instruments")
    venues = tuple(instrument.venue for instrument in instruments)
    if len(venues) != len(set(venues)):
        raise InvalidSelectionCommandError(
            "selected group has multiple eligible instruments on one Venue"
        )
    if primary_venue_instrument_id not in {
        instrument.venue_instrument_id for instrument in instruments
    }:
        raise InvalidSelectionCommandError(
            "primary instrument is not an eligible current group member"
        )
    for instrument in instruments:
        validate_selected_instrument(instrument)
    return instruments


def _instrument_from_row(row: Sequence[object]) -> CatalogInstrument:
    if len(row) != 17 or not isinstance(row[16], dict):
        raise SelectionRuntimeError("selected instrument row has an invalid shape")
    venue_text = str(row[0])
    if venue_text not in {"bitget", "hyperliquid", "aster"}:
        raise SelectionRuntimeError("selected instrument row has an invalid Venue")
    quantity_text = str(row[11])
    if quantity_text not in {"base", "contracts", "unknown"}:
        raise SelectionRuntimeError("selected instrument row has an invalid quantity unit")
    return CatalogInstrument(
        venue=cast(Venue, venue_text),
        source_symbol=str(row[1]),
        active=bool(row[2]),
        source_status=str(row[3]),
        asset_class=str(row[4]),
        market_type=str(row[5]),
        execution_model=str(row[6]),
        base_asset=str(row[7]),
        quote_asset=str(row[8]),
        settle_asset=str(row[9]),
        collateral_asset=None if row[10] is None else str(row[10]),
        quantity_unit=cast(QuantityUnit, quantity_text),
        contract_multiplier=_optional_decimal(row[12]),
        price_tick=_optional_decimal(row[13]),
        amount_step=_optional_decimal(row[14]),
        funding_interval_seconds=None if row[15] is None else int(cast(int, row[15])),
        raw_definition=cast(dict[str, object], row[16]),
    )


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _instrument_fingerprint(
    instruments: Sequence[CatalogInstrument],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                instrument.venue_instrument_id,
                instrument.definition_sha256(),
            )
            for instrument in instruments
        )
    )


def _parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require_utc(parsed, "selection timestamp")
    return parsed


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _connect(database_url: str) -> Connection[Any]:
    return psycopg.connect(database_url, autocommit=True, connect_timeout=5)


def _selected_stream_factory(
    session: aiohttp.ClientSession | None,
    emit: SelectedEmitter,
) -> _StreamManager:
    return SelectedStreamController(session, emit)
