from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import aiohttp
import pytest

from prep_watchdeck_market.funding_store import _validate_batches
from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.sources import funding, mexc
from prep_watchdeck_market.sources.funding import (
    ASTER_FUNDING_ENDPOINT,
    BITGET_FUNDING_ENDPOINT,
    HYPERLIQUID_FUNDING_ENDPOINT,
    FundingSourceError,
    parse_aster_funding_history,
    parse_bitget_funding_history,
    parse_hyperliquid_funding_history,
)

START = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
END = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
OBSERVED = datetime(2026, 8, 18, 12, 0, 5, tzinfo=UTC)


def test_mexc_history_shares_the_http_completion_time_with_its_events(monkeypatch) -> None:
    instrument = _instrument("mexc", "BTC_USDT", 28_800)
    session = cast(aiohttp.ClientSession, object())
    settled_at = datetime(2026, 8, 18, 8, tzinfo=UTC)
    payload = {
        "success": True,
        "code": 0,
        "data": {
            "resultList": [
                {"symbol": "BTC_USDT", "fundingRate": "-0.0001", "settleTime": _ms(settled_at)}
            ]
        },
    }
    response_completed = False
    clock = iter((OBSERVED, OBSERVED + timedelta(microseconds=1)))

    async def fetch(_session, endpoint, *, params, lane):
        nonlocal response_completed
        assert _session is session
        assert endpoint == "/api/v1/contract/funding_rate/history"
        assert params == {"symbol": "BTC_USDT", "page_size": "100", "page_num": "1"}
        assert lane == "recovery"
        response_completed = True
        return payload

    def observed_now() -> datetime:
        assert response_completed
        return next(clock)

    monkeypatch.setattr(mexc, "fetch_mexc_json", fetch)
    monkeypatch.setattr(funding, "observed_now", observed_now)
    batch = asyncio.run(
        funding.fetch_funding_history(session, instrument, start_at=START, end_at=END)
    )

    _validate_batches((batch,))
    assert batch.observed_at == OBSERVED
    assert len(batch.events) == 1
    assert batch.events[0].observed_at == OBSERVED
    assert batch.events[0].funding_at == settled_at
    assert batch.events[0].funding_rate_raw == Decimal("-0.0001")
    assert batch.raw_payload == payload


def test_bitget_parser_filters_window_sorts_and_deduplicates() -> None:
    instrument = _instrument("bitget", "BTCUSDT", 28_800)
    payload = {
        "code": "00000",
        "msg": "success",
        "requestTime": _ms(OBSERVED),
        "data": {
            "resultList": [
                _bitget_row("BTCUSDT", "0.0002", datetime(2026, 8, 18, 11, tzinfo=UTC)),
                _bitget_row("BTCUSDT", "-0.0001", datetime(2026, 8, 18, 9, tzinfo=UTC)),
                _bitget_row("BTCUSDT", "-0.0001", datetime(2026, 8, 18, 9, tzinfo=UTC)),
                _bitget_row("BTCUSDT", "0.9", datetime(2026, 8, 18, 7, tzinfo=UTC)),
            ]
        },
    }

    batch = parse_bitget_funding_history(
        payload,
        instrument,
        start_at=START,
        end_at=END,
        observed_at=OBSERVED,
    )

    assert batch.endpoint == BITGET_FUNDING_ENDPOINT
    assert [item.funding_at.hour for item in batch.events] == [9, 11]
    assert [item.funding_rate_raw for item in batch.events] == [
        Decimal("-0.0001"),
        Decimal("0.0002"),
    ]
    assert all(item.observed_at == OBSERVED for item in batch.events)


def test_hyperliquid_and_aster_parsers_preserve_provider_identity() -> None:
    hyperliquid = _instrument("hyperliquid", "BTC", 3_600)
    hyperliquid_batch = parse_hyperliquid_funding_history(
        [
            {
                "coin": "BTC",
                "fundingRate": "0.0000125",
                "premium": "0.0001",
                "time": _ms(datetime(2026, 8, 18, 10, tzinfo=UTC)),
            }
        ],
        hyperliquid,
        start_at=START,
        end_at=END,
        observed_at=OBSERVED,
    )
    assert hyperliquid_batch.endpoint == HYPERLIQUID_FUNDING_ENDPOINT
    assert hyperliquid_batch.events[0].venue_instrument_id == "hyperliquid:BTC"

    aster = _instrument("aster", "BTCUSDT", None)
    aster_batch = parse_aster_funding_history(
        [
            {
                "symbol": "BTCUSDT",
                "fundingRate": "-0.0003",
                "fundingTime": _ms(datetime(2026, 8, 18, 8, tzinfo=UTC)),
            }
        ],
        aster,
        start_at=START,
        end_at=END,
        observed_at=OBSERVED,
    )
    assert aster_batch.endpoint == ASTER_FUNDING_ENDPOINT
    assert aster_batch.events[0].funding_rate_raw == Decimal("-0.0003")


def test_parser_rejects_conflicting_duplicate_or_wrong_symbol() -> None:
    instrument = _instrument("aster", "BTCUSDT", None)
    timestamp = datetime(2026, 8, 18, 8, tzinfo=UTC)
    with pytest.raises(FundingSourceError, match="conflicting duplicate"):
        parse_aster_funding_history(
            [
                {"symbol": "BTCUSDT", "fundingRate": "0.1", "fundingTime": _ms(timestamp)},
                {"symbol": "BTCUSDT", "fundingRate": "0.2", "fundingTime": _ms(timestamp)},
            ],
            instrument,
            start_at=START,
            end_at=END,
            observed_at=OBSERVED,
        )

    with pytest.raises(FundingSourceError, match="requested instrument"):
        parse_aster_funding_history(
            [{"symbol": "ETHUSDT", "fundingRate": "0.1", "fundingTime": _ms(timestamp)}],
            instrument,
            start_at=START,
            end_at=END,
            observed_at=OBSERVED,
        )


def _instrument(
    venue: str,
    symbol: str,
    interval_seconds: int | None,
) -> CatalogInstrument:
    base = symbol.removesuffix("USDT").removesuffix("_")
    return CatalogInstrument(
        venue=venue,  # type: ignore[arg-type]
        source_symbol=symbol,
        active=True,
        source_status="normal",
        asset_class="crypto",
        market_type="linear_perpetual",
        execution_model="clob",
        base_asset=base,
        quote_asset="USDT",
        settle_asset="USDT",
        collateral_asset="USDT",
        quantity_unit="base",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.01"),
        amount_step=Decimal("0.001"),
        funding_interval_seconds=interval_seconds,
        raw_definition={"symbol": symbol},
    )


def _bitget_row(symbol: str, rate: str, timestamp: datetime) -> dict[str, object]:
    return {
        "symbol": symbol,
        "fundingRate": rate,
        "fundingRateTimestamp": str(_ms(timestamp)),
    }


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1_000)
