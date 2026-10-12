from __future__ import annotations

import asyncio
import random
from contextlib import suppress
from datetime import UTC, datetime

import aiohttp
from loguru import logger

from prep_watchdeck_market.candles import CandleParseError
from prep_watchdeck_market.sources.mexc_candles import MexcCandleFinalizer
from prep_watchdeck_market.sources.mexc_stream_common import (
    MexcStreamFailure,
    decode_message,
    mexc_subscription_pacer,
    source_call,
    source_connection,
)

# Capacity design values, not representations of a provider's official limits.
MEXC_CANDLE_SHARD_SIZE = 25
MEXC_SUBSCRIPTION_ACK_TIMEOUT_SECONDS = 10.0
MEXC_PING_INTERVAL_SECONDS = 15.0


async def produce_mexc_candles(
    session,
    instruments,
    emit,
    stop_event,
    *,
    ws_factory=None,
    receive_poll_seconds=1.0,
    reconnect_delay_seconds=1.0,
    subscription_pacer=None,
    ack_timeout_seconds=MEXC_SUBSCRIPTION_ACK_TIMEOUT_SECONDS,
):
    selected = tuple(i for i in instruments if i.venue == "mexc" and i.active)
    if not selected:
        return
    if session is None and ws_factory is None:
        raise ValueError("MEXC candles require session or websocket factory")
    connect = ws_factory or (lambda url: session.ws_connect(url, heartbeat=15))
    pacer = subscription_pacer or mexc_subscription_pacer()

    async def shard(index, items):
        failures = 0
        connections = ack_failures = gap_minutes = emitted_count = 0
        last_message_at = last_candle_at = None
        previous_buckets = {}
        acknowledged = set()

        def report(state, failure_code=None):
            now = asyncio.get_running_loop().time()
            logger.log(
                "WARNING" if failure_code else "INFO",
                "MEXC candle shard={shard} state={state} symbols={symbols} "
                "reconnects={reconnects} acknowledgements={acks} ack_failures={ack_failures} "
                "observed_gap_minutes={gaps} candles={candles} "
                "last_message_age_seconds={message_age} last_candle_age_seconds={candle_age} "
                "failure_code={failure_code}",
                shard=index,
                state=state,
                symbols=len(items),
                reconnects=max(0, connections - 1),
                acks=len(acknowledged),
                ack_failures=ack_failures,
                gaps=gap_minutes,
                candles=emitted_count,
                message_age=None if last_message_at is None else round(now - last_message_at, 1),
                candle_age=None if last_candle_at is None else round(now - last_candle_at, 1),
                failure_code=failure_code,
            )

        loop = asyncio.get_running_loop()
        while not stop_event.is_set():
            finalizer = MexcCandleFinalizer(items)
            connected_at = loop.time()
            try:
                async with source_connection(connect) as websocket:
                    connections += 1
                    remaining = iter(items)
                    acknowledged = set()
                    pending = None
                    ack_deadline = 0.0
                    ping_at = loop.time() + MEXC_PING_INTERVAL_SECONDS
                    report_at = loop.time() + 60
                    report("connected")
                    while not stop_event.is_set():
                        # Official ACK is rs.<method>, data='success', with no symbol/id.
                        # One outstanding subscription per connection makes attribution exact.
                        if pending is None:
                            item = next(remaining, None)
                            if item is not None:
                                await pacer.acquire()
                                if stop_event.is_set():
                                    break
                                await source_call(
                                    websocket.send_json(
                                        {
                                            "method": "sub.kline",
                                            "param": {
                                                "symbol": item.source_symbol,
                                                "interval": "Min1",
                                            },
                                        }
                                    )
                                )
                                pending = item.source_symbol
                                ack_deadline = loop.time() + ack_timeout_seconds
                        if pending is not None and loop.time() >= ack_deadline:
                            raise MexcStreamFailure("MEXC candle subscription ACK timeout")
                        if loop.time() >= ping_at:
                            await source_call(websocket.send_json({"method": "ping"}))
                            ping_at = loop.time() + MEXC_PING_INTERVAL_SECONDS
                        try:
                            message = await asyncio.wait_for(
                                source_call(websocket.receive()), timeout=receive_poll_seconds
                            )
                        except TimeoutError:
                            message = None
                        if message is not None:
                            last_message_at = loop.time()
                            if message.type in {
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            }:
                                raise MexcStreamFailure("MEXC candle stream disconnected")
                            if message.type == aiohttp.WSMsgType.TEXT:
                                payload = decode_message(message)
                                if payload.get("channel") == "rs.error":
                                    raise MexcStreamFailure("MEXC candle subscription rejected")
                                if payload.get("channel") == "rs.sub.kline":
                                    if pending is None or payload.get("data") != "success":
                                        raise MexcStreamFailure(
                                            "MEXC candle subscription ACK invalid"
                                        )
                                    acknowledged.add(pending)
                                    pending = None
                                    if len(acknowledged) == len(items):
                                        report("subscribed")
                                elif payload.get("channel") == "push.kline":
                                    try:
                                        data = payload.get("data")
                                        symbol = (
                                            data.get("symbol") if isinstance(data, dict) else None
                                        )
                                        if (
                                            not isinstance(symbol, str)
                                            or symbol not in finalizer.instruments
                                        ):
                                            raise CandleParseError("MEXC kline series mismatch")
                                        if symbol not in acknowledged:
                                            continue
                                        finalizer.ingest(payload, observed_at=datetime.now(UTC))
                                    except CandleParseError:
                                        raise MexcStreamFailure(
                                            "MEXC candle stream decode failed"
                                        ) from None
                        for candle in finalizer.finalize(now=datetime.now(UTC)):
                            await emit(candle)
                            emitted_count += 1
                            last_candle_at = loop.time()
                            previous = previous_buckets.get(candle.source_symbol)
                            if previous is not None and candle.bucket_start > previous:
                                gap_minutes += max(
                                    0,
                                    int((candle.bucket_start - previous).total_seconds() / 60) - 1,
                                )
                            if previous is None or candle.bucket_start > previous:
                                previous_buckets[candle.source_symbol] = candle.bucket_start
                        if loop.time() >= report_at:
                            report("streaming")
                            report_at = loop.time() + 60
                        if loop.time() - connected_at >= 60:
                            failures = 0
            except MexcStreamFailure as exc:
                failure = str(exc)
                if "subscription" in failure:
                    ack_failures += 1
                failure_code = (
                    "ack_timeout"
                    if "ACK timeout" in failure
                    else "ack_invalid"
                    if "ACK invalid" in failure
                    else "subscription_rejected"
                    if "subscription rejected" in failure
                    else "stream_decode"
                    if "decode" in failure or "JSON" in failure
                    else "stream_disconnected"
                )
                report("backoff", failure_code)
            if not stop_event.is_set():
                delay = min(60, reconnect_delay_seconds * 2 ** min(failures, 6))
                failures += 1
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=delay * random.uniform(0.8, 1.2)
                    )

        report("stopped")

    # Native failures are recovered inside their shard; writer/cancellation failures
    # propagate and stop acquisition rather than hiding a failed durable consumer.
    async with asyncio.TaskGroup() as group:
        for start in range(0, len(selected), MEXC_CANDLE_SHARD_SIZE):
            group.create_task(
                shard(
                    start // MEXC_CANDLE_SHARD_SIZE,
                    selected[start : start + MEXC_CANDLE_SHARD_SIZE],
                )
            )
