"""Public, allowlisted USDT perpetual endpoints; no credentials or original venues."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .models import MINUTE, MinuteBar, Provider, Reference

REST = {"bybit": "https://api.bybit.com", "binance": "https://fapi.binance.com"}
WS = {
    "bybit": "wss://stream.bybit.com/v5/public/linear",
    "binance": "wss://fstream.binance.com/market/ws",
}


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def rest_bars(reference: Reference, payload: Any, now: int) -> list[MinuteBar]:
    if reference.provider == "bybit":
        if not isinstance(payload, dict) or payload.get("retCode") != 0:
            raise ValueError("Bybit kline rejected")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("malformed Bybit kline result")
        if result.get("symbol") != reference.symbol or result.get("category") != "linear":
            raise ValueError("Bybit contract mismatch")
        entries = result.get("list")
        if not isinstance(entries, list):
            raise ValueError("malformed Bybit minute records")
    else:
        if not isinstance(payload, list):
            raise ValueError("Binance kline rejected")
        entries = payload
    found: dict[int, MinuteBar] = {}
    for row in entries:
        if not isinstance(row, list) or len(row) < (7 if reference.provider == "bybit" else 8):
            raise ValueError("malformed public minute record")
        start = int(row[0])
        end = start + MINUTE
        if end > now // MINUTE * MINUTE:
            continue
        if reference.provider == "binance" and int(row[6]) + 1 != end:
            raise ValueError("Binance minute duration mismatch")
        bar = MinuteBar(
            reference_key=reference.key,
            end=end,
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            quote_turnover=float(row[6 if reference.provider == "bybit" else 7]),
        )
        if end in found and found[end] != bar:
            raise ValueError("conflicting duplicate minute")
        found[end] = bar
    return sorted(found.values(), key=lambda bar: bar.end)


def stream_bars(
    provider: Provider, payload: dict[str, Any], references: dict[str, Reference], now: int
) -> list[MinuteBar]:
    bars = []
    if provider == "bybit":
        topic = payload.get("topic", "")
        if not isinstance(topic, str):
            raise ValueError("malformed Bybit topic")
        if not topic.startswith("kline.1."):
            return bars
        symbol = topic.removeprefix("kline.1.")
        if symbol not in references:
            raise ValueError("unexpected Bybit subscription")
        entries = payload.get("data", [])
        if not isinstance(entries, list):
            raise ValueError("malformed Bybit candles")
        for candle in entries:
            if not isinstance(candle, dict):
                raise ValueError("malformed Bybit candle")
            if candle.get("confirm") is not True:
                continue
            if str(candle.get("interval")) != "1":
                raise ValueError("Bybit interval mismatch")
            end = int(candle["end"]) + 1
            if end - int(candle["start"]) != MINUTE:
                raise ValueError("Bybit minute duration mismatch")
            bars.append(
                MinuteBar(
                    reference_key=references[symbol].key,
                    end=end,
                    open=float(candle["open"]),
                    high=float(candle["high"]),
                    low=float(candle["low"]),
                    close=float(candle["close"]),
                    quote_turnover=float(candle["turnover"]),
                )
            )
    else:
        candle = payload.get("k")
        if payload.get("e") != "kline":
            return bars
        if not isinstance(candle, dict):
            raise ValueError("malformed Binance candle")
        if candle.get("x") is not True:
            return bars
        symbol = candle["s"]
        if symbol not in references or payload.get("s") != symbol or candle.get("i") != "1m":
            raise ValueError("Binance contract or interval mismatch")
        end = int(candle["T"]) + 1
        if end - int(candle["t"]) != MINUTE:
            raise ValueError("Binance minute duration mismatch")
        bars.append(
            MinuteBar(
                reference_key=references[symbol].key,
                end=end,
                open=float(candle["o"]),
                high=float(candle["h"]),
                low=float(candle["l"]),
                close=float(candle["c"]),
                quote_turnover=float(candle["q"]),
            )
        )
    if any(bar.end > now // MINUTE * MINUTE for bar in bars):
        raise ValueError("provider sent a future confirmed minute")
    return bars


@dataclass
class ProviderHealth:
    connections: int = 0
    reconnects: int = 0
    rest_requests: int = 0
    rest_weight: int = 0
    closed_bars: int = 0
    last_closed_at: int | None = None
    last_error: str | None = None
    last_error_at: int | None = None
    lag_max_ms: int = 0
    subscriptions: int = 0
    backfill_pending: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _rest_slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))
    _next_request: float = 0

    def error(self, exc: Exception) -> None:
        # Do not serialize upstream bodies, headers, connection configuration, or secrets.
        self.last_error = type(exc).__name__ + ": " + str(exc)[:160]
        self.last_error_at = now_ms()

    def public(self) -> dict[str, Any]:
        return {key: value for key, value in vars(self).items() if not key.startswith("_")}


class PublicClient:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session
        self.health: dict[Provider, ProviderHealth] = {
            "bybit": ProviderHealth(),
            "binance": ProviderHealth(),
        }
        self.connections: dict[str, aiohttp.ClientWebSocketResponse] = {}

    async def request(
        self, provider: Provider, path: str, params: dict[str, Any], weight: int = 5
    ) -> Any:
        health = self.health[provider]
        async with health._rest_slots:
            async with health._lock:
                while (delay := health._next_request - time.monotonic()) > 0:
                    await asyncio.sleep(delay)
                health._next_request = time.monotonic() + 0.5
            health.rest_requests += 1
            health.rest_weight += weight
            async with self.session.get(
                REST[provider] + path, params=params, allow_redirects=False
            ) as response:
                if response.status in (418, 429):
                    health._next_request = max(
                        health._next_request,
                        time.monotonic() + (600 if response.status == 418 else 60),
                    )
                if response.status != 200:
                    raise ValueError(f"{provider} public endpoint HTTP {response.status}")
                if response.content_length and response.content_length > 8 * 1024 * 1024:
                    raise ValueError("provider response too large")
                content = bytearray()
                async for chunk in response.content.iter_chunked(65_536):
                    content.extend(chunk)
                    if len(content) > 8 * 1024 * 1024:
                        raise ValueError("provider response too large")
                return json.loads(content)

    async def catalog(self, provider: Provider) -> dict[str, Any]:
        if provider == "binance":
            response = await self.request(provider, "/fapi/v1/exchangeInfo", {}, 1)
            if not isinstance(response, dict):
                raise ValueError("malformed Binance catalog response")
            symbols = response.get("symbols")
            if not isinstance(symbols, list) or any(not isinstance(row, dict) for row in symbols):
                raise ValueError("malformed Binance catalog symbols")
            return response
        entries, cursor = [], ""
        seen = set()
        for _ in range(20):
            params = {"category": "linear", "limit": "1000"}
            if cursor:
                params["cursor"] = cursor
            response = await self.request(provider, "/v5/market/instruments-info", params, 1)
            if not isinstance(response, dict):
                raise ValueError("malformed Bybit catalog response")
            if response.get("retCode") != 0:
                raise ValueError("Bybit catalog rejected")
            result = response.get("result")
            if not isinstance(result, dict):
                raise ValueError("malformed Bybit catalog result")
            rows = result.get("list")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("malformed Bybit catalog list")
            cursor = result.get("nextPageCursor", "")
            if not isinstance(cursor, str):
                raise ValueError("malformed Bybit catalog cursor")
            entries.extend(rows)
            if not cursor:
                return {"retCode": 0, "result": {"list": entries, "nextPageCursor": ""}}
            if cursor in seen:
                raise ValueError("Bybit catalog cursor repeated")
            seen.add(cursor)
        raise ValueError("Bybit catalog page budget exceeded")

    async def history(self, reference: Reference, first: int, last: int) -> list[MinuteBar]:
        found: dict[int, MinuteBar] = {}
        # Initial 1,441 bars take at most two 1,000-bar pages; gap repair is also bounded.
        end = last
        for _ in range(3):
            if end < first:
                break
            if reference.provider == "bybit":
                path = "/v5/market/kline"
                params = {
                    "category": "linear",
                    "symbol": reference.symbol,
                    "interval": "1",
                    "start": first - MINUTE,
                    "end": end - 1,
                    "limit": 1000,
                }
            else:
                path = "/fapi/v1/klines"
                # Binance returns the oldest bars after startTime. Bound start to this page.
                params = {
                    "symbol": reference.symbol,
                    "interval": "1m",
                    "startTime": max(first, end - 999 * MINUTE) - MINUTE,
                    "endTime": end - 1,
                    "limit": 1000,
                }
            payload = await self.request(reference.provider, path, params)
            bars = rest_bars(reference, payload, now_ms())
            bars = [bar for bar in bars if first <= bar.end <= end]
            if not bars:
                break
            found.update((bar.end, bar) for bar in bars)
            oldest = min(bar.end for bar in bars)
            if oldest <= first:
                break
            end = oldest - MINUTE
        return sorted(found.values(), key=lambda bar: bar.end)

    async def stream(
        self, provider: Provider, references: list[Reference], connection_id: str
    ) -> AsyncIterator[list[MinuteBar]]:
        by_symbol = {reference.symbol: reference for reference in references}
        health = self.health[provider]
        backoff = 1
        while True:
            ping: asyncio.Task[None] | None = None
            try:
                async with self.session.ws_connect(
                    WS[provider], heartbeat=20, max_msg_size=4 * 1024 * 1024
                ) as socket:
                    self.connections[connection_id] = socket
                    health.connections += 1
                    if provider == "bybit":
                        await socket.send_json(
                            {
                                "op": "subscribe",
                                "args": [f"kline.1.{symbol}" for symbol in by_symbol],
                            }
                        )

                        async def heartbeat() -> None:
                            while True:
                                await asyncio.sleep(20)
                                await socket.send_json({"op": "ping"})

                        ping = asyncio.create_task(heartbeat())
                    else:
                        await socket.send_json(
                            {
                                "method": "SUBSCRIBE",
                                "id": 1,
                                "params": [f"{s.lower()}@kline_1m" for s in by_symbol],
                            }
                        )
                    async for message in socket:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            continue
                        payload = json.loads(message.data)
                        if not isinstance(payload, dict):
                            raise ValueError("malformed public stream message")
                        if payload.get("success") is False or "code" in payload:
                            raise ValueError(f"{provider} subscription rejected")
                        bars = stream_bars(provider, payload, by_symbol, now_ms())
                        if bars:
                            backoff = 1
                            health.closed_bars += len(bars)
                            health.last_closed_at = now_ms()
                            health.lag_max_ms = max(
                                health.lag_max_ms, max(now_ms() - bar.end for bar in bars)
                            )
                            yield bars
            except (
                aiohttp.ClientError,
                TimeoutError,
                ValueError,
                KeyError,
                TypeError,
                IndexError,
            ) as exc:
                health.error(exc)
            finally:
                if ping:
                    ping.cancel()
                    await asyncio.gather(ping, return_exceptions=True)
                if self.connections.pop(connection_id, None):
                    health.connections -= 1
            health.reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
