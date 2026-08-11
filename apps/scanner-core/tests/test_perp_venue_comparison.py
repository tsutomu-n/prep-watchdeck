import asyncio
import contextlib
from typing import cast

import pytest

from prep_watchdeck.application.perp_venue_comparison import (
    PerpVenueComparisonCollector,
    PerpVenueFetcher,
    PerpVenueFetchResult,
    refresh_perp_venue_comparison_once,
    refresh_perp_venue_comparison_periodically,
)
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


async def test_perp_venue_collector_keeps_catalog_only_across_failure_and_recovers() -> None:
    contracts = aave_contracts()
    fetcher = fetch_sequence(
        (contracts, aave_observations(), {}),
        (
            [contracts[1]],
            [aave_observations(now_ms=NOW_MS + 300_000, hyperliquid_mark=102)[1]],
            {"bitget": "TimeoutError"},
        ),
        (
            contracts,
            aave_observations(
                now_ms=NOW_MS + 600_000,
                bitget_mark=103,
                hyperliquid_mark=104,
            ),
            {},
        ),
    )

    collector = PerpVenueComparisonCollector()
    await refresh_perp_venue_comparison_once(
        collector,
        fetcher=fetcher,
        generated_at_ms=NOW_MS,
    )
    initial = cast(dict[str, object], collector.snapshot())
    assert cast(list[dict[str, object]], initial["items"])[0]["status"] == "ready"

    await refresh_perp_venue_comparison_once(
        collector,
        fetcher=fetcher,
        generated_at_ms=NOW_MS + 300_000,
    )
    failed = cast(dict[str, object], collector.snapshot())
    failed_item = cast(list[dict[str, object]], failed["items"])[0]
    assert failed_item["status"] == "partial"
    failed_sources = cast(list[dict[str, object]], failed_item["sources"])
    assert failed_sources[0]["markPrice"] is None
    assert failed_sources[0]["error"] == "TimeoutError"
    assert failed_sources[1]["markPrice"] == 102
    source_health = cast(list[dict[str, object]], failed["sources"])
    assert source_health == [
        {
            "venue": "bitget",
            "status": "unavailable",
            "observedAt": None,
            "error": "TimeoutError",
        },
        {
            "venue": "hyperliquid",
            "status": "ok",
            "observedAt": NOW_MS + 300_000,
            "error": None,
        },
    ]

    await refresh_perp_venue_comparison_once(
        collector,
        fetcher=fetcher,
        generated_at_ms=NOW_MS + 600_000,
    )
    recovered = cast(dict[str, object], collector.snapshot())
    recovered_item = cast(list[dict[str, object]], recovered["items"])[0]
    assert recovered_item["status"] == "ready"
    recovered_sources = cast(list[dict[str, object]], recovered_item["sources"])
    assert recovered_sources[0]["markPrice"] == 103
    assert recovered_sources[1]["markPrice"] == 104


async def test_perp_venue_collector_expires_cached_catalog_after_thirty_minutes() -> None:
    contracts = aave_contracts()
    fetcher = fetch_sequence(
        (contracts, aave_observations(), {}),
        (
            [contracts[1]],
            [aave_observations(now_ms=NOW_MS + 1_800_001, hyperliquid_mark=102)[1]],
            {"bitget": "TimeoutError"},
        ),
    )

    collector = PerpVenueComparisonCollector()
    await refresh_perp_venue_comparison_once(
        collector,
        fetcher=fetcher,
        generated_at_ms=NOW_MS,
    )
    await refresh_perp_venue_comparison_once(
        collector,
        fetcher=fetcher,
        generated_at_ms=NOW_MS + 1_800_001,
    )

    expired = cast(dict[str, object], collector.snapshot())
    assert expired["items"] == []
    source_health = cast(list[dict[str, object]], expired["sources"])
    assert source_health[0]["status"] == "unavailable"
    assert source_health[0]["error"] == "TimeoutError"


async def test_perp_venue_periodic_refresh_continues_after_internal_error() -> None:
    contracts = aave_contracts()
    fetcher = fetch_sequence(
        (contracts, cast(list[PerpVenueObservation], [object()]), {}),
        (contracts, aave_observations(), {}),
    )
    refresh_completed = asyncio.Event()
    errors: list[Exception] = []

    collector = PerpVenueComparisonCollector()
    task = asyncio.create_task(
        refresh_perp_venue_comparison_periodically(
            collector,
            interval_seconds=0.001,
            initial_delay_seconds=0,
            refresh_immediately=True,
            fetcher=fetcher,
            on_refresh=lambda _block, _duration: refresh_completed.set(),
            on_error=errors.append,
        )
    )
    try:
        await asyncio.wait_for(refresh_completed.wait(), timeout=1)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert [type(error).__name__ for error in errors] == ["AttributeError"]
    recovered = cast(dict[str, object], collector.snapshot())
    assert cast(list[dict[str, object]], recovered["items"])[0]["status"] == "unavailable"


def aave_contracts() -> list[PerpVenueContract]:
    return [
        contract("bitget", "AAVEUSDT", "AAVE", "USDT", "USDT", funding_hours=8),
        contract("hyperliquid", "AAVE", "AAVE", "USDT", "USDC", funding_hours=1),
    ]


def aave_observations(
    *,
    now_ms: int = NOW_MS,
    bitget_mark: float = 100,
    hyperliquid_mark: float = 101,
) -> list[PerpVenueObservation]:
    return [
        observation(
            "bitget",
            "AAVEUSDT",
            bitget_mark,
            0.0008,
            10,
            1_000_000,
            now_ms=now_ms,
        ),
        observation(
            "hyperliquid",
            "AAVE",
            hyperliquid_mark,
            0.0001,
            20,
            2_000_000,
            now_ms=now_ms,
        ),
    ]


def fetch_sequence(*results: PerpVenueFetchResult) -> PerpVenueFetcher:
    remaining = iter(results)

    async def fetcher() -> PerpVenueFetchResult:
        return next(remaining)

    return fetcher


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
    now_ms: int = NOW_MS,
) -> PerpVenueObservation:
    return PerpVenueObservation(
        venue=venue,
        source_symbol=source_symbol,
        mark_price=mark,
        funding_rate=funding,
        open_interest_base=open_interest,
        volume_24h_notional=volume,
        observed_at_ms=now_ms - age_ms,
        source_at_ms=now_ms - age_ms if venue == "bitget" else None,
    )
