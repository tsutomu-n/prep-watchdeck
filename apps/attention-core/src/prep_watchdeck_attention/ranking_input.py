"""One bounded canonical Ranking HTTP request to a fixed loopback endpoint."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType

import aiohttp
from prep_watchdeck_ranking.models import RankingResponse
from pydantic import ValidationError

from prep_watchdeck_attention.config import validate_loopback_port

CANONICAL_RANKING_QUERY: Mapping[str, str] = MappingProxyType(
    {"period": "15m", "dailyReferenceJst": "00:00", "order": "turnover", "minTurnover": "0"}
)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 5
RankingFetcher = Callable[..., Awaitable[bytes]]


class RankingInputError(ValueError):
    """Ranking generation is unavailable, malformed, stale or future-dated."""


async def _fetch(url: str, *, params: Mapping[str, str]) -> bytes:
    async with (
        aiohttp.ClientSession(
            trust_env=False, timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        ) as session,
        session.get(url, params=params, allow_redirects=False) as response,
    ):
        if response.status != 200:
            raise RankingInputError(f"ranking_http_status:{response.status}")
        if response.content_length is not None and response.content_length > MAX_RESPONSE_BYTES:
            raise RankingInputError("ranking_response_too_large")
        chunks = bytearray()
        async for chunk in response.content.iter_chunked(64 * 1024):
            chunks.extend(chunk)
            if len(chunks) > MAX_RESPONSE_BYTES:
                raise RankingInputError("ranking_response_too_large")
        return bytes(chunks)


class RankingInputReader:
    def __init__(self, *, port: int, fetcher: RankingFetcher | None = None):
        validate_loopback_port(port, reserved={5432, 55432})
        self.url = f"http://127.0.0.1:{port}/rankings"
        self.fetcher = fetcher or _fetch

    async def read(self, *, now_ms: int) -> RankingResponse:
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                raw = await self.fetcher(self.url, params=CANONICAL_RANKING_QUERY)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RankingInputError("ranking_response_too_large")
            value = RankingResponse.model_validate_json(raw)
        except (aiohttp.ClientError, TimeoutError, ValidationError) as error:
            raise RankingInputError("ranking_input_unavailable") from error
        if len({row.id for row in value.rows}) != len(value.rows) or value.coverage.rows != len(
            value.rows
        ):
            raise RankingInputError("ranking_row_identity_invalid")
        if (
            value.cutoff > now_ms
            or value.generated_at > now_ms
            or value.roster_generated_at > now_ms
            or value.cutoff <= 0
            or value.cutoff % 60_000
            or value.generated_at < value.cutoff
        ):
            raise RankingInputError("invalid_ranking_timestamp")
        if now_ms - value.cutoff > 150_000 or now_ms - value.generated_at > 150_000:
            raise RankingInputError("ranking_stale")
        if value.stale or value.status in ("starting", "stale"):
            raise RankingInputError("ranking_unavailable")
        if (
            value.period != "15m"
            or value.daily_reference_jst != "00:00"
            or value.order != "turnover"
            or value.min_turnover != 0
        ):
            raise RankingInputError("noncanonical_ranking_response")
        return value
