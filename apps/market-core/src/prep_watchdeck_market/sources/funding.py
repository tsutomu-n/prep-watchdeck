from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

import aiohttp

from prep_watchdeck_market.models import (
    CatalogInstrument,
    JsonPayload,
    Venue,
    canonical_json_sha256,
)
from prep_watchdeck_market.sources.common import (
    CatalogSourceError,
    observed_now,
    require_list,
    require_mapping,
    safe_source_error_code,
    text,
    timestamp_from_milliseconds,
)

BITGET_FUNDING_URL = "https://api.bitget.com/api/v3/market/history-fund-rate"
BITGET_FUNDING_ENDPOINT = "/api/v3/market/history-fund-rate"
HYPERLIQUID_FUNDING_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_FUNDING_ENDPOINT = "/info:type=fundingHistory,dex=default"
ASTER_FUNDING_URL = "https://fapi.asterdex.com/fapi/v3/fundingRate"
ASTER_FUNDING_ENDPOINT = "/fapi/v3/fundingRate"


class FundingSourceError(CatalogSourceError):
    """A settled public funding-history response did not match its documented contract."""


@dataclass(frozen=True, slots=True)
class FundingEvent:
    venue: Venue
    source_symbol: str
    funding_at: datetime
    funding_rate_raw: Decimal
    observed_at: datetime
    raw_payload: dict[str, object] = field(repr=False, compare=False)

    @property
    def venue_instrument_id(self) -> str:
        return f"{self.venue}:{self.source_symbol}"


@dataclass(frozen=True, slots=True)
class FundingBatch:
    venue: Venue
    source_symbol: str
    endpoint: str
    observed_at: datetime
    payload_hash: str
    events: tuple[FundingEvent, ...]
    raw_payload: JsonPayload = field(repr=False, compare=False)


async def fetch_funding_history(
    session: aiohttp.ClientSession,
    instrument: CatalogInstrument,
    *,
    start_at: datetime,
    end_at: datetime,
) -> FundingBatch:
    """Fetch settled funding events for one active instrument over one bounded window."""

    _validate_request(instrument, start_at=start_at, end_at=end_at)
    try:
        if instrument.venue == "bitget":
            async with session.get(
                BITGET_FUNDING_URL,
                params={
                    "category": "USDT-FUTURES",
                    "symbol": instrument.source_symbol,
                    "limit": "100",
                    "cursor": "1",
                },
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
            return parse_bitget_funding_history(
                payload,
                instrument,
                start_at=start_at,
                end_at=end_at,
                observed_at=observed_now(),
            )

        if instrument.venue == "hyperliquid":
            async with session.post(
                HYPERLIQUID_FUNDING_URL,
                json={
                    "type": "fundingHistory",
                    "coin": instrument.source_symbol,
                    "startTime": _milliseconds(start_at),
                    "endTime": _milliseconds(end_at),
                },
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
            return parse_hyperliquid_funding_history(
                payload,
                instrument,
                start_at=start_at,
                end_at=end_at,
                observed_at=observed_now(),
            )

        if instrument.venue == "aster":
            async with session.get(
                ASTER_FUNDING_URL,
                params={
                    "symbol": instrument.source_symbol,
                    "startTime": str(_milliseconds(start_at)),
                    "endTime": str(_milliseconds(end_at)),
                    "limit": "1000",
                },
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
            return parse_aster_funding_history(
                payload,
                instrument,
                start_at=start_at,
                end_at=end_at,
                observed_at=observed_now(),
            )
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise FundingSourceError(
            f"{instrument.venue} funding history fetch failed",
            error_code=safe_source_error_code(exc),
        ) from exc

    raise FundingSourceError("unsupported funding-history Venue")


def parse_bitget_funding_history(
    payload: object,
    instrument: CatalogInstrument,
    *,
    start_at: datetime,
    end_at: datetime,
    observed_at: datetime,
) -> FundingBatch:
    _validate_request(instrument, start_at=start_at, end_at=end_at)
    _require_aware(observed_at, "observed_at")
    root = require_mapping(payload, field_name="Bitget funding history")
    if root.get("code") != "00000":
        raw_code = root.get("code")
        error_code = "bitget_business_429" if str(raw_code) == "429" else "bitget_business_error"
        raise FundingSourceError(
            "Bitget funding history returned a non-success code",
            error_code=error_code,
        )
    data = require_mapping(root.get("data"), field_name="Bitget funding history data")
    rows = require_list(data.get("resultList"), field_name="Bitget funding history rows")
    events = _parse_events(
        rows,
        instrument,
        start_at=start_at,
        end_at=end_at,
        observed_at=observed_at,
        symbol_field="symbol",
        rate_field="fundingRate",
        timestamp_field="fundingRateTimestamp",
    )
    raw_payload: JsonPayload = root
    return _batch(
        instrument,
        endpoint=BITGET_FUNDING_ENDPOINT,
        observed_at=observed_at,
        events=events,
        raw_payload=raw_payload,
    )


def parse_hyperliquid_funding_history(
    payload: object,
    instrument: CatalogInstrument,
    *,
    start_at: datetime,
    end_at: datetime,
    observed_at: datetime,
) -> FundingBatch:
    _validate_request(instrument, start_at=start_at, end_at=end_at)
    _require_aware(observed_at, "observed_at")
    rows = require_list(payload, field_name="Hyperliquid funding history")
    events = _parse_events(
        rows,
        instrument,
        start_at=start_at,
        end_at=end_at,
        observed_at=observed_at,
        symbol_field="coin",
        rate_field="fundingRate",
        timestamp_field="time",
    )
    raw_payload: JsonPayload = rows
    return _batch(
        instrument,
        endpoint=HYPERLIQUID_FUNDING_ENDPOINT,
        observed_at=observed_at,
        events=events,
        raw_payload=raw_payload,
    )


def parse_aster_funding_history(
    payload: object,
    instrument: CatalogInstrument,
    *,
    start_at: datetime,
    end_at: datetime,
    observed_at: datetime,
) -> FundingBatch:
    _validate_request(instrument, start_at=start_at, end_at=end_at)
    _require_aware(observed_at, "observed_at")
    rows = require_list(payload, field_name="Aster funding history")
    events = _parse_events(
        rows,
        instrument,
        start_at=start_at,
        end_at=end_at,
        observed_at=observed_at,
        symbol_field="symbol",
        rate_field="fundingRate",
        timestamp_field="fundingTime",
    )
    raw_payload: JsonPayload = rows
    return _batch(
        instrument,
        endpoint=ASTER_FUNDING_ENDPOINT,
        observed_at=observed_at,
        events=events,
        raw_payload=raw_payload,
    )


def _batch(
    instrument: CatalogInstrument,
    *,
    endpoint: str,
    observed_at: datetime,
    events: tuple[FundingEvent, ...],
    raw_payload: JsonPayload,
) -> FundingBatch:
    return FundingBatch(
        venue=instrument.venue,
        source_symbol=instrument.source_symbol,
        endpoint=endpoint,
        observed_at=observed_at,
        payload_hash=canonical_json_sha256(raw_payload),
        events=events,
        raw_payload=raw_payload,
    )


def _parse_events(
    rows: list[object],
    instrument: CatalogInstrument,
    *,
    start_at: datetime,
    end_at: datetime,
    observed_at: datetime,
    symbol_field: str,
    rate_field: str,
    timestamp_field: str,
) -> tuple[FundingEvent, ...]:
    by_timestamp: dict[datetime, FundingEvent] = {}
    for value in rows:
        row = require_mapping(value, field_name=f"{instrument.venue} funding row")
        symbol = text(row.get(symbol_field))
        if symbol != instrument.source_symbol:
            raise FundingSourceError("funding event does not match its requested instrument")
        funding_at = timestamp_from_milliseconds(row.get(timestamp_field))
        funding_rate = _finite_decimal(row.get(rate_field))
        if funding_at is None or funding_rate is None:
            raise FundingSourceError("funding event is missing a valid timestamp or rate")
        if funding_at < start_at or funding_at > end_at:
            continue
        event = FundingEvent(
            venue=instrument.venue,
            source_symbol=instrument.source_symbol,
            funding_at=funding_at,
            funding_rate_raw=funding_rate,
            observed_at=observed_at,
            raw_payload=dict(row),
        )
        previous = by_timestamp.get(funding_at)
        if previous is not None and previous.funding_rate_raw != funding_rate:
            raise FundingSourceError("funding history contains conflicting duplicate events")
        by_timestamp[funding_at] = previous or event
    return tuple(by_timestamp[timestamp] for timestamp in sorted(by_timestamp))


def _finite_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _validate_request(
    instrument: CatalogInstrument,
    *,
    start_at: datetime,
    end_at: datetime,
) -> None:
    _require_aware(start_at, "start_at")
    _require_aware(end_at, "end_at")
    if start_at > end_at:
        raise ValueError("funding-history start must not be after end")
    if not instrument.active or instrument.market_type != "linear_perpetual":
        raise ValueError("funding history requires an active linear perpetual instrument")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1_000)
