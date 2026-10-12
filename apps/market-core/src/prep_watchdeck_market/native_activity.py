"""Bitget quote-turnover activity from complete, version-specific candle windows."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Self
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import Field, model_validator

from prep_watchdeck_market.artifacts import ArtifactModel
from prep_watchdeck_market.market_metrics import candle_cutoff

METRIC_VERSION = "bitget-activity-v1"
BASELINE_DAYS = 7
MIN_BASELINE_DAYS = 3
LOW_BASELINE_TURNOVER = {15: 1000.0, 60: 4000.0}
ActivityStatus = Literal["ready", "history_missing", "invalid_data", "no_baseline", "low_baseline"]


def _utc_minute(value: datetime) -> None:
    if value.utcoffset() != timedelta(0) or value.second or value.microsecond:
        raise ValueError("activity timestamp must be a UTC minute boundary")


class ActivityValue(ArtifactModel):
    value: float | None
    status: ActivityStatus

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.status == "ready") != (self.value is not None):
            raise ValueError("only ready activity values contain a finite value")
        return self


class ActivitySample(ArtifactModel):
    start_at: datetime
    end_at: datetime
    turnover: ActivityValue
    price_change_pct: ActivityValue

    @model_validator(mode="after")
    def consistent(self) -> Self:
        _utc_minute(self.start_at)
        _utc_minute(self.end_at)
        if self.start_at >= self.end_at:
            raise ValueError("activity sample must have a positive duration")
        if self.turnover.value is not None and self.turnover.value < 0:
            raise ValueError("turnover cannot be negative")
        return self


class ActivityWindow(ArtifactModel):
    minutes: Literal[15, 60]
    current: ActivitySample
    history: tuple[ActivitySample, ...] = Field(min_length=4, max_length=4)
    baseline_turnover: ActivityValue
    baseline_days: int = Field(ge=0, le=BASELINE_DAYS)
    baseline_end_times: tuple[datetime, ...] = Field(max_length=BASELINE_DAYS)
    relative_ratio: ActivityValue
    previous_change_pct: ActivityValue

    @model_validator(mode="after")
    def consistent(self) -> Self:
        duration = timedelta(minutes=self.minutes)
        if (
            self.current != self.history[-1]
            or any(sample.end_at - sample.start_at != duration for sample in self.history)
            or any(
                a.end_at != b.start_at for a, b in zip(self.history, self.history[1:], strict=False)
            )
        ):
            raise ValueError("history must be four consecutive windows ending at current")
        if self.baseline_days != len(self.baseline_end_times):
            raise ValueError("baseline day count must match its timestamps")
        expected = {self.current.end_at - timedelta(days=n) for n in range(1, BASELINE_DAYS + 1)}
        if list(self.baseline_end_times) != sorted(set(self.baseline_end_times)) or any(
            stamp not in expected for stamp in self.baseline_end_times
        ):
            raise ValueError("baseline timestamps must be distinct same-time historical windows")
        if self.baseline_turnover.value is not None and (
            self.baseline_days < MIN_BASELINE_DAYS or self.baseline_turnover.value < 0
        ):
            raise ValueError("baseline requires three complete days and nonnegative turnover")
        if self.relative_ratio.value is not None and (
            self.relative_ratio.value < 0
            or self.current.turnover.value is None
            or self.baseline_turnover.value is None
            or self.baseline_turnover.value < LOW_BASELINE_TURNOVER[self.minutes]
        ):
            raise ValueError("relative activity requires a usable current value and baseline")
        if self.previous_change_pct.value is not None and (
            self.current.turnover.value is None
            or self.history[-2].turnover.value is None
            or self.history[-2].turnover.value < LOW_BASELINE_TURNOVER[self.minutes]
        ):
            raise ValueError("previous change requires usable adjacent windows")
        return self


class NativeActivityRow(ArtifactModel):
    venue: Literal["bitget"] = "bitget"
    venue_instrument_id: str
    venue_instrument_version_id: int = Field(gt=0)
    source_symbol: str = Field(min_length=1)
    quote_asset: Literal["USDT"] = "USDT"
    windows: dict[str, ActivityWindow]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.venue_instrument_id != f"bitget:{self.source_symbol}":
            raise ValueError("native activity identity must match its exact source symbol")
        if set(self.windows) != {"15m", "1h"} or any(
            self.windows[key].minutes != minutes for key, minutes in (("15m", 15), ("1h", 60))
        ):
            raise ValueError("native activity requires 15m and 1h windows")
        return self


class NativeActivityArtifact(ArtifactModel):
    schema_version: Literal[1] = 1
    metric_version: Literal["bitget-activity-v1"] = METRIC_VERSION
    generation_id: str = Field(min_length=1)
    generated_at: datetime
    candle_cutoff: datetime
    rows: tuple[NativeActivityRow, ...]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if candle_cutoff(self.generated_at) != self.candle_cutoff:
            raise ValueError("activity cutoff must match its generation clock")
        identities = [row.venue_instrument_id for row in self.rows]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate native activity identity")
        if any(
            window.current.end_at != self.candle_cutoff
            for row in self.rows
            for window in row.windows.values()
        ):
            raise ValueError("all activity windows must use the common cutoff")
        return self


def _unavailable(status: ActivityStatus) -> ActivityValue:
    return ActivityValue(value=None, status=status)


def _ready(value: float) -> ActivityValue:
    return (
        ActivityValue(value=value, status="ready")
        if math.isfinite(value)
        else _unavailable("invalid_data")
    )


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _sample(row: dict[str, Any], *, now: datetime) -> ActivitySample:
    def unavailable(status: ActivityStatus) -> ActivitySample:
        return ActivitySample(
            start_at=row["start_at"],
            end_at=row["end_at"],
            turnover=_unavailable(status),
            price_change_pct=_unavailable(status),
        )

    if row["candle_count"] != row["minutes"] or row["missing_volume_count"]:
        return unavailable("history_missing")
    if (
        row["invalid_candle_count"]
        or row["end_finality"] not in ("confirmed", "derived_final")
        or any(
            row[field] is not None and row[field] > now
            for field in ("end_source_at", "end_observed_at")
        )
    ):
        return unavailable("invalid_data")
    turnover = _number(row["turnover"])
    if turnover is None or turnover < 0:
        return unavailable("invalid_data")
    start, end = _number(row["start_close"]), _number(row["end_close"])
    if row["start_close"] is None or row["end_close"] is None:
        price = _unavailable("history_missing")
    elif (
        start is None
        or end is None
        or start <= 0
        or end <= 0
        or any(
            row[field] not in ("confirmed", "derived_final")
            for field in ("start_finality", "end_finality")
        )
        or any(
            row[field] is not None and row[field] > now
            for field in ("start_source_at", "start_observed_at")
        )
    ):
        price = _unavailable("invalid_data")
    else:
        price = _ready((end / start - 1) * 100)
    return ActivitySample(
        start_at=row["start_at"],
        end_at=row["end_at"],
        turnover=_ready(turnover),
        price_change_pct=price,
    )


def _comparison(
    current: ActivityValue, baseline: ActivityValue, *, minutes: int, percent: bool = False
) -> ActivityValue:
    for value in (current, baseline):
        if value.status != "ready":
            return _unavailable(value.status)
    assert current.value is not None and baseline.value is not None
    if baseline.value == 0:
        return _unavailable("no_baseline")
    if baseline.value < LOW_BASELINE_TURNOVER[minutes]:
        return _unavailable("low_baseline")
    ratio = current.value / baseline.value
    return _ready((ratio - 1) * 100 if percent else ratio)


def build_native_activity(
    aggregate_rows: list[dict[str, Any]], *, now: datetime
) -> NativeActivityArtifact:
    """Build only from SQL window aggregates, never from substituted market data."""
    cutoff = candle_cutoff(now)
    grouped: dict[tuple[str, int], dict[tuple[int, str, int], dict[str, Any]]] = {}
    for row in aggregate_rows:
        if row["venue"] != "bitget" or row["quote_asset"] != "USDT":
            raise ValueError("native activity only accepts Bitget USDT contracts")
        identity = (row["source_symbol"], row["venue_instrument_version_id"])
        key = (row["minutes"], row["sample_kind"], row["sample_index"])
        samples = grouped.setdefault(identity, {})
        if key in samples:
            raise ValueError("duplicate activity window aggregate")
        samples[key] = row
    results = []
    expected = {
        (minutes, kind, index)
        for minutes in (15, 60)
        for kind, indexes in (("recent", range(4)), ("baseline", range(1, BASELINE_DAYS + 1)))
        for index in indexes
    }
    for (symbol, version), rows in sorted(grouped.items()):
        if set(rows) != expected:
            raise ValueError("activity query must return every requested aggregate window")
        windows = {}
        for key, minutes in (("15m", 15), ("1h", 60)):
            samples = {}
            for kind, indexes in (("recent", range(4)), ("baseline", range(1, BASELINE_DAYS + 1))):
                for index in indexes:
                    row = rows[(minutes, kind, index)]
                    end = cutoff - (
                        timedelta(minutes=(3 - index) * minutes)
                        if kind == "recent"
                        else timedelta(days=index)
                    )
                    if row["end_at"] != end or row["start_at"] != end - timedelta(minutes=minutes):
                        raise ValueError("activity aggregate has an unexpected window boundary")
                    samples[(kind, index)] = _sample(row, now=now)
            history = tuple(samples[("recent", index)] for index in range(4))
            baseline_samples = [
                samples[("baseline", index)]
                for index in range(BASELINE_DAYS, 0, -1)
                if samples[("baseline", index)].turnover.status == "ready"
            ]
            baseline_values = sorted(
                sample.turnover.value
                for sample in baseline_samples
                if sample.turnover.value is not None
            )
            baseline = _unavailable("history_missing")
            if len(baseline_values) >= MIN_BASELINE_DAYS:
                middle = len(baseline_values) // 2
                median = (
                    baseline_values[middle]
                    if len(baseline_values) % 2
                    else (baseline_values[middle - 1] / 2 + baseline_values[middle] / 2)
                )
                baseline = _ready(median)
            windows[key] = ActivityWindow(
                minutes=minutes,
                current=history[-1],
                history=history,
                baseline_turnover=baseline,
                baseline_days=len(baseline_samples),
                baseline_end_times=tuple(sample.end_at for sample in baseline_samples),
                relative_ratio=_comparison(history[-1].turnover, baseline, minutes=minutes),
                previous_change_pct=_comparison(
                    history[-1].turnover, history[-2].turnover, minutes=minutes, percent=True
                ),
            )
        results.append(
            NativeActivityRow(
                venue_instrument_id=f"bitget:{symbol}",
                venue_instrument_version_id=version,
                source_symbol=symbol,
                windows=windows,
            )
        )
    return NativeActivityArtifact(
        generation_id=f"{cutoff.isoformat()}:{uuid4().hex}",
        generated_at=now.astimezone(UTC),
        candle_cutoff=cutoff,
        rows=tuple(results),
    )


# At most 825 candle reads per current instrument (plus exact price endpoints):
# 7 same-time historical windows and 4 recent windows for each of 15m and 1h.
# The (version, bucket_at) primary key bounds every range; no seven-day raw scan.
NATIVE_ACTIVITY_SQL = """
WITH periods(minutes) AS (VALUES (15), (60)),
window_ends AS (
    SELECT minutes, 'recent'::text AS sample_kind, n AS sample_index,
           %(cutoff)s::timestamptz - (3 - n) * minutes * interval '1 minute' AS end_at
    FROM periods CROSS JOIN generate_series(0, 3) n
    UNION ALL
    SELECT minutes, 'baseline'::text, n,
           %(cutoff)s::timestamptz - n * interval '1 day'
    FROM periods CROSS JOIN generate_series(1, 7) n
), windows AS (
    SELECT *, end_at - minutes * interval '1 minute' AS start_at FROM window_ends
)
SELECT vi.venue_instrument_version_id, vi.venue, vi.source_symbol, vi.quote_asset,
       w.minutes, w.sample_kind, w.sample_index, w.start_at, w.end_at,
       totals.candle_count, totals.missing_volume_count, totals.invalid_candle_count,
       totals.turnover,
       c_start.close_price AS start_close, c_end.close_price AS end_close,
       c_start.finality AS start_finality, c_end.finality AS end_finality,
       c_start.source_at AS start_source_at, c_end.source_at AS end_source_at,
       c_start.observed_at AS start_observed_at, c_end.observed_at AS end_observed_at
FROM venue_instrument_versions vi
CROSS JOIN windows w
CROSS JOIN LATERAL (
    SELECT count(*) AS candle_count,
           count(*) FILTER (WHERE c.volume_notional IS NULL) AS missing_volume_count,
           count(*) FILTER (WHERE
               c.finality NOT IN ('confirmed', 'derived_final')
               OR c.bucket_at <> date_trunc('minute', c.bucket_at)
               OR c.volume_notional < 0
               OR c.volume_notional::text IN ('NaN', 'Infinity', '-Infinity')
               OR c.source_at > %(now)s::timestamptz
               OR c.observed_at > %(now)s::timestamptz
           ) AS invalid_candle_count,
           sum(c.volume_notional) AS turnover
    FROM candle_1m c
    WHERE c.venue_instrument_version_id = vi.venue_instrument_version_id
      AND c.bucket_at >= w.start_at AND c.bucket_at < w.end_at
      AND c.bucket_at >= vi.valid_from
) totals
LEFT JOIN candle_1m c_start
  ON c_start.venue_instrument_version_id = vi.venue_instrument_version_id
 AND c_start.bucket_at = w.start_at - interval '1 minute'
 AND c_start.bucket_at >= vi.valid_from
LEFT JOIN candle_1m c_end
  ON c_end.venue_instrument_version_id = vi.venue_instrument_version_id
 AND c_end.bucket_at = w.end_at - interval '1 minute'
 AND c_end.bucket_at >= vi.valid_from
WHERE vi.valid_to IS NULL AND vi.active AND vi.venue = 'bitget'
  AND vi.asset_class = 'crypto' AND vi.market_type = 'linear_perpetual'
  AND vi.quote_asset = 'USDT' AND vi.settle_asset = 'USDT'
ORDER BY vi.source_symbol, w.minutes, w.sample_kind, w.sample_index
"""


def read_native_activity(connection: Connection[Any], *, now: datetime) -> NativeActivityArtifact:
    cutoff = candle_cutoff(now)
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(NATIVE_ACTIVITY_SQL, {"cutoff": cutoff, "now": now}).fetchall()
        return build_native_activity(rows, now=now)
