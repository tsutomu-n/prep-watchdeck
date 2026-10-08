"""Prospective, single-step family max-T; not a paper-exact White/SPA/Romano-Wolf test.

The only inferential endpoint is selected mean future maximum absolute reference return.
Observations are averaged inside UTC blocks, then whole *joint* block vectors are sampled
with replacement. Centered means use the original block standard errors (fixed scaling).
This approximation assumes sufficiently weak dependence between days; the six-hour run
is a sensitivity diagnostic, not additional independent evidence. Descriptive retrieval
metrics and normal-approximation power planning cannot establish statistical support.
"""

import math
import random
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist, fmean, median, stdev

from .models import (
    MINUTE,
    AttentionEvaluationReport,
    AttentionResponse,
    CandidateEvaluation,
    CandidatePolicy,
    EvaluationMetrics,
    FeatureSnapshotRow,
    InputReference,
    OutcomeRow,
    content_digest,
    outcome_cutoff,
)
from .storage import AttentionStore

BASELINES = {
    "reference-abs-return-15m": "reference_return15m",
    "reference-abs-return-1h": "reference_return1h",
    "turnover-ratio": "reference_turnover_ratio15m",
}
BASELINE_VERSION = "attention-reference-baselines-v1"
DAY = 1440 * MINUTE
Generation = tuple[InputReference, tuple[FeatureSnapshotRow, ...], AttentionResponse]
Series = dict[str, list[tuple[int, float]]]


def _average(values: Sequence[float]) -> float | None:
    return fmean(values) if values else None


def _semantic(policy: CandidatePolicy) -> str:
    return content_digest(policy.model_dump(exclude={"id", "family_id", "frozen_at"}))


def _ranking(policy: CandidatePolicy, generation: Generation) -> list[str]:
    _, features, response = generation
    scores: dict[str, float] = {}
    for row in features:
        if row.identity_status not in ("ready", "partial") or row.reference_key is None:
            continue
        field = BASELINES.get(policy.signal)
        if field is not None:
            value = getattr(row, field)
            if value.status == "ready" and value.value is not None:
                scores[row.asset_id] = (
                    value.value if policy.signal == "turnover-ratio" else abs(value.value)
                )
        else:
            attention = next((r for r in response.rows if r.asset_id == row.asset_id), None)
            if attention is None:
                continue
            component = next(
                (value for name, value in attention.components.items() if name == policy.signal),
                None,
            )
            if (
                component is not None
                and component.status == "ready"
                and component.score is not None
                and component.policy_version == policy.version
            ):
                scores[row.asset_id] = component.score
    return sorted(scores, key=lambda asset: (-scores[asset], asset))


def _outcomes(rows: Sequence[OutcomeRow]) -> dict[tuple[str, str, int], OutcomeRow]:
    latest: dict[tuple[str, str, int], OutcomeRow] = {}
    for row in rows:
        if row.family != "reference":
            continue
        key = (row.generation_id, row.asset_id, row.horizon_minutes)
        old = latest.get(key)
        if old is None or row.edition > old.edition:
            latest[key] = row
        elif row.edition == old.edition and row != old:
            raise ValueError("conflicting duplicate outcome edition")
    return latest


@dataclass(frozen=True)
class _PolicyMetrics:
    metrics: EvaluationMetrics
    returns: dict[int, float]
    complete_fraction: float
    universe_outcome_coverage: float
    mature_outcome_count: int


def _metrics(
    policy: CandidatePolicy,
    k: int,
    generations: Sequence[Generation],
    outcomes: dict[tuple[str, str, int], OutcomeRow],
) -> _PolicyMetrics:
    recalls: list[float] = []
    precisions: list[float] = []
    ndcgs: list[float] = []
    future: list[float] = []
    lead: list[float] = []
    coverages: list[float] = []
    missing_rates: list[float] = []
    universe_coverages: list[float] = []
    churns: list[float] = []
    rank_churns: list[float] = []
    returns: dict[int, float] = {}
    mature_outcome_count = 0
    previous: list[str] | None = None
    previous_map: str | None = None
    for inputs, features, response in generations:
        ranked = _ranking(policy, (inputs, features, response))
        selected = ranked[:k]  # Selection precedes looking at future outcomes. Never backfill.
        ready: dict[str, OutcomeRow] = {}
        for row in features:
            outcome = outcomes.get((inputs.generation_id, row.asset_id, policy.horizon_minutes))
            if outcome is not None and outcome.status != "pending":
                mature_outcome_count += 1
            if (
                row.identity_status in ("ready", "partial")
                and row.reference_key is not None
                and outcome is not None
                and outcome.reference_key == row.reference_key
                and outcome.cutoff == outcome_cutoff(inputs.decision_at)
                and outcome.status == "ready"
                and outcome.max_abs_return is not None
            ):
                ready[row.asset_id] = outcome
        total = len(features)
        coverages.append(len(ranked) / total if total else 0.0)
        universe_coverages.append(len(ready) / total if total else 0.0)
        missing_rates.append(
            sum(asset not in ready for asset in selected) / len(selected) if selected else 1.0
        )
        if previous is not None and previous_map == inputs.ranking_map_version:
            union = set(previous) | set(selected)
            churns.append(1 - len(set(previous) & set(selected)) / len(union) if union else 0.0)
            common = set(previous) & set(selected)
            if common:
                rank_churns.append(
                    fmean(
                        abs(previous.index(a) - selected.index(a)) / max(k - 1, 1) for a in common
                    )
                )
        previous, previous_map = selected, inputs.ranking_map_version
        if not selected or any(asset not in ready for asset in selected):
            continue
        realized = sorted(ready, key=lambda a: (-float(ready[a].max_abs_return or 0), a))
        # Exact ceil(n / 10) set, with asset-ID tie breaking; all-zero outcomes have no opportunity.
        positive = [a for a in realized if (ready[a].max_abs_return or 0) > 0]
        relevant = set(positive[: math.ceil(len(realized) / 10)])
        hits = len(set(selected) & relevant)
        if relevant:
            recalls.append(hits / len(relevant))
            precisions.append(hits / min(k, total))
        gains = {a: float(ready[a].max_abs_return or 0) for a in realized}
        dcg = sum(gains[a] / math.log2(i + 2) for i, a in enumerate(selected))
        ideal = sum(gains[a] / math.log2(i + 2) for i, a in enumerate(realized[:k]))
        if ideal > 0:
            ndcgs.append(dcg / ideal)
        value = fmean(gains[a] for a in selected)
        future.append(value)
        returns[inputs.decision_at] = value
        for asset in selected:
            lead_time = ready[asset].time_to_top_decile_move
            if asset in relevant and lead_time is not None:
                lead.append(lead_time)
    count = len(generations)
    return _PolicyMetrics(
        metrics=EvaluationMetrics(
            recall=_average(recalls),
            precision=_average(precisions),
            ndcg=_average(ndcgs),
            mean_future_max_abs_return=_average(future),
            median_lead_time=median(lead) if lead else None,
            coverage=fmean(coverages) if count else 0,
            unscorable_rate=fmean(missing_rates) if count else 1,
            set_churn=_average(churns),
            rank_churn=_average(rank_churns),
            generation_count=count,
        ),
        returns=returns,
        complete_fraction=len(returns) / count if count else 0,
        universe_outcome_coverage=fmean(universe_coverages) if count else 0,
        mature_outcome_count=mature_outcome_count,
    )


@dataclass(frozen=True)
class _Inference:
    mean: float | None
    standard_error: float | None
    p: float | None
    blocks: int
    critical: float | None


def _joint_max_t(series: Series, *, hours: int, samples: int, seed: int) -> dict[str, _Inference]:
    """Resample the same calendar block indices for every hypothesis, once per draw."""
    block_values: dict[str, dict[int, float]] = {}
    for key, observations in sorted(series.items()):
        blocks: dict[int, list[float]] = defaultdict(list)
        for at, value in sorted(observations):
            blocks[at // (hours * 60 * MINUTE)].append(value)
        block_values[key] = {block: fmean(values) for block, values in blocks.items()}
    populated = [set(values) for values in block_values.values() if values]
    common = sorted(set.intersection(*populated)) if populated else []
    vectors = {
        key: [blocks[block] for block in common]
        for key, blocks in block_values.items()
        if blocks and common
    }
    means = {key: fmean(values) for key, values in vectors.items()}
    errors = {
        key: stdev(values) / math.sqrt(len(values))
        for key, values in vectors.items()
        if len(values) >= 2
    }
    usable = {key: error for key, error in errors.items() if error > 1e-14}
    rng = random.Random(seed)
    maxima: list[float] = []
    if usable:
        for _ in range(samples):
            indices = [rng.randrange(len(common)) for _ in common]
            maxima.append(
                max(
                    0.0,
                    max(
                        (fmean(vectors[key][i] for i in indices) - means[key]) / error
                        for key, error in usable.items()
                    ),
                )
            )
    critical = sorted(maxima)[math.ceil(0.95 * len(maxima)) - 1] if maxima else None
    result: dict[str, _Inference] = {}
    for key in series:
        mean, error = means.get(key), errors.get(key)
        p = None
        if key in usable and mean is not None and error is not None:
            statistic = mean / error
            p = (1 + sum(m >= statistic for m in maxima)) / (samples + 1)
        elif mean == 0 and error == 0:
            p = 1.0  # Identical rankings cannot establish an edge; not an estimated variance.
        result[key] = _Inference(mean, error, p, len(common) if key in vectors else 0, critical)
    return result


def _decision(
    policy: CandidatePolicy,
    candidate: _PolicyMetrics,
    baseline: _PolicyMetrics,
    day: _Inference,
    sensitivity: _Inference,
    delta: float,
) -> tuple[str, tuple[str, ...]]:
    if candidate.metrics.generation_count == 0:
        return "not_estimable", ("no_prospective_evidence",)
    if candidate.mature_outcome_count == 0:
        return "not_estimable", ("awaiting_mature_prospective_outcomes",)
    if (
        candidate.metrics.coverage < policy.minimum_coverage
        or baseline.metrics.coverage - candidate.metrics.coverage
        > policy.maximum_coverage_regression
        or candidate.complete_fraction < policy.minimum_coverage
        or baseline.complete_fraction - candidate.complete_fraction
        > policy.maximum_coverage_regression
        or candidate.universe_outcome_coverage < policy.minimum_coverage
        or candidate.metrics.unscorable_rate > 1 - policy.minimum_coverage
    ):
        return "rejected_coverage", ("candidate_input_or_outcome_coverage_loss",)
    if (
        baseline.metrics.coverage < policy.minimum_coverage
        or baseline.complete_fraction < policy.minimum_coverage
        or baseline.universe_outcome_coverage < policy.minimum_coverage
    ):
        return "not_estimable", ("baseline_coverage_insufficient",)
    if day.blocks < policy.minimum_day_blocks:
        return "not_estimable", ("too_few_joint_utc_day_blocks",)
    if day.p is None or sensitivity.p is None:
        return "not_estimable", ("degenerate_block_variance_or_missing_paired_outcomes",)
    supported = day.p <= 0.05 and day.mean is not None and day.mean > 0 and day.mean >= delta
    six_supported = (
        sensitivity.p <= 0.05
        and sensitivity.mean is not None
        and sensitivity.mean > 0
        and sensitivity.mean >= delta
    )
    if supported != six_supported or (
        day.mean is not None and sensitivity.mean is not None and day.mean * sensitivity.mean < 0
    ):
        return "inconclusive", ("utc_day_six_hour_sensitivity_disagreement",)
    if supported:
        return "supported", ("family_adjusted_edge_exceeds_frozen_practical_delta",)
    return "not_supported", ("family_adjusted_or_practical_edge_not_established",)


def evaluate_candidate_family(
    store: AttentionStore,
    *,
    policy_ids: Sequence[str],
    baseline_policy_ids: Sequence[str],
    k_values: tuple[int, ...],
    minimum_practical_delta: float,
    bootstrap_samples: int,
    seed: int,
) -> AttentionEvaluationReport:
    if tuple(sorted(k_values)) != (10, 20):
        raise ValueError("initial evaluation requires fixed K=10,20")
    if not math.isfinite(minimum_practical_delta) or minimum_practical_delta < 0:
        raise ValueError("minimum practical delta must be finite and nonnegative")
    if bootstrap_samples < 199:
        raise ValueError("at least 199 bootstrap samples are required")
    all_policies = {p.id: p for p in store.policies()}
    requested = set(policy_ids) | set(baseline_policy_ids)
    if not policy_ids or not baseline_policy_ids or not requested <= all_policies.keys():
        raise ValueError("registered candidates and baselines are required")
    policies = [all_policies[key] for key in sorted(requested)]
    families = {p.family_id for p in policies}
    if len(families) != 1:
        raise ValueError("one frozen family is required")
    family = policies[0].family_id
    if {p.id for p in store.policies(family)} != requested:
        raise ValueError("evaluate the entire frozen family, including all baselines")
    if any(tuple(sorted(p.k_values)) != (10, 20) for p in policies):
        raise ValueError("evaluation K differs from frozen policy")
    if any(p.minimum_practical_delta != minimum_practical_delta for p in policies):
        raise ValueError("practical delta differs from frozen policy")
    baseline_policies = [all_policies[key] for key in sorted(set(baseline_policy_ids))]
    if any(p.signal in BASELINES and p.version != BASELINE_VERSION for p in policies):
        raise ValueError("unknown baseline implementation version")
    for policy in baseline_policies:
        if policy.signal not in BASELINES or policy.version != BASELINE_VERSION:
            raise ValueError("unknown baseline signal or implementation version")
    horizons = {all_policies[key].horizon_minutes for key in policy_ids}
    for horizon in horizons:
        if {p.signal for p in baseline_policies if p.horizon_minutes == horizon} != set(BASELINES):
            raise ValueError("each candidate horizon needs all three frozen baselines")
    store.freeze_family(policies)  # Rechecks the immutable hashes, never creates a new family here.
    freeze_at = max(p.frozen_at for p in policies)
    unique: dict[int, Generation] = {}
    excluded = 0
    for generation in sorted(
        store.evidence_generations(), key=lambda g: (g[0].decision_at, g[0].generation_id)
    ):
        inputs, _, _ = generation
        if inputs.decision_at <= freeze_at or inputs.ranking_cutoff <= freeze_at:
            excluded += 1
            continue
        # One decision per source cutoff; repeated publication does not multiply evidence.
        unique.setdefault(inputs.ranking_cutoff, generation)
    generations = sorted(unique.values(), key=lambda g: (g[0].decision_at, g[0].generation_id))
    outcomes = _outcomes(store.latest_outcomes())
    cache: dict[tuple[str, int], _PolicyMetrics] = {}
    for policy in policies:
        for k in sorted(k_values):
            cache.setdefault((_semantic(policy), k), _metrics(policy, k, generations, outcomes))
    comparisons: list[tuple[CandidatePolicy, CandidatePolicy, int, str]] = []
    series: Series = {}
    for candidate_id in sorted(set(policy_ids)):
        candidate = all_policies[candidate_id]
        for baseline in baseline_policies:
            if baseline.horizon_minutes != candidate.horizon_minutes:
                continue
            for k in sorted(k_values):
                left, right = _semantic(candidate), _semantic(baseline)
                key = f"{left}:{right}:{k}"
                comparisons.append((candidate, baseline, k, key))
                c, b = cache[(left, k)], cache[(right, k)]
                series[key] = [
                    (at, c.returns[at] - b.returns[at])
                    for at in sorted(c.returns.keys() & b.returns.keys())
                ]
    daily = _joint_max_t(series, hours=24, samples=bootstrap_samples, seed=seed)
    six_hour = _joint_max_t(series, hours=6, samples=bootstrap_samples, seed=seed)
    evaluations: list[CandidateEvaluation] = []
    for candidate, baseline, k, key in comparisons:
        c, b = cache[(_semantic(candidate), k)], cache[(_semantic(baseline), k)]
        day, six = daily[key], six_hour[key]
        decision, reasons = _decision(candidate, c, b, day, six, minimum_practical_delta)
        power = mde = None
        if (
            day.blocks >= candidate.minimum_day_blocks
            and day.standard_error is not None
            and day.standard_error > 1e-14
            and day.critical is not None
        ):
            power = NormalDist().cdf(minimum_practical_delta / day.standard_error - day.critical)
            mde = (day.critical + NormalDist().inv_cdf(0.8)) * day.standard_error
        evaluations.append(
            CandidateEvaluation.model_validate(
                {
                    "policy_id": candidate.id,
                    "baseline_policy_id": baseline.id,
                    "k": k,
                    "horizon_minutes": candidate.horizon_minutes,
                    "metrics": c.metrics,
                    "baseline_metrics": b.metrics,
                    "mean_delta": day.mean,
                    "adjusted_p_value": day.p
                    if day.blocks >= candidate.minimum_day_blocks
                    else None,
                    "sensitivity_p_value": six.p
                    if day.blocks >= candidate.minimum_day_blocks
                    else None,
                    "block_count": day.blocks,
                    "effective_days": day.blocks,
                    "minimum_practical_delta": minimum_practical_delta,
                    "estimated_power": power,
                    "mde80": mde,
                    "decision": decision,
                    "reasons": reasons,
                }
            )
        )
    relevant_ids = {g[0].generation_id for g in generations}
    fingerprint = content_digest(
        [
            row.model_dump(mode="json", by_alias=True)
            for key, row in sorted(outcomes.items())
            if key[0] in relevant_ids
        ]
    )
    created_at = time.time_ns() // 1_000_000
    hashes = {p.id: content_digest(p.model_dump(mode="json", by_alias=True)) for p in policies}
    report = AttentionEvaluationReport(
        run_id=content_digest(
            {
                "created_at": created_at,
                "policies": hashes,
                "outcomes": fingerprint,
                "candidates": sorted(set(policy_ids)),
                "baselines": sorted(set(baseline_policy_ids)),
                "bootstrap_samples": bootstrap_samples,
                "seed": seed,
            }
        ),
        family_id=family,
        policy_hashes=hashes,
        outcome_fingerprint=fingerprint,
        created_at=created_at,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
        evaluations=tuple(evaluations),
        reasons=(
            "primary_endpoint_equal_weight_utc_block_mean_future_max_abs_return_delta",
            "single_step_centered_joint_block_bootstrap_fixed_standard_error_max_t",
            "all_nonempty_comparisons_use_common_calendar_blocks_no_missing_value_imputation",
            "power_mde_normal_approximation_using_day_block_se_and_family_critical_value_planning_only",
            "weak_between_day_dependence_assumed_six_hour_check_not_independent_confirmation",
            "retrieval_metrics_descriptive_linear_gain_ndcg_asset_id_ties_top_decile_ceil",
            "precision_denominator_min_k_universe_size_lead_time_seconds_return_percentage_points",
            "coverage_input_availability_unscorable_includes_pending_selected_outcomes",
            f"prefreeze_generations_excluded:{excluded}",
        ),
    )
    store.save_evaluation(report)
    return report
