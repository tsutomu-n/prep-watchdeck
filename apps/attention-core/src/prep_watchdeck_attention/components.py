"""Explainable v1 raw maxima and per-component cross-sectional midrank scoring.

Positioning/dislocation maxima intentionally compare different raw units in v1;
they are an explicit heuristic, not a dimensionally normalized model.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean

from prep_watchdeck_attention.models import (
    COMPONENTS,
    AttentionComponent,
    AttentionCoverage,
    AttentionResponse,
    AttentionRow,
    ComponentName,
    Direction,
    FeatureSnapshotRow,
    InputReference,
)
from prep_watchdeck_attention.percentiles import midrank_percentiles


@dataclass(frozen=True, slots=True)
class ComponentPolicy:
    version: str
    minimum_peers: int = 20

    def __post_init__(self):
        if not self.version or self.minimum_peers < 1:
            raise ValueError("invalid_component_policy")


CANDIDATES = {
    "movement": ("reference_return15m", "reference_return1h"),
    "activity": ("reference_turnover_ratio15m", "reference_turnover_ratio1h"),
    "positioning": ("oi_change15m_median", "oi_change1h_median", "funding_abs_max_per_hour"),
    "dislocation": ("mark_dispersion_bps", "funding_range_per_hour", "spread_max_bps"),
}


def score_attention(
    generation: InputReference,
    features: Sequence[FeatureSnapshotRow],
    *,
    policy: ComponentPolicy,
    previous: AttentionResponse | None = None,
) -> AttentionResponse:
    if len({f.asset_id for f in features}) != len(features):
        raise ValueError("duplicate_feature_asset")
    if any(f.decision_at != generation.decision_at for f in features):
        raise ValueError("feature_generation_mismatch")
    comparable = (
        previous is not None
        and previous.policy_version == policy.version
        and previous.inputs.feature_version == generation.feature_version
        and previous.inputs.ranking_map_version == generation.ranking_map_version
        and previous.inputs.ranking_metric_version == generation.ranking_metric_version
        and previous.decision_at < generation.decision_at
    )
    previous_rows = {r.asset_id: r for r in previous.rows} if comparable and previous else {}
    components: dict[str, dict[ComponentName, AttentionComponent]] = {
        f.asset_id: {} for f in features
    }
    for name in COMPONENTS:
        raw: dict[str, float] = {}
        selected: dict[str, tuple[str, ...]] = {}
        directions: dict[str, Direction] = {}
        for row in features:
            if row.identity_status not in ("ready", "partial"):
                continue
            available = [
                (field, getattr(row, field).value)
                for field in CANDIDATES[name]
                if getattr(row, field).status == "ready"
            ]
            if not available:
                continue
            # Stable max preserves 15m precedence when movement magnitudes tie.
            field, value = max(
                available, key=lambda pair: abs(pair[1]) if name != "activity" else pair[1]
            )
            raw[row.asset_id] = abs(value) if name != "activity" else value
            selected[row.asset_id] = (field,)
            directions[row.asset_id] = (
                ("up" if value > 0 else "down" if value < 0 else "flat")
                if name == "movement"
                else "unknown"
            )
        scores = (
            midrank_percentiles(raw, minimum_peers=policy.minimum_peers)
            if len(raw) >= policy.minimum_peers
            else {}
        )
        ranks = {
            asset_id: index + 1
            for index, asset_id in enumerate(sorted(scores, key=lambda key: (-scores[key], key)))
        }
        for row in features:
            asset_id = row.asset_id
            previous_component = (
                previous_rows[asset_id].components[name] if asset_id in previous_rows else None
            )
            if asset_id in scores:
                components[asset_id][name] = AttentionComponent(
                    policy_version=policy.version,
                    status="ready",
                    score=scores[asset_id],
                    raw_value=raw[asset_id],
                    rank=ranks[asset_id],
                    rank_change=(
                        previous_component.rank - ranks[asset_id]
                        if previous_component and previous_component.rank is not None
                        else None
                    ),
                    direction=directions[asset_id],
                    inputs=selected[asset_id],
                    peer_count=len(raw),
                )
            else:
                reason = (
                    "identity_ineligible"
                    if row.identity_status in ("invalid", "excluded")
                    else "insufficient_peers"
                    if asset_id in raw
                    else "no_ready_inputs"
                )
                components[asset_id][name] = AttentionComponent(
                    policy_version=policy.version,
                    status="unavailable",
                    reason=reason,
                    raw_value=raw.get(asset_id),
                    inputs=selected.get(asset_id, ()),
                    direction=directions.get(asset_id, "unknown"),
                    peer_count=len(raw),
                )
    confluence = {
        asset_id: mean([c.score for c in values.values() if c.score is not None])
        for asset_id, values in components.items()
        if all(c.status == "ready" for c in values.values())
    }
    ranks = {
        asset_id: index + 1
        for index, asset_id in enumerate(
            sorted(confluence, key=lambda key: (-confluence[key], key))
        )
    }
    result = []
    for row in features:
        values = components[row.asset_id]
        previous_component = (
            previous_rows[row.asset_id].components["confluence"]
            if row.asset_id in previous_rows
            else None
        )
        if row.asset_id in confluence:
            rank = ranks[row.asset_id]
            values["confluence"] = AttentionComponent(
                policy_version=policy.version,
                status="ready",
                score=confluence[row.asset_id],
                raw_value=confluence[row.asset_id],
                rank=rank,
                rank_change=(
                    previous_component.rank - rank
                    if previous_component and previous_component.rank is not None
                    else None
                ),
                inputs=COMPONENTS,
                peer_count=len(confluence),
            )
        else:
            values["confluence"] = AttentionComponent(
                policy_version=policy.version,
                status="unavailable",
                reason="incomplete_components",
                inputs=COMPONENTS,
                peer_count=len(confluence),
            )
        count = sum(values[name].status == "ready" for name in COMPONENTS)
        result.append(
            AttentionRow(
                asset_id=row.asset_id,
                asset=row.asset,
                reference_key=row.reference_key,
                originals=row.original_instrument_versions,
                components=values,
                ready_component_count=count,
                coverage_ratio=count / 4,
                quality_reasons=row.quality_reasons,
                data_as_of=generation.ranking_cutoff,
                identity_status=row.identity_status,
            )
        )
    result.sort(
        key=lambda row: (
            *(
                -row.components[name].score
                if row.components[name].score is not None
                else float("inf")
                for name in ("confluence", "movement", "activity")
            ),
            row.asset_id,
        )
    )
    ready = {
        name: sum(row.components[name].status == "ready" for row in result) for name in COMPONENTS
    }
    eligible = sum(row.identity_status in ("ready", "partial") for row in result)
    status = (
        "ready"
        if result and len(confluence) == len(result)
        else "partial"
        if any(ready.values())
        else "unavailable"
    )
    return AttentionResponse(
        generation_id=generation.generation_id,
        decision_at=generation.decision_at,
        status=status,
        reason=None if status == "ready" else "incomplete_component_coverage",
        policy_version=policy.version,
        inputs=generation,
        rows=tuple(result),
        coverage=AttentionCoverage(
            rows=len(result),
            eligible=eligible,
            confluence_ready=len(confluence),
            component_ready=ready,
        ),
    )
