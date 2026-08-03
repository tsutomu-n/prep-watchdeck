from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp
import pybotters

from prep_watchdeck.errors import BitgetAPIError, BitgetNonJSONError

RETRY_STATUSES = {429, 500, 502, 503, 504}


class BitgetPublicClient:
    def __init__(
        self,
        base_url: str = "https://api.bitget.com",
        timeout_seconds: float = 10.0,
        max_retries: int = 4,
        rate_limit_per_second: float = 15.0,
        retry_base_delay_seconds: float = 0.5,
        retry_max_delay_seconds: float = 10.0,
        retry_jitter_ratio: float = 0.2,
        retry_after_max_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.rate_limit_per_second = rate_limit_per_second
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.retry_max_delay_seconds = retry_max_delay_seconds
        self.retry_jitter_ratio = retry_jitter_ratio
        self.retry_after_max_seconds = retry_after_max_seconds
        self._client: pybotters.Client | None = None
        self._rate_lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def __aenter__(self) -> BitgetPublicClient:
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        self._client = pybotters.Client(apis=None, base_url=self.base_url, timeout=timeout)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def get_json(self, path: str, params: Mapping[str, str | int | float]) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("BitgetPublicClient must be used as an async context manager")

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                await self._wait_for_rate_limit()
                retry_status: int | None = None
                retry_after_seconds: float | None = None
                async with self._client.get(
                    path, params={k: str(v) for k, v in params.items()}
                ) as resp:
                    if resp.status in RETRY_STATUSES:
                        retry_status = resp.status
                        retry_after_seconds = _parse_retry_after_seconds(
                            resp.headers.get("Retry-After"),
                            now=time.time(),
                        )
                        await resp.read()
                    elif resp.status >= 400:
                        text = await resp.text()
                        raise BitgetAPIError(f"HTTP {resp.status}: {text[:200]}")
                    else:
                        try:
                            payload = await resp.json()
                        except Exception as exc:
                            raise BitgetNonJSONError("Bitget response is not JSON") from exc
                        if not isinstance(payload, dict):
                            raise BitgetNonJSONError("Bitget response JSON is not an object")
                        if str(payload.get("code")) != "00000":
                            raise BitgetAPIError(str(payload.get("msg") or payload))
                        return payload
                if retry_status is not None:
                    if attempt < self.max_retries:
                        await asyncio.sleep(
                            self._retry_delay_seconds(
                                attempt,
                                retry_after_seconds=retry_after_seconds,
                            )
                        )
                        continue
                    raise BitgetAPIError(
                        "retryable HTTP status exhausted: "
                        f"status={retry_status} attempts={attempt + 1}"
                    )
            except (TimeoutError, aiohttp.ClientError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(self._retry_delay_seconds(attempt))
                    continue
                detail = str(exc) or type(exc).__name__
                raise BitgetAPIError(
                    "request failed after retries: "
                    f"attempts={attempt + 1} error={type(exc).__name__}: {detail}"
                ) from exc
        raise BitgetAPIError(f"request failed: {last_error}")

    def _retry_delay_seconds(
        self,
        attempt: int,
        *,
        retry_after_seconds: float | None = None,
    ) -> float:
        return _calculate_retry_delay_seconds(
            attempt=attempt,
            base_delay_seconds=self.retry_base_delay_seconds,
            max_delay_seconds=self.retry_max_delay_seconds,
            jitter_ratio=self.retry_jitter_ratio,
            jitter_fraction=random.random(),
            retry_after_seconds=retry_after_seconds,
            retry_after_max_seconds=self.retry_after_max_seconds,
        )

    async def _wait_for_rate_limit(self) -> None:
        if self.rate_limit_per_second <= 0:
            return
        interval = 1.0 / self.rate_limit_per_second
        async with self._rate_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_seconds = self._next_request_at - now
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
                now = loop.time()
            self._next_request_at = now + interval


def _calculate_retry_delay_seconds(
    *,
    attempt: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
    jitter_ratio: float,
    jitter_fraction: float,
    retry_after_seconds: float | None,
    retry_after_max_seconds: float,
) -> float:
    exponential_delay = min(base_delay_seconds * (2**attempt), max_delay_seconds)
    if retry_after_seconds is None:
        delay = exponential_delay
        delay_limit = max_delay_seconds
    else:
        delay = max(exponential_delay, min(retry_after_seconds, retry_after_max_seconds))
        delay_limit = retry_after_max_seconds
    jitter = delay * jitter_ratio * jitter_fraction
    return min(delay + jitter, delay_limit)


def _parse_retry_after_seconds(value: str | None, *, now: float) -> float | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            return None
        seconds = retry_at.timestamp() - now
    return seconds if seconds >= 0 else None
