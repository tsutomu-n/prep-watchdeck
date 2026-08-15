from decimal import Decimal
from typing import Any

import pytest

from prep_watchdeck_market.identity import resolve_market_groups
from prep_watchdeck_market.models import CatalogInstrument, QuantityUnit, Venue


def _instrument(
    venue: Venue,
    source_symbol: str,
    base_asset: str,
    *,
    active: bool = True,
    asset_class: str = "crypto",
    market_type: str = "linear_perpetual",
    quantity_unit: QuantityUnit = "base",
    contract_multiplier: Decimal | None = Decimal("1"),
    raw_definition: dict[str, Any] | None = None,
) -> CatalogInstrument:
    return CatalogInstrument(
        venue=venue,
        source_symbol=source_symbol,
        active=active,
        source_status="TRADING" if active else "CLOSED",
        asset_class=asset_class,
        market_type=market_type,
        execution_model="clob",
        base_asset=base_asset,
        quote_asset="USDT",
        settle_asset="USDT",
        collateral_asset="USDT",
        quantity_unit=quantity_unit,
        contract_multiplier=contract_multiplier,
        price_tick=Decimal("0.01"),
        amount_step=Decimal("0.001"),
        funding_interval_seconds=28_800,
        raw_definition=raw_definition or {},
    )


@pytest.mark.parametrize(
    ("instruments", "expected"),
    [
        (
            [
                _instrument("bitget", "BTCUSDT", "BTC"),
                _instrument("hyperliquid", "BTC", "BTC"),
                _instrument("aster", "BTCUSDT", "BTC"),
                _instrument("bitget", "SOLUSDT", "SOL"),
            ],
            {
                "bitget:BTCUSDT": (
                    "crypto:BTC:linear-perp",
                    "exact_base_heuristic",
                    None,
                ),
                "hyperliquid:BTC": (
                    "crypto:BTC:linear-perp",
                    "exact_base_heuristic",
                    None,
                ),
                "aster:BTCUSDT": (
                    "crypto:BTC:linear-perp",
                    "exact_base_heuristic",
                    None,
                ),
                "bitget:SOLUSDT": (
                    "crypto:SOL:linear-perp",
                    "exact_base_heuristic",
                    None,
                ),
            },
        ),
        (
            [
                _instrument("bitget", "ETHUSDT", "ETH"),
                _instrument("bitget", "ETHUSDT_ALT", "ETH"),
                _instrument("hyperliquid", "ETH", "ETH"),
                _instrument(
                    "bitget",
                    "XBTUSDT",
                    "XBT",
                    raw_definition={"identity_alias_required": True},
                ),
                _instrument(
                    "bitget",
                    "1000PEPEUSDT",
                    "PEPE",
                    contract_multiplier=Decimal("1000"),
                ),
                _instrument("bitget", "DOGEUSDT", "DOGE", contract_multiplier=None),
                _instrument("aster", "UNKNOWNUSDT", "UNKNOWN", quantity_unit="unknown"),
                _instrument("aster", "CONTRACTUSDT", "CONTRACT", quantity_unit="contracts"),
                _instrument("bitget", "OLDUSDT", "OLD", active=False),
                _instrument("aster", "XAUUSDT", "XAU", asset_class="commodity"),
                _instrument("aster", "BTCUSD_FUTURE", "BTC", market_type="future"),
                _instrument("hyperliquid", "EMPTY", ""),
            ],
            {
                "bitget:ETHUSDT": (None, None, "same_venue_collision"),
                "bitget:ETHUSDT_ALT": (None, None, "same_venue_collision"),
                "hyperliquid:ETH": (None, None, "same_venue_collision"),
                "bitget:XBTUSDT": (None, None, "alias_required"),
                "bitget:1000PEPEUSDT": (None, None, "contract_multiplier_not_one"),
                "bitget:DOGEUSDT": (None, None, "contract_multiplier_unknown"),
                "aster:UNKNOWNUSDT": (None, None, "quantity_unit_unknown"),
                "aster:CONTRACTUSDT": (None, None, "quantity_unit_not_base"),
                "bitget:OLDUSDT": (None, None, "inactive"),
                "aster:XAUUSDT": (None, None, "asset_class_not_crypto"),
                "aster:BTCUSD_FUTURE": (None, None, "market_type_not_linear_perpetual"),
                "hyperliquid:EMPTY": (None, None, "base_asset_missing"),
            },
        ),
    ],
)
def test_resolve_market_groups_is_exact_and_fail_closed(
    instruments: list[CatalogInstrument],
    expected: dict[str, tuple[str | None, str | None, str | None]],
) -> None:
    resolutions = resolve_market_groups(instruments)

    assert [resolution.venue_instrument_id for resolution in resolutions] == list(expected)
    assert {
        resolution.venue_instrument_id: (
            resolution.group_id,
            resolution.mapping_method,
            resolution.unmapped_reason,
        )
        for resolution in resolutions
    } == expected
