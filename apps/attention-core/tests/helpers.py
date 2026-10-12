from prep_watchdeck_attention.models import (
    COMPONENTS,
    AttentionComponent,
    AttentionCoverage,
    AttentionResponse,
    AttentionRow,
    FeatureSnapshotRow,
    InputReference,
    OriginalReference,
    RawFeatureValue,
)

CUTOFF = 1_800_000_000_000


def feature(asset_id="a", cutoff=CUTOFF):
    missing = RawFeatureValue(
        value=None, status="missing", reason="fixture_missing", source="fixture"
    )
    fields = {
        name: missing
        for name in FeatureSnapshotRow.model_fields
        if name
        not in {
            "asset_id",
            "asset",
            "reference_key",
            "original_instrument_versions",
            "decision_at",
            "identity_status",
            "quality_reasons",
            "fresh_native_venue_count",
            "ready_native_venue_count",
        }
    }
    fields["reference_close"] = RawFeatureValue(
        value=100, status="ready", source="fixture", end_at=cutoff
    )
    return FeatureSnapshotRow.model_validate(
        fields
        | {
            "asset_id": asset_id,
            "asset": asset_id.upper(),
            "reference_key": f"bybit:{asset_id.upper()}USDT:rev1",
            "original_instrument_versions": (
                OriginalReference(
                    instrument_id=f"bitget:{asset_id}",
                    version_id=1,
                    venue="bitget",
                    group_id=asset_id,
                    multiplier=1,
                ),
            ),
            "decision_at": cutoff + 10_000,
            "identity_status": "partial",
            "quality_reasons": ("single_native_source",),
            "fresh_native_venue_count": 1,
            "ready_native_venue_count": 1,
        }
    )


def generation(features, *, generation_id="test", cutoff=CUTOFF, scores=None):
    inputs = InputReference(
        generation_id=generation_id,
        decision_at=cutoff + 10_000,
        ranking_cutoff=cutoff,
        ranking_generated_at=cutoff + 8_000,
        ranking_generation_id=f"ranking-{cutoff}",
        ranking_map_version="map",
        ranking_metric_version="v1",
        universe_generated_at=cutoff,
        service_generated_at=cutoff,
        market_metrics_generation_id=None,
        market_metrics_generated_at=None,
        market_metrics_candle_cutoff=None,
        input_skew_seconds=8,
    )
    rows = []
    for index, f in enumerate(features):
        score = scores[index] if scores is not None else 100 - index
        components = {
            name: AttentionComponent(
                policy_version=f"{name}-v1",
                status="ready",
                score=score,
                rank=index + 1,
                raw_value=score,
            )
            for name in (*COMPONENTS, "confluence")
        }
        rows.append(
            AttentionRow.model_validate(
                {
                    "asset_id": f.asset_id,
                    "asset": f.asset,
                    "reference_key": f.reference_key,
                    "originals": f.original_instrument_versions,
                    "components": components,
                    "ready_component_count": 4,
                    "coverage_ratio": 1,
                    "quality_reasons": f.quality_reasons,
                    "data_as_of": cutoff,
                    "identity_status": f.identity_status,
                }
            )
        )
    response = AttentionResponse(
        generation_id=generation_id,
        decision_at=inputs.decision_at,
        status="ready",
        reason=None,
        policy_version="attention-components-v1",
        inputs=inputs,
        coverage=AttentionCoverage(
            rows=len(rows),
            eligible=len(rows),
            confluence_ready=len(rows),
            component_ready={name: len(rows) for name in COMPONENTS},
        ),
        rows=tuple(rows),
    )
    return inputs, response
