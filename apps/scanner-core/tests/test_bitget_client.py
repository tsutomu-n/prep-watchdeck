from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
from aiohttp import ClientResponse
from aioresponses import aioresponses

from prep_watchdeck.bitget import client as client_module
from prep_watchdeck.bitget.client import BitgetPublicClient
from prep_watchdeck.errors import BitgetAPIError, BitgetNonJSONError

TEST_URL = "https://api.bitget.com/api/test"
SUCCESS_PAYLOAD = {"code": "00000", "data": []}


def test_retry_defaults_are_bounded() -> None:
    client = BitgetPublicClient()

    assert client.max_retries == 4
    assert client.retry_base_delay_seconds == 0.5
    assert client.retry_max_delay_seconds == 10.0
    assert client.retry_jitter_ratio == 0.2
    assert client.retry_after_max_seconds == 60.0
    assert client.timeout_seconds == 10.0
    assert client.rate_limit_per_second == 15.0


def test_parse_retry_after_supports_delta_seconds_and_http_date() -> None:
    now = datetime(2026, 7, 17, 13, 0, tzinfo=UTC)
    retry_at = format_datetime(now + timedelta(seconds=20), usegmt=True)

    assert client_module._parse_retry_after_seconds("3", now=now.timestamp()) == 3.0
    assert client_module._parse_retry_after_seconds(retry_at, now=now.timestamp()) == 20.0


@pytest.mark.parametrize("value", [None, "", "not-a-delay", "-1"])
def test_parse_retry_after_rejects_invalid_values(value: str | None) -> None:
    assert client_module._parse_retry_after_seconds(value, now=0.0) is None


def test_parse_retry_after_rejects_past_http_date() -> None:
    now = datetime(2026, 7, 17, 13, 0, tzinfo=UTC)
    retry_at = format_datetime(now - timedelta(seconds=1), usegmt=True)

    assert client_module._parse_retry_after_seconds(retry_at, now=now.timestamp()) is None


def test_retry_delay_helper_caps_exponential_and_retry_after() -> None:
    calculate = client_module._calculate_retry_delay_seconds

    assert (
        calculate(
            attempt=5,
            base_delay_seconds=0.5,
            max_delay_seconds=10.0,
            jitter_ratio=0.2,
            jitter_fraction=0.0,
            retry_after_seconds=None,
            retry_after_max_seconds=60.0,
        )
        == 10.0
    )
    assert (
        calculate(
            attempt=0,
            base_delay_seconds=0.5,
            max_delay_seconds=10.0,
            jitter_ratio=0.2,
            jitter_fraction=1.0,
            retry_after_seconds=5.0,
            retry_after_max_seconds=60.0,
        )
        == 6.0
    )
    assert (
        calculate(
            attempt=0,
            base_delay_seconds=0.5,
            max_delay_seconds=10.0,
            jitter_ratio=0.2,
            jitter_fraction=1.0,
            retry_after_seconds=120.0,
            retry_after_max_seconds=60.0,
        )
        == 60.0
    )


async def test_retry_after_header_delays_retry(monkeypatch) -> None:
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", record_sleep)
    with aioresponses() as mocked:
        mocked.get(TEST_URL, status=429, headers={"Retry-After": "3"})
        mocked.get(TEST_URL, payload=SUCCESS_PAYLOAD)
        async with retry_client(max_retries=1) as client:
            payload = await client.get_json("/api/test", {})

    assert payload == SUCCESS_PAYLOAD
    assert sleeps == [3.0]


async def test_retryable_5xx_uses_capped_exponential_backoff(monkeypatch) -> None:
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", record_sleep)
    with aioresponses() as mocked:
        for _ in range(4):
            mocked.get(TEST_URL, status=503)
        mocked.get(TEST_URL, payload=SUCCESS_PAYLOAD)
        async with retry_client(max_retries=4) as client:
            payload = await client.get_json("/api/test", {})

    assert payload == SUCCESS_PAYLOAD
    assert sleeps == [0.5, 1.0, 2.0, 4.0]


async def test_retry_response_is_released_before_backoff_sleep(monkeypatch) -> None:
    TrackingResponse.released = False

    async def assert_released_before_sleep(_seconds: float) -> None:
        assert TrackingResponse.released is True

    monkeypatch.setattr(client_module.asyncio, "sleep", assert_released_before_sleep)
    with aioresponses() as mocked:
        mocked.get(TEST_URL, status=503, response_class=TrackingResponse)
        mocked.get(TEST_URL, payload=SUCCESS_PAYLOAD)
        async with retry_client(max_retries=1) as client:
            payload = await client.get_json("/api/test", {})

    assert payload == SUCCESS_PAYLOAD


async def test_network_timeout_retries_then_succeeds(monkeypatch) -> None:
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", record_sleep)
    with aioresponses() as mocked:
        mocked.get(TEST_URL, exception=TimeoutError())
        mocked.get(TEST_URL, payload=SUCCESS_PAYLOAD)
        async with retry_client(max_retries=1) as client:
            payload = await client.get_json("/api/test", {})

    assert payload == SUCCESS_PAYLOAD
    assert sleeps == [0.5]


async def test_timeout_exhaustion_includes_attempt_count_and_exception_type(monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(client_module.asyncio, "sleep", no_sleep)
    with aioresponses() as mocked:
        mocked.get(TEST_URL, exception=TimeoutError(), repeat=True)
        async with retry_client(max_retries=4) as client:
            with pytest.raises(BitgetAPIError) as exc_info:
                await client.get_json("/api/test", {})

    message = str(exc_info.value)
    assert "attempts=5" in message
    assert "TimeoutError" in message


async def test_non_retryable_400_fails_after_one_attempt() -> None:
    with aioresponses() as mocked:
        mocked.get(TEST_URL, status=400, body="invalid request")
        async with retry_client(max_retries=4) as client:
            with pytest.raises(BitgetAPIError, match="HTTP 400"):
                await client.get_json("/api/test", {})

    assert request_count(mocked) == 1


async def test_invalid_json_fails_after_one_attempt() -> None:
    with aioresponses() as mocked:
        mocked.get(TEST_URL, body="not json", content_type="application/json")
        async with retry_client(max_retries=4) as client:
            with pytest.raises(BitgetNonJSONError, match="not JSON"):
                await client.get_json("/api/test", {})

    assert request_count(mocked) == 1


async def test_bitget_business_error_fails_after_one_attempt() -> None:
    with aioresponses() as mocked:
        mocked.get(TEST_URL, payload={"code": "40017", "msg": "invalid symbol"})
        async with retry_client(max_retries=4) as client:
            with pytest.raises(BitgetAPIError, match="invalid symbol"):
                await client.get_json("/api/test", {})

    assert request_count(mocked) == 1


async def test_cancellation_is_not_retried() -> None:
    with aioresponses() as mocked:
        mocked.get(TEST_URL, exception=asyncio.CancelledError())
        async with retry_client(max_retries=4) as client:
            with pytest.raises(asyncio.CancelledError):
                await client.get_json("/api/test", {})

    assert request_count(mocked) == 1


def retry_client(*, max_retries: int) -> BitgetPublicClient:
    client = BitgetPublicClient(max_retries=max_retries, rate_limit_per_second=0)
    client.retry_base_delay_seconds = 0.5
    client.retry_max_delay_seconds = 10.0
    client.retry_jitter_ratio = 0.0
    client.retry_after_max_seconds = 60.0
    return client


def request_count(mocked: aioresponses) -> int:
    requests = mocked.requests or {}
    return sum(len(calls) for calls in requests.values())


class TrackingResponse(ClientResponse):
    released = False

    def release(self) -> None:
        type(self).released = True
        super().release()
