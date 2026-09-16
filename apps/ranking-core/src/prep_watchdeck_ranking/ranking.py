"""Pure period calculation over one immutable, common-cutoff input generation."""

import math
import re
from collections import Counter, OrderedDict
from copy import copy
from dataclasses import dataclass
from statistics import median
from types import MappingProxyType
from typing import Literal, cast

from .models import (
    METRIC_VERSION,
    MINUTE,
    Coverage,
    Indicator,
    RankChange,
    RankedRow,
    RankingMap,
    RankingResponse,
    RowState,
)
from .storage import Store

Period = Literal["15m", "1h", "daily"]
Order = Literal["gainers", "losers", "turnover"]
DAY = 1440 * MINUTE
JST = 9 * 60 * MINUTE


def turnover_ratio(turnovers: list[float | None], minutes: int) -> Indicator:
    """24 hours of completed bars; the newest nonoverlapping window is excluded from B."""
    if len(turnovers) != 1440 or any(value is None for value in turnovers):
        return Indicator(status="history_missing")
    values = cast(list[float], turnovers)
    if any(not math.isfinite(value) or value < 0 for value in values):
        return Indicator(status="invalid_data")
    try:
        windows = [math.fsum(values[start : start + minutes]) for start in range(0, 1440, minutes)]
        baseline = median(windows[:-1])
        if baseline == 0:
            return Indicator(status="no_baseline")
        ratio = windows[-1] / baseline
    except OverflowError:
        return Indicator(status="invalid_data")
    return (
        Indicator(value=ratio, status="ready")
        if math.isfinite(ratio)
        else Indicator(status="invalid_data")
    )


def day_range_position(
    cutoff: int, rows: list[tuple[int, float, float, float, float]]
) -> Indicator:
    """The bar ending at D is excluded: today's first bar ends at D + one minute."""
    start = (cutoff + JST) // DAY * DAY - JST
    if start == cutoff:
        return Indicator(status="starting")
    today = [row for row in rows if start < row[0] <= cutoff]
    expected = range(start + MINUTE, cutoff + MINUTE, MINUTE)
    if [row[0] for row in today] != list(expected):
        return Indicator(status="history_missing")
    if any(
        not all(math.isfinite(v) and v > 0 for v in (close, high, low)) or not low <= close <= high
        for _, close, _, high, low in today
    ):
        return Indicator(status="invalid_data")
    high, low = max(row[3] for row in today), min(row[4] for row in today)
    if high == low:
        return Indicator(status="no_range")
    position = (today[-1][1] - low) / (high - low) * 100
    if not math.isfinite(position) or not 0 <= position <= 100:
        return Indicator(status="invalid_data")
    return Indicator(value=position, status="ready")


def anchor_at(cutoff: int, period: Period, daily_reference: str) -> int:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", daily_reference):
        raise ValueError("dailyReferenceJst must be HH:mm")
    if cutoff % MINUTE:
        raise ValueError("cutoff must be a minute boundary")
    if period == "15m":
        return cutoff - 15 * MINUTE
    if period == "1h":
        return cutoff - 60 * MINUTE
    if period != "daily":
        raise ValueError("unknown ranking period")
    hours, minutes = map(int, daily_reference.split(":"))
    anchor = (cutoff + JST) // DAY * DAY - JST + (hours * 60 + minutes) * MINUTE
    return anchor - DAY if anchor > cutoff else anchor


@dataclass(frozen=True)
class Series:
    first: int
    closes: tuple[float | None, ...]
    turnover_prefix: tuple[float, ...]
    missing_prefix: tuple[int, ...]
    turnover_15m: Indicator
    turnover_1h: Indicator
    day_position: Indicator

    @classmethod
    def from_rows(
        cls, first: int, cutoff: int, rows: list[tuple[int, float, float, float, float]]
    ) -> "Series":
        size = (cutoff - first) // MINUTE + 1
        closes: list[float | None] = [None] * size
        turnovers: list[float | None] = [None] * size
        for end, close, turnover, _high, _low in rows:
            offset = (end - first) // MINUTE
            closes[offset], turnovers[offset] = close, turnover
        total = [0.0]
        missing = [0]
        for value in turnovers:
            total.append(total[-1] + (value if value is not None else 0))
            missing.append(missing[-1] + (value is None))
        return cls(
            first,
            tuple(closes),
            tuple(total),
            tuple(missing),
            turnover_ratio(turnovers[1:], 15),
            turnover_ratio(turnovers[1:], 60),
            day_range_position(cutoff, rows),
        )

    def calculate(self, anchor: int, cutoff: int) -> tuple[float | None, float | None, RowState]:
        if anchor == cutoff:
            return None, None, "starting"
        start, end = (anchor - self.first) // MINUTE, (cutoff - self.first) // MINUTE
        close = self.closes[end]
        if close is None:
            return None, None, "source_delayed"
        base = self.closes[start]
        if base is None or self.missing_prefix[end + 1] != self.missing_prefix[start + 1]:
            return None, None, "history_missing"
        turnover = self.turnover_prefix[end + 1] - self.turnover_prefix[start + 1]
        change = (close / base - 1) * 100
        if not math.isfinite(change) or not math.isfinite(turnover):
            return None, None, "invalid_data"
        return change, max(0.0, turnover), "ready"


class Generation:
    def __init__(
        self,
        mapping: RankingMap,
        cutoff: int,
        generated_at: int,
        store: Store,
        unavailable_keys: set[str] | None = None,
        disconnected: set[str] | None = None,
        invalid_keys: set[str] | None = None,
        previous: "Generation | None" = None,
    ) -> None:
        if cutoff % MINUTE or generated_at < cutoff:
            raise ValueError("invalid generation cutoff")
        self.mapping, self.cutoff, self.generated_at = mapping, cutoff, generated_at
        self.metric_version = METRIC_VERSION
        # Share immutable inputs and the bounded base cache, without retaining a chain.
        self.previous = copy(previous) if previous else None
        if self.previous is not None:
            self.previous.previous = None
        self.unavailable_keys = frozenset(unavailable_keys or ())
        self.disconnected = frozenset(disconnected or ())
        self.invalid_keys = frozenset(invalid_keys or ())
        first = cutoff - DAY
        self.series = MappingProxyType(
            {
                row.id: Series.from_rows(
                    first, cutoff, store.window(row.reference.key, first, cutoff)
                )
                for row in mapping.rows
                if row.reference
            }
        )
        self.id = f"{mapping.version}:{cutoff}:{generated_at}"
        self.cache: OrderedDict[tuple[str, str, str, float], RankingResponse] = OrderedDict()

    def _base_response(
        self, period: Period, daily_reference: str, order: Order, minimum: float
    ) -> RankingResponse:
        anchor = anchor_at(self.cutoff, period, daily_reference)
        if order not in ("gainers", "losers", "turnover"):
            raise ValueError("unknown ranking order")
        if not math.isfinite(minimum) or minimum < 0 or minimum > 1e18:
            raise ValueError("minTurnover must be finite and between 0 and 1e18")
        key = (period, daily_reference, order, minimum)
        result = self.cache.get(key)
        if result is None:
            result = self._calculate(period, daily_reference, order, minimum, anchor)
            self.cache[key] = result
            if len(self.cache) > 32:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(key)
        return result

    def response(
        self, period: Period, daily_reference: str, order: Order, minimum: float, now: int
    ) -> RankingResponse:
        result = self._base_response(period, daily_reference, order, minimum)
        stale = now - self.cutoff > 150_000
        previous = self.previous
        reason = None
        if stale:
            reason = "current_stale"
        elif previous is None:
            reason = "no_previous_generation"
        elif previous.cutoff != self.cutoff - MINUTE:
            reason = "generation_gap"
        elif previous.mapping.version != self.mapping.version:
            reason = "map_changed"
        elif previous.metric_version != self.metric_version:
            reason = "metric_changed"
        elif now - previous.cutoff > 150_000:
            reason = "previous_stale"
        elif (
            period == "daily"
            and anchor_at(previous.cutoff, period, daily_reference) != result.anchor
        ):
            reason = "anchor_changed"
        old_rows = (
            {
                row.id: row
                for row in previous._base_response(period, daily_reference, order, minimum).rows
            }
            if previous is not None and reason is None
            else {}
        )
        rows = []
        for row in result.rows:
            old = old_rows.get(row.id)
            if row.rank is None:
                change = RankChange(status="not_ranked", reason=row.reason or row.state)
            elif reason is not None:
                change = RankChange(status="unavailable", reason=reason)
            elif old is None:
                change = RankChange(status="unavailable", reason="previous_row_missing")
            elif old.rank is None:
                change = RankChange(status="new", reason=old.reason or old.state)
            else:
                change = RankChange(
                    status="compared", previous_rank=old.rank, delta=old.rank - row.rank
                )
            rows.append(row.model_copy(update={"rank_change": change}))
        return result.model_copy(
            update={
                "rows": tuple(rows),
                "previous_generation_id": previous.id if previous else None,
                "previous_cutoff": previous.cutoff if previous else None,
                "stale": stale,
                "status": "stale" if stale else result.status,
                "roster_stale": now - self.mapping.roster_generated_at > DAY,
            }
        )

    def _calculate(
        self, period: Period, daily_reference: str, order: Order, minimum: float, anchor: int
    ) -> RankingResponse:
        rows: list[RankedRow] = []
        valid = 0
        for item in self.mapping.rows:
            change, turnover = None, None
            ratio = position = Indicator(status="reference_unavailable")
            reason = item.reason
            if item.reference:
                series = self.series[item.id]
                change, turnover, state = series.calculate(anchor, self.cutoff)
                ratio = series.turnover_15m if period == "15m" else series.turnover_1h
                position = series.day_position
                if item.reference.key in self.invalid_keys:
                    change, turnover, state = None, None, "reference_invalid"
                    ratio = position = Indicator(status="reference_unavailable")
                elif item.reference.key in self.unavailable_keys:
                    change, turnover, state = None, None, "source_unavailable"
                    ratio = position = Indicator(status="reference_unavailable")
                elif state == "source_delayed" and item.reference.provider in self.disconnected:
                    state = "source_unavailable"
                reason = None if state == "ready" else state
                if state == "ready":
                    valid += 1
                    if turnover is not None and turnover < minimum:
                        state, reason = "filtered", "min_turnover"
                    elif change is not None and (
                        (order == "gainers" and change <= 0) or (order == "losers" and change >= 0)
                    ):
                        state, reason = "direction_excluded", "direction"
            else:
                state = {
                    "review": "mapping_review",
                    "unsupported": "unsupported",
                    "out_of_scope": "out_of_scope",
                }.get(item.status, "mapping_review")
            if period == "daily":
                ratio = Indicator(status="unsupported_period")
            rows.append(
                RankedRow(
                    id=item.id,
                    asset=item.asset,
                    mapping_status=item.status,
                    venues=tuple(sorted({o.venue for o in item.originals})),
                    originals=item.originals,
                    reference=item.reference,
                    widget=item.widget,
                    state=cast(RowState, state),
                    reason=reason,
                    return_pct=change,
                    quote_turnover=turnover,
                    rank=None,
                    turnover_ratio=ratio,
                    day_range_position=position,
                )
            )
        eligible = [row for row in rows if row.state == "ready"]
        eligible.sort(
            key=lambda row: (
                -(row.quote_turnover or 0)
                if order == "turnover"
                else (row.return_pct or 0) * (1 if order == "losers" else -1),
                row.id,
            )
        )
        ranks = {row.id: index + 1 for index, row in enumerate(eligible)}
        rows = [row.model_copy(update={"rank": ranks.get(row.id)}) for row in rows]
        rows.sort(key=lambda row: (row.rank is None, row.rank or 0, row.id))
        supported = sum(row.reference is not None for row in rows)
        status = (
            "starting"
            if anchor == self.cutoff
            else ("ready" if valid == supported and supported > 0 else "partial")
        )
        return RankingResponse(
            generation_id=self.id,
            map_version=self.mapping.version,
            cutoff=self.cutoff,
            generated_at=self.generated_at,
            roster_generated_at=self.mapping.roster_generated_at,
            roster_stale=False,
            stale=False,
            status=status,
            period=period,
            daily_reference_jst=daily_reference,
            anchor=anchor,
            order=order,
            min_turnover=minimum,
            coverage=Coverage(
                source_instruments=self.mapping.source_instrument_count,
                rows=len(rows),
                crypto_rows=sum(r.mapping_status != "out_of_scope" for r in rows),
                supported=supported,
                widget_supported=sum(r.widget.status == "supported" for r in rows),
                valid=valid,
                ranked=len(eligible),
                reasons=dict(Counter(str(r.state) for r in rows if r.state != "ready")),
            ),
            rows=tuple(rows),
        )
