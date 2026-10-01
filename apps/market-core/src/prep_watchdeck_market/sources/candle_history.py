from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import aiohttp

from prep_watchdeck_market.candle_recovery_store import RecoveryTarget
from prep_watchdeck_market.candles import (
    Candle1m,
    CandleParseError,
    decimal_value,
    non_negative_integer,
    require_list,
    require_mapping,
    timestamp_milliseconds,
)
from prep_watchdeck_market.sources.bitget_candles import parse_bitget_history_candles

BITGET_HISTORY_URL = "https://api.bitget.com/api/v2/mix/market/history-candles"
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
ASTER_HISTORY_URL = "https://fapi.asterdex.com/fapi/v1/klines"
MAX_BODY_BYTES = 8 * 1024 * 1024
MIN_REQUEST_INTERVAL_SECONDS = 5.0


class HistoryFetchError(RuntimeError):
    """A native history request failed without exposing its response or URL."""

    error_code = "history_unavailable"


class HistoryRateLimited(HistoryFetchError):
    error_code = "history_rate_limited"

    def __init__(self, retry_after_seconds: int | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("history rate limited")


class HistoryBudgetExceeded(HistoryFetchError):
    error_code = "history_budget_exceeded"

    def __init__(self, message: str, *, scope: str = "run") -> None:
        self.scope = scope
        super().__init__(message)


class HistoryPayloadInvalid(HistoryFetchError):
    error_code = "history_payload_invalid"


@dataclass(frozen=True, slots=True)
class HistoryFetchResult:
    candles: tuple[Candle1m, ...]
    rejected_buckets: int
    pages: int
    budget_scope: str | None = None


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise HistoryPayloadInvalid("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise HistoryPayloadInvalid("non-finite JSON value")


def _millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _ranges(buckets: Sequence[datetime]) -> tuple[tuple[datetime, datetime], ...]:
    if not buckets:
        return ()
    ranges: list[tuple[datetime, datetime]] = []
    start = previous = buckets[0]
    for bucket in buckets[1:]:
        if bucket != previous + timedelta(minutes=1):
            ranges.append((start, previous + timedelta(minutes=1)))
            start = bucket
        previous = bucket
    ranges.append((start, previous + timedelta(minutes=1)))
    return tuple(ranges)


class NativeCandleHistoryClient:
    """Single-lane, bounded native REST history transport for one recovery run."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        max_requests: int,
        deadline_seconds: float,
    ) -> None:
        self._session = session
        self._max_requests = max_requests
        self._deadline = asyncio.get_running_loop().time() + deadline_seconds
        self._last_started: float | None = None
        self.request_count = 0

    def _check_budget(self) -> None:
        if (
            self.request_count >= self._max_requests
            or asyncio.get_running_loop().time() >= self._deadline
        ):
            raise HistoryBudgetExceeded("recovery request budget exceeded")

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> tuple[object, datetime]:
        for attempt in range(3):
            self._check_budget()
            now = asyncio.get_running_loop().time()
            if self._last_started is not None:
                wait = MIN_REQUEST_INTERVAL_SECONDS - (now - self._last_started)
                if wait > 0:
                    if now + wait >= self._deadline:
                        raise HistoryBudgetExceeded("recovery deadline reached")
                    await asyncio.sleep(wait)
            self._check_budget()
            self._last_started = asyncio.get_running_loop().time()
            self.request_count += 1
            try:
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=body,
                    timeout=aiohttp.ClientTimeout(
                        total=min(20.0, max(0.001, self._deadline - self._last_started))
                    ),
                ) as response:
                    if response.status in {418, 429}:
                        raw_retry = response.headers.get("Retry-After")
                        retry = (
                            int(raw_retry)
                            if raw_retry
                            and len(raw_retry) <= 5
                            and raw_retry.isdecimal()
                            and 0 < int(raw_retry) <= 86_400
                            else None
                        )
                        raise HistoryRateLimited(retry)
                    if response.status in {401, 403}:
                        raise HistoryFetchError("history authorization failed")
                    if response.status >= 500:
                        if attempt < 2:
                            continue
                        raise HistoryFetchError("history server unavailable")
                    if response.status != 200:
                        raise HistoryFetchError("history request rejected")
                    data = await response.content.read(MAX_BODY_BYTES + 1)
                    observed_at = datetime.now(UTC)
                    if len(data) > MAX_BODY_BYTES:
                        raise HistoryPayloadInvalid("history response exceeds size limit")
                    try:
                        parsed = json.loads(
                            data,
                            parse_float=Decimal,
                            parse_constant=_reject_constant,
                            object_pairs_hook=_reject_duplicate_json_keys,
                        )
                    except (ValueError, UnicodeError) as error:
                        raise HistoryPayloadInvalid("history JSON invalid") from error
                    return parsed, observed_at
            except HistoryRateLimited:
                raise
            except (aiohttp.ClientError, TimeoutError):
                if asyncio.get_running_loop().time() >= self._deadline:
                    raise HistoryBudgetExceeded("recovery deadline reached") from None
                if attempt == 2:
                    raise HistoryFetchError("history transport unavailable") from None
        raise HistoryFetchError("history request exhausted")

    async def fetch_missing(
        self,
        target: RecoveryTarget,
        missing: Sequence[datetime],
        *,
        max_pages: int,
    ) -> HistoryFetchResult:
        expected = set(missing)
        accepted: dict[datetime, Candle1m] = {}
        rejected: set[datetime] = set()
        pages = 0

        async def fetch_pages() -> None:
            nonlocal pages
            for range_start, range_end in _ranges(missing):
                if target.venue == "bitget":
                    if target.quote_asset != target.settle_asset or target.quote_asset not in {
                        "USDT",
                        "USDC",
                    }:
                        raise HistoryPayloadInvalid("unsupported Bitget product type")
                    cursor = range_end
                    while cursor > range_start:
                        if pages >= max_pages:
                            raise HistoryBudgetExceeded(
                                "target page budget exceeded", scope="target"
                            )
                        payload, observed = await self._request_json(
                            "GET",
                            BITGET_HISTORY_URL,
                            params={
                                "symbol": target.source_symbol,
                                "productType": f"{target.quote_asset}-FUTURES",
                                "granularity": "1m",
                                "startTime": str(_millis(range_start)),
                                # Bitget floors endTime to the interval before selecting
                                # earlier candles. Subtracting 1ms loses the final minute.
                                "endTime": str(_millis(cursor)),
                                "limit": "200",
                            },
                        )
                        pages += 1
                        candles, conflicts = parse_bitget_history_candles(
                            payload, source_symbol=target.source_symbol, observed_at=observed
                        )
                        rejected.update(bucket for bucket in conflicts if bucket in expected)
                        if not candles:
                            break
                        for candle in candles:
                            _accept(candle, target, expected, accepted, rejected)
                        earliest = min(c.bucket_start for c in candles)
                        if earliest >= cursor:
                            raise HistoryPayloadInvalid("Bitget page did not move backward")
                        cursor = earliest
                else:
                    max_minutes = 360 if target.venue == "hyperliquid" else 500
                    chunk_start = range_start
                    while chunk_start < range_end:
                        if pages >= max_pages:
                            raise HistoryBudgetExceeded(
                                "target page budget exceeded", scope="target"
                            )
                        chunk_end = min(range_end, chunk_start + timedelta(minutes=max_minutes))
                        if target.venue == "hyperliquid":
                            payload, observed = await self._request_json(
                                "POST",
                                HYPERLIQUID_INFO_URL,
                                body={
                                    "type": "candleSnapshot",
                                    "req": {
                                        "coin": target.source_symbol,
                                        "interval": "1m",
                                        "startTime": _millis(chunk_start),
                                        "endTime": _millis(chunk_end),
                                    },
                                },
                            )
                            candles = _parse_hyperliquid_page(payload, target, observed_at=observed)
                        else:
                            payload, observed = await self._request_json(
                                "GET",
                                ASTER_HISTORY_URL,
                                params={
                                    "symbol": target.source_symbol,
                                    "interval": "1m",
                                    "startTime": str(_millis(chunk_start)),
                                    "endTime": str(_millis(chunk_end) - 1),
                                    "limit": "500",
                                },
                            )
                            candles = _parse_aster_page(payload, target, observed_at=observed)
                        pages += 1
                        for candle in candles:
                            _accept(candle, target, expected, accepted, rejected)
                        chunk_start = chunk_end

        budget_scope: str | None = None
        try:
            await fetch_pages()
        except HistoryBudgetExceeded as exc:
            budget_scope = exc.scope
        return HistoryFetchResult(
            candles=tuple(accepted[b] for b in sorted(accepted)),
            rejected_buckets=len(rejected),
            pages=pages,
            budget_scope=budget_scope,
        )


def _accept(
    candle: Candle1m,
    target: RecoveryTarget,
    expected: set[datetime],
    accepted: dict[datetime, Candle1m],
    rejected: set[datetime],
) -> None:
    if candle.venue != target.venue or candle.source_symbol != target.source_symbol:
        raise HistoryPayloadInvalid("history target mismatch")
    if candle.bucket_start not in expected or candle.bucket_start in rejected:
        return
    prior = accepted.get(candle.bucket_start)
    if prior is not None and (
        prior.open_price,
        prior.high_price,
        prior.low_price,
        prior.close_price,
        prior.volume_base,
        prior.volume_notional,
        prior.trade_count,
        prior.finality,
    ) != (
        candle.open_price,
        candle.high_price,
        candle.low_price,
        candle.close_price,
        candle.volume_base,
        candle.volume_notional,
        candle.trade_count,
        candle.finality,
    ):
        accepted.pop(candle.bucket_start)
        rejected.add(candle.bucket_start)
    else:
        accepted[candle.bucket_start] = candle


def _parse_hyperliquid_page(
    payload: object, target: RecoveryTarget, *, observed_at: datetime
) -> tuple[Candle1m, ...]:
    rows = require_list(payload, field_name="Hyperliquid candle history")
    result: list[Candle1m] = []
    for row in rows:
        item = require_mapping(row, field_name="Hyperliquid candle")
        if item.get("s") != target.source_symbol or item.get("i") != "1m":
            raise HistoryPayloadInvalid("Hyperliquid series mismatch")
        bucket = timestamp_milliseconds(item.get("t"), field_name="Hyperliquid start")
        end = timestamp_milliseconds(item.get("T"), field_name="Hyperliquid end")
        if end != bucket + timedelta(minutes=1) - timedelta(milliseconds=1):
            raise HistoryPayloadInvalid("Hyperliquid interval mismatch")
        result.append(
            Candle1m(
                venue="hyperliquid",
                source_symbol=target.source_symbol,
                bucket_start=bucket,
                open_price=decimal_value(
                    item.get("o"), field_name="Hyperliquid open", positive=True
                ),
                high_price=decimal_value(
                    item.get("h"), field_name="Hyperliquid high", positive=True
                ),
                low_price=decimal_value(item.get("l"), field_name="Hyperliquid low", positive=True),
                close_price=decimal_value(
                    item.get("c"), field_name="Hyperliquid close", positive=True
                ),
                volume_base=decimal_value(item.get("v"), field_name="Hyperliquid base volume"),
                volume_notional=None,
                trade_count=non_negative_integer(item.get("n"), field_name="Hyperliquid trades"),
                finality="derived_final",
                source_at=None,
                observed_at=observed_at,
            )
        )
    return tuple(result)


def _parse_aster_page(
    payload: object, target: RecoveryTarget, *, observed_at: datetime
) -> tuple[Candle1m, ...]:
    rows = require_list(payload, field_name="Aster candle history")
    result: list[Candle1m] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 9:
            raise CandleParseError("Aster kline row is incomplete")
        bucket = timestamp_milliseconds(row[0], field_name="Aster start")
        end = timestamp_milliseconds(row[6], field_name="Aster close")
        if end != bucket + timedelta(minutes=1) - timedelta(milliseconds=1):
            raise HistoryPayloadInvalid("Aster interval mismatch")
        result.append(
            Candle1m(
                venue="aster",
                source_symbol=target.source_symbol,
                bucket_start=bucket,
                open_price=decimal_value(row[1], field_name="Aster open", positive=True),
                high_price=decimal_value(row[2], field_name="Aster high", positive=True),
                low_price=decimal_value(row[3], field_name="Aster low", positive=True),
                close_price=decimal_value(row[4], field_name="Aster close", positive=True),
                volume_base=decimal_value(row[5], field_name="Aster base volume"),
                volume_notional=decimal_value(row[7], field_name="Aster quote volume"),
                trade_count=non_negative_integer(row[8], field_name="Aster trades"),
                finality="derived_final",
                source_at=None,
                observed_at=observed_at,
            )
        )
    return tuple(result)
