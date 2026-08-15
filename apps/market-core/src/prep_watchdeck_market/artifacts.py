from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from prep_watchdeck_market.models import Venue
from prep_watchdeck_market.selected_store import SelectedMarketView, read_selected_market

ArtifactStatus = Literal["ready", "partial", "unavailable", "stale"]
MarketStatus = Literal["ready", "partial", "unavailable", "stale"]
CollectorStatus = Literal["succeeded", "partial", "failed"]
ChartFinality = Literal["confirmed", "derived_final", "mixed"]
ChartTimeframeName = Literal["5m", "15m", "1h", "4h", "24h"]

_USD_LIKE = frozenset({"USD", "USDC", "USDT"})
_L1_MAX_AGE = timedelta(seconds=120)
_CATALOG_MAX_AGE = timedelta(minutes=30)
_DEPTH_MAX_AGE = timedelta(seconds=10)
_CHART_LIMIT = 500
_TIMEFRAMES: tuple[tuple[ChartTimeframeName, int], ...] = (
    ("5m", 5 * 60),
    ("15m", 15 * 60),
    ("1h", 60 * 60),
    ("4h", 4 * 60 * 60),
    ("24h", 24 * 60 * 60),
)


class ArtifactContractError(RuntimeError):
    """An artifact could not be built or published without weakening its contract."""


def _camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class ArtifactModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel_case,
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class ParityAssumption(ArtifactModel):
    code: Literal["usd_usdc_usdt_reference_only"]
    applied_to: Literal["reference_mark_median_only"]
    statement: str


class CatalogProvenanceArtifact(ArtifactModel):
    source_kind: str
    endpoint: str
    documentation_url: str | None
    payload_hash: str
    observed_at: datetime
    source_at: datetime | None


class ReferenceMarkMedianArtifact(ArtifactModel):
    status: Literal["ready", "unavailable"]
    value: float | None
    venue_count: int = Field(ge=0)
    venues: tuple[Venue, ...]
    cycle_at: datetime | None
    max_age_seconds: float | None = Field(default=None, ge=0)
    skew_seconds: float | None = Field(default=None, ge=0)
    unavailable_reason: str | None
    parity_assumption_code: Literal["usd_usdc_usdt_reference_only"]


class UniverseInstrumentArtifact(ArtifactModel):
    venue_instrument_id: str
    venue_instrument_version_id: int = Field(gt=0)
    group_id: str | None
    mapping_method: str | None
    venue: Venue
    source_symbol: str
    base_asset: str
    quote_asset: str
    settle_asset: str
    collateral_asset: str | None
    active: bool
    market_type: str
    execution_model: str
    catalog: CatalogProvenanceArtifact
    quality: ArtifactStatus
    quality_reasons: tuple[str, ...]
    age_seconds: float | None = Field(default=None, ge=0)
    collector_run_id: str | None
    cycle_at: datetime | None
    observed_at: datetime | None
    source_at: datetime | None
    source_payload_hash: str | None
    error_code: str | None
    mark_price: float | None
    reference_price: float | None
    reference_price_kind: Literal["index", "oracle", "none"]
    best_bid: float | None
    best_ask: float | None
    funding_rate_raw: float | None
    funding_interval_seconds: int | None = Field(default=None, gt=0)
    funding_rate_per_hour: float | None
    next_funding_at: datetime | None
    open_interest_raw: float | None
    open_interest_raw_unit: str | None
    open_interest_base: float | None
    open_interest_notional: float | None
    volume_24h_raw: float | None
    volume_24h_unit: str | None
    reference_mark_median: ReferenceMarkMedianArtifact


class UniverseSnapshotArtifact(ArtifactModel):
    schema_version: Literal[1]
    generated_at: datetime
    status: ArtifactStatus
    quality_reasons: tuple[str, ...]
    parity_assumption: ParityAssumption
    items: tuple[UniverseInstrumentArtifact, ...]


class ChartBarArtifact(ArtifactModel):
    bucket_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume_base: float | None
    volume_notional: float | None
    trade_count: int | None = Field(default=None, ge=0)
    finality: ChartFinality
    source_at: datetime | None
    observed_at: datetime
    source_bar_count: int = Field(ge=1)
    expected_source_bar_count: int = Field(ge=1)
    complete: bool
    quality_reasons: tuple[str, ...]


class ChartTimeframeArtifact(ArtifactModel):
    timeframe: ChartTimeframeName
    seconds: int = Field(gt=0)
    bars: tuple[ChartBarArtifact, ...] = Field(max_length=_CHART_LIMIT)


class MarketChartArtifact(ArtifactModel):
    schema_version: Literal[1]
    generated_at: datetime
    status: ArtifactStatus
    quality_reasons: tuple[str, ...]
    venue_instrument_id: str | None
    timeframes: tuple[ChartTimeframeArtifact, ...]


class DepthLevelArtifact(ArtifactModel):
    price: float
    size_base: float


class BookWalkFillArtifact(ArtifactModel):
    base_size: float
    average_price: float
    top_price_impact_bps: float


class BookWalkEstimateArtifact(ArtifactModel):
    notional_quote: float
    buy: BookWalkFillArtifact | None
    sell: BookWalkFillArtifact | None
    buy_unavailable_reason: str | None
    sell_unavailable_reason: str | None
    includes_fees: Literal[False]
    predicts_future_impact: Literal[False]
    confirms_order_availability: Literal[False]


class SelectedInstrumentArtifact(ArtifactModel):
    venue_instrument_id: str
    venue_instrument_version_id: int = Field(gt=0)
    venue: Venue
    source_symbol: str
    quote_asset: str
    depth_received_at: datetime | None
    depth_age_seconds: float | None = Field(default=None, ge=0)
    quality: ArtifactStatus
    quality_reasons: tuple[str, ...]
    bids: tuple[DepthLevelArtifact, ...] = Field(max_length=20)
    asks: tuple[DepthLevelArtifact, ...] = Field(max_length=20)
    book_walks: tuple[BookWalkEstimateArtifact, ...] = Field(max_length=3)


class SelectedTradeArtifact(ArtifactModel):
    venue_instrument_id: str
    venue_instrument_version_id: int = Field(gt=0)
    venue: Venue
    source_symbol: str
    trade_id: str
    side: Literal["buy", "sell"]
    price: float
    size_base: float
    source_at: datetime | None
    received_at: datetime


class BookWalkDisclaimersArtifact(ArtifactModel):
    includes_fees: Literal[False]
    predicts_future_impact: Literal[False]
    confirms_order_availability: Literal[False]
    statement: str


class SelectedPayloadArtifact(ArtifactModel):
    selection_id: str
    group_id: str
    primary_venue_instrument_id: str
    expires_at: datetime
    instruments: tuple[SelectedInstrumentArtifact, ...]
    trades: tuple[SelectedTradeArtifact, ...] = Field(max_length=100)


class SelectedMarketArtifact(ArtifactModel):
    schema_version: Literal[1]
    generated_at: datetime
    status: ArtifactStatus
    quality_reasons: tuple[str, ...]
    disclaimers: BookWalkDisclaimersArtifact
    selection: SelectedPayloadArtifact | None


class CollectorRunArtifact(ArtifactModel):
    run_kind: Literal["catalog", "l1"]
    status: CollectorStatus
    started_at: datetime
    completed_at: datetime | None
    cycle_at: datetime | None
    age_seconds: float = Field(ge=0)
    records_received: int = Field(ge=0)
    records_written: int = Field(ge=0)
    error_code: str | None


class FreshnessArtifact(ArtifactModel):
    status: ArtifactStatus
    latest_at: datetime | None
    age_seconds: float | None = Field(default=None, ge=0)
    max_age_seconds: float = Field(gt=0)
    error_code: str | None


class ArtifactFileStatus(ArtifactModel):
    name: str
    status: Literal["ready", "unavailable"]
    generated_at: datetime | None
    error_code: str | None


class MarketServiceStateArtifact(ArtifactModel):
    schema_version: Literal[1]
    generated_at: datetime
    status: ArtifactStatus
    quality_reasons: tuple[str, ...]
    collectors: tuple[CollectorRunArtifact, ...]
    catalog: FreshnessArtifact
    l1: FreshnessArtifact
    artifacts: tuple[ArtifactFileStatus, ...]


ARTIFACT_MODELS: dict[str, type[ArtifactModel]] = {
    "universe-snapshot.schema.json": UniverseSnapshotArtifact,
    "market-chart.schema.json": MarketChartArtifact,
    "selected-market.schema.json": SelectedMarketArtifact,
    "service-state.schema.json": MarketServiceStateArtifact,
}


@dataclass(frozen=True, slots=True)
class UniverseRecord:
    venue_instrument_version_id: int
    venue: Venue
    source_symbol: str
    base_asset: str
    quote_asset: str
    settle_asset: str
    collateral_asset: str | None
    active: bool
    market_type: str
    execution_model: str
    group_id: str | None
    mapping_method: str | None
    catalog_source_kind: str
    catalog_endpoint: str
    catalog_documentation_url: str | None
    catalog_payload_hash: str
    catalog_observed_at: datetime
    catalog_source_at: datetime | None
    collector_run_id: str | None
    cycle_at: datetime | None
    observed_at: datetime | None
    source_at: datetime | None
    status: MarketStatus | None
    mark_price: Decimal | None
    reference_price: Decimal | None
    reference_price_kind: Literal["index", "oracle", "none"]
    best_bid: Decimal | None
    best_ask: Decimal | None
    funding_rate_raw: Decimal | None
    funding_interval_seconds: int | None
    funding_rate_per_hour: Decimal | None
    next_funding_at: datetime | None
    open_interest_raw: Decimal | None
    open_interest_raw_unit: str | None
    open_interest_base: Decimal | None
    open_interest_notional: Decimal | None
    volume_24h_raw: Decimal | None
    volume_24h_unit: str | None
    l1_source_payload_hash: str | None
    error_code: str | None

    @property
    def venue_instrument_id(self) -> str:
        return f"{self.venue}:{self.source_symbol}"


@dataclass(frozen=True, slots=True)
class CandleRecord:
    venue_instrument_version_id: int
    bucket_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume_base: Decimal | None
    volume_notional: Decimal | None
    trade_count: int | None
    finality: Literal["confirmed", "derived_final"]
    source_at: datetime | None
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class CollectorRunRecord:
    run_kind: Literal["catalog", "l1"]
    status: CollectorStatus
    started_at: datetime
    completed_at: datetime | None
    cycle_at: datetime | None
    records_received: int
    records_written: int
    error_code: str | None


@dataclass(frozen=True, slots=True)
class ArtifactPublishResult:
    status: Literal["ready", "partial"]
    files: tuple[ArtifactFileStatus, ...]


@dataclass(frozen=True, slots=True)
class _MedianPoint:
    venue: Venue
    cycle_at: datetime
    observed_at: datetime
    mark_price: Decimal


def build_universe_snapshot(
    records: Sequence[UniverseRecord],
    *,
    generated_at: datetime,
) -> UniverseSnapshotArtifact:
    now = _utc(generated_at, "generated_at")
    median_by_group = _reference_medians(records, now)
    items = tuple(
        _universe_item(record, now, median_by_group.get(record.group_id))
        for record in sorted(
            records,
            key=lambda item: (
                item.base_asset.upper(),
                item.venue,
                item.source_symbol,
            ),
        )
    )
    reasons: list[str] = []
    if not items:
        status: ArtifactStatus = "unavailable"
        reasons.append("no_current_instruments")
    elif any(item.quality != "ready" for item in items):
        status = "partial"
        reasons.append("contains_non_ready_instruments")
    else:
        status = "ready"
    return UniverseSnapshotArtifact(
        schema_version=1,
        generated_at=now,
        status=status,
        quality_reasons=tuple(reasons),
        parity_assumption=ParityAssumption(
            code="usd_usdc_usdt_reference_only",
            applied_to="reference_mark_median_only",
            statement=(
                "USD, USDC, and USDT are assumed to be at parity only for the reference "
                "mark median; Venue values are not converted, combined, ranked, or treated "
                "as executable prices."
            ),
        ),
        items=items,
    )


def _universe_item(
    record: UniverseRecord,
    now: datetime,
    median: ReferenceMarkMedianArtifact | None,
) -> UniverseInstrumentArtifact:
    quality, age_seconds, reasons = _market_quality(record, now)
    publish_values = quality in {"ready", "partial"}
    numeric_inputs = (
        record.mark_price,
        record.reference_price,
        record.best_bid,
        record.best_ask,
        record.funding_rate_raw,
        record.funding_rate_per_hour,
        record.open_interest_raw,
        record.open_interest_base,
        record.open_interest_notional,
        record.volume_24h_raw,
    )
    if publish_values and any(
        value is not None and _finite_float(value) is None for value in numeric_inputs
    ):
        reasons.append("non_finite_numeric_value")

    def number(value: Decimal | None) -> float | None:
        return _finite_float(value) if publish_values else None

    return UniverseInstrumentArtifact(
        venue_instrument_id=record.venue_instrument_id,
        venue_instrument_version_id=record.venue_instrument_version_id,
        group_id=record.group_id,
        mapping_method=record.mapping_method,
        venue=record.venue,
        source_symbol=record.source_symbol,
        base_asset=record.base_asset,
        quote_asset=record.quote_asset,
        settle_asset=record.settle_asset,
        collateral_asset=record.collateral_asset,
        active=record.active,
        market_type=record.market_type,
        execution_model=record.execution_model,
        catalog=CatalogProvenanceArtifact(
            source_kind=record.catalog_source_kind,
            endpoint=record.catalog_endpoint,
            documentation_url=record.catalog_documentation_url,
            payload_hash=record.catalog_payload_hash,
            observed_at=_utc(record.catalog_observed_at, "catalog_observed_at"),
            source_at=_optional_utc(record.catalog_source_at, "catalog_source_at"),
        ),
        quality=quality,
        quality_reasons=tuple(dict.fromkeys(reasons)),
        age_seconds=age_seconds,
        collector_run_id=record.collector_run_id,
        cycle_at=_optional_utc(record.cycle_at, "cycle_at"),
        observed_at=_optional_utc(record.observed_at, "observed_at"),
        source_at=_optional_utc(record.source_at, "source_at"),
        source_payload_hash=record.l1_source_payload_hash,
        error_code=record.error_code,
        mark_price=number(record.mark_price),
        reference_price=number(record.reference_price),
        reference_price_kind=record.reference_price_kind,
        best_bid=number(record.best_bid),
        best_ask=number(record.best_ask),
        funding_rate_raw=number(record.funding_rate_raw),
        funding_interval_seconds=(record.funding_interval_seconds if publish_values else None),
        funding_rate_per_hour=number(record.funding_rate_per_hour),
        next_funding_at=(
            _optional_utc(record.next_funding_at, "next_funding_at") if publish_values else None
        ),
        open_interest_raw=number(record.open_interest_raw),
        open_interest_raw_unit=record.open_interest_raw_unit if publish_values else None,
        open_interest_base=number(record.open_interest_base),
        open_interest_notional=number(record.open_interest_notional),
        volume_24h_raw=number(record.volume_24h_raw),
        volume_24h_unit=record.volume_24h_unit if publish_values else None,
        reference_mark_median=median or _unavailable_median("unmapped_instrument"),
    )


def _market_quality(
    record: UniverseRecord,
    now: datetime,
) -> tuple[ArtifactStatus, float | None, list[str]]:
    if record.observed_at is None or record.status is None:
        return "unavailable", None, ["l1_missing"]
    observed_at = _utc(record.observed_at, "observed_at")
    age = (now - observed_at).total_seconds()
    if age < 0:
        return "unavailable", None, ["l1_observed_in_future"]
    if age > _L1_MAX_AGE.total_seconds():
        return "stale", age, ["l1_older_than_120_seconds"]
    if record.status == "stale":
        return "stale", age, ["source_status_stale"]
    reasons: list[str] = []
    if record.status != "ready":
        reasons.append(f"source_status_{record.status}")
    if record.error_code:
        reasons.append(f"source_error_{record.error_code}")
    return record.status, age, reasons


def _reference_medians(
    records: Sequence[UniverseRecord],
    now: datetime,
) -> dict[str | None, ReferenceMarkMedianArtifact]:
    records_by_group: dict[str, list[UniverseRecord]] = defaultdict(list)
    for record in records:
        if record.group_id is not None:
            records_by_group[record.group_id].append(record)
    results: dict[str | None, ReferenceMarkMedianArtifact] = {}
    for group_id, members in records_by_group.items():
        points: list[_MedianPoint] = []
        for member in members:
            if (
                not member.active
                or member.status != "ready"
                or member.cycle_at is None
                or member.observed_at is None
                or member.mark_price is None
                or member.quote_asset.upper() not in _USD_LIKE
                or member.settle_asset.upper() not in _USD_LIKE
                or member.collateral_asset is None
                or member.collateral_asset.upper() not in _USD_LIKE
                or not member.mark_price.is_finite()
            ):
                continue
            observed_at = _utc(member.observed_at, "median observed_at")
            age = (now - observed_at).total_seconds()
            if age < 0 or age > _L1_MAX_AGE.total_seconds():
                continue
            points.append(
                _MedianPoint(
                    venue=member.venue,
                    cycle_at=_utc(member.cycle_at, "median cycle_at"),
                    observed_at=observed_at,
                    mark_price=member.mark_price,
                )
            )
        by_cycle: dict[datetime, list[_MedianPoint]] = defaultdict(list)
        for point in points:
            by_cycle[point.cycle_at].append(point)
        eligible_cycles = [
            (cycle_at, cycle_points)
            for cycle_at, cycle_points in by_cycle.items()
            if len({point.venue for point in cycle_points}) >= 2
        ]
        if not eligible_cycles:
            results[group_id] = _unavailable_median("fewer_than_two_venues_same_cycle")
            continue
        cycle_at, cycle_points = max(eligible_cycles, key=lambda item: item[0])
        observed_values = [point.observed_at for point in cycle_points]
        skew_seconds = (max(observed_values) - min(observed_values)).total_seconds()
        if skew_seconds > 30:
            results[group_id] = _unavailable_median("observation_skew_exceeds_30_seconds")
            continue
        values = sorted(point.mark_price for point in cycle_points)
        center = len(values) // 2
        median_value = (
            values[center]
            if len(values) % 2
            else (values[center - 1] + values[center]) / Decimal(2)
        )
        max_age = max((now - value).total_seconds() for value in observed_values)
        venues = tuple(sorted({point.venue for point in cycle_points}))
        results[group_id] = ReferenceMarkMedianArtifact(
            status="ready",
            value=_finite_float(median_value),
            venue_count=len(venues),
            venues=venues,
            cycle_at=cycle_at,
            max_age_seconds=max_age,
            skew_seconds=skew_seconds,
            unavailable_reason=None,
            parity_assumption_code="usd_usdc_usdt_reference_only",
        )
    return results


def _unavailable_median(reason: str) -> ReferenceMarkMedianArtifact:
    return ReferenceMarkMedianArtifact(
        status="unavailable",
        value=None,
        venue_count=0,
        venues=(),
        cycle_at=None,
        max_age_seconds=None,
        skew_seconds=None,
        unavailable_reason=reason,
        parity_assumption_code="usd_usdc_usdt_reference_only",
    )


def build_market_chart(
    venue_instrument_id: str | None,
    candles: Sequence[CandleRecord],
    *,
    generated_at: datetime,
) -> MarketChartArtifact:
    now = _utc(generated_at, "generated_at")
    if venue_instrument_id is None:
        return MarketChartArtifact(
            schema_version=1,
            generated_at=now,
            status="unavailable",
            quality_reasons=("no_selected_instrument",),
            venue_instrument_id=None,
            timeframes=_empty_timeframes(),
        )
    if not _valid_venue_instrument_id(venue_instrument_id):
        raise ArtifactContractError("selected venue_instrument_id is invalid")
    timeframe_artifacts: list[ChartTimeframeArtifact] = []
    top_reasons: list[str] = []
    for timeframe, seconds in _TIMEFRAMES:
        bars, reasons = _aggregate_chart(candles, seconds, now)
        timeframe_artifacts.append(
            ChartTimeframeArtifact(
                timeframe=timeframe,
                seconds=seconds,
                bars=bars[-_CHART_LIMIT:],
            )
        )
        top_reasons.extend(reasons)
    has_bars = any(item.bars for item in timeframe_artifacts)
    if not has_bars:
        status: ArtifactStatus = "unavailable"
        top_reasons.append("no_candles")
    elif top_reasons:
        status = "partial"
    else:
        status = "ready"
    return MarketChartArtifact(
        schema_version=1,
        generated_at=now,
        status=status,
        quality_reasons=tuple(dict.fromkeys(top_reasons)),
        venue_instrument_id=venue_instrument_id,
        timeframes=tuple(timeframe_artifacts),
    )


def _aggregate_chart(
    candles: Sequence[CandleRecord],
    seconds: int,
    now: datetime,
) -> tuple[tuple[ChartBarArtifact, ...], tuple[str, ...]]:
    grouped: dict[datetime, list[CandleRecord]] = defaultdict(list)
    for candle in candles:
        bucket_at = _utc(candle.bucket_at, "candle bucket_at")
        epoch = int(bucket_at.timestamp())
        grouped[datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC)].append(candle)
    artifacts: list[ChartBarArtifact] = []
    top_reasons: list[str] = []
    expected_count = seconds // 60
    for bucket_at, source_rows in sorted(grouped.items()):
        ordered = sorted(source_rows, key=lambda item: item.bucket_at)
        if len({item.venue_instrument_version_id for item in ordered}) != 1:
            top_reasons.append("instrument_version_boundary_omitted")
            continue
        price_values = [
            value
            for item in ordered
            for value in (item.open_price, item.high_price, item.low_price, item.close_price)
        ]
        if any(not value.is_finite() for value in price_values):
            top_reasons.append("non_finite_chart_bar_omitted")
            continue
        starts = {_utc(item.bucket_at, "candle bucket_at") for item in ordered}
        expected_starts = {bucket_at + timedelta(minutes=index) for index in range(expected_count)}
        complete = (
            len(ordered) == expected_count
            and starts == expected_starts
            and bucket_at + timedelta(seconds=seconds) <= now
        )
        finalities = {item.finality for item in ordered}
        finality: ChartFinality = next(iter(finalities)) if len(finalities) == 1 else "mixed"
        reasons: list[str] = []
        if not complete:
            reasons.append("incomplete_source_bars")
        if finality == "mixed":
            reasons.append("mixed_finality")
        if any(item.source_at is None for item in ordered):
            reasons.append("source_time_missing")
            source_at = None
        else:
            source_at = max(
                _utc(item.source_at, "candle source_at")
                for item in ordered
                if item.source_at is not None
            )
        artifacts.append(
            ChartBarArtifact(
                bucket_at=bucket_at,
                open=_required_number(ordered[0].open_price, "chart open"),
                high=_required_number(max(item.high_price for item in ordered), "chart high"),
                low=_required_number(min(item.low_price for item in ordered), "chart low"),
                close=_required_number(ordered[-1].close_price, "chart close"),
                volume_base=_sum_optional(item.volume_base for item in ordered),
                volume_notional=_sum_optional(item.volume_notional for item in ordered),
                trade_count=(
                    None
                    if any(item.trade_count is None for item in ordered)
                    else sum(item.trade_count or 0 for item in ordered)
                ),
                finality=finality,
                source_at=source_at,
                observed_at=max(_utc(item.observed_at, "candle observed_at") for item in ordered),
                source_bar_count=len(ordered),
                expected_source_bar_count=expected_count,
                complete=complete,
                quality_reasons=tuple(reasons),
            )
        )
        top_reasons.extend(reasons)
    return tuple(artifacts), tuple(top_reasons)


def _empty_timeframes() -> tuple[ChartTimeframeArtifact, ...]:
    return tuple(
        ChartTimeframeArtifact(timeframe=timeframe, seconds=seconds, bars=())
        for timeframe, seconds in _TIMEFRAMES
    )


def build_selected_market(
    view: SelectedMarketView | None,
    *,
    generated_at: datetime,
) -> SelectedMarketArtifact:
    now = _utc(generated_at, "generated_at")
    disclaimers = BookWalkDisclaimersArtifact(
        includes_fees=False,
        predicts_future_impact=False,
        confirms_order_availability=False,
        statement=(
            "Book-walk values use only the received visible depth. They exclude fees, do not "
            "predict future impact, and do not confirm order availability or execution."
        ),
    )
    if view is None:
        return SelectedMarketArtifact(
            schema_version=1,
            generated_at=now,
            status="unavailable",
            quality_reasons=("no_active_selection",),
            disclaimers=disclaimers,
            selection=None,
        )
    instruments: list[SelectedInstrumentArtifact] = []
    top_reasons: list[str] = []
    for instrument in view.instruments:
        reasons: list[str] = []
        age: float | None = None
        publish_depth = False
        if instrument.depth_received_at is None:
            quality: ArtifactStatus = "unavailable"
            reasons.append("depth_unavailable")
        else:
            depth_at = _utc(instrument.depth_received_at, "depth_received_at")
            age = (now - depth_at).total_seconds()
            if age < 0:
                quality = "unavailable"
                age = None
                reasons.append("depth_observed_in_future")
            elif age > _DEPTH_MAX_AGE.total_seconds():
                quality = "stale"
                reasons.append("depth_older_than_10_seconds")
            elif not instrument.bids or not instrument.asks:
                quality = "unavailable"
                reasons.append("depth_unavailable")
            else:
                quality = "ready"
                publish_depth = True
        bids = (
            tuple(_depth_level(item.price, item.size_base) for item in instrument.bids[:20])
            if publish_depth
            else ()
        )
        asks = (
            tuple(_depth_level(item.price, item.size_base) for item in instrument.asks[:20])
            if publish_depth
            else ()
        )
        walks = tuple(_book_walk(item) for item in instrument.book_walks[:3])
        instruments.append(
            SelectedInstrumentArtifact(
                venue_instrument_id=f"{instrument.venue}:{instrument.source_symbol}",
                venue_instrument_version_id=instrument.venue_instrument_version_id,
                venue=instrument.venue,
                source_symbol=instrument.source_symbol,
                quote_asset=instrument.quote_asset,
                depth_received_at=instrument.depth_received_at,
                depth_age_seconds=age,
                quality=quality,
                quality_reasons=tuple(reasons),
                bids=bids,
                asks=asks,
                book_walks=walks,
            )
        )
        top_reasons.extend(reasons)
    trades = tuple(
        SelectedTradeArtifact(
            venue_instrument_id=f"{trade.venue}:{trade.source_symbol}",
            venue_instrument_version_id=trade.venue_instrument_version_id,
            venue=trade.venue,
            source_symbol=trade.source_symbol,
            trade_id=trade.trade_id,
            side=trade.side,
            price=_required_number(trade.price, "trade price"),
            size_base=_required_number(trade.size_base, "trade size_base"),
            source_at=_optional_utc(trade.source_at, "trade source_at"),
            received_at=_utc(trade.received_at, "trade received_at"),
        )
        for trade in view.trades[:100]
    )
    if not instruments:
        status: ArtifactStatus = "unavailable"
        top_reasons.append("selected_group_has_no_current_instruments")
    elif top_reasons:
        status = "partial"
    else:
        status = "ready"
    return SelectedMarketArtifact(
        schema_version=1,
        generated_at=now,
        status=status,
        quality_reasons=tuple(dict.fromkeys(top_reasons)),
        disclaimers=disclaimers,
        selection=SelectedPayloadArtifact(
            selection_id=str(view.selection_id),
            group_id=view.group_id,
            primary_venue_instrument_id=view.primary_venue_instrument_id,
            expires_at=_utc(view.expires_at, "selection expires_at"),
            instruments=tuple(instruments),
            trades=trades,
        ),
    )


def _depth_level(price: Decimal, size_base: Decimal) -> DepthLevelArtifact:
    return DepthLevelArtifact(
        price=_required_number(price, "depth price"),
        size_base=_required_number(size_base, "depth size_base"),
    )


def _book_walk(value: Any) -> BookWalkEstimateArtifact:
    return BookWalkEstimateArtifact(
        notional_quote=_required_number(value.notional_quote, "book-walk notional"),
        buy=None if value.buy is None else _book_fill(value.buy),
        sell=None if value.sell is None else _book_fill(value.sell),
        buy_unavailable_reason=value.buy_unavailable_reason,
        sell_unavailable_reason=value.sell_unavailable_reason,
        includes_fees=False,
        predicts_future_impact=False,
        confirms_order_availability=False,
    )


def _book_fill(value: Any) -> BookWalkFillArtifact:
    return BookWalkFillArtifact(
        base_size=_required_number(value.base_size, "book-walk base_size"),
        average_price=_required_number(value.average_price, "book-walk average_price"),
        top_price_impact_bps=_required_number(
            value.top_price_impact_bps, "book-walk top_price_impact_bps"
        ),
    )


def build_market_service_state(
    runs: Sequence[CollectorRunRecord],
    artifact_files: Sequence[ArtifactFileStatus],
    *,
    generated_at: datetime,
) -> MarketServiceStateArtifact:
    now = _utc(generated_at, "generated_at")
    latest: dict[str, CollectorRunRecord] = {}
    for run in runs:
        current = latest.get(run.run_kind)
        if current is None or run.started_at > current.started_at:
            latest[run.run_kind] = run
    collectors = tuple(
        _collector_artifact(latest[kind], now) for kind in ("catalog", "l1") if kind in latest
    )
    catalog = _run_freshness(latest.get("catalog"), now, _CATALOG_MAX_AGE)
    l1 = _run_freshness(latest.get("l1"), now, _L1_MAX_AGE)
    reasons: list[str] = []
    if catalog.status != "ready":
        reasons.append(f"catalog_{catalog.status}")
    if l1.status != "ready":
        reasons.append(f"l1_{l1.status}")
    if any(item.status != "ready" for item in artifact_files):
        reasons.append("artifact_write_failure")
    if catalog.status == "unavailable" and l1.status == "unavailable":
        status: ArtifactStatus = "unavailable"
    elif reasons:
        status = "partial"
    else:
        status = "ready"
    return MarketServiceStateArtifact(
        schema_version=1,
        generated_at=now,
        status=status,
        quality_reasons=tuple(reasons),
        collectors=collectors,
        catalog=catalog,
        l1=l1,
        artifacts=tuple(artifact_files),
    )


def _collector_artifact(run: CollectorRunRecord, now: datetime) -> CollectorRunArtifact:
    latest_at = run.cycle_at or run.completed_at or run.started_at
    return CollectorRunArtifact(
        run_kind=run.run_kind,
        status=run.status,
        started_at=_utc(run.started_at, "collector started_at"),
        completed_at=_optional_utc(run.completed_at, "collector completed_at"),
        cycle_at=_optional_utc(run.cycle_at, "collector cycle_at"),
        age_seconds=max(0.0, (now - _utc(latest_at, "collector latest_at")).total_seconds()),
        records_received=run.records_received,
        records_written=run.records_written,
        error_code=run.error_code,
    )


def _run_freshness(
    run: CollectorRunRecord | None,
    now: datetime,
    max_age: timedelta,
) -> FreshnessArtifact:
    if run is None:
        return FreshnessArtifact(
            status="unavailable",
            latest_at=None,
            age_seconds=None,
            max_age_seconds=max_age.total_seconds(),
            error_code="collector_run_missing",
        )
    latest_at = _utc(run.cycle_at or run.completed_at or run.started_at, "collector latest_at")
    age = (now - latest_at).total_seconds()
    if age < 0:
        return FreshnessArtifact(
            status="unavailable",
            latest_at=latest_at,
            age_seconds=None,
            max_age_seconds=max_age.total_seconds(),
            error_code="collector_time_in_future",
        )
    if run.status == "failed":
        status: ArtifactStatus = "unavailable"
    elif age > max_age.total_seconds():
        status = "stale"
    elif run.status == "partial":
        status = "partial"
    else:
        status = "ready"
    return FreshnessArtifact(
        status=status,
        latest_at=latest_at,
        age_seconds=age,
        max_age_seconds=max_age.total_seconds(),
        error_code=run.error_code,
    )


def write_artifact_atomic(path: Path, artifact: ArtifactModel) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = artifact.model_dump(mode="json", by_alias=True)
        encoded = (
            json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ArtifactContractError("artifact contains a non-JSON or non-finite value") from None
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(target.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        raise ArtifactContractError("artifact atomic write failed") from None
    finally:
        temporary.unlink(missing_ok=True)


def read_universe_records(connection: Connection[Any]) -> tuple[UniverseRecord, ...]:
    try:
        with connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                """
                    SELECT instrument.venue_instrument_version_id, instrument.venue,
                           instrument.source_symbol, instrument.base_asset,
                           instrument.quote_asset, instrument.settle_asset,
                           instrument.collateral_asset, instrument.active,
                           instrument.market_type, instrument.execution_model,
                           membership.group_id, membership.mapping_method,
                           catalog.source_kind AS catalog_source_kind,
                           catalog.endpoint AS catalog_endpoint,
                           catalog.documentation_url AS catalog_documentation_url,
                           catalog.payload_hash AS catalog_payload_hash,
                           catalog.observed_at AS catalog_observed_at,
                           catalog.source_at AS catalog_source_at,
                           state.collector_run_id, state.cycle_at, state.observed_at,
                           state.source_at, state.status, state.mark_price,
                           state.reference_price, state.reference_price_kind,
                           state.best_bid, state.best_ask, state.funding_rate_raw,
                           state.funding_interval_seconds, state.funding_rate_per_hour,
                           state.next_funding_at, state.open_interest_raw,
                           state.open_interest_raw_unit, state.open_interest_base,
                           state.open_interest_notional, state.volume_24h_raw,
                           state.volume_24h_unit,
                           state.source_payload_hash AS l1_source_payload_hash,
                           state.error_code
                    FROM venue_instrument_versions AS instrument
                    JOIN raw_catalog_payloads AS catalog
                      USING (raw_catalog_payload_id)
                    LEFT JOIN group_memberships AS membership
                      ON membership.venue_instrument_version_id =
                         instrument.venue_instrument_version_id
                     AND membership.valid_to IS NULL
                    LEFT JOIN latest_market_state AS state
                      ON state.venue_instrument_version_id =
                         instrument.venue_instrument_version_id
                    WHERE instrument.valid_to IS NULL
                    ORDER BY upper(instrument.base_asset), instrument.venue,
                             instrument.source_symbol
                """
            ).fetchall()
    except psycopg.Error:
        raise ArtifactContractError("universe artifact query failed") from None
    return tuple(_universe_record_from_row(row) for row in rows)


def _universe_record_from_row(row: dict[str, Any]) -> UniverseRecord:
    status_value = row["status"]
    status: MarketStatus | None
    if status_value is None:
        status = None
    elif str(status_value) in {"ready", "partial", "unavailable", "stale"}:
        status = str(status_value)  # type: ignore[assignment]
    else:
        raise ArtifactContractError("universe query returned an invalid market status")
    reference_kind_value = (
        "none" if row["reference_price_kind"] is None else str(row["reference_price_kind"])
    )
    if reference_kind_value not in {"index", "oracle", "none"}:
        raise ArtifactContractError("universe query returned an invalid reference price kind")
    return UniverseRecord(
        venue_instrument_version_id=int(row["venue_instrument_version_id"]),
        venue=_venue(row["venue"]),
        source_symbol=str(row["source_symbol"]),
        base_asset=str(row["base_asset"]),
        quote_asset=str(row["quote_asset"]),
        settle_asset=str(row["settle_asset"]),
        collateral_asset=(
            None if row["collateral_asset"] is None else str(row["collateral_asset"])
        ),
        active=bool(row["active"]),
        market_type=str(row["market_type"]),
        execution_model=str(row["execution_model"]),
        group_id=None if row["group_id"] is None else str(row["group_id"]),
        mapping_method=(None if row["mapping_method"] is None else str(row["mapping_method"])),
        catalog_source_kind=str(row["catalog_source_kind"]),
        catalog_endpoint=str(row["catalog_endpoint"]),
        catalog_documentation_url=(
            None
            if row["catalog_documentation_url"] is None
            else str(row["catalog_documentation_url"])
        ),
        catalog_payload_hash=str(row["catalog_payload_hash"]),
        catalog_observed_at=_database_datetime(row["catalog_observed_at"], "catalog_observed_at"),
        catalog_source_at=_database_optional_datetime(
            row["catalog_source_at"], "catalog_source_at"
        ),
        collector_run_id=(
            None if row["collector_run_id"] is None else str(row["collector_run_id"])
        ),
        cycle_at=_database_optional_datetime(row["cycle_at"], "cycle_at"),
        observed_at=_database_optional_datetime(row["observed_at"], "observed_at"),
        source_at=_database_optional_datetime(row["source_at"], "source_at"),
        status=status,
        mark_price=_database_decimal(row["mark_price"]),
        reference_price=_database_decimal(row["reference_price"]),
        reference_price_kind=reference_kind_value,  # type: ignore[arg-type]
        best_bid=_database_decimal(row["best_bid"]),
        best_ask=_database_decimal(row["best_ask"]),
        funding_rate_raw=_database_decimal(row["funding_rate_raw"]),
        funding_interval_seconds=(
            None
            if row["funding_interval_seconds"] is None
            else int(row["funding_interval_seconds"])
        ),
        funding_rate_per_hour=_database_decimal(row["funding_rate_per_hour"]),
        next_funding_at=_database_optional_datetime(row["next_funding_at"], "next_funding_at"),
        open_interest_raw=_database_decimal(row["open_interest_raw"]),
        open_interest_raw_unit=(
            None if row["open_interest_raw_unit"] is None else str(row["open_interest_raw_unit"])
        ),
        open_interest_base=_database_decimal(row["open_interest_base"]),
        open_interest_notional=_database_decimal(row["open_interest_notional"]),
        volume_24h_raw=_database_decimal(row["volume_24h_raw"]),
        volume_24h_unit=(None if row["volume_24h_unit"] is None else str(row["volume_24h_unit"])),
        l1_source_payload_hash=(
            None if row["l1_source_payload_hash"] is None else str(row["l1_source_payload_hash"])
        ),
        error_code=None if row["error_code"] is None else str(row["error_code"]),
    )


def read_chart_records(
    connection: Connection[Any],
    venue_instrument_id: str | None,
    *,
    now: datetime,
) -> tuple[CandleRecord, ...]:
    if venue_instrument_id is None:
        return ()
    venue_text, separator, source_symbol = venue_instrument_id.partition(":")
    if (
        separator != ":"
        or venue_text not in {"bitget", "hyperliquid", "aster"}
        or not source_symbol
    ):
        raise ArtifactContractError("selected venue_instrument_id is invalid")
    generated_at = _utc(now, "chart query now")
    try:
        with connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                """
                    SELECT candle.venue_instrument_version_id, candle.bucket_at,
                           candle.open_price, candle.high_price, candle.low_price,
                           candle.close_price, candle.volume_base,
                           candle.volume_notional, candle.trade_count, candle.finality,
                           candle.source_at, candle.observed_at
                    FROM candle_1m AS candle
                    JOIN venue_instrument_versions AS instrument
                      USING (venue_instrument_version_id)
                    WHERE instrument.venue = %s AND instrument.source_symbol = %s
                      AND candle.bucket_at >= %s AND candle.bucket_at < %s
                    ORDER BY candle.bucket_at, candle.venue_instrument_version_id
                """,
                (
                    venue_text,
                    source_symbol,
                    generated_at - timedelta(days=8),
                    generated_at,
                ),
            ).fetchall()
    except psycopg.Error:
        raise ArtifactContractError("chart artifact query failed") from None
    records: list[CandleRecord] = []
    for row in rows:
        finality_text = str(row["finality"])
        if finality_text not in {"confirmed", "derived_final"}:
            raise ArtifactContractError("chart query returned an invalid finality")
        records.append(
            CandleRecord(
                venue_instrument_version_id=int(row["venue_instrument_version_id"]),
                bucket_at=_database_datetime(row["bucket_at"], "candle bucket_at"),
                open_price=_database_required_decimal(row["open_price"], "candle open"),
                high_price=_database_required_decimal(row["high_price"], "candle high"),
                low_price=_database_required_decimal(row["low_price"], "candle low"),
                close_price=_database_required_decimal(row["close_price"], "candle close"),
                volume_base=_database_decimal(row["volume_base"]),
                volume_notional=_database_decimal(row["volume_notional"]),
                trade_count=None if row["trade_count"] is None else int(row["trade_count"]),
                finality=finality_text,  # type: ignore[arg-type]
                source_at=_database_optional_datetime(row["source_at"], "candle source_at"),
                observed_at=_database_datetime(row["observed_at"], "candle observed_at"),
            )
        )
    return tuple(records)


def read_collector_runs(connection: Connection[Any]) -> tuple[CollectorRunRecord, ...]:
    try:
        with connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                """
                    SELECT DISTINCT ON (run_kind)
                           run_kind, status, started_at, completed_at, cycle_at,
                           records_received, records_written, error_code
                    FROM collector_runs
                    WHERE run_kind IN ('catalog', 'l1')
                      AND status IN ('succeeded', 'partial', 'failed')
                    ORDER BY run_kind, started_at DESC
                """
            ).fetchall()
    except psycopg.Error:
        raise ArtifactContractError("service-state collector query failed") from None
    records: list[CollectorRunRecord] = []
    for row in rows:
        kind_text = str(row["run_kind"])
        status_text = str(row["status"])
        if kind_text not in {"catalog", "l1"} or status_text not in {
            "succeeded",
            "partial",
            "failed",
        }:
            raise ArtifactContractError("collector query returned an invalid run contract")
        records.append(
            CollectorRunRecord(
                run_kind=kind_text,  # type: ignore[arg-type]
                status=status_text,  # type: ignore[arg-type]
                started_at=_database_datetime(row["started_at"], "collector started_at"),
                completed_at=_database_optional_datetime(
                    row["completed_at"], "collector completed_at"
                ),
                cycle_at=_database_optional_datetime(row["cycle_at"], "collector cycle_at"),
                records_received=int(row["records_received"]),
                records_written=int(row["records_written"]),
                error_code=None if row["error_code"] is None else str(row["error_code"]),
            )
        )
    return tuple(records)


def publish_artifacts(
    connection: Connection[Any],
    artifact_root: Path,
    *,
    generated_at: datetime,
) -> ArtifactPublishResult:
    now = _utc(generated_at, "generated_at")
    selected_view = read_selected_market(connection, now=now)
    primary_id = None if selected_view is None else selected_view.primary_venue_instrument_id
    payloads: tuple[tuple[str, ArtifactModel], ...] = (
        (
            "universe-snapshot.json",
            build_universe_snapshot(read_universe_records(connection), generated_at=now),
        ),
        (
            "market-chart.json",
            build_market_chart(
                primary_id,
                read_chart_records(connection, primary_id, now=now),
                generated_at=now,
            ),
        ),
        ("selected-market.json", build_selected_market(selected_view, generated_at=now)),
    )
    file_states: list[ArtifactFileStatus] = []
    for name, payload in payloads:
        try:
            write_artifact_atomic(artifact_root / name, payload)
        except ArtifactContractError:
            file_states.append(
                ArtifactFileStatus(
                    name=name,
                    status="unavailable",
                    generated_at=None,
                    error_code="atomic_write_failed",
                )
            )
        else:
            file_states.append(
                ArtifactFileStatus(
                    name=name,
                    status="ready",
                    generated_at=now,
                    error_code=None,
                )
            )
    service_state = build_market_service_state(
        read_collector_runs(connection),
        file_states,
        generated_at=now,
    )
    write_artifact_atomic(artifact_root / "service-state.json", service_state)
    service_file = ArtifactFileStatus(
        name="service-state.json",
        status="ready",
        generated_at=now,
        error_code=None,
    )
    all_files = (*file_states, service_file)
    return ArtifactPublishResult(
        status=("ready" if all(item.status == "ready" for item in all_files) else "partial"),
        files=all_files,
    )


def publish_selected_artifact(
    connection: Connection[Any],
    artifact_root: Path,
    previous_files: Sequence[ArtifactFileStatus],
    *,
    generated_at: datetime,
) -> ArtifactPublishResult:
    """Refresh selected data and rebuild the chart only when the primary instrument changes."""

    now = _utc(generated_at, "generated_at")
    previous = {item.name: item for item in previous_files if item.name != "service-state.json"}
    required_previous = {"universe-snapshot.json", "market-chart.json"}
    if not required_previous.issubset(previous):
        raise ArtifactContractError("full artifact generation has not completed")
    selected_view = read_selected_market(connection, now=now)
    primary_id = None if selected_view is None else selected_view.primary_venue_instrument_id
    chart_name = "market-chart.json"
    chart_state = previous[chart_name]
    refresh_chart = chart_state.status != "ready"
    if not refresh_chart:
        try:
            current_chart = MarketChartArtifact.model_validate_json(
                (artifact_root / chart_name).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            refresh_chart = True
        else:
            refresh_chart = current_chart.venue_instrument_id != primary_id
    if refresh_chart:
        try:
            write_artifact_atomic(
                artifact_root / chart_name,
                build_market_chart(
                    primary_id,
                    read_chart_records(connection, primary_id, now=now),
                    generated_at=now,
                ),
            )
        except ArtifactContractError:
            previous[chart_name] = ArtifactFileStatus(
                name=chart_name,
                status="unavailable",
                generated_at=None,
                error_code="atomic_write_failed",
            )
        else:
            previous[chart_name] = ArtifactFileStatus(
                name=chart_name,
                status="ready",
                generated_at=now,
                error_code=None,
            )
    selected_name = "selected-market.json"
    try:
        write_artifact_atomic(
            artifact_root / selected_name,
            build_selected_market(selected_view, generated_at=now),
        )
    except ArtifactContractError:
        previous[selected_name] = ArtifactFileStatus(
            name=selected_name,
            status="unavailable",
            generated_at=None,
            error_code="atomic_write_failed",
        )
    else:
        previous[selected_name] = ArtifactFileStatus(
            name=selected_name,
            status="ready",
            generated_at=now,
            error_code=None,
        )
    file_states = tuple(
        previous[name]
        for name in (
            "universe-snapshot.json",
            "market-chart.json",
            selected_name,
        )
    )
    service_state = build_market_service_state(
        read_collector_runs(connection),
        file_states,
        generated_at=now,
    )
    write_artifact_atomic(artifact_root / "service-state.json", service_state)
    service_file = ArtifactFileStatus(
        name="service-state.json",
        status="ready",
        generated_at=now,
        error_code=None,
    )
    all_files = (*file_states, service_file)
    return ArtifactPublishResult(
        status=("ready" if all(item.status == "ready" for item in all_files) else "partial"),
        files=all_files,
    )


def _database_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ArtifactContractError("database numeric value is invalid") from None


def _database_required_decimal(value: object, field_name: str) -> Decimal:
    result = _database_decimal(value)
    if result is None:
        raise ArtifactContractError(f"{field_name} is missing")
    return result


def _database_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ArtifactContractError(f"{field_name} has an invalid database type")
    return _utc(value, field_name)


def _database_optional_datetime(value: object, field_name: str) -> datetime | None:
    return None if value is None else _database_datetime(value, field_name)


def _venue(value: object) -> Venue:
    venue_text = str(value)
    if venue_text not in {"bitget", "hyperliquid", "aster"}:
        raise ArtifactContractError("database Venue is invalid")
    return venue_text  # type: ignore[return-value]


def _finite_float(value: Decimal | int | float | str | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal_value.is_finite():
        return None
    result = float(decimal_value)
    return result if math.isfinite(result) else None


def _required_number(value: Decimal | int | float | str, field_name: str) -> float:
    result = _finite_float(value)
    if result is None:
        raise ArtifactContractError(f"{field_name} is non-finite")
    return result


def _sum_optional(values: Sequence[Decimal | None] | Any) -> float | None:
    materialized = tuple(values)
    if any(value is None for value in materialized):
        return None
    total = sum((value for value in materialized if value is not None), Decimal(0))
    return _finite_float(total)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ArtifactContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None, field_name: str) -> datetime | None:
    return None if value is None else _utc(value, field_name)


def _valid_venue_instrument_id(value: str) -> bool:
    venue, separator, source_symbol = value.partition(":")
    return separator == ":" and venue in {"bitget", "hyperliquid", "aster"} and bool(source_symbol)
