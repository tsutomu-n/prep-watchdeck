from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from prep_watchdeck_market.market_state import MarketBatch
from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.sources.aster_l1 import parse_aster_l1
from prep_watchdeck_market.sources.bitget_l1 import parse_bitget_l1
from prep_watchdeck_market.sources.common import CatalogSourceError, safe_source_error_code
from prep_watchdeck_market.sources.hyperliquid_l1 import parse_hyperliquid_l1

FIXTURES = Path(__file__).parent / "fixtures" / "l1"
CYCLE_AT = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 8, 14, 10, 0, 1, tzinfo=UTC)


def _instrument(
    venue: str,
    source_symbol: str,
    *,
    interval_seconds: int | None,
) -> CatalogInstrument:
    quote = "USDT"
    collateral = "USDC" if venue == "hyperliquid" else "USDT"
    return CatalogInstrument(
        venue=venue,  # type: ignore[arg-type]
        source_symbol=source_symbol,
        active=True,
        source_status="normal",
        asset_class="crypto",
        market_type="linear_perpetual",
        execution_model="clob",
        base_asset=source_symbol.removesuffix("USDT"),
        quote_asset=quote,
        settle_asset=collateral,
        collateral_asset=collateral,
        quantity_unit="base",
        contract_multiplier=Decimal("1"),
        price_tick=None,
        amount_step=None,
        funding_interval_seconds=interval_seconds,
        raw_definition={},
    )


@pytest.mark.parametrize(
    ("venue", "fixture_name", "parser", "symbols", "interval", "expected"),
    [
        (
            "bitget",
            "bitget.json",
            parse_bitget_l1,
            ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            28_800,
            {
                "mark": Decimal("60000"),
                "reference": Decimal("59990"),
                "reference_kind": "index",
                "funding_hour": Decimal("0.0001"),
                "oi": Decimal("10"),
                "oi_notional": Decimal("600000"),
                "volume": Decimal("1200000"),
                "bid": Decimal("59999"),
                "ask": Decimal("60001"),
                "source_at": datetime(2026, 8, 14, 9, 59, 59, tzinfo=UTC),
            },
        ),
        (
            "hyperliquid",
            "hyperliquid.json",
            parse_hyperliquid_l1,
            ("BTC", "ETH", "SOL"),
            3_600,
            {
                "mark": Decimal("60010"),
                "reference": Decimal("60000"),
                "reference_kind": "oracle",
                "funding_hour": Decimal("0.00001"),
                "oi": Decimal("11.5"),
                "oi_notional": Decimal("690115.0"),
                "volume": Decimal("1300000"),
                "bid": None,
                "ask": None,
                "source_at": None,
            },
        ),
        (
            "aster",
            "aster.json",
            parse_aster_l1,
            ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            None,
            {
                "mark": Decimal("60020"),
                "reference": Decimal("60000"),
                "reference_kind": "index",
                "funding_hour": None,
                "oi": None,
                "oi_notional": None,
                "volume": Decimal("1400000"),
                "bid": Decimal("60019"),
                "ask": Decimal("60021"),
                "source_at": datetime(2026, 8, 14, 9, 59, 57, tzinfo=UTC),
            },
        ),
    ],
)
def test_l1_parsers_table(
    venue: str,
    fixture_name: str,
    parser: Callable[..., MarketBatch],
    symbols: tuple[str, str, str],
    interval: int | None,
    expected: dict[str, object],
) -> None:
    payload = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    instruments = tuple(_instrument(venue, symbol, interval_seconds=interval) for symbol in symbols)
    kwargs = (
        {
            "premium_index_payload": payload["premiumIndex"],
            "book_ticker_payload": payload["bookTicker"],
            "ticker_24h_payload": payload["ticker24h"],
        }
        if venue == "aster"
        else {"payload": payload}
    )

    batch = parser(
        **kwargs,
        instruments=instruments,
        cycle_at=CYCLE_AT,
        observed_at=OBSERVED_AT,
    )

    assert batch.venue == venue
    assert batch.cycle_at == CYCLE_AT
    assert batch.observed_at == OBSERVED_AT
    assert len(batch.payload_hash) == 64
    assert tuple(item.status for item in batch.observations) == (
        "ready",
        "partial",
        "unavailable",
    )
    ready, partial, unavailable = batch.observations
    assert ready.venue_instrument_id == f"{venue}:{symbols[0]}"
    assert ready.source_symbol == symbols[0]
    assert ready.mark_price == expected["mark"]
    assert ready.reference_price == expected["reference"]
    assert ready.reference_price_kind == expected["reference_kind"]
    assert ready.best_bid == expected["bid"]
    assert ready.best_ask == expected["ask"]
    assert ready.funding_interval_seconds == interval
    assert ready.funding_rate_per_hour == expected["funding_hour"]
    assert ready.open_interest_raw == expected["oi"]
    assert ready.open_interest_raw_unit == ("base" if expected["oi"] is not None else None)
    assert ready.open_interest_base == expected["oi"]
    assert ready.open_interest_notional == expected["oi_notional"]
    assert ready.volume_24h_raw == expected["volume"]
    assert ready.volume_24h_unit == "quote"
    assert ready.source_at == expected["source_at"]
    assert ready.error_code is None
    assert len(ready.source_payload_hash) == 64
    assert partial.error_code == "incomplete_source_row"
    assert unavailable.error_code == "missing_source_row"
    assert unavailable.mark_price is None

    if venue == "aster":
        assert ready.next_funding_at == datetime(2026, 8, 14, 16, 0, tzinfo=UTC)
        assert ready.open_interest_raw is None
    elif venue == "bitget":
        assert ready.next_funding_at is None
        with pytest.raises(CatalogSourceError) as rate_limited:
            parse_bitget_l1(
                {"code": "429", "msg": "request frequency limit", "data": []},
                instruments=instruments,
                cycle_at=CYCLE_AT,
                observed_at=OBSERVED_AT,
            )
        assert rate_limited.value.error_code == "bitget_business_429"
        assert safe_source_error_code(rate_limited.value) == "bitget_business_429"
        assert safe_source_error_code(TimeoutError()) == "fetch_timeout"
        assert safe_source_error_code(_Http429Error()) == "http_429"
    else:
        assert ready.reference_price_kind != "index"


class _Http429Error(RuntimeError):
    status = 429
