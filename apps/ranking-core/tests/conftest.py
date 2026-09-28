from collections.abc import Iterator
from pathlib import Path

import pytest

from prep_watchdeck_ranking.models import (
    MINUTE,
    MappingRow,
    MinuteBar,
    OriginalInstrument,
    RankingMap,
    Reference,
    Widget,
)
from prep_watchdeck_ranking.storage import Store

# 2026-09-12 01:00:00 JST, away from UTC midnight.
CUTOFF = 1_789_142_400_000


def reference(symbol: str = "BTCUSDT", revision: str = "v1") -> Reference:
    return Reference(
        provider="bybit",
        symbol=symbol,
        base_asset=symbol.removesuffix("USDT"),
        multiplier=1,
        revision=revision,
    )


def mapped(asset: str = "BTC") -> MappingRow:
    ref = reference(asset + "USDT")
    return MappingRow(
        id="asset:" + asset,
        asset=asset,
        status="verified",
        reason=None,
        originals=(
            OriginalInstrument(
                venue="bitget",
                instrument_id="bitget:" + asset,
                version_id=1,
                symbol=asset + "USDT",
                base_asset=asset,
                multiplier=1,
            ),
        ),
        reference=ref,
        widget=Widget(
            status="supported",
            symbol=f"BYBIT:{ref.symbol}.P",
            reason=None,
            evidence=("widget-fixture",),
            reference_key=ref.key,
        ),
        evidence=("identity-fixture",),
    )


def mapping(*assets: str) -> RankingMap:
    return RankingMap(
        version="map-v1",
        verified_at=CUTOFF,
        roster_generated_at=CUTOFF,
        roster_fingerprint="fixture",
        roster_source="isolated-fixture",
        source_instrument_count=len(assets),
        rows=tuple(mapped(a) for a in assets),
    )


def candle(ref: Reference, end: int, close: float = 100, turnover: float = 5) -> MinuteBar:
    return MinuteBar(
        reference_key=ref.key,
        end=end,
        open=close,
        high=close,
        low=close,
        close=close,
        quote_turnover=turnover,
    )


def seed(
    store: Store,
    ref: Reference,
    *,
    start_price: float = 100,
    end_price: float = 110,
    turnover: float = 5,
    minutes: int = 1440,
) -> None:
    store.put(
        (
            candle(
                ref, CUTOFF - offset * MINUTE, end_price if offset == 0 else start_price, turnover
            )
            for offset in range(minutes + 1)
        ),
        CUTOFF,
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    state = Store(tmp_path / "ranking", tmp_path / "protected-original")
    try:
        yield state
    finally:
        state.close()
