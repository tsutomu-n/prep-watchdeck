from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.selected_market import SelectedTrade
from prep_watchdeck_market.selected_store import (
    SelectedStoreResult,
    SelectionLease,
    SelectionTransition,
)
from prep_watchdeck_market.selection_runtime import (
    SelectionRuntime,
    read_selection_command,
)
from prep_watchdeck_market.sources.selected_streams import SelectedEmitter


def test_selection_command_runtime_switches_safely_with_one_bounded_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        started_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        clock = _MutableClock(started_at + timedelta(milliseconds=600))
        command_path = tmp_path / "control" / "selection.json"
        command_path.parent.mkdir(parents=True)
        connection = _FakeConnection()
        log: list[str] = []
        active_lease: SelectionLease | None = None

        groups = {
            "crypto:BTC": _group("BTC"),
            "crypto:ETH": _group("ETH"),
        }

        def fake_load(
            _connection: object,
            group_id: str,
            primary_venue_instrument_id: str,
        ) -> tuple[CatalogInstrument, ...]:
            instruments = groups[group_id]
            assert primary_venue_instrument_id in {item.venue_instrument_id for item in instruments}
            return instruments

        def fake_activate(
            actual_connection: object,
            *,
            selection_id: UUID,
            group_id: str,
            primary_venue_instrument_id: str,
            activated_at: datetime,
        ) -> SelectionTransition:
            nonlocal active_lease
            assert actual_connection is connection
            previous = active_lease
            log.append(f"activate:{group_id.removeprefix('crypto:')}")
            primary_version = 1 if primary_venue_instrument_id.startswith("bitget:") else 2
            active_lease = SelectionLease(
                selection_id=selection_id,
                group_id=group_id,
                primary_venue_instrument_version_id=primary_version,
                activated_at=activated_at,
                heartbeat_at=activated_at,
                expires_at=activated_at + timedelta(minutes=15),
                superseded_at=None,
                cleanup_deadline_at=None,
                cleaned_at=None,
            )
            return SelectionTransition(current=active_lease, previous=previous)

        def fake_mark_cleaned(
            actual_connection: object,
            selection_id: UUID,
            _cleaned_at: datetime,
        ) -> bool:
            assert actual_connection is connection
            assert selection_id is not None
            log.append("clean:previous")
            return True

        def fake_store(
            actual_connection: object,
            selection_id: UUID,
            events: list[object],
        ) -> SelectedStoreResult:
            assert actual_connection is connection
            assert events
            log.append(f"store:{selection_id}")
            connection.writer_connections.add(id(actual_connection))
            return SelectedStoreResult(0, len(events), len(events), len(events), len(events))

        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime._load_group_instruments", fake_load
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime.activate_selection", fake_activate
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime.mark_selection_cleaned", fake_mark_cleaned
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime.close_selection",
            lambda _connection, _selection_id, _cleaned_at: True,
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime.store_selected_events", fake_store
        )

        fake_streams: _FakeStreams | None = None

        def stream_factory(_session: object, emit: SelectedEmitter) -> _FakeStreams:
            nonlocal fake_streams
            fake_streams = _FakeStreams(emit, clock, log)
            return fake_streams

        _write_command(
            command_path,
            group_id="crypto:BTC",
            primary="bitget:BTCUSDT",
            requested_at=started_at,
            heartbeat_at=started_at,
        )
        runtime = SelectionRuntime(
            "postgresql://not-used",
            tmp_path,
            None,
            connection_factory=lambda _url: cast(Any, connection),
            stream_factory=stream_factory,
            poll_seconds=0.01,
            batch_wait_seconds=0,
            clock=clock,
        )
        stop_event = asyncio.Event()
        task = asyncio.create_task(runtime.run_forever(stop_event))
        await _wait_until(lambda: "open:BTC" in log)

        malformed: dict[str, object] = {
            "schemaVersion": 1,
            "groupId": "crypto:ETH",
            "venueInstrumentId": "bitget:ETHUSDT",
            "requestedAt": (started_at + timedelta(seconds=2)).isoformat(),
            "heartbeatAt": (started_at + timedelta(seconds=2)).isoformat(),
            "credential": "must-not-be-read",
        }
        _atomic_write(command_path, malformed)
        await asyncio.sleep(0.03)
        assert [entry for entry in log if entry.startswith("open:")] == ["open:BTC"]

        clock.value = started_at + timedelta(seconds=1, milliseconds=600)
        _write_command(
            command_path,
            group_id="crypto:ETH",
            primary="bitget:ETHUSDT",
            requested_at=started_at + timedelta(seconds=1),
            heartbeat_at=started_at + timedelta(seconds=1),
        )
        await _wait_until(lambda: "open:ETH" in log)

        _write_command(
            command_path,
            group_id="crypto:BTC",
            primary="bitget:BTCUSDT",
            requested_at=started_at,
            heartbeat_at=started_at + timedelta(seconds=1),
        )
        await asyncio.sleep(0.03)
        assert [entry for entry in log if entry.startswith("open:")] == [
            "open:BTC",
            "open:ETH",
        ]

        stop_event.set()
        await asyncio.wait_for(task, timeout=1)
        assert fake_streams is not None
        assert connection.close_calls == 1
        assert connection.writer_connections == {id(connection)}
        assert log.index("close:BTC") < log.index("activate:ETH")
        assert log.index("activate:ETH") < log.index("clean:previous")
        assert log.index("clean:previous") < log.index("open:ETH")
        assert log[-1] == "close:ETH"

        non_utc: dict[str, object] = {
            "schemaVersion": 1,
            "groupId": "crypto:BTC",
            "venueInstrumentId": "bitget:BTCUSDT",
            "requestedAt": "2026-08-14T12:00:00",
            "heartbeatAt": "2026-08-14T12:00:00",
        }
        _atomic_write(command_path, non_utc)
        assert read_selection_command(command_path, now=clock()) is None
        future = dict(non_utc)
        future["requestedAt"] = "2026-08-14T12:00:03Z"
        future["heartbeatAt"] = "2026-08-14T12:00:03Z"
        _atomic_write(command_path, future)
        assert read_selection_command(command_path, now=clock()) is None

    asyncio.run(scenario())


def test_expired_selection_cleans_lease_and_same_command_heartbeat_reactivates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        requested_at = datetime(2026, 8, 14, 15, 14, tzinfo=UTC)
        clock = _MutableClock(requested_at + timedelta(milliseconds=600))
        command_path = tmp_path / "control" / "selection.json"
        command_path.parent.mkdir(parents=True)
        connection = _FakeConnection()
        log: list[str] = []
        active_lease: SelectionLease | None = None
        activation_ids: list[UUID] = []
        cleaned_ids: list[UUID] = []

        def fake_load(
            _connection: object,
            group_id: str,
            primary_venue_instrument_id: str,
        ) -> tuple[CatalogInstrument, ...]:
            assert group_id == "crypto:ETH"
            instruments = _group("ETH")
            assert primary_venue_instrument_id in {item.venue_instrument_id for item in instruments}
            return instruments

        def fake_activate(
            actual_connection: object,
            *,
            selection_id: UUID,
            group_id: str,
            primary_venue_instrument_id: str,
            activated_at: datetime,
        ) -> SelectionTransition:
            nonlocal active_lease
            assert actual_connection is connection
            assert active_lease is None
            activation_ids.append(selection_id)
            active_lease = SelectionLease(
                selection_id=selection_id,
                group_id=group_id,
                primary_venue_instrument_version_id=1,
                activated_at=activated_at,
                heartbeat_at=activated_at,
                expires_at=activated_at + timedelta(minutes=15),
                superseded_at=None,
                cleanup_deadline_at=None,
                cleaned_at=None,
            )
            return SelectionTransition(current=active_lease, previous=None)

        def fake_close(
            actual_connection: object,
            selection_id: UUID,
            cleaned_at: datetime,
        ) -> bool:
            nonlocal active_lease
            assert actual_connection is connection
            assert active_lease is not None
            assert active_lease.selection_id == selection_id
            if selection_id == activation_ids[0]:
                assert cleaned_at >= active_lease.expires_at
            cleaned_ids.append(selection_id)
            active_lease = None
            return True

        def fake_store(
            _connection: object,
            _selection_id: UUID,
            events: list[object],
        ) -> SelectedStoreResult:
            return SelectedStoreResult(0, len(events), len(events), len(events), len(events))

        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime._load_group_instruments", fake_load
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime.activate_selection", fake_activate
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime.close_selection",
            fake_close,
            raising=False,
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime.store_selected_events", fake_store
        )

        _write_command(
            command_path,
            group_id="crypto:ETH",
            primary="bitget:ETHUSDT",
            requested_at=requested_at,
            heartbeat_at=requested_at,
        )
        runtime = SelectionRuntime(
            "postgresql://not-used",
            tmp_path,
            None,
            connection_factory=lambda _url: cast(Any, connection),
            stream_factory=lambda _session, emit: _FakeStreams(emit, clock, log),
            poll_seconds=0.005,
            batch_wait_seconds=0,
            clock=clock,
        )
        stop_event = asyncio.Event()
        task = asyncio.create_task(runtime.run_forever(stop_event))
        await _wait_until(lambda: len(activation_ids) == 1)

        clock.value = requested_at + timedelta(minutes=15, seconds=1)
        await _wait_until(lambda: cleaned_ids == activation_ids[:1])

        _write_command(
            command_path,
            group_id="crypto:ETH",
            primary="bitget:ETHUSDT",
            requested_at=requested_at,
            heartbeat_at=clock.value,
        )
        await _wait_until(
            lambda: [entry for entry in log if entry == "open:ETH"] == ["open:ETH", "open:ETH"]
        )

        assert len(activation_ids) == 2
        assert activation_ids[1] != activation_ids[0]
        assert cleaned_ids == activation_ids[:1]

        stop_event.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())


def test_failed_stream_open_flushes_events_and_closes_new_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        requested_at = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)
        clock = _MutableClock(requested_at + timedelta(milliseconds=600))
        command_path = tmp_path / "control" / "selection.json"
        command_path.parent.mkdir(parents=True)
        connection = _FakeConnection()
        log: list[str] = []
        active_lease: SelectionLease | None = None

        def fake_activate(
            _connection: object,
            *,
            selection_id: UUID,
            group_id: str,
            primary_venue_instrument_id: str,
            activated_at: datetime,
        ) -> SelectionTransition:
            nonlocal active_lease
            assert active_lease is None
            active_lease = SelectionLease(
                selection_id=selection_id,
                group_id=group_id,
                primary_venue_instrument_version_id=1,
                activated_at=activated_at,
                heartbeat_at=activated_at,
                expires_at=activated_at + timedelta(minutes=15),
                superseded_at=None,
                cleanup_deadline_at=None,
                cleaned_at=None,
            )
            log.append("lease:activate")
            return SelectionTransition(current=active_lease, previous=None)

        def fake_close(
            _connection: object,
            selection_id: UUID,
            _cleaned_at: datetime,
        ) -> bool:
            nonlocal active_lease
            assert active_lease is not None
            assert selection_id == active_lease.selection_id
            assert "store:event" in log
            active_lease = None
            log.append("lease:close")
            return True

        def fake_store(
            _connection: object,
            _selection_id: UUID,
            events: list[object],
        ) -> SelectedStoreResult:
            assert len(events) == 1
            log.append("store:event")
            return SelectedStoreResult(0, 1, 1, 1, 1)

        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime._load_group_instruments",
            lambda _connection, _group_id, _primary: _group("ETH"),
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime.activate_selection", fake_activate
        )
        monkeypatch.setattr("prep_watchdeck_market.selection_runtime.close_selection", fake_close)
        monkeypatch.setattr(
            "prep_watchdeck_market.selection_runtime.store_selected_events", fake_store
        )

        _write_command(
            command_path,
            group_id="crypto:ETH",
            primary="bitget:ETHUSDT",
            requested_at=requested_at,
            heartbeat_at=requested_at,
        )
        runtime = SelectionRuntime(
            "postgresql://not-used",
            tmp_path,
            None,
            connection_factory=lambda _url: cast(Any, connection),
            stream_factory=lambda _session, emit: _FailingStreams(emit, clock, log),
            poll_seconds=0.005,
            batch_wait_seconds=0,
            clock=clock,
        )

        with pytest.raises(RuntimeError, match="stream open failed"):
            await runtime.run_forever(asyncio.Event())

        assert active_lease is None
        assert log.index("close:ETH") < log.index("store:event") < log.index("lease:close")
        assert connection.close_calls == 1

    asyncio.run(scenario())


@dataclass
class _MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value


class _FakeConnection:
    def __init__(self) -> None:
        self.close_calls = 0
        self.writer_connections: set[int] = set()

    def close(self) -> None:
        self.close_calls += 1


class _FakeStreams:
    def __init__(self, emit, clock: _MutableClock, log: list[str]) -> None:
        self._emit = emit
        self._clock = clock
        self._log = log
        self._active_base: str | None = None

    async def replace_selection(self, instruments: Sequence[CatalogInstrument]) -> None:
        if not instruments:
            await self.close()
            return
        assert self._active_base is None
        base = instruments[0].base_asset
        self._active_base = base
        self._log.append(f"open:{base}")
        first = instruments[0]
        await self._emit(
            SelectedTrade(
                venue=first.venue,
                source_symbol=first.source_symbol,
                trade_id=f"{base}-trade",
                side="buy",
                price=Decimal("100"),
                size_base=Decimal("1"),
                source_at=self._clock(),
                received_at=self._clock(),
                source_channel="fake-trade",
                raw_payload={"base": base},
            )
        )

    async def close(self) -> None:
        if self._active_base is not None:
            self._log.append(f"close:{self._active_base}")
            self._active_base = None


class _FailingStreams(_FakeStreams):
    async def replace_selection(self, instruments: Sequence[CatalogInstrument]) -> None:
        await super().replace_selection(instruments)
        if instruments:
            raise RuntimeError("stream open failed")


def _group(base: str) -> tuple[CatalogInstrument, ...]:
    return (
        _instrument("bitget", f"{base}USDT", base),
        _instrument("hyperliquid", base, base),
        _instrument("aster", f"{base}USDT", base),
    )


def _instrument(venue: str, symbol: str, base: str) -> CatalogInstrument:
    collateral = "USDC" if venue == "hyperliquid" else "USDT"
    return CatalogInstrument(
        venue=venue,  # type: ignore[arg-type]
        source_symbol=symbol,
        active=True,
        source_status="normal",
        asset_class="crypto",
        market_type="linear_perpetual",
        execution_model="clob",
        base_asset=base,
        quote_asset="USD" if venue == "hyperliquid" else "USDT",
        settle_asset=collateral,
        collateral_asset=collateral,
        quantity_unit="base",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.1"),
        amount_step=Decimal("0.001"),
        funding_interval_seconds=3_600,
        raw_definition={"symbol": symbol},
    )


async def _wait_until(predicate, *, timeout_seconds: float = 0.5) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0)


def _write_command(
    path: Path,
    *,
    group_id: str,
    primary: str,
    requested_at: datetime,
    heartbeat_at: datetime,
) -> None:
    _atomic_write(
        path,
        {
            "schemaVersion": 1,
            "groupId": group_id,
            "venueInstrumentId": primary,
            "requestedAt": requested_at.isoformat().replace("+00:00", "Z"),
            "heartbeatAt": heartbeat_at.isoformat().replace("+00:00", "Z"),
        },
    )


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)
