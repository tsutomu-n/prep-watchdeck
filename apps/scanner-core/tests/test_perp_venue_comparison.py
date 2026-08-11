from typing import cast

import pytest

from prep_watchdeck.domain.perp_venue_comparison import (
    PerpVenueContract,
    PerpVenueObservation,
    build_perp_venue_comparison,
)

NOW_MS = 1_780_000_000_000


def test_perp_venue_comparison_maps_only_proven_fresh_exact_contracts() -> None:
    contracts = [
        contract("bitget", "AAVEUSDT", "AAVE", "USDT", "USDT", funding_hours=8),
        contract("hyperliquid", "AAVE", "AAVE", "USDT", "USDC", funding_hours=1),
        contract("bitget", "HYPEUSDT", "HYPE", "USDT", "USDT", funding_hours=8),
        contract("hyperliquid", "HYPE", "HYPE", "USDC", "USDC", funding_hours=1),
        contract("bitget", "1000PEPEUSDT", "1000PEPE", "USDT", "USDT", funding_hours=8),
        contract("hyperliquid", "kPEPE", "kPEPE", "USDT", "USDC", funding_hours=1),
    ]
    observations = [
        observation("bitget", "AAVEUSDT", 100.0, 0.0008, 10.0, 1_000_000.0),
        observation("hyperliquid", "AAVE", 101.0, 0.0001, 20.0, 2_000_000.0),
    ]

    block = build_perp_venue_comparison(
        contracts,
        observations,
        generated_at_ms=NOW_MS,
    )

    assert block["schemaVersion"] == 1
    assert block["mode"] == "perp_venue_comparison_v1"
    items = cast(list[dict[str, object]], block["items"])
    assert [item["symbol"] for item in items] == ["AAVEUSDT"]
    item = items[0]
    assert item["status"] == "ready"
    assert item["markSpreadPct"] == pytest.approx(1.0)
    bitget, hyperliquid = cast(list[dict[str, object]], item["sources"])
    assert bitget["fundingRatePerHour"] == 0.0001
    assert hyperliquid["fundingRatePerHour"] == 0.0001
    assert bitget["openInterestBase"] == 10.0
    assert bitget["openInterestNotional"] == 1_000.0
    assert hyperliquid["openInterestNotional"] == 2_020.0
    assert hyperliquid["sourceAt"] is None

    partial_block = build_perp_venue_comparison(
        contracts[:2],
        [observations[0]],
        generated_at_ms=NOW_MS,
        errors={"hyperliquid": "TimeoutError"},
    )
    partial = cast(list[dict[str, object]], partial_block["items"])[0]
    assert partial["status"] == "partial"
    assert partial["markSpreadPct"] is None
    partial_sources = cast(list[dict[str, object]], partial["sources"])
    assert partial_sources[1]["error"] == "TimeoutError"

    stale_block = build_perp_venue_comparison(
        contracts[:2],
        [
            observations[0],
            observation(
                "hyperliquid",
                "AAVE",
                101,
                0.0001,
                20,
                2_000_000,
                age_ms=660_000,
            ),
        ],
        generated_at_ms=NOW_MS,
    )
    stale = cast(list[dict[str, object]], stale_block["items"])[0]
    assert stale["status"] == "partial"
    stale_sources = cast(list[dict[str, object]], stale["sources"])
    assert stale_sources[1]["error"] == "stale"


def contract(
    venue: str,
    source_symbol: str,
    asset: str,
    quote: str,
    collateral: str,
    *,
    funding_hours: int,
) -> PerpVenueContract:
    return PerpVenueContract(
        venue=venue,
        source_symbol=source_symbol,
        asset=asset,
        quote=quote,
        collateral=collateral,
        contract_kind="perpetual",
        status="normal",
        is_rwa=False,
        is_default_core=True,
        open_interest_unit="base",
        funding_interval_hours=funding_hours,
    )


def observation(
    venue: str,
    source_symbol: str,
    mark: float,
    funding: float,
    open_interest: float,
    volume: float,
    *,
    age_ms: int = 0,
) -> PerpVenueObservation:
    return PerpVenueObservation(
        venue=venue,
        source_symbol=source_symbol,
        mark_price=mark,
        funding_rate=funding,
        open_interest_base=open_interest,
        volume_24h_notional=volume,
        observed_at_ms=NOW_MS - age_ms,
        source_at_ms=NOW_MS - age_ms if venue == "bitget" else None,
    )
