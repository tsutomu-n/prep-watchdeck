from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from prep_watchdeck.adapters.duckdb import DuckDbSnapshotCache
from prep_watchdeck.constants import TIMEFRAME_BARS
from prep_watchdeck.domain.enums import Category
from prep_watchdeck.domain.features.time_grid import FIVE_MINUTES_MS
from prep_watchdeck.models import CandleBar
from prep_watchdeck.storage.past_notes import PastNote, PastNoteRepository, make_past_note

AUTO_REKINDLE_REASON = "自動検出: 過去急変"
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_MIN_ABS_CHANGE_PCT = 8.0
DEFAULT_MIN_TURNOVER_USDT = 300_000.0
DAY_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class RekindleMatch:
    symbol: str
    event_at_ms: int
    change_pct: float
    turnover_usdt: float


@dataclass(frozen=True)
class RekindleDetectionResult:
    matches: list[RekindleMatch]
    written_count: int
    current_path: str


def detect_rekindle_notes(
    *,
    cache: DuckDbSnapshotCache,
    past_notes: PastNoteRepository,
    now_ms: int | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    min_abs_change_pct: float = DEFAULT_MIN_ABS_CHANGE_PCT,
    min_turnover_usdt: float = DEFAULT_MIN_TURNOVER_USDT,
) -> RekindleDetectionResult:
    resolved_now_ms = now_ms if now_ms is not None else int(datetime.now(UTC).timestamp() * 1000)
    snapshot = cache.latest()
    if snapshot is None:
        past_notes.save_many([], now_ms=resolved_now_ms)
        return RekindleDetectionResult(
            matches=[], written_count=0, current_path=str(past_notes.current_path())
        )

    active_symbols = [
        row.symbol
        for row in snapshot.rows
        if row.category != Category.NO_TRADE and row.symbol.strip()
    ]
    start_ms = resolved_now_ms - lookback_days * DAY_MS
    candles_by_symbol = cache.load_candles_5m(
        active_symbols, start_ms=start_ms, end_ms=resolved_now_ms
    )
    matches: list[RekindleMatch] = []
    for symbol in active_symbols:
        match = _best_rekindle_match(
            symbol=symbol,
            bars=candles_by_symbol.get(symbol, []),
            min_abs_change_pct=min_abs_change_pct,
            min_turnover_usdt=min_turnover_usdt,
        )
        if match is not None:
            matches.append(match)
    notes = [_match_to_note(match, now_ms=resolved_now_ms) for match in matches]
    past_notes.save_many(notes, now_ms=resolved_now_ms)
    return RekindleDetectionResult(
        matches=matches,
        written_count=len(notes),
        current_path=str(past_notes.current_path()),
    )


def _best_rekindle_match(
    *,
    symbol: str,
    bars: list[CandleBar],
    min_abs_change_pct: float,
    min_turnover_usdt: float,
) -> RekindleMatch | None:
    ordered = sorted({bar.ts: bar for bar in bars}.values(), key=lambda bar: bar.ts)
    window_bars = TIMEFRAME_BARS["4h"]
    if len(ordered) <= window_bars:
        return None

    best: RekindleMatch | None = None
    for end_index in range(window_bars, len(ordered)):
        start_bar = ordered[end_index - window_bars]
        end_bar = ordered[end_index]
        if end_bar.ts - start_bar.ts > window_bars * FIVE_MINUTES_MS:
            continue
        previous_close = float(start_bar.close)
        if previous_close <= 0:
            continue
        change_pct = (float(end_bar.close) / previous_close - 1.0) * 100.0
        window = ordered[end_index - window_bars + 1 : end_index + 1]
        turnover_usdt = sum(float(bar.quote_vol) for bar in window)
        if abs(change_pct) < min_abs_change_pct or turnover_usdt < min_turnover_usdt:
            continue
        candidate = RekindleMatch(
            symbol=symbol,
            event_at_ms=end_bar.ts,
            change_pct=change_pct,
            turnover_usdt=turnover_usdt,
        )
        if best is None or _match_sort_key(candidate) > _match_sort_key(best):
            best = candidate
    return best


def _match_to_note(match: RekindleMatch, *, now_ms: int) -> PastNote:
    event_at = datetime.fromtimestamp(match.event_at_ms / 1000, UTC).strftime("%Y-%m-%d %H:%M UTC")
    note = (
        f"検出日={event_at}, "
        f"4h変化率={match.change_pct:+.1f}%, "
        f"4h売買代金={match.turnover_usdt:,.0f} USDT"
    )
    return make_past_note(
        symbol=match.symbol,
        reason=AUTO_REKINDLE_REASON,
        note=note,
        now_ms=now_ms,
    )


def _match_sort_key(match: RekindleMatch) -> tuple[float, float, int]:
    return (abs(match.change_pct), match.turnover_usdt, match.event_at_ms)
