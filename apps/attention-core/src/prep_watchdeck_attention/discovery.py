"""Discovery projection uses existing exact joins and retained Market/Ranking inputs only."""

from collections.abc import Sequence

from prep_watchdeck_ranking.models import RankingResponse

from .discovery_models import DiscoveryDirection, DiscoveryNative, DiscoveryRow, DiscoveryState
from .features import (
    _funding_timestamp_diagnostics,
    _funding_unavailable_reason,
    _l1_fresh,
    _l1_observation,
    _metric,
    _missing,
    _ready,
)
from .identity import JoinedAsset, join_attention_assets
from .market_input import MarketInputBundle
from .models import FeatureSnapshotRow, InputReference, RawFeatureValue, content_digest


def _native(asset: JoinedAsset, decision_ms: int) -> tuple[DiscoveryNative, ...]:
    metrics = {(m.venue_instrument_id, m.venue_instrument_version_id): m for m in asset.metrics}
    rows = []
    for item in asset.universe:
        fresh = _l1_fresh(item, decision_ms)
        funding_reason = _funding_unavailable_reason(item, decision_ms)
        source = f"{item.venue_instrument_id}@{item.venue_instrument_version_id}"

        def l1(
            name: str,
            value: float | None,
            unit: str,
            *,
            item=item,
            fresh=fresh,
            source=source,
            funding_reason=funding_reason,
        ) -> RawFeatureValue:
            observation = _l1_observation(item, name, value, unit, decision_ms=decision_ms)
            if name.startswith("funding") and funding_reason:
                return _missing(
                    funding_reason, source=source, unit=unit, observations=(observation,)
                )
            if not fresh:
                return _missing(
                    "native_l1_stale",
                    source=source,
                    status="stale",
                    unit=unit,
                    observations=(observation,),
                )
            if value is None:
                return _missing(
                    "native_value_missing", source=source, unit=unit, observations=(observation,)
                )
            if (name == "mark" and value <= 0) or (name.startswith("oi_") and value < 0):
                return _missing(
                    "native_value_invalid",
                    source=source,
                    status="invalid",
                    unit=unit,
                    observations=(observation,),
                )
            return _ready(value, source=source, unit=unit, observations=(observation,))

        metric = metrics.get((item.venue_instrument_id, item.venue_instrument_version_id))

        def changes(oi: bool, *, metric=metric, source=source) -> dict[str, RawFeatureValue]:
            result = {}
            for window in ("15m", "1h") if oi else ("15m", "1h", "24h"):
                label = f"{source}:{'oi' if oi else 'native-close-return'}:{window}"
                result[window] = (
                    _metric(
                        (metric.oi_change if oi else metric.trade_change)[window],
                        source=label,
                        decision_ms=decision_ms,
                        oi=oi,
                    )
                    if metric is not None
                    else _missing(
                        "metrics_missing_or_version_mismatch", source=label, unit="percent"
                    )
                )
            return result

        rows.append(
            DiscoveryNative(
                instrument_id=item.venue_instrument_id,
                version_id=item.venue_instrument_version_id,
                venue=item.venue,
                source_symbol=item.source_symbol,
                quality=item.quality,
                quality_reasons=tuple(
                    dict.fromkeys(
                        (
                            *item.quality_reasons,
                            *_funding_timestamp_diagnostics(item, decision_ms),
                        )
                    )
                ),
                mark_price=l1("mark", item.mark_price, item.quote_asset),
                funding_rate_raw=l1("funding_raw", item.funding_rate_raw, "rate/interval"),
                funding_rate_per_hour=l1("funding", item.funding_rate_per_hour, "rate/hour"),
                funding_interval_seconds=None if funding_reason else item.funding_interval_seconds,
                open_interest_raw=l1(
                    "oi_raw", item.open_interest_raw, item.open_interest_raw_unit or "unknown"
                ),
                open_interest_base=l1("oi_base", item.open_interest_base, "base"),
                open_interest_notional=l1(
                    "oi_notional", item.open_interest_notional, item.quote_asset
                ),
                oi_change=changes(True),
                return_pct=changes(False),
            )
        )
    return tuple(rows)


def build_discovery_rows(
    market: MarketInputBundle,
    ranking: RankingResponse,
    inputs: InputReference,
    features: Sequence[FeatureSnapshotRow],
) -> tuple[DiscoveryRow, ...]:
    raw = {row.asset_id: row for row in features}
    result = []
    for joined in join_attention_assets(ranking, market):
        ranked = joined.ranked
        feature = raw[ranked.id]
        eligible = (
            ranked.mapping_status == "verified"
            and feature.identity_status in ("ready", "partial")
            and all(original.current for original in feature.original_instrument_versions)
        )
        comparison = ranked.turnover_comparison
        ratios = (comparison.previous_day_ratio, comparison.two_days_ago_ratio)
        state: DiscoveryState = "unknown"
        reason = "identity_ineligible"
        # Both complete same-clock windows are mandatory. Values are never imputed.
        windows = (comparison.current, comparison.previous_day, comparison.two_days_ago)
        exact_windows = all(
            window.status == "ready"
            and window.cutoff == ranking.cutoff - day * 24 * 60 * 60_000
            and window.anchor == window.cutoff - 15 * 60_000
            for day, window in enumerate(windows)
        )
        if eligible:
            reason = "comparison_unavailable"
            if exact_windows and all(r.status == "ready" and r.value is not None for r in ratios):
                state = (
                    "matched"
                    if all(r.value is not None and r.value >= 3 for r in ratios)
                    else "not_matched"
                )
                reason = None
        direction: DiscoveryDirection = "unknown"
        price = feature.reference_return15m
        if price.status == "ready" and price.value is not None:
            direction = "up" if price.value >= 2 else "down" if price.value <= -2 else "turnover"
        identity_key = content_digest(
            {
                "assetId": ranked.id,
                "referenceKey": feature.reference_key,
                "originals": sorted(
                    (o.instrument_id, o.version_id, o.venue, o.multiplier)
                    for o in feature.original_instrument_versions
                ),
            }
        )
        result.append(
            DiscoveryRow(
                asset_id=ranked.id,
                asset=ranked.asset,
                reference_key=feature.reference_key,
                originals=feature.original_instrument_versions,
                identity_key=identity_key,
                state=state,
                reason=reason,
                direction=direction,
                raw=feature,
                turnover_comparison=comparison,
                native=_native(joined, inputs.decision_at),
            )
        )
    return tuple(result)
