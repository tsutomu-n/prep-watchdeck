"""Attention contracts. Public timestamps are UTC milliseconds, never local clock strings."""

import hashlib
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

MINUTE = 60_000
FEATURE_VERSION = "attention-features-v1"
COMPONENTS = ("movement", "activity", "positioning", "dislocation")
ComponentName = Literal["movement", "activity", "positioning", "dislocation", "confluence"]
FeatureStatus = Literal["ready", "missing", "stale", "invalid", "unsupported"]
ComponentStatus = Literal["ready", "unavailable"]
AttentionStatus = Literal["ready", "partial", "unavailable", "stale"]
Direction = Literal["up", "down", "flat", "mixed", "unknown"]


class Contract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        json_schema_serialization_defaults_required=True,
    )


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


def content_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class SourceObservation(Contract):
    source: str
    start_at: int | None = None
    end_at: int | None = None
    observed_at: int | None = None
    source_at: int | None = None
    finality: str | None = None
    unit: str | None = None


class RawFeatureValue(Contract):
    value: float | None
    status: FeatureStatus
    reason: str | None = None
    unit: str | None = None
    source: str
    start_at: int | None = None
    end_at: int | None = None
    observed_at: int | None = None
    observations: tuple[SourceObservation, ...] = ()

    @model_validator(mode="after")
    def valid_value(self) -> Self:
        if self.status == "ready":
            if self.value is None or self.reason is not None:
                raise ValueError("ready feature requires a value and no reason")
        elif self.value is not None or not self.reason or not self.reason.strip():
            raise ValueError("unavailable feature requires null and a reason")
        if self.start_at is not None and self.end_at is not None and self.start_at > self.end_at:
            raise ValueError("feature start follows end")
        return self


class InputReference(Contract):
    generation_id: str = Field(min_length=1)
    feature_version: Literal["attention-features-v1"] = FEATURE_VERSION
    decision_at: int = Field(gt=0)
    ranking_cutoff: int = Field(gt=0)
    ranking_generated_at: int = Field(gt=0)
    ranking_generation_id: str = Field(min_length=1)
    ranking_map_version: str = Field(min_length=1)
    ranking_metric_version: str = Field(min_length=1)
    universe_generated_at: int = Field(gt=0)
    service_generated_at: int = Field(gt=0)
    market_metrics_generation_id: str | None
    market_metrics_generated_at: int | None
    market_metrics_candle_cutoff: int | None
    input_skew_seconds: float = Field(ge=0)
    quality_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def time_consistency(self) -> Self:
        times = (
            self.ranking_cutoff,
            self.ranking_generated_at,
            self.universe_generated_at,
            self.service_generated_at,
            self.market_metrics_generated_at,
            self.market_metrics_candle_cutoff,
        )
        if any(t is not None and t > self.decision_at for t in times):
            raise ValueError("future input timestamp")
        if self.ranking_cutoff % MINUTE or self.ranking_generated_at < self.ranking_cutoff:
            raise ValueError("invalid ranking cutoff")
        if (self.market_metrics_generation_id is None) != (
            self.market_metrics_generated_at is None
        ):
            raise ValueError("metrics identity and time must agree")
        return self


class OriginalReference(Contract):
    instrument_id: str
    version_id: int = Field(gt=0)
    venue: str
    group_id: str | None = None
    multiplier: int | None = Field(default=None, gt=0)


class FeatureSnapshotRow(Contract):
    asset_id: str
    asset: str
    reference_key: str | None
    original_instrument_versions: tuple[OriginalReference, ...]
    decision_at: int
    identity_status: Literal["ready", "partial", "invalid", "excluded"]
    quality_reasons: tuple[str, ...]
    reference_close: RawFeatureValue
    reference_return15m: RawFeatureValue
    reference_return1h: RawFeatureValue
    reference_return24h: RawFeatureValue
    reference_turnover15m: RawFeatureValue
    reference_turnover1h: RawFeatureValue
    reference_turnover_ratio15m: RawFeatureValue
    reference_turnover_ratio1h: RawFeatureValue
    reference_day_range_position: RawFeatureValue
    native_return15m_median: RawFeatureValue
    native_return1h_median: RawFeatureValue
    oi_change15m_median: RawFeatureValue
    oi_change1h_median: RawFeatureValue
    funding_abs_max_per_hour: RawFeatureValue
    funding_range_per_hour: RawFeatureValue
    spread_median_bps: RawFeatureValue
    spread_max_bps: RawFeatureValue
    mark_dispersion_bps: RawFeatureValue
    fresh_native_venue_count: int = Field(ge=0)
    ready_native_venue_count: int = Field(ge=0)

    @model_validator(mode="after")
    def no_future_features(self) -> Self:
        for value in self.__dict__.values():
            if not isinstance(value, RawFeatureValue):
                continue
            times = [value.start_at, value.end_at, value.observed_at]
            for observation in value.observations:
                times.extend(
                    (
                        observation.start_at,
                        observation.end_at,
                        observation.observed_at,
                        observation.source_at,
                    )
                )
            if any(t is not None and t > self.decision_at for t in times):
                raise ValueError("future feature observation")
            if self.identity_status in ("invalid", "excluded") and value.status == "ready":
                raise ValueError("ineligible identity cannot carry ready features")
        return self


class AttentionComponent(Contract):
    policy_version: str
    status: ComponentStatus
    score: float | None = Field(default=None, ge=0, le=100)
    raw_value: float | None = None
    rank: int | None = Field(default=None, ge=1)
    rank_change: int | None = None
    direction: Direction = "unknown"
    reason: str | None = None
    inputs: tuple[str, ...] = ()
    peer_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def availability(self) -> Self:
        if self.status == "ready":
            if self.score is None or self.rank is None or self.reason is not None:
                raise ValueError("ready component needs score, rank and no reason")
        elif self.score is not None or self.rank is not None or not self.reason:
            raise ValueError("unavailable component needs null score/rank and reason")
        return self


class AttentionRow(Contract):
    asset_id: str
    asset: str
    reference_key: str | None
    originals: tuple[OriginalReference, ...]
    components: dict[ComponentName, AttentionComponent]
    ready_component_count: int = Field(ge=0, le=4)
    total_component_count: Literal[4] = 4
    coverage_ratio: float = Field(ge=0, le=1)
    quality_reasons: tuple[str, ...]
    data_as_of: int
    identity_status: Literal["ready", "partial", "invalid", "excluded"]

    @model_validator(mode="after")
    def complete_components(self) -> Self:
        if set(self.components) != {*COMPONENTS, "confluence"}:
            raise ValueError("all component fields are required")
        ready = sum(self.components[name].status == "ready" for name in COMPONENTS)
        if ready != self.ready_component_count or self.coverage_ratio != ready / 4:
            raise ValueError("component coverage mismatch")
        if self.components["confluence"].status == "ready" and ready != 4:
            raise ValueError("confluence requires all four components")
        return self


class AttentionCoverage(Contract):
    rows: int = Field(ge=0)
    eligible: int = Field(ge=0)
    confluence_ready: int = Field(ge=0)
    component_ready: dict[str, int]


class AllocationPolicy(Contract):
    id: str
    kind: Literal["top-k-v1", "hysteresis-v1", "cost-aware-greedy-v1"]
    component: ComponentName = "confluence"
    k: int = Field(gt=0, le=100)
    buffer: int = Field(default=0, ge=0)
    minimum_hold_minutes: int = Field(default=0, ge=0)
    switch_penalty: float = Field(default=0, ge=0)
    warm_up_cost: float = Field(default=0, ge=0)


class ShadowSlot(Contract):
    asset_id: str
    group_ids: tuple[str, ...]
    entered_at: int
    score: float = Field(ge=0, le=100)
    rank: int = Field(ge=1)


class ShadowAllocation(Contract):
    schema_version: Literal["attention-shadow-allocation-v1"] = "attention-shadow-allocation-v1"
    generation_id: str
    decision_at: int
    map_version: str
    policy: AllocationPolicy
    score_policy_version: str
    mode: Literal["shadow_only"] = "shadow_only"
    manual_selection_id: str | None = None
    manual_selection_mutated: Literal[False] = False
    comparable: bool
    reason: str | None = None
    slots: tuple[ShadowSlot, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    retained: tuple[str, ...]
    added_groups: tuple[str, ...] = ()
    removed_groups: tuple[str, ...] = ()
    churn: float = Field(ge=0, le=1)
    estimated_switch_cost: float = Field(ge=0)
    cost_status: Literal["estimated"] = "estimated"


class AttentionResponse(Contract):
    schema_version: Literal["attention-response-v1"] = "attention-response-v1"
    generation_id: str
    decision_at: int
    status: AttentionStatus
    reason: str | None
    policy_version: str
    inputs: InputReference
    coverage: AttentionCoverage
    rows: tuple[AttentionRow, ...]
    shadow_allocations: tuple[ShadowAllocation, ...] = ()

    @model_validator(mode="after")
    def generation_identity(self) -> Self:
        if (
            self.generation_id != self.inputs.generation_id
            or self.decision_at != self.inputs.decision_at
        ):
            raise ValueError("generation identity mismatch")
        if (
            len({row.asset_id for row in self.rows}) != len(self.rows)
            or len(self.rows) != self.coverage.rows
        ):
            raise ValueError("duplicate or missing row")
        if any(row.data_as_of > self.decision_at for row in self.rows):
            raise ValueError("future row")
        return self


class OutcomeRow(Contract):
    generation_id: str
    asset_id: str
    reference_key: str | None
    horizon_minutes: Literal[15, 60]
    family: Literal["reference", "native"] = "reference"
    edition: int = Field(default=1, ge=1)
    status: Literal["ready", "pending", "unscorable"]
    reason: str | None
    cutoff: int
    through: int
    settled_at: int
    max_abs_return: float | None = Field(default=None, ge=0)
    close_return: float | None = None
    time_to_top_decile_move: float | None = Field(default=None, ge=0)
    native_dispersion_max: float | None = Field(default=None, ge=0)
    oi_change_abs_max: float | None = Field(default=None, ge=0)
    input_fingerprint: str

    @model_validator(mode="after")
    def outcome_values(self) -> Self:
        if self.through != self.cutoff + self.horizon_minutes * MINUTE:
            raise ValueError("outcome horizon mismatch")
        values = (
            self.max_abs_return,
            self.close_return,
            self.time_to_top_decile_move,
            self.native_dispersion_max,
            self.oi_change_abs_max,
        )
        if self.status == "ready":
            if self.reason is not None or self.settled_at < self.through:
                raise ValueError("ready outcome must be complete")
            if self.family == "reference" and (
                self.max_abs_return is None or self.close_return is None
            ):
                raise ValueError("ready reference outcome requires returns")
        elif not self.reason or any(v is not None for v in values):
            raise ValueError("unsettled outcome must not impute values")
        return self


class CandidatePolicy(Contract):
    id: str
    family_id: str
    signal: Literal[
        "reference-abs-return-15m",
        "reference-abs-return-1h",
        "turnover-ratio",
        "movement",
        "activity",
        "positioning",
        "dislocation",
        "confluence",
    ]
    version: str
    frozen_at: int
    k_values: tuple[int, ...] = (10, 20)
    horizon_minutes: Literal[15, 60] = 15
    minimum_day_blocks: int = Field(default=30, ge=2)
    minimum_coverage: float = Field(default=0.8, ge=0, le=1)
    maximum_coverage_regression: float = Field(default=0.05, ge=0, le=1)

    @model_validator(mode="after")
    def fixed_k(self) -> Self:
        if (
            not self.k_values
            or len(set(self.k_values)) != len(self.k_values)
            or min(self.k_values) < 1
        ):
            raise ValueError("invalid candidate K values")
        return self


class EvaluationMetrics(Contract):
    recall: float | None
    precision: float | None
    ndcg: float | None
    mean_future_max_abs_return: float | None
    median_lead_time: float | None
    coverage: float = Field(ge=0, le=1)
    unscorable_rate: float = Field(ge=0, le=1)
    set_churn: float | None
    rank_churn: float | None = None
    generation_count: int = Field(ge=0)


class CandidateEvaluation(Contract):
    policy_id: str
    baseline_policy_id: str
    k: int
    horizon_minutes: int
    metrics: EvaluationMetrics
    baseline_metrics: EvaluationMetrics
    mean_delta: float | None
    adjusted_p_value: float | None = Field(default=None, ge=0, le=1)
    sensitivity_p_value: float | None = Field(default=None, ge=0, le=1)
    block_count: int
    effective_days: int
    minimum_practical_delta: float
    estimated_power: float | None = Field(default=None, ge=0, le=1)
    mde80: float | None = Field(default=None, ge=0)
    planning_only: Literal[True] = True
    decision: Literal[
        "supported", "not_supported", "not_estimable", "inconclusive", "rejected_coverage"
    ]
    reasons: tuple[str, ...]


class AttentionEvaluationReport(Contract):
    schema_version: Literal["attention-evaluation-v1"] = "attention-evaluation-v1"
    method: Literal["attention-family-max-t-v1"] = "attention-family-max-t-v1"
    run_id: str
    family_id: str
    policy_hashes: dict[str, str]
    outcome_fingerprint: str
    created_at: int
    bootstrap_samples: int
    seed: int
    primary_block_hours: Literal[24] = 24
    sensitivity_block_hours: Literal[6] = 6
    planning_only: Literal[True] = True
    stale: bool = False
    evaluations: tuple[CandidateEvaluation, ...]
    reasons: tuple[str, ...] = ()
