from __future__ import annotations

from dataclasses import dataclass

from prep_watchdeck.models import CandleBar

FIVE_MINUTES_MS = 300_000


@dataclass(frozen=True)
class GridQuality:
    coverage_ratio: float
    missing_bar_count: int
    zero_volume_bar_ratio: float


def normalize_5m_grid(bars: list[CandleBar]) -> tuple[list[CandleBar | None], GridQuality]:
    """Normalize bars to a 5m timestamp grid without shifting missing rows."""
    if not bars:
        return [], GridQuality(coverage_ratio=0.0, missing_bar_count=0, zero_volume_bar_ratio=0.0)

    ordered = sorted(bars, key=lambda bar: bar.ts)
    by_ts = {bar.ts: bar for bar in ordered}
    start = ordered[0].ts
    end = ordered[-1].ts
    expected_ts = range(start, end + FIVE_MINUTES_MS, FIVE_MINUTES_MS)
    grid = [by_ts.get(ts) for ts in expected_ts]
    expected_count = len(grid)
    missing = sum(1 for bar in grid if bar is None)
    zero_volume = sum(1 for bar in grid if bar is not None and bar.quote_vol == 0)
    present = expected_count - missing
    return grid, GridQuality(
        coverage_ratio=present / expected_count if expected_count else 0.0,
        missing_bar_count=missing,
        zero_volume_bar_ratio=zero_volume / present if present else 0.0,
    )


def change_pct_at(grid: list[CandleBar | None], timeframe_ms: int) -> float | None:
    if not grid:
        return None
    current = grid[-1]
    if current is None:
        return None
    offset = timeframe_ms // FIVE_MINUTES_MS
    if offset <= 0 or len(grid) <= offset:
        return None
    previous = grid[-1 - offset]
    if previous is None or previous.close == 0:
        return None
    return float((current.close / previous.close - 1) * 100)
