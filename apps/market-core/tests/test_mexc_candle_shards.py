import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from itertools import pairwise
from types import SimpleNamespace

import aiohttp
import pytest

from prep_watchdeck_market.sources.mexc_candle_stream import produce_mexc_candles
from prep_watchdeck_market.sources.mexc_stream_common import MexcSubscriptionPacer

from .test_mexc_sources import instrument


@pytest.mark.parametrize("failure", ["rejected", "malformed_symbol"])
def test_one_candle_shard_failure_keeps_other_25_symbol_connections_open(failure):
    sockets = []

    async def run():
        stop = asyncio.Event()

        class WS:
            def __init__(self):
                self.id = len(sockets)
                self.symbols = []
                self.acks = 0
                self.messages = asyncio.Queue()
                self.closed_before_stop = False
                sockets.append(self)

            async def send_json(self, payload):
                if payload["method"] != "sub.kline":
                    return
                self.symbols.append(payload["param"]["symbol"])
                payload = {"channel": "rs.sub.kline", "data": "success"}
                if self.id == 0 and len(self.symbols) == 2:
                    payload = (
                        {"channel": "rs.error", "data": "success"}
                        if failure == "rejected"
                        else {"channel": "push.kline", "data": {"symbol": []}}
                    )
                self.messages.put_nowait(
                    SimpleNamespace(
                        type=aiohttp.WSMsgType.TEXT,
                        data=json.dumps(payload),
                    )
                )

            async def receive(self):
                message = await self.messages.get()
                if json.loads(message.data)["channel"] == "rs.sub.kline":
                    self.acks += 1
                    if sum(ws.acks for ws in sockets[1:]) == 100:
                        stop.set()
                return message

        @asynccontextmanager
        async def connect(url):
            ws = WS()
            try:
                yield ws
            finally:
                ws.closed_before_stop = not stop.is_set()

        async def emit(candle):
            raise AssertionError("no candle payload was sent")

        items = [replace(instrument(), source_symbol=f"TEST{i}_USDT") for i in range(100)]
        await asyncio.wait_for(
            produce_mexc_candles(
                None,
                items,
                emit,
                stop,
                ws_factory=connect,
                subscription_pacer=MexcSubscriptionPacer(0),
                reconnect_delay_seconds=0,
                receive_poll_seconds=0.01,
            ),
            timeout=2,
        )

    asyncio.run(run())
    assert len(sockets) == 5  # four shards and the failed shard's replacement
    assert sockets[0].closed_before_stop is True
    assert all(not ws.closed_before_stop for ws in sockets[1:])
    assert all(len(ws.symbols) == 25 for ws in sockets[1:])
    assert len({symbol for ws in sockets[1:] for symbol in ws.symbols}) == 100


def test_missing_subscription_ack_reconnects_without_accepting_unconfirmed_candles():
    async def run():
        stop = asyncio.Event()
        attempts = []

        class WS:
            async def send_json(self, payload):
                pass

            async def receive(self):
                await asyncio.sleep(1)

        @asynccontextmanager
        async def connect(url):
            attempts.append(url)
            if len(attempts) == 2:
                stop.set()
            yield WS()

        async def emit(candle):
            raise AssertionError("unacknowledged subscription emitted a candle")

        await asyncio.wait_for(
            produce_mexc_candles(
                None,
                [instrument()],
                emit,
                stop,
                ws_factory=connect,
                subscription_pacer=MexcSubscriptionPacer(0),
                reconnect_delay_seconds=0,
                receive_poll_seconds=0.005,
                ack_timeout_seconds=0.02,
            ),
            timeout=1,
        )
        assert len(attempts) == 2

    asyncio.run(run())


def test_all_connections_use_five_subscription_commands_per_second():
    async def run():
        pacer = MexcSubscriptionPacer()
        starts = []

        async def connection():
            for _ in range(2):
                await pacer.acquire()
                starts.append(asyncio.get_running_loop().time())

        await asyncio.gather(*(connection() for _ in range(3)))
        assert len(starts) == 6
        assert starts[5] - starts[0] >= 1
        assert all(b - a >= 0.2 for a, b in pairwise(starts))

    asyncio.run(run())


def test_shard_diagnostics_count_emitted_candles_and_observed_forward_gap():
    from datetime import UTC, datetime, timedelta

    from loguru import logger

    logs = []
    sink = logger.add(lambda message: logs.append(str(message)))

    async def run():
        stop = asyncio.Event()
        old = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=5)
        payloads = [{"channel": "rs.sub.kline", "data": "success"}] + [
            {
                "channel": "push.kline",
                "data": {
                    "symbol": "BTC_USDT",
                    "interval": "Min1",
                    "t": int(bucket.timestamp()),
                    "o": 100,
                    "h": 101,
                    "l": 99,
                    "c": 100,
                    "q": 10000,
                    "a": 100,
                },
            }
            for bucket in [old, old + timedelta(minutes=2)]
        ]

        class WS:
            async def send_json(self, payload):
                pass

            async def receive(self):
                return SimpleNamespace(
                    type=aiohttp.WSMsgType.TEXT, data=json.dumps(payloads.pop(0))
                )

        @asynccontextmanager
        async def connect(url):
            yield WS()

        emitted = []

        async def emit(candle):
            emitted.append(candle)
            if len(emitted) == 2:
                stop.set()

        await produce_mexc_candles(
            None,
            [instrument()],
            emit,
            stop,
            ws_factory=connect,
            subscription_pacer=MexcSubscriptionPacer(0),
        )

    try:
        asyncio.run(run())
    finally:
        logger.remove(sink)
    final = next(log for log in logs if "state=stopped" in log)
    assert "observed_gap_minutes=1 candles=2" in final
    assert "acknowledgements=1 ack_failures=0" in final
