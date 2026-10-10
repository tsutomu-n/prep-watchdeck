from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import aiohttp

from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.selected_market import (
    DepthLevel,
    SelectedContractError,
    SelectedDepth,
    SelectedDepthInvalidated,
    SelectedEvent,
    SelectedTrade,
)
from prep_watchdeck_market.sources.common import (
    CatalogSourceError,
    positive_int,
    require_list,
    require_mapping,
    timestamp_from_milliseconds,
)
from prep_watchdeck_market.sources.mexc import (
    fetch_mexc_json,
    mexc_data,
    mexc_quantity_multiplier,
)

MEXC_DEPTH_BRIDGE_INTERVAL_SECONDS = 0.15


class MexcSelectedState:
    """Absolute quantities, contiguous sequence ranges, and bounded trade id dedup."""

    def __init__(self, instrument: CatalogInstrument) -> None:
        self.instrument = instrument
        self.factor = mexc_quantity_multiplier(instrument)
        self.version: int | None = None
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.seen: OrderedDict[str, None] = OrderedDict()

    def _levels(self, values: object, book: dict[Decimal, Decimal]) -> None:
        if not isinstance(values, list):
            raise SelectedContractError("MEXC levels must be arrays")
        for row in values:
            if not isinstance(row, list) or len(row) < 2:
                raise SelectedContractError("MEXC depth row invalid")
            try:
                price, size = Decimal(str(row[0])), Decimal(str(row[1]))
            except Exception:
                raise SelectedContractError("MEXC depth numeric value invalid") from None
            if not price.is_finite() or price <= 0 or not size.is_finite() or size < 0:
                raise SelectedContractError("MEXC depth value invalid")
            if size == 0:
                book.pop(price, None)
            else:
                book[price] = size * self.factor

    def _depth(
        self, raw: dict[str, object], received_at: datetime, source: object
    ) -> SelectedDepth:
        return SelectedDepth(
            "mexc",
            self.instrument.source_symbol,
            tuple(DepthLevel(p, self.bids[p]) for p in sorted(self.bids, reverse=True)[:20]),
            tuple(DepthLevel(p, self.asks[p]) for p in sorted(self.asks)[:20]),
            timestamp_from_milliseconds(source),
            received_at,
            "sub.depth",
            {**raw, "watchdeckBasePerContract": format(self.factor, "f")},
        )

    def snapshot(self, payload: object, *, received_at: datetime) -> SelectedDepth:
        try:
            return self._snapshot(payload, received_at=received_at)
        except (CatalogSourceError, InvalidOperation, ValueError, TypeError, OverflowError):
            raise SelectedContractError("MEXC native snapshot payload invalid") from None

    def _snapshot(self, payload: object, *, received_at: datetime) -> SelectedDepth:
        row = require_mapping(mexc_data(payload), field_name="MEXC depth snapshot")
        version = positive_int(row.get("version"))
        if version is None:
            raise SelectedContractError("MEXC snapshot version missing")
        self.bids.clear()
        self.asks.clear()
        self.version = None
        self._levels(row.get("bids"), self.bids)
        self._levels(row.get("asks"), self.asks)
        event = self._depth(dict(row), received_at, row.get("timestamp"))
        self.version = version
        return event

    def parse(
        self, payload: dict[str, object], *, received_at: datetime
    ) -> tuple[SelectedEvent, ...]:
        try:
            root = require_mapping(payload, field_name="MEXC selected payload")
            return self._parse(root, received_at=received_at)
        except SelectedContractError:
            raise
        except (CatalogSourceError, InvalidOperation, ValueError, TypeError, OverflowError):
            raise SelectedContractError("MEXC native selected payload invalid") from None

    def depth_gap(self, payload: dict[str, object]) -> bool:
        if payload.get("channel") != "push.depth" or self.version is None:
            return False
        row = require_mapping(payload.get("data"), field_name="MEXC delta")
        begin = positive_int(row.get("begin", row.get("version")))
        return begin is not None and begin > self.version + 1

    def bridge(self, commits: object, pending: dict[str, object], received_at: datetime) -> None:
        """Replay only a complete native commit chain before the pending WS update."""
        rows = require_list(mexc_data(commits), field_name="MEXC depth commits")
        if not rows or len(rows) > 1000 or self.version is None:
            raise SelectedContractError("MEXC depth commit bridge invalid")
        parsed = []
        for value in rows:
            row = require_mapping(value, field_name="MEXC depth commit")
            version = positive_int(row.get("version"))
            if version is None:
                raise SelectedContractError("MEXC depth commit version invalid")
            parsed.append((version, row))
        versions = [version for version, _ in parsed]
        # The endpoint's examples are descending; its maintenance guide says ascending.
        # Accept either monotonic order, reject duplicate or mixed-order evidence.
        if len(set(versions)) != len(versions) or versions not in (
            sorted(versions),
            sorted(versions, reverse=True),
        ):
            raise SelectedContractError("MEXC depth commit order invalid")
        row = require_mapping(pending.get("data"), field_name="MEXC pending depth")
        begin = positive_int(row.get("begin", row.get("version")))
        if begin is None:
            raise SelectedContractError("MEXC pending depth version invalid")
        for version, commit in sorted(parsed, key=lambda item: item[0]):
            if version <= self.version or version >= begin:
                continue
            self.parse(
                {
                    "channel": "push.depth",
                    "symbol": self.instrument.source_symbol,
                    "data": commit,
                    "ts": commit.get("cts"),
                },
                received_at=received_at,
            )
        if self.version != begin - 1:
            raise SelectedContractError("MEXC depth commit bridge incomplete")

    def _parse(
        self, payload: dict[str, object], *, received_at: datetime
    ) -> tuple[SelectedEvent, ...]:
        channel = payload.get("channel")
        if channel not in {"push.depth", "push.deal"}:
            return ()
        if payload.get("symbol") != self.instrument.source_symbol:
            raise SelectedContractError("MEXC selected symbol mismatch")
        if channel == "push.depth":
            row = require_mapping(payload.get("data"), field_name="MEXC delta")
            begin, end = positive_int(row.get("begin")), positive_int(row.get("end"))
            if "begin" not in row and "end" not in row:
                # Unmerged compress=false frames carry a single sequence version.
                begin = end = positive_int(row.get("version"))
            if self.version is None or begin is None or end is None or begin > end:
                self.version = None
                raise SelectedContractError("MEXC depth invalid sequence")
            if end <= self.version:
                return ()
            if not begin <= self.version + 1 <= end:
                self.version = None
                self.bids.clear()
                self.asks.clear()
                raise SelectedContractError("MEXC depth sequence gap")
            try:
                self._levels(row.get("bids"), self.bids)
                self._levels(row.get("asks"), self.asks)
                event = self._depth(payload, received_at, payload.get("ts"))
            except (ValueError, SelectedContractError):
                self.version = None
                self.bids.clear()
                self.asks.clear()
                raise
            self.version = end
            return (event,)
        data = payload.get("data")
        rows = data if isinstance(data, list) else [data]
        trades: list[SelectedEvent] = []
        for value in rows:
            row = require_mapping(value, field_name="MEXC deal")
            trade_id = row.get("i")
            if not isinstance(trade_id, (str, int)) or isinstance(trade_id, bool):
                raise SelectedContractError("MEXC deal id absent")
            key = str(trade_id)
            if key in self.seen:
                continue
            side = row.get("T")
            if side not in {1, 2}:
                raise SelectedContractError("MEXC deal direction unknown")
            trade = SelectedTrade(
                "mexc",
                self.instrument.source_symbol,
                key,
                "buy" if side == 1 else "sell",
                Decimal(str(row.get("p"))),
                Decimal(str(row.get("v"))) * self.factor,
                timestamp_from_milliseconds(row.get("t")),
                received_at,
                "sub.deal",
                {**row, "watchdeckBasePerContract": format(self.factor, "f")},
            )
            self.seen[key] = None
            if len(self.seen) > 10000:
                self.seen.popitem(last=False)
            trades.append(trade)
        return tuple(trades)


async def produce_mexc_selected(
    session,
    instrument,
    emit,
    stop_event,
    *,
    ws_factory=None,
    receive_poll_seconds=0.25,
    reconnect_delay_seconds=1.0,
    clock=None,
):
    if session is None:
        raise ValueError("MEXC selected stream requires snapshot session")
    connect = ws_factory or (lambda url: session.ws_connect(url, heartbeat=15))
    from prep_watchdeck_market.sources.mexc_stream_common import (
        MexcStreamFailure,
        decode_message,
        mexc_subscription_pacer,
        source_call,
        source_connection,
    )

    now = clock or (lambda: datetime.now(UTC))
    next_bridge_at = 0.0
    while not stop_event.is_set():
        await emit(
            SelectedDepthInvalidated(
                "mexc", instrument.source_symbol, now(), "sub.depth", {"reason": "snapshot_resync"}
            )
        )
        state = MexcSelectedState(instrument)
        failure_code = "socket_disconnected"
        synchronized = False
        try:
            async with source_connection(connect) as websocket:
                await mexc_subscription_pacer().acquire()
                await source_call(
                    websocket.send_json(
                        {
                            "method": "sub.depth",
                            "param": {"symbol": instrument.source_symbol, "compress": True},
                        }
                    )
                )
                await mexc_subscription_pacer().acquire()
                await source_call(
                    websocket.send_json(
                        {
                            "method": "sub.deal",
                            "param": {"symbol": instrument.source_symbol, "compress": False},
                        }
                    )
                )
                # Subscribe before snapshot so queued deltas bridge snapshot.version.
                snapshot = await source_call(
                    fetch_mexc_json(
                        session,
                        "/api/v1/contract/depth/" + instrument.source_symbol,
                        params={"limit": "1000"},
                    )
                )
                try:
                    state.snapshot(snapshot, received_at=now())
                except SelectedContractError:
                    raise MexcStreamFailure("MEXC snapshot decode failed") from None
                deals = await source_call(
                    fetch_mexc_json(
                        session,
                        "/api/v1/contract/deals/" + instrument.source_symbol,
                        params={"limit": "100"},
                    )
                )
                try:
                    events = state.parse(
                        {
                            "channel": "push.deal",
                            "symbol": instrument.source_symbol,
                            "data": mexc_data(deals),
                        },
                        received_at=now(),
                    )
                except (SelectedContractError, CatalogSourceError):
                    raise MexcStreamFailure("MEXC deal snapshot decode failed") from None
                for event in events:
                    await emit(event)
                ping_at = asyncio.get_running_loop().time() + 15
                while not stop_event.is_set():
                    if asyncio.get_running_loop().time() >= ping_at:
                        await source_call(websocket.send_json({"method": "ping"}))
                        ping_at = asyncio.get_running_loop().time() + 15
                    try:
                        msg = await asyncio.wait_for(
                            source_call(websocket.receive()), timeout=receive_poll_seconds
                        )
                    except TimeoutError:
                        continue
                    if msg.type in {
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    }:
                        break
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    payload = decode_message(msg)
                    bridge = None
                    try:
                        gap = state.depth_gap(payload)
                    except CatalogSourceError:
                        raise MexcStreamFailure("MEXC selected stream decode failed") from None
                    if gap:
                        failure_code = "depth_sequence_gap"
                        if synchronized:
                            await emit(
                                SelectedDepthInvalidated(
                                    "mexc",
                                    instrument.source_symbol,
                                    now(),
                                    "sub.depth",
                                    {"reason": "depth_sequence_gap", "lastVersion": state.version},
                                )
                            )
                        delay = next_bridge_at - asyncio.get_running_loop().time()
                        if delay > 0:
                            await asyncio.sleep(delay)
                        next_bridge_at = (
                            asyncio.get_running_loop().time() + MEXC_DEPTH_BRIDGE_INTERVAL_SECONDS
                        )
                        bridge = await source_call(
                            fetch_mexc_json(
                                session,
                                "/api/v1/contract/depth_commits/"
                                + instrument.source_symbol
                                + "/1000",
                            )
                        )
                    try:
                        if bridge is not None:
                            state.bridge(bridge, payload, now())
                        events = state.parse(payload, received_at=now())
                    except (SelectedContractError, CatalogSourceError):
                        raise MexcStreamFailure("MEXC selected stream decode failed") from None
                    for event in events:
                        if isinstance(event, SelectedDepth):
                            evidence = dict(event.raw_payload)
                            if not synchronized:
                                evidence["watchdeckSnapshot"] = snapshot
                            if bridge is not None:
                                evidence["watchdeckDepthCommits"] = bridge
                            event = replace(event, raw_payload=evidence)
                            synchronized = True
                            failure_code = "socket_disconnected"
                        await emit(event)
        except MexcStreamFailure:
            if failure_code != "depth_sequence_gap":
                failure_code = "native_source_invalid_or_unavailable"
            # Discard book and reconnect with a fresh snapshot; never emit stale deltas.
            pass
        finally:
            if not stop_event.is_set():
                await emit(
                    SelectedDepthInvalidated(
                        "mexc",
                        instrument.source_symbol,
                        now(),
                        "sub.depth",
                        {"reason": "stream_disconnected_or_invalid", "errorCode": failure_code},
                    )
                )
        if not stop_event.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=reconnect_delay_seconds)
