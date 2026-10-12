"""Fixed discovery policy and latest raw projection; UTC millisecond timestamps."""

from typing import Literal

from prep_watchdeck_ranking.models import TurnoverComparison
from pydantic import Field

from .models import Contract, FeatureSnapshotRow, InputReference, OriginalReference, RawFeatureValue

POLICY_ID = "discovery-reference-turnover-15m-v1"
DiscoveryState = Literal["matched", "not_matched", "unknown"]
DiscoveryDirection = Literal["up", "down", "turnover", "unknown"]
Confirmation = Literal["new", "initial_confirmation", "reconfirmation", "continuing"]


class DiscoveryPolicy(Contract):
    id: Literal["discovery-reference-turnover-15m-v1"] = POLICY_ID
    turnover_ratio_threshold: Literal[3] = 3
    return_threshold_pct: Literal[2] = 2
    window_minutes: Literal[15] = 15
    browser_settings_independent: Literal[True] = True


class DiscoveryNative(Contract):
    instrument_id: str
    version_id: int
    venue: str
    source_symbol: str
    quality: str
    quality_reasons: tuple[str, ...]
    mark_price: RawFeatureValue
    funding_rate_raw: RawFeatureValue
    funding_rate_per_hour: RawFeatureValue
    funding_interval_seconds: int | None
    open_interest_raw: RawFeatureValue
    open_interest_base: RawFeatureValue
    open_interest_notional: RawFeatureValue
    oi_change: dict[str, RawFeatureValue]
    return_pct: dict[str, RawFeatureValue]


class DiscoveryRow(Contract):
    asset_id: str
    asset: str
    reference_key: str | None
    originals: tuple[OriginalReference, ...]
    identity_key: str
    state: DiscoveryState
    reason: str | None
    direction: DiscoveryDirection
    confirmation: Confirmation | None = None
    episode_id: str | None = None
    raw: FeatureSnapshotRow
    turnover_comparison: TurnoverComparison
    native: tuple[DiscoveryNative, ...]


class DiscoveryEpisode(Contract):
    id: str
    policy_id: str = POLICY_ID
    identity_key: str
    asset_id: str
    asset: str
    reference_key: str | None
    originals: tuple[OriginalReference, ...]
    state: Literal["active", "interrupted", "ended"]
    start_kind: Literal["new", "initial_confirmation", "reconfirmation"]
    first_observed_at: int
    last_confirmed_at: int
    consecutive_confirmations: int = Field(ge=1)
    observed_duration_ms: int = Field(ge=0)
    ended_at: int | None = None
    end_reason: str | None = None
    interruption_reason: str | None = None
    direction: DiscoveryDirection
    first_source_generation_id: str
    last_source_generation_id: str
    first_ranking_cutoff: int
    last_ranking_cutoff: int


class DiscoveryResponse(Contract):
    schema_version: Literal["discovery-response-v1"] = "discovery-response-v1"
    policy: DiscoveryPolicy = DiscoveryPolicy()
    generation_id: str | None
    decision_at: int | None
    ranking_cutoff: int | None
    inputs: InputReference | None
    status: Literal["ready", "partial", "stale", "unavailable"]
    reason: str | None
    history_available_from: int | None
    rows: tuple[DiscoveryRow, ...]
    episodes: tuple[DiscoveryEpisode, ...]
    next_cursor: str | None = None


class DiscoverySummaryRow(Contract):
    """List labels and exact identity only; frozen evidence remains in the detail contract."""

    asset_id: str
    asset: str
    reference_key: str | None
    originals: tuple[OriginalReference, ...]
    identity_key: str
    state: DiscoveryState
    reason: str | None
    direction: DiscoveryDirection
    confirmation: Confirmation | None = None
    episode_id: str | None = None


class DiscoverySummary(Contract):
    schema_version: Literal["discovery-summary-v1"] = "discovery-summary-v1"
    policy: DiscoveryPolicy = DiscoveryPolicy()
    generation_id: str | None
    decision_at: int | None
    ranking_cutoff: int | None
    status: Literal["ready", "partial", "stale", "unavailable"]
    reason: str | None
    history_available_from: int | None
    rows: tuple[DiscoverySummaryRow, ...]
