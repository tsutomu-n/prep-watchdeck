from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from prep_watchdeck.application.ws_frames import ChannelSpec, WsChannel
from prep_watchdeck.application.ws_ingestion import TickerRuntimeSink, WsBatchBuffer
from prep_watchdeck.domain.service_models import (
    Candle1mRecord,
    StreamHealthRecord,
    TickerLatestRecord,
)

PayloadSourceFactory = Callable[[Sequence[ChannelSpec]], AsyncIterable[Mapping[str, Any]]]


class WsShardStore(Protocol):
    def upsert_ticker_latest(self, tickers: list[TickerLatestRecord]) -> None:
        """Persist latest ticker rows."""

    def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
        """Persist 1m candle rows."""

    def upsert_stream_health(self, health: list[StreamHealthRecord]) -> None:
        """Persist stream health rows."""


@dataclass(frozen=True)
class WsShardIngestResult:
    shard_count: int
    payload_count: int
    ticker_count: int
    candle_1m_count: int
    reconnect_count: int = 0


@dataclass(frozen=True)
class ShardRuntimeConfig:
    max_reconnects: int | None = None
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    batch_flush_records: int = 25
    batch_flush_interval_seconds: float = 1.0
    channel_gap_seconds: int = 0
    now_ms: Callable[[], int] = field(default_factory=lambda: _now_ms)


async def ingest_ws_shards(
    store: WsShardStore,
    shards: Sequence[Sequence[ChannelSpec]],
    *,
    payload_source_factory: PayloadSourceFactory,
    max_records_per_shard: int | None = None,
    runtime: ShardRuntimeConfig | None = None,
    ticker_sink: TickerRuntimeSink | None = None,
) -> WsShardIngestResult:
    if max_records_per_shard is not None and max_records_per_shard < 1:
        raise ValueError("max_records_per_shard must be positive")
    runtime = runtime or ShardRuntimeConfig()

    results = await asyncio.gather(
        *(
            _run_shard(
                store,
                shard_id=f"ws-{index:03d}",
                shard=shard,
                payload_source_factory=payload_source_factory,
                max_records=max_records_per_shard,
                runtime=runtime,
                ticker_sink=ticker_sink,
            )
            for index, shard in enumerate(shards)
        )
    )
    return WsShardIngestResult(
        shard_count=len(shards),
        payload_count=sum(result.payload_count for result in results),
        ticker_count=sum(result.ticker_count for result in results),
        candle_1m_count=sum(result.candle_1m_count for result in results),
        reconnect_count=sum(result.reconnect_count for result in results),
    )


async def _run_shard(
    store: WsShardStore,
    *,
    shard_id: str,
    shard: Sequence[ChannelSpec],
    payload_source_factory: PayloadSourceFactory,
    max_records: int | None,
    runtime: ShardRuntimeConfig,
    ticker_sink: TickerRuntimeSink | None,
) -> WsShardIngestResult:
    payload_count = 0
    ticker_count = 0
    candle_1m_count = 0
    reconnect_count = 0
    last_message_at_ms: int | None = None
    channel_last_message_at_ms: dict[str, int] = {}
    batch = WsBatchBuffer.empty()
    last_flush_monotonic = time.monotonic()

    while True:
        await _write_health_async(
            store,
            shard_id=shard_id,
            shard=shard,
            connected=True,
            last_message_at_ms=last_message_at_ms,
            reconnect_count=reconnect_count,
            last_error=None,
            channel_last_message_at_ms=channel_last_message_at_ms,
            runtime=runtime,
        )
        try:
            async for payload in payload_source_factory(shard):
                payload_count += 1
                result = batch.add_payload(payload)
                ticker_count += result.ticker_count
                candle_1m_count += result.candle_1m_count
                last_message_at_ms = _payload_ts_ms(payload) or _now_ms()
                if channel := _payload_channel(payload):
                    channel_last_message_at_ms[channel] = last_message_at_ms
                if _should_flush_batch(batch, runtime, last_flush_monotonic):
                    await _flush_batch_async(store, batch, ticker_sink=ticker_sink)
                    last_flush_monotonic = time.monotonic()
                await _write_health_async(
                    store,
                    shard_id=shard_id,
                    shard=shard,
                    connected=True,
                    last_message_at_ms=last_message_at_ms,
                    reconnect_count=reconnect_count,
                    last_error=None,
                    channel_last_message_at_ms=channel_last_message_at_ms,
                    runtime=runtime,
                )
                if max_records is not None and ticker_count + candle_1m_count >= max_records:
                    await _flush_batch_async(store, batch, ticker_sink=ticker_sink)
                    await _write_health_async(
                        store,
                        shard_id=shard_id,
                        shard=shard,
                        connected=False,
                        last_message_at_ms=last_message_at_ms,
                        reconnect_count=reconnect_count,
                        last_error=None,
                        channel_last_message_at_ms=channel_last_message_at_ms,
                        runtime=runtime,
                    )
                    return WsShardIngestResult(
                        shard_count=1,
                        payload_count=payload_count,
                        ticker_count=ticker_count,
                        candle_1m_count=candle_1m_count,
                        reconnect_count=reconnect_count,
                    )
            await _flush_batch_async(store, batch, ticker_sink=ticker_sink)
            reconnect_count = await _handle_reconnectable_disconnect(
                store,
                shard_id=shard_id,
                shard=shard,
                last_message_at_ms=last_message_at_ms,
                channel_last_message_at_ms=channel_last_message_at_ms,
                reconnect_count=reconnect_count,
                runtime=runtime,
                last_error="websocket stream closed",
            )
        except asyncio.CancelledError:
            await _flush_batch_async(store, batch, ticker_sink=ticker_sink)
            await _write_health_async(
                store,
                shard_id=shard_id,
                shard=shard,
                connected=False,
                last_message_at_ms=last_message_at_ms,
                reconnect_count=reconnect_count,
                last_error=None,
                channel_last_message_at_ms=channel_last_message_at_ms,
                runtime=runtime,
            )
            raise
        except Exception as exc:
            if isinstance(exc, ValueError):
                await _flush_batch_async(store, batch, ticker_sink=ticker_sink)
                await _write_health_async(
                    store,
                    shard_id=shard_id,
                    shard=shard,
                    connected=False,
                    last_message_at_ms=last_message_at_ms,
                    reconnect_count=reconnect_count,
                    last_error=str(exc),
                    channel_last_message_at_ms=channel_last_message_at_ms,
                    runtime=runtime,
                )
                raise
            await _flush_batch_async(store, batch, ticker_sink=ticker_sink)
            await _write_health_async(
                store,
                shard_id=shard_id,
                shard=shard,
                connected=False,
                last_message_at_ms=last_message_at_ms,
                reconnect_count=reconnect_count,
                last_error=str(exc),
                channel_last_message_at_ms=channel_last_message_at_ms,
                runtime=runtime,
            )
            if runtime.max_reconnects is not None and reconnect_count >= runtime.max_reconnects:
                raise
            reconnect_count += 1
            await _sleep_before_reconnect(runtime, reconnect_count)


async def _sleep_before_reconnect(
    runtime: ShardRuntimeConfig,
    reconnect_count: int,
) -> None:
    if runtime.base_backoff_seconds <= 0:
        return
    delay = min(
        runtime.base_backoff_seconds * (2 ** max(reconnect_count - 1, 0)),
        runtime.max_backoff_seconds,
    )
    await asyncio.sleep(delay)


async def _handle_reconnectable_disconnect(
    store: WsShardStore,
    *,
    shard_id: str,
    shard: Sequence[ChannelSpec],
    last_message_at_ms: int | None,
    channel_last_message_at_ms: Mapping[str, int],
    reconnect_count: int,
    runtime: ShardRuntimeConfig,
    last_error: str,
) -> int:
    await _write_health_async(
        store,
        shard_id=shard_id,
        shard=shard,
        connected=False,
        last_message_at_ms=last_message_at_ms,
        reconnect_count=reconnect_count,
        last_error=last_error,
        channel_last_message_at_ms=channel_last_message_at_ms,
        runtime=runtime,
    )
    if runtime.max_reconnects is not None and reconnect_count >= runtime.max_reconnects:
        raise RuntimeError(last_error)
    reconnect_count += 1
    await _sleep_before_reconnect(runtime, reconnect_count)
    return reconnect_count


async def _write_health_async(
    store: WsShardStore,
    *,
    shard_id: str,
    shard: Sequence[ChannelSpec],
    connected: bool,
    last_message_at_ms: int | None,
    reconnect_count: int,
    last_error: str | None,
    channel_last_message_at_ms: Mapping[str, int],
    runtime: ShardRuntimeConfig,
) -> None:
    await asyncio.to_thread(
        _write_health,
        store,
        shard_id=shard_id,
        shard=shard,
        connected=connected,
        last_message_at_ms=last_message_at_ms,
        reconnect_count=reconnect_count,
        last_error=last_error,
        channel_last_message_at_ms=channel_last_message_at_ms,
        runtime=runtime,
    )


async def _flush_batch_async(
    store: WsShardStore,
    batch: WsBatchBuffer,
    *,
    ticker_sink: TickerRuntimeSink | None = None,
) -> None:
    if batch.record_count == 0:
        return
    await asyncio.to_thread(batch.flush, store, ticker_sink=ticker_sink)


def _should_flush_batch(
    batch: WsBatchBuffer,
    runtime: ShardRuntimeConfig,
    last_flush_monotonic: float,
) -> bool:
    if batch.record_count == 0:
        return False
    if runtime.batch_flush_records <= 1:
        return True
    if batch.record_count >= runtime.batch_flush_records:
        return True
    if runtime.batch_flush_interval_seconds <= 0:
        return False
    return time.monotonic() - last_flush_monotonic >= runtime.batch_flush_interval_seconds


def _write_health(
    store: WsShardStore,
    *,
    shard_id: str,
    shard: Sequence[ChannelSpec],
    connected: bool,
    last_message_at_ms: int | None,
    reconnect_count: int,
    last_error: str | None,
    channel_last_message_at_ms: Mapping[str, int],
    runtime: ShardRuntimeConfig,
) -> None:
    health = [
        StreamHealthRecord(
            shard_id=shard_id,
            stream_kind=_stream_kind(shard),
            channel_count=len(shard),
            connected=connected,
            last_message_at_ms=last_message_at_ms,
            reconnect_count=reconnect_count,
            gap_count=sum(
                _channel_gap_count(
                    channel_last_message_at_ms.get(channel),
                    last_message_at_ms,
                    now_ms=runtime.now_ms(),
                    threshold_seconds=runtime.channel_gap_seconds,
                )
                for channel in _channels(shard)
            ),
            last_error=last_error,
        )
    ]
    health.extend(
        StreamHealthRecord(
            shard_id=f"{shard_id}:{channel}",
            stream_kind=channel,
            channel_count=sum(1 for spec in shard if spec.channel == channel),
            connected=connected,
            last_message_at_ms=channel_last_message_at_ms.get(channel),
            reconnect_count=reconnect_count,
            gap_count=_channel_gap_count(
                channel_last_message_at_ms.get(channel),
                last_message_at_ms,
                now_ms=runtime.now_ms(),
                threshold_seconds=runtime.channel_gap_seconds,
            ),
            last_error=last_error,
        )
        for channel in _channels(shard)
    )
    store.upsert_stream_health(health)


def _stream_kind(shard: Sequence[ChannelSpec]):
    channels = {spec.channel for spec in shard}
    if channels == {"ticker"}:
        return "ticker"
    if channels == {"candle1m"}:
        return "candle1m"
    return "mixed"


def _channels(shard: Sequence[ChannelSpec]) -> list[WsChannel]:
    return sorted({spec.channel for spec in shard})


def _channel_gap_count(
    channel_last_message_at_ms: int | None,
    last_message_at_ms: int | None,
    *,
    now_ms: int,
    threshold_seconds: int,
) -> int:
    if threshold_seconds <= 0:
        return 0
    if channel_last_message_at_ms is None:
        return 1 if last_message_at_ms is not None else 0
    return int(now_ms - channel_last_message_at_ms > threshold_seconds * 1000)


def _payload_ts_ms(payload: Mapping[str, Any]) -> int | None:
    value = payload.get("ts")
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _payload_channel(payload: Mapping[str, Any]) -> str | None:
    arg = payload.get("arg")
    if not isinstance(arg, Mapping):
        return None
    value = arg.get("channel")
    return value if value in {"ticker", "candle1m"} else None
