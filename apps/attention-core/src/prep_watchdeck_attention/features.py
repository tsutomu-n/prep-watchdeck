"""Immutable raw features with native observations, units and exact version provenance."""

import math
from collections.abc import Sequence
from datetime import datetime
from statistics import median

from prep_watchdeck_market.artifacts import UniverseInstrumentArtifact
from prep_watchdeck_market.market_metrics import MetricValue
from prep_watchdeck_ranking.models import Indicator, RankingResponse

from prep_watchdeck_attention.identity import JoinedAsset, join_attention_assets
from prep_watchdeck_attention.market_input import MarketInputBundle, utc_ms
from prep_watchdeck_attention.models import (
    FEATURE_VERSION,
    FeatureSnapshotRow,
    FeatureStatus,
    InputReference,
    OriginalReference,
    RawFeatureValue,
    SourceObservation,
    content_digest,
)


def spread_bps(bid: float, ask: float) -> float:
    if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask < bid:
        raise ValueError("invalid_bbo")
    return 10_000 * (ask - bid) / ((ask + bid) / 2)


def mark_dispersion_bps(values: Sequence[float]) -> float:
    if len(values) < 2 or any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("insufficient_valid_marks")
    return 10_000 * (max(values) - min(values)) / median(values)


def _missing(
    reason: str,
    *,
    source: str,
    status: FeatureStatus = "missing",
    unit: str | None = None,
    observations: tuple[SourceObservation, ...] = (),
) -> RawFeatureValue:
    return RawFeatureValue(
        value=None,
        status=status,
        reason=reason,
        source=source,
        unit=unit,
        observations=observations,
    )


def _ready(
    value: float,
    *,
    source: str,
    unit: str | None,
    observations: tuple[SourceObservation, ...] = (),
) -> RawFeatureValue:
    ends = [o.end_at for o in observations if o.end_at is not None]
    starts = [o.start_at for o in observations if o.start_at is not None]
    observed = [o.observed_at for o in observations if o.observed_at is not None]
    return RawFeatureValue(
        value=value,
        status="ready",
        source=source,
        unit=unit,
        start_at=min(starts) if starts else None,
        end_at=max(ends) if ends else None,
        observed_at=max(observed) if observed else None,
        observations=observations,
    )


def median_ready(values: Sequence[RawFeatureValue], *, minimum_sources: int = 1) -> RawFeatureValue:
    if minimum_sources < 1:
        raise ValueError("invalid_minimum_sources")
    ready = [v for v in values if v.status == "ready" and v.value is not None]
    observations = tuple(o for v in values for o in v.observations)
    if len(ready) < minimum_sources:
        reasons = sorted({v.reason for v in values if v.reason})
        return _missing(
            "insufficient_sources" + (":" + ";".join(reasons) if reasons else ""),
            source="native-median",
            observations=observations,
        )
    units = {v.unit for v in ready}
    if len(units) != 1:
        return _missing(
            "incompatible_units",
            source="native-median",
            status="invalid",
            observations=observations,
        )
    return _ready(
        median([v.value for v in ready if v.value is not None]),
        source="native-median",
        unit=ready[0].unit,
        observations=observations,
    )


def _metric(value: MetricValue, *, source: str, decision_ms: int, oi: bool) -> RawFeatureValue:
    def stamp(value: datetime | None) -> int | None:
        return utc_ms(value) if value is not None else None

    observations = (
        SourceObservation(
            source=source,
            start_at=stamp(value.start_at),
            observed_at=stamp(value.start_observed_at),
            source_at=stamp(value.start_source_at),
            unit=value.unit,
            value=value.start_value,
        ),
        SourceObservation(
            source=source,
            end_at=stamp(value.end_at),
            observed_at=stamp(value.end_observed_at),
            source_at=stamp(value.end_source_at),
            finality=value.end_finality,
            unit=value.unit,
            value=value.end_value,
        ),
    )
    times = [
        t
        for o in observations
        for t in (o.start_at, o.end_at, o.observed_at, o.source_at)
        if t is not None
    ]
    if any(t > decision_ms for t in times):
        raise ValueError("future_native_metric_timestamp")
    if value.availability != "available":
        status = (
            value.availability if value.availability in ("invalid", "unsupported") else "missing"
        )
        return _missing(
            value.reason_code or "metric_unavailable",
            source=source,
            status=status,
            unit="percent",
            observations=observations,
        )
    if oi and value.unit != "base":
        return _missing(
            "oi_unit_not_base",
            source=source,
            status="unsupported",
            unit="percent",
            observations=observations,
        )
    if not oi and value.end_finality not in ("confirmed", "derived_final"):
        return _missing(
            "native_close_not_final",
            source=source,
            status="invalid",
            unit="percent",
            observations=observations,
        )
    end = stamp(value.end_at)
    if end is None or value.end_observed_at is None:
        return _missing("metric_timestamp_missing", source=source, observations=observations)
    latest = [
        end,
        *[t for t in (stamp(value.end_source_at), stamp(value.end_observed_at)) if t is not None],
    ]
    if any(decision_ms - t > (120_000 if oi else 300_000) for t in latest):
        return _missing(
            "native_metric_stale",
            source=source,
            status="stale",
            unit="percent",
            observations=observations,
        )
    assert value.value is not None
    return _ready(value.value, source=source, unit="percent", observations=observations)


def _l1_observation(item: UniverseInstrumentArtifact, field: str, value: float | None, unit: str):
    return SourceObservation(
        source=f"{item.venue_instrument_id}@{item.venue_instrument_version_id}:{field}",
        end_at=utc_ms(item.cycle_at) if item.cycle_at else None,
        observed_at=utc_ms(item.observed_at) if item.observed_at else None,
        source_at=utc_ms(item.source_at) if item.source_at else None,
        unit=unit,
        value=value,
        payload_hash=item.source_payload_hash,
    )


def _l1_fresh(item: UniverseInstrumentArtifact, decision_ms: int) -> bool:
    times = [utc_ms(t) for t in (item.cycle_at, item.observed_at, item.source_at) if t is not None]
    if any(t > decision_ms for t in times):
        raise ValueError("future_l1_timestamp")
    return (
        item.cycle_at is not None
        and item.observed_at is not None
        and item.quality not in ("stale", "unavailable")
        and all(decision_ms - t <= 120_000 for t in times)
    )


def build_feature_row(asset: JoinedAsset, *, decision_at: datetime) -> FeatureSnapshotRow:
    decision_ms = utc_ms(decision_at)
    row = asset.ranked
    eligible = asset.state in ("ready", "partial")
    quality = list(asset.reasons)
    reference_source = f"ranking:{row.reference.key if row.reference else 'none'}"
    # The row window cutoff is fixed by Ranking; decision may be later than that cutoff.
    cutoff = asset.ranking_cutoff
    if cutoff is None:
        # All native window builders require generation cutoff; direct row helper uses 15m anchor.
        cutoff = row.windows["15m"].anchor + 15 * 60_000
    if cutoff > decision_ms:
        raise ValueError("future_reference_cutoff")

    def reference(value: float | None, status: str, *, unit: str, start: int | None = None):
        if start is not None and start > cutoff:
            raise ValueError("future_reference_anchor")
        observation = SourceObservation(
            source=reference_source,
            start_at=start,
            end_at=cutoff,
            observed_at=asset.ranking_generated_at or cutoff,
            finality="confirmed",
            unit=unit,
            value=value,
        )
        if not eligible:
            return _missing(
                "identity_ineligible", source=reference_source, observations=(observation,)
            )
        if status != "ready" or value is None:
            return _missing(
                f"reference_{status}",
                source=reference_source,
                unit=unit,
                observations=(observation,),
            )
        return _ready(value, source=reference_source, unit=unit, observations=(observation,))

    def indicator(value: Indicator, unit: str):
        return reference(value.value, value.status, unit=unit)

    fields: dict[str, RawFeatureValue] = {
        "reference_close": indicator(row.reference_close, "USDT"),
        "reference_day_range_position": indicator(row.day_range_position, "percent"),
    }
    for window in ("15m", "1h", "24h"):
        w = row.windows[window]
        fields[f"reference_return{window}"] = reference(
            w.return_pct, w.state, unit="percent", start=w.anchor
        )
        if window != "24h":
            fields[f"reference_turnover{window}"] = reference(
                w.quote_turnover, w.state, unit="USDT", start=w.anchor
            )
            fields[f"reference_turnover_ratio{window}"] = indicator(
                row.turnover_ratios[window], "ratio"
            )
    for name, oi in (("oi_change", True), ("native_return", False)):
        for window in ("15m", "1h"):
            values = (
                [
                    _metric(
                        (m.oi_change if oi else m.trade_change)[window],
                        source=(
                            f"{m.venue_instrument_id}@{m.venue_instrument_version_id}:"
                            f"{'oi' if oi else 'native-close-return'}:{window}"
                        ),
                        decision_ms=decision_ms,
                        oi=oi,
                    )
                    for m in asset.metrics
                ]
                if eligible
                else []
            )
            fields[f"{name}{window}_median"] = median_ready(values)
    fresh = []
    funding = []
    spreads = []
    marks = []
    mark_observations = []
    originals = {(o.instrument_id, o.version_id): o for o in row.originals}
    for item in asset.universe:
        is_fresh = _l1_fresh(item, decision_ms)
        source = f"{item.venue_instrument_id}@{item.venue_instrument_version_id}"
        if not eligible:
            continue
        if not is_fresh:
            quality.append(f"native_l1_stale:{source}")
            funding.append(
                _missing(
                    "native_l1_stale",
                    source=source,
                    status="stale",
                    unit="rate/hour",
                    observations=(
                        _l1_observation(item, "funding", item.funding_rate_per_hour, "rate/hour"),
                    ),
                )
            )
            spreads.append(
                _missing(
                    "native_l1_stale",
                    source=source,
                    status="stale",
                    unit="bps",
                    observations=tuple(
                        _l1_observation(item, name, value, item.quote_asset)
                        for name, value in (("bid", item.best_bid), ("ask", item.best_ask))
                    ),
                )
            )
            mark_observations.append(
                _l1_observation(item, "mark", item.mark_price, item.quote_asset)
            )
            continue
        fresh.append(item)
        funding_observation = _l1_observation(
            item, "funding", item.funding_rate_per_hour, "rate/hour"
        )
        if item.funding_rate_per_hour is not None:
            funding.append(
                _ready(
                    item.funding_rate_per_hour,
                    source=source,
                    unit="rate/hour",
                    observations=(funding_observation,),
                )
            )
        bbo_observations = tuple(
            _l1_observation(item, name, value, item.quote_asset)
            for name, value in (("bid", item.best_bid), ("ask", item.best_ask))
        )
        if item.best_bid is not None and item.best_ask is not None:
            try:
                value = spread_bps(item.best_bid, item.best_ask)
                spreads.append(
                    _ready(value, source=source, unit="bps", observations=bbo_observations)
                )
            except ValueError:
                quality.append(f"invalid_bbo:{source}")
                spreads.append(
                    _missing(
                        "invalid_bbo",
                        source=source,
                        status="invalid",
                        observations=bbo_observations,
                    )
                )
        original = originals[(item.venue_instrument_id, item.venue_instrument_version_id)]
        mark_observations.append(_l1_observation(item, "mark", item.mark_price, item.quote_asset))
        if original.multiplier is None:
            quality.append(f"original_multiplier_unknown:{source}")
        elif item.quote_asset not in ("USD", "USDC", "USDT"):
            quality.append(f"non_usd_like_mark:{source}")
        elif item.mark_price is not None and item.mark_price > 0:
            marks.append((item.venue, item.mark_price / original.multiplier))
        elif item.mark_price is not None:
            quality.append(f"invalid_mark:{source}")

    def aggregate(values, operation, *, source, unit, minimum=1):
        available = [v.value for v in values if v.status == "ready" and v.value is not None]
        observations = tuple(o for v in values for o in v.observations)
        if len(available) < minimum:
            return _missing(
                "insufficient_sources"
                + (
                    ":" + ";".join(sorted({v.reason for v in values if v.reason})) if values else ""
                ),
                source=source,
                unit=unit,
                observations=observations,
                status="invalid"
                if any(v.status == "invalid" for v in values)
                else "stale"
                if any(v.status == "stale" for v in values)
                else "missing",
            )
        return _ready(operation(available), source=source, unit=unit, observations=observations)

    fields["funding_abs_max_per_hour"] = aggregate(
        funding, lambda v: max(abs(x) for x in v), source="native-funding-max", unit="rate/hour"
    )
    fields["funding_range_per_hour"] = aggregate(
        funding,
        lambda v: max(v) - min(v),
        source="native-funding-range",
        unit="rate/hour",
        minimum=2,
    )
    fields["spread_median_bps"] = median_ready(spreads)
    fields["spread_max_bps"] = aggregate(spreads, max, source="native-spread-max", unit="bps")
    if len({venue for venue, _ in marks}) >= 2:
        fields["mark_dispersion_bps"] = _ready(
            mark_dispersion_bps([v for _, v in marks]),
            source="native-normalized-mark-dispersion",
            unit="bps",
            observations=tuple(mark_observations),
        )
    else:
        reason = "insufficient_native_venues"
        if any("multiplier_unknown" in reason for reason in quality):
            reason += ":original_multiplier_unknown"
        fields["mark_dispersion_bps"] = _missing(
            reason,
            source="native-normalized-mark-dispersion",
            unit="bps",
            observations=tuple(mark_observations),
        )
    return FeatureSnapshotRow(
        asset_id=row.id,
        asset=row.asset,
        reference_key=row.reference.key if row.reference else None,
        original_instrument_versions=tuple(
            OriginalReference(
                instrument_id=o.instrument_id,
                version_id=o.version_id,
                venue=o.venue,
                multiplier=o.multiplier,
                current=any(
                    u.venue_instrument_id == o.instrument_id
                    and u.venue_instrument_version_id == o.version_id
                    for u in asset.universe
                ),
                group_id=next(
                    (
                        u.group_id
                        for u in asset.universe
                        if u.venue_instrument_id == o.instrument_id
                    ),
                    None,
                ),
            )
            for o in row.originals
        ),
        decision_at=decision_ms,
        identity_status=asset.state,
        quality_reasons=tuple(sorted(set(quality))),
        fresh_native_venue_count=len({i.venue for i in fresh}),
        ready_native_venue_count=len({i.venue for i in fresh if i.quality == "ready"}),
        **fields,
    )


def build_feature_generation(
    market: MarketInputBundle, ranking: RankingResponse, *, decision_at: datetime
) -> tuple[InputReference, tuple[FeatureSnapshotRow, ...]]:
    decision_ms = utc_ms(decision_at)
    rows = tuple(
        build_feature_row(asset, decision_at=decision_at)
        for asset in join_attention_assets(ranking, market)
    )
    times = [
        ranking.cutoff,
        ranking.generated_at,
        utc_ms(market.universe.generated_at),
        utc_ms(market.service.generated_at),
    ]
    metrics = market.metrics
    if metrics is not None:
        times.extend((utc_ms(metrics.generated_at), utc_ms(metrics.candle_cutoff)))
    values = dict(
        decision_at=decision_ms,
        ranking_cutoff=ranking.cutoff,
        ranking_generated_at=ranking.generated_at,
        ranking_generation_id=ranking.generation_id,
        ranking_map_version=ranking.map_version,
        ranking_metric_version=ranking.metric_version,
        universe_generated_at=utc_ms(market.universe.generated_at),
        service_generated_at=utc_ms(market.service.generated_at),
        market_metrics_generation_id=metrics.generation_id if metrics else None,
        market_metrics_generated_at=utc_ms(metrics.generated_at) if metrics else None,
        market_metrics_candle_cutoff=utc_ms(metrics.candle_cutoff) if metrics else None,
        input_skew_seconds=(max(times) - min(times)) / 1000,
        quality_reasons=(f"metrics_unavailable:{market.metrics_error}",)
        if market.metrics_error
        else (),
    )
    generation_id = content_digest(
        {
            "inputs": values,
            "featureVersion": FEATURE_VERSION,
            "rows": [row.model_dump(mode="json", by_alias=True) for row in rows],
        }
    )
    return InputReference(generation_id=generation_id, **values), rows
