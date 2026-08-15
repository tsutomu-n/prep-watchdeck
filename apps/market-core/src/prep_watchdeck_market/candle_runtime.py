from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Collection, Coroutine, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import aiohttp
import psycopg
from loguru import logger
from psycopg import Connection

from prep_watchdeck_market.candle_store import CandleStoreResult, upsert_candles
from prep_watchdeck_market.candles import Candle1m, CandleParseError
from prep_watchdeck_market.models import CatalogInstrument, Venue
from prep_watchdeck_market.sources.aster_candle_stream import produce_aster_candles
from prep_watchdeck_market.sources.bitget_candles import parse_bitget_finished_candles
from prep_watchdeck_market.sources.hyperliquid_candle_stream import (
    produce_hyperliquid_candles,
)

BITGET_FINISHED_CANDLES_URL = "https://api.bitget.com/api/v2/mix/market/history-candles"
BITGET_SWEEP_SECONDS = 120.0
BITGET_MAX_CONCURRENCY = 4
CANDLE_QUEUE_SIZE = 20_000
CANDLE_BATCH_SIZE = 250
CANDLE_FLUSH_SECONDS = 1.0

InstrumentSupplier = Callable[[], Sequence[CatalogInstrument]]
ActiveInstrumentIdSupplier = Callable[[], Collection[str]]
CurrentVersionStartSupplier = Callable[[], Mapping[str, datetime]]
UtcClock = Callable[[], datetime]
CandleEmitter = Callable[[Candle1m], Awaitable[None]]
WsProducer = Callable[
    [
        aiohttp.ClientSession | None,
        Collection[CatalogInstrument],
        CandleEmitter,
        asyncio.Event,
    ],
    Coroutine[Any, Any, None],
]


class CandleRuntime:
    """Collect and persist closed 1-minute candles with one database connection."""

    def __init__(
        self,
        database_url: str,
        session: aiohttp.ClientSession,
        instrument_supplier: InstrumentSupplier,
        *,
        catalog_update_lock: asyncio.Lock,
        current_version_starts: CurrentVersionStartSupplier,
        utc_clock: UtcClock | None = None,
    ) -> None:
        self._database_url = database_url
        self._session = session
        self._instrument_supplier = instrument_supplier
        self._catalog_update_lock = catalog_update_lock
        self._current_version_starts = current_version_starts
        self._utc_clock = utc_clock or (lambda: datetime.now(UTC))

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        connection = await asyncio.to_thread(
            psycopg.connect,
            self._database_url,
            connect_timeout=5,
        )
        writer = CandleBatchWriter(
            connection,
            catalog_update_lock=self._catalog_update_lock,
            active_instrument_ids=self._active_instrument_ids,
            current_version_starts=self._current_version_starts,
        )
        writer_task = asyncio.create_task(writer.run(), name="candle-batch-writer")
        producer_tasks = (
            asyncio.create_task(
                self._run_bitget_poller(writer, stop_event), name="bitget-candle-poller"
            ),
            asyncio.create_task(
                self._run_ws_supervisor(
                    "hyperliquid",
                    produce_hyperliquid_candles,
                    writer,
                    stop_event,
                ),
                name="hyperliquid-candle-supervisor",
            ),
            asyncio.create_task(
                self._run_ws_supervisor(
                    "aster",
                    produce_aster_candles,
                    writer,
                    stop_event,
                ),
                name="aster-candle-supervisor",
            ),
        )
        stop_task = asyncio.create_task(stop_event.wait(), name="candle-runtime-stop")
        try:
            done, _ = await asyncio.wait(
                (writer_task, *producer_tasks, stop_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if writer_task in done:
                await writer_task
                if not stop_event.is_set():
                    raise RuntimeError("candle batch writer stopped unexpectedly")
            for producer_task in producer_tasks:
                if producer_task in done:
                    await producer_task
                    if not stop_event.is_set():
                        raise RuntimeError("candle producer stopped unexpectedly")
        finally:
            stop_task.cancel()
            for producer_task in producer_tasks:
                producer_task.cancel()
            await asyncio.gather(stop_task, *producer_tasks, return_exceptions=True)
            try:
                if not writer_task.done():
                    await writer.close()
                await writer_task
            finally:
                await asyncio.to_thread(connection.close)

    async def _run_bitget_poller(
        self,
        writer: CandleBatchWriter,
        stop_event: asyncio.Event,
    ) -> None:
        loop = asyncio.get_running_loop()
        next_sweep = loop.time()
        while not stop_event.is_set():
            if await _wait_or_stop(stop_event, max(0.0, next_sweep - loop.time())):
                return
            await poll_bitget_sweep(
                self._session,
                self._instrument_supplier(),
                writer,
                stop_event,
                utc_clock=self._utc_clock,
            )
            next_sweep += BITGET_SWEEP_SECONDS
            if next_sweep < loop.time():
                next_sweep = loop.time()

    async def _run_ws_supervisor(
        self,
        venue: Venue,
        producer: WsProducer,
        writer: CandleBatchWriter,
        stop_event: asyncio.Event,
    ) -> None:
        current_fingerprint: tuple[tuple[str, str], ...] = ()
        producer_task: asyncio.Task[None] | None = None

        async def emit(candle: Candle1m) -> None:
            await writer.add((candle,))

        try:
            while not stop_event.is_set():
                instruments = _active_venue_instruments(self._instrument_supplier(), venue)
                fingerprint = tuple(
                    (instrument.venue_instrument_id, instrument.definition_sha256())
                    for instrument in instruments
                )
                if fingerprint != current_fingerprint:
                    if producer_task is not None:
                        producer_task.cancel()
                        await asyncio.gather(producer_task, return_exceptions=True)
                    current_fingerprint = fingerprint
                    producer_task = (
                        asyncio.create_task(
                            producer(self._session, instruments, emit, stop_event),
                            name=f"{venue}-candle-stream",
                        )
                        if instruments
                        else None
                    )
                if producer_task is not None and producer_task.done():
                    await producer_task
                    if not stop_event.is_set():
                        raise RuntimeError(f"{venue} candle producer stopped unexpectedly")
                if await _wait_or_stop(stop_event, 5.0):
                    return
        finally:
            if producer_task is not None:
                producer_task.cancel()
                await asyncio.gather(producer_task, return_exceptions=True)

    def _active_instrument_ids(self) -> frozenset[str]:
        return frozenset(
            instrument.venue_instrument_id
            for instrument in self._instrument_supplier()
            if instrument.active and instrument.market_type == "linear_perpetual"
        )


class CandleBatchWriter:
    def __init__(
        self,
        connection: Connection[Any],
        *,
        batch_size: int = CANDLE_BATCH_SIZE,
        flush_seconds: float = CANDLE_FLUSH_SECONDS,
        catalog_update_lock: asyncio.Lock | None = None,
        active_instrument_ids: ActiveInstrumentIdSupplier | None = None,
        current_version_starts: CurrentVersionStartSupplier | None = None,
    ) -> None:
        if not 0 < batch_size <= CANDLE_BATCH_SIZE:
            raise ValueError("candle batch_size must be between 1 and 250")
        if not 0 < flush_seconds <= CANDLE_FLUSH_SECONDS:
            raise ValueError("candle flush_seconds must be between 0 and 1 second")
        if current_version_starts is not None and catalog_update_lock is None:
            raise ValueError("current candle versions require the catalog update lock")
        self._connection = connection
        self._batch_size = batch_size
        self._flush_seconds = flush_seconds
        self._catalog_update_lock = catalog_update_lock
        self._active_instrument_ids = active_instrument_ids
        self._current_version_starts = current_version_starts
        self._queue: asyncio.Queue[Candle1m | None] = asyncio.Queue(maxsize=CANDLE_QUEUE_SIZE)
        self._closed = False

    async def add(self, candles: Sequence[Candle1m]) -> None:
        if self._closed:
            raise RuntimeError("candle writer is closed")
        if self._current_version_starts is None:
            eligible = tuple(candles)
        else:
            assert self._catalog_update_lock is not None
            async with self._catalog_update_lock:
                eligible = _candles_covered_by_current_versions(
                    candles,
                    self._current_version_starts(),
                )
        for candle in eligible:
            await self._queue.put(candle)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)

    async def run(self) -> None:
        pending: dict[tuple[Venue, str, datetime], Candle1m] = {}
        received = 0
        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=self._flush_seconds)
            except TimeoutError:
                await self._flush(pending, received=received)
                received = 0
                continue
            if item is None:
                await self._flush(pending, received=received)
                return
            received += 1
            previous = pending.get(item.storage_key)
            pending[item.storage_key] = _preferred_candle(previous, item)
            if len(pending) >= self._batch_size:
                await self._flush(pending, received=received)
                received = 0

    async def _flush(
        self,
        pending: dict[tuple[Venue, str, datetime], Candle1m],
        *,
        received: int,
    ) -> CandleStoreResult | None:
        if not pending:
            return None
        if self._catalog_update_lock is None:
            return await self._flush_current(pending, received=received)
        async with self._catalog_update_lock:
            return await self._flush_current(pending, received=received)

    async def _flush_current(
        self,
        pending: dict[tuple[Venue, str, datetime], Candle1m],
        *,
        received: int,
    ) -> CandleStoreResult | None:
        unique = len(pending)
        deduplicated = unique
        active_ids = (
            None if self._active_instrument_ids is None else set(self._active_instrument_ids())
        )
        current_version_starts = (
            None if self._current_version_starts is None else self._current_version_starts()
        )
        batch = tuple(
            item
            for item in sorted(pending.values(), key=lambda item: item.storage_key)
            if active_ids is None or item.venue_instrument_id in active_ids
            if current_version_starts is None
            or _candle_is_covered_by_current_version(item, current_version_starts)
        )
        pending.clear()
        filtered = unique - len(batch)
        if not batch:
            _log_candle_flush(
                received=received,
                deduplicated=deduplicated,
                stored=0,
                ignored=filtered,
            )
            return None
        persist_task = asyncio.create_task(
            asyncio.to_thread(upsert_candles, self._connection, batch),
            name="candle-batch-persist",
        )
        try:
            result = await asyncio.shield(persist_task)
        except asyncio.CancelledError:
            await asyncio.gather(persist_task, return_exceptions=True)
            raise
        except Exception:
            _log_candle_flush(
                received=received,
                deduplicated=deduplicated,
                stored=0,
                ignored=filtered,
                error_code="persistence_error",
            )
            raise
        _log_candle_flush(
            received=received,
            deduplicated=deduplicated,
            stored=result.stored,
            ignored=filtered + result.ignored,
        )
        return result


async def poll_bitget_sweep(
    session: aiohttp.ClientSession,
    instruments: Sequence[CatalogInstrument],
    writer: CandleBatchWriter,
    stop_event: asyncio.Event,
    *,
    utc_clock: UtcClock | None = None,
    sweep_seconds: float = BITGET_SWEEP_SECONDS,
    max_concurrency: int = BITGET_MAX_CONCURRENCY,
) -> None:
    if sweep_seconds < 0 or not 0 < max_concurrency <= BITGET_MAX_CONCURRENCY:
        raise ValueError("Bitget candle sweep limits are invalid")
    active = _active_bitget_instruments(instruments)
    if not active:
        return
    now = (utc_clock or (lambda: datetime.now(UTC)))()
    _require_aware(now)
    end_time = now.replace(second=0, microsecond=0)
    end_time_ms = int(end_time.timestamp() * 1_000)
    loop = asyncio.get_running_loop()
    started = loop.time()
    interval = sweep_seconds / len(active)
    running: set[asyncio.Task[None]] = set()
    try:
        for index, instrument in enumerate(active):
            if await _wait_or_stop(
                stop_event,
                max(0.0, started + index * interval - loop.time()),
            ):
                return
            while len(running) >= max_concurrency:
                done, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    await task
            running.add(
                asyncio.create_task(
                    _fetch_bitget_instrument(
                        session,
                        instrument,
                        writer,
                        end_time_ms=end_time_ms,
                        utc_clock=utc_clock,
                    ),
                    name=f"bitget-candle-{instrument.source_symbol}",
                )
            )
        if running:
            await asyncio.gather(*running)
    finally:
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)


async def _fetch_bitget_instrument(
    session: aiohttp.ClientSession,
    instrument: CatalogInstrument,
    writer: CandleBatchWriter,
    *,
    end_time_ms: int,
    utc_clock: UtcClock | None,
) -> None:
    try:
        async with session.get(
            BITGET_FINISHED_CANDLES_URL,
            params={
                "symbol": instrument.source_symbol,
                "productType": "USDT-FUTURES",
                "granularity": "1m",
                "endTime": str(end_time_ms),
                "limit": "3",
            },
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        observed_at = (utc_clock or (lambda: datetime.now(UTC)))()
        candles = parse_bitget_finished_candles(
            payload,
            source_symbol=instrument.source_symbol,
            observed_at=observed_at,
        )
    except (aiohttp.ClientError, TimeoutError, ValueError, CandleParseError) as exc:
        logger.warning(
            "Bitget candle fetch skipped symbol={symbol} errorType={error_type}",
            symbol=instrument.source_symbol,
            error_type=type(exc).__name__,
        )
        return
    await writer.add(candles)


def _active_bitget_instruments(
    instruments: Sequence[CatalogInstrument],
) -> tuple[CatalogInstrument, ...]:
    return tuple(
        sorted(
            (
                instrument
                for instrument in instruments
                if instrument.venue == "bitget"
                and instrument.active
                and instrument.market_type == "linear_perpetual"
            ),
            key=lambda instrument: instrument.source_symbol,
        )
    )


def _active_venue_instruments(
    instruments: Sequence[CatalogInstrument],
    venue: Venue,
) -> tuple[CatalogInstrument, ...]:
    return tuple(
        sorted(
            (
                instrument
                for instrument in instruments
                if instrument.venue == venue
                and instrument.active
                and instrument.market_type == "linear_perpetual"
            ),
            key=lambda instrument: instrument.source_symbol,
        )
    )


def _preferred_candle(previous: Candle1m | None, candidate: Candle1m) -> Candle1m:
    if previous is None:
        return candidate
    if previous.finality == "derived_final" and candidate.finality == "confirmed":
        return candidate
    if previous.finality == candidate.finality and candidate.observed_at > previous.observed_at:
        return candidate
    return previous


def _candles_covered_by_current_versions(
    candles: Sequence[Candle1m],
    current_version_starts: Mapping[str, datetime],
) -> tuple[Candle1m, ...]:
    return tuple(
        candle
        for candle in candles
        if _candle_is_covered_by_current_version(candle, current_version_starts)
    )


def _candle_is_covered_by_current_version(
    candle: Candle1m,
    current_version_starts: Mapping[str, datetime],
) -> bool:
    valid_from = current_version_starts.get(candle.venue_instrument_id)
    return valid_from is not None and valid_from <= candle.bucket_start


def _log_candle_flush(
    *,
    received: int,
    deduplicated: int,
    stored: int,
    ignored: int,
    error_code: str | None = None,
) -> None:
    fields = {
        "event": "candle_flush",
        "received": received,
        "deduplicated": deduplicated,
        "stored": stored,
        "ignored": ignored,
        "error_code": error_code,
    }
    logger.bind(**fields).info(
        "candle_flush received={received} deduplicated={deduplicated} "
        "stored={stored} ignored={ignored} error_code={error_code}",
        **fields,
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("candle runtime clock must return a timezone-aware datetime")


async def _wait_or_stop(stop_event: asyncio.Event, delay_seconds: float) -> bool:
    if delay_seconds <= 0:
        return stop_event.is_set()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=delay_seconds)
    except TimeoutError:
        return False
    return True
