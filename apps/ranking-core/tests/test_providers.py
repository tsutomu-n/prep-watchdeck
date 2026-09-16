import asyncio
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest

from prep_watchdeck_ranking import providers as module
from prep_watchdeck_ranking.models import MINUTE, Provider
from prep_watchdeck_ranking.providers import REST, PublicClient, rest_bars, stream_bars

from .conftest import CUTOFF, reference


def test_rest_bounds_inflight_bodies_per_provider_and_preserves_start_spacing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        started: dict[Provider, list[float]] = {"bybit": [], "binance": []}
        active = {"bybit": 0, "binance": 0}
        maximum = {"bybit": 0, "binance": 0}
        entered = {provider: [asyncio.Event() for _ in range(4)] for provider in started}
        release = {provider: [asyncio.Event() for _ in range(4)] for provider in started}

        @asynccontextmanager
        async def response(url: str, **_kwargs: Any) -> AsyncGenerator[SimpleNamespace]:
            provider: Provider = "bybit" if url.startswith(REST["bybit"]) else "binance"
            index = len(started[provider])
            started[provider].append(time.monotonic())
            active[provider] += 1
            maximum[provider] = max(maximum[provider], active[provider])
            entered[provider][index].set()

            async def chunks(_size: int) -> AsyncIterator[bytes]:
                await release[provider][index].wait()
                yield b"{}"

            try:
                yield SimpleNamespace(
                    status=200, content_length=2, content=SimpleNamespace(iter_chunked=chunks)
                )
            finally:
                active[provider] -= 1

        async with aiohttp.ClientSession() as session:
            monkeypatch.setattr(session, "get", response)
            client = PublicClient(session)
            tasks = [asyncio.create_task(client.request("bybit", "/test", {})) for _ in range(4)]
            try:
                await asyncio.wait_for(entered["bybit"][1].wait(), 3)
                tasks.append(asyncio.create_task(client.request("binance", "/test", {})))
                await asyncio.wait_for(entered["binance"][0].wait(), 1)
                release["binance"][0].set()
                assert await asyncio.wait_for(tasks[-1], 1) == {}

                # A third request would start after 0.5 s without an in-flight limit.
                await asyncio.sleep(0.6)
                assert len(started["bybit"]) == 2
                release["bybit"][0].set()
                await asyncio.wait_for(entered["bybit"][2].wait(), 1)
                assert len(started["bybit"]) == 3
                for event in release["bybit"]:
                    event.set()
                assert await asyncio.wait_for(asyncio.gather(*tasks), 3) == [{}] * 5
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

            assert maximum == {"bybit": 2, "binance": 1}
            assert active == {"bybit": 0, "binance": 0}
            assert all(
                later - earlier >= 0.49
                for earlier, later in zip(started["bybit"], started["bybit"][1:], strict=False)
            )
            assert client.health["bybit"].rest_requests == 4
            assert client.health["binance"].rest_requests == 1

    asyncio.run(check())


@pytest.mark.parametrize("status, cooldown", [(429, 60), (418, 600)])
def test_rate_wait_honors_cooldown_extended_by_an_inflight_response(
    monkeypatch: pytest.MonkeyPatch, status: int, cooldown: int
) -> None:
    async def check() -> None:
        clock = 0.0
        real_sleep = asyncio.sleep
        first_started = asyncio.Event()
        pacing_started = asyncio.Event()
        send_throttle = asyncio.Event()
        resume_pacing = asyncio.Event()
        starts: list[float] = []

        async def sleep(delay: float) -> None:
            nonlocal clock
            wake_at = clock + delay
            if delay > 0 and not pacing_started.is_set():
                pacing_started.set()
                await resume_pacing.wait()
            clock = max(clock, wake_at)
            await real_sleep(0)

        async def chunks(_size: int) -> AsyncIterator[bytes]:
            yield b"{}"

        @asynccontextmanager
        async def response(_url: str, **_kwargs: Any) -> AsyncGenerator[SimpleNamespace]:
            starts.append(clock)
            first = len(starts) == 1
            if first:
                first_started.set()
                await send_throttle.wait()
            yield SimpleNamespace(
                status=status if first else 200,
                content_length=2,
                content=SimpleNamespace(iter_chunked=chunks),
            )

        # Replace this module's clock without changing the event loop's timeout clock.
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock))
        monkeypatch.setattr(module.asyncio, "sleep", sleep)
        async with asyncio.timeout(3), aiohttp.ClientSession() as session:
            monkeypatch.setattr(session, "get", response)
            client = PublicClient(session)
            first = asyncio.create_task(client.request("bybit", "/test", {}))
            tasks = [first]
            try:
                await first_started.wait()
                second = asyncio.create_task(client.request("bybit", "/test", {}))
                tasks.append(second)
                await pacing_started.wait()
                clock = 0.25
                send_throttle.set()
                with pytest.raises(ValueError, match=f"HTTP {status}"):
                    await first
                resume_pacing.set()
                assert await second == {}
                assert starts == [0.0, 0.25 + cooldown]
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize(
    "provider, payload",
    [
        ("bybit", None),
        ("bybit", []),
        ("bybit", {"retCode": 0, "result": None}),
        ("bybit", {"retCode": 0, "result": []}),
        ("bybit", {"retCode": 0, "result": {}}),
        ("bybit", {"retCode": 0, "result": {"list": None}}),
        ("bybit", {"retCode": 0, "result": {"list": {}}}),
        ("bybit", {"retCode": 0, "result": {"list": [None]}}),
        ("bybit", {"retCode": 0, "result": {"list": [], "nextPageCursor": None}}),
        ("bybit", {"retCode": 0, "result": {"list": [], "nextPageCursor": 1}}),
        ("bybit", {"retCode": 0, "result": {"list": [], "nextPageCursor": ["next"]}}),
        ("binance", None),
        ("binance", []),
        ("binance", {}),
        ("binance", {"symbols": None}),
        ("binance", {"symbols": {}}),
        ("binance", {"symbols": [None]}),
    ],
)
def test_malformed_catalog_shape_is_a_recoverable_validation_error(
    monkeypatch: pytest.MonkeyPatch, provider: Provider, payload: Any
) -> None:
    async def check() -> None:
        async with aiohttp.ClientSession() as session:
            client = PublicClient(session)

            async def request(*_args: Any) -> Any:
                return payload

            monkeypatch.setattr(client, "request", request)
            with pytest.raises(ValueError, match=r"malformed.*catalog"):
                await client.catalog(provider)

    asyncio.run(check())


@pytest.mark.parametrize("paginated", [False, True])
def test_valid_bybit_catalog_preserves_entries_and_page_requests(
    monkeypatch: pytest.MonkeyPatch, paginated: bool
) -> None:
    async def check() -> None:
        first = {"symbol": "BTCUSDT", "status": "Trading", "launchTime": "1584230400000"}
        second = {"symbol": "ETHUSDT", "status": "Trading", "launchTime": "1585526400000"}
        pages = [
            {
                "retCode": 0,
                "result": {"list": [first], "nextPageCursor": "next-page" if paginated else ""},
            },
            {"retCode": 0, "result": {"list": [second]}},
        ]
        calls: list[tuple[Provider, str, dict[str, Any], int]] = []
        async with aiohttp.ClientSession() as session:
            client = PublicClient(session)

            async def request(
                provider: Provider, path: str, params: dict[str, Any], weight: int
            ) -> dict[str, Any]:
                calls.append((provider, path, dict(params), weight))
                return pages[len(calls) - 1]

            monkeypatch.setattr(client, "request", request)
            result = await client.catalog("bybit")
            expected = [first, second] if paginated else [first]
            assert result == {"retCode": 0, "result": {"list": expected, "nextPageCursor": ""}}
            base_params = {"category": "linear", "limit": "1000"}
            expected_calls = [("bybit", "/v5/market/instruments-info", base_params, 1)]
            if paginated:
                expected_calls.append(
                    (
                        "bybit",
                        "/v5/market/instruments-info",
                        {**base_params, "cursor": "next-page"},
                        1,
                    )
                )
            assert calls == expected_calls

    asyncio.run(check())


def test_valid_binance_catalog_is_returned_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    async def check() -> None:
        payload = {
            "serverTime": CUTOFF,
            "symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "onboardDate": 1569398400000}],
        }
        async with aiohttp.ClientSession() as session:
            client = PublicClient(session)

            async def request(
                provider: Provider, path: str, params: dict[str, Any], weight: int
            ) -> dict[str, Any]:
                assert (provider, path, params, weight) == (
                    "binance",
                    "/fapi/v1/exchangeInfo",
                    {},
                    1,
                )
                return payload

            monkeypatch.setattr(client, "request", request)
            assert await client.catalog("binance") is payload

    asyncio.run(check())


def test_rest_bybit_uses_quote_turnover_and_discards_unclosed() -> None:
    rows = [
        [str(CUTOFF - MINUTE), "100", "110", "90", "105", "99999", "1234"],
        [str(CUTOFF), "105", "106", "100", "106", "5000", "54321"],
    ]
    payload = {"retCode": 0, "result": {"category": "linear", "symbol": "BTCUSDT", "list": rows}}
    bars = rest_bars(reference(), payload, CUTOFF + 8000)
    assert len(bars) == 1 and bars[0].quote_turnover == 1234 and bars[0].close == 105


def test_rest_binance_quote_field_and_period_validation() -> None:
    ref = reference().model_copy(update={"provider": "binance"})
    row = [CUTOFF - MINUTE, "100", "110", "90", "105", "99999", CUTOFF - 1, "1234"]
    assert rest_bars(ref, [row], CUTOFF)[0].quote_turnover == 1234
    with pytest.raises(ValueError, match="duration"):
        rest_bars(ref, [[*row[:6], CUTOFF - 2, "1234"]], CUTOFF)


def test_short_public_record_is_a_recoverable_validation_error() -> None:
    ref = reference().model_copy(update={"provider": "binance"})
    with pytest.raises(ValueError, match="malformed"):
        rest_bars(ref, [[CUTOFF - MINUTE, "100"]], CUTOFF)


@pytest.mark.parametrize("result", [None, [], "unexpected", {"list": None}])
def test_malformed_bybit_rest_result_is_a_recoverable_validation_error(result: Any) -> None:
    if isinstance(result, dict):
        result.update(category="linear", symbol="BTCUSDT")
    with pytest.raises(ValueError, match="malformed"):
        rest_bars(reference(), {"retCode": 0, "result": result}, CUTOFF)


@pytest.mark.parametrize(
    "provider, payload",
    [
        ("bybit", {"topic": None}),
        ("bybit", {"topic": "kline.1.BTCUSDT", "data": None}),
        ("bybit", {"topic": "kline.1.BTCUSDT", "data": [None]}),
        ("bybit", {"topic": "kline.1.BTCUSDT", "data": [[1]]}),
        ("binance", {"e": "kline", "k": [1]}),
        ("binance", {"e": "kline", "k": None}),
    ],
)
def test_malformed_stream_shape_is_a_recoverable_validation_error(
    provider: Provider, payload: dict[str, Any]
) -> None:
    ref = reference().model_copy(update={"provider": provider})
    with pytest.raises(ValueError, match="malformed"):
        stream_bars(provider, payload, {"BTCUSDT": ref}, CUTOFF)


def test_conflicting_rest_duplicate_and_wrong_contract_rejected() -> None:
    row = [CUTOFF - MINUTE, "100", "110", "90", "105", "99999", "1234"]
    payload = {
        "retCode": 0,
        "result": {
            "category": "linear",
            "symbol": "BTCUSDT",
            "list": [row, [*row[:4], "106", *row[5:]]],
        },
    }
    with pytest.raises(ValueError, match="duplicate"):
        rest_bars(reference(), payload, CUTOFF)
    payload["result"]["symbol"] = "ETHUSDT"
    with pytest.raises(ValueError, match="mismatch"):
        rest_bars(reference(), payload, CUTOFF)


def test_bybit_stream_requires_confirmation_and_exact_interval() -> None:
    candle = {
        "start": CUTOFF - MINUTE,
        "end": CUTOFF - 1,
        "interval": "1",
        "open": "100",
        "high": "110",
        "low": "90",
        "close": "105",
        "volume": "9999",
        "turnover": "1234",
        "confirm": False,
    }
    payload = {"topic": "kline.1.BTCUSDT", "data": [candle]}
    assert stream_bars("bybit", payload, {"BTCUSDT": reference()}, CUTOFF) == []
    candle["confirm"] = True
    assert stream_bars("bybit", payload, {"BTCUSDT": reference()}, CUTOFF)[0].quote_turnover == 1234
    candle["interval"] = "5"
    with pytest.raises(ValueError, match="interval"):
        stream_bars("bybit", payload, {"BTCUSDT": reference()}, CUTOFF)


def test_binance_stream_requires_correct_symbol_and_confirmed_trade_kline() -> None:
    ref = reference().model_copy(update={"provider": "binance"})
    candle = {
        "s": "BTCUSDT",
        "i": "1m",
        "t": CUTOFF - MINUTE,
        "T": CUTOFF - 1,
        "o": "100",
        "h": "110",
        "l": "90",
        "c": "105",
        "q": "1234",
        "x": True,
    }
    payload = {"e": "kline", "s": "BTCUSDT", "k": candle}
    assert stream_bars("binance", payload, {"BTCUSDT": ref}, CUTOFF)[0].close == 105
    payload["s"] = "ETHUSDT"
    with pytest.raises(ValueError, match="mismatch"):
        stream_bars("binance", payload, {"BTCUSDT": ref}, CUTOFF)
