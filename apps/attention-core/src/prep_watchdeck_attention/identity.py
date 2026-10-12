"""Exact identity/version joins without symbol, base or legacy-contract fallbacks."""

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from prep_watchdeck_market.artifacts import UniverseInstrumentArtifact
from prep_watchdeck_market.market_metrics import MarketMetricRow
from prep_watchdeck_ranking.models import RankedRow, RankingResponse

from prep_watchdeck_attention.market_input import MarketInputBundle


@dataclass(frozen=True, slots=True)
class JoinedAsset:
    ranked: RankedRow
    universe: tuple[UniverseInstrumentArtifact, ...]
    metrics: tuple[MarketMetricRow, ...]
    state: Literal["ready", "partial", "invalid", "excluded"]
    reasons: tuple[str, ...]
    ranking_cutoff: int | None = None
    ranking_generated_at: int | None = None


def join_attention_assets(
    ranking: RankingResponse, market: MarketInputBundle
) -> tuple[JoinedAsset, ...]:
    universe_keys = Counter(
        (item.venue_instrument_id, item.venue_instrument_version_id)
        for item in market.universe.items
    )
    universe = {
        (item.venue_instrument_id, item.venue_instrument_version_id): item
        for item in market.universe.items
    }
    metric_rows = market.metrics.rows if market.metrics is not None else ()
    metric_keys = Counter(
        (item.venue_instrument_id, item.venue_instrument_version_id) for item in metric_rows
    )
    metrics = {
        (item.venue_instrument_id, item.venue_instrument_version_id): item for item in metric_rows
    }
    current_ids = {item.venue_instrument_id for item in market.universe.items}
    result = []
    for row in sorted(ranking.rows, key=lambda row: row.id):
        reasons = []
        matched = []
        native = []
        invalid = False
        original_keys = [(o.instrument_id, o.version_id) for o in row.originals]
        if len(original_keys) != len(set(original_keys)):
            reasons.append("duplicate_original_identity")
            invalid = True
        for original in row.originals:
            key = (original.instrument_id, original.version_id)
            if universe_keys[key] > 1 or metric_keys[key] > 1:
                reasons.append(f"duplicate_native_identity:{original.instrument_id}")
                invalid = True
                continue
            item = universe.get(key)
            if item is None:
                mismatch = original.instrument_id in current_ids
                reason = "original_version_mismatch" if mismatch else "original_missing"
                reasons.append(f"{reason}:{original.instrument_id}")
                invalid |= mismatch
                continue
            if not item.active or item.venue != original.venue:
                reasons.append(f"original_identity_invalid:{original.instrument_id}")
                invalid = True
                continue
            matched.append(item)
            metric = metrics.get(key)
            if metric is not None and metric.venue == item.venue:
                native.append(metric)
            else:
                reasons.append(f"metrics_missing_or_version_mismatch:{original.instrument_id}")
        if market.metrics_error:
            reasons.append(f"metrics_unavailable:{market.metrics_error}")
        state: Literal["ready", "partial", "invalid", "excluded"]
        if row.mapping_status != "verified":
            state = "excluded"
            reasons.append(f"mapping_{row.mapping_status}")
        elif invalid or row.reference is None or not matched:
            state = "invalid"
            if not matched:
                reasons.append("no_current_original")
            if row.reference is None:
                reasons.append("reference_missing")
        elif len({item.venue for item in matched}) < 2 or reasons:
            state = "partial"
            if len({item.venue for item in matched}) < 2:
                reasons.append("single_native_venue")
        else:
            state = "ready"
        result.append(
            JoinedAsset(
                row,
                tuple(matched),
                tuple(native),
                state,
                tuple(sorted(set(reasons))),
                ranking.cutoff,
                ranking.generated_at,
            )
        )
    return tuple(result)
