"""Consistent read-only Market bundle; optional metrics never become empty success."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from prep_watchdeck_market.artifacts import MarketServiceStateArtifact, UniverseSnapshotArtifact
from prep_watchdeck_market.market_metrics import MarketMetricsArtifact
from pydantic import ValidationError

from prep_watchdeck_attention.stable_files import StableFileError, read_stable_regular_file

MAX_INPUT_BYTES = 32 * 1024 * 1024


class MarketInputError(ValueError):
    """Required Market inputs are unavailable or inconsistent."""


@dataclass(frozen=True, slots=True)
class MarketInputBundle:
    service: MarketServiceStateArtifact
    universe: UniverseSnapshotArtifact
    metrics: MarketMetricsArtifact | None
    metrics_error: str | None


def utc_ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_aware_timestamp_required")
    return int(value.timestamp() * 1000)


def _fresh(value: datetime, now: datetime, maximum_seconds: int) -> None:
    age = (utc_ms(now) - utc_ms(value)) / 1000
    if age < 0:
        raise MarketInputError("future_timestamp")
    if age > maximum_seconds:
        raise MarketInputError("input_stale")


def read_market_inputs(
    market_state_dir: Path, *, now: datetime, retries: int = 1
) -> MarketInputBundle:
    utc_ms(now)
    if not 0 <= retries <= 1:
        raise MarketInputError("at_most_one_retry")
    root = market_state_dir / "artifacts"
    for attempt in range(retries + 1):
        try:
            before_bytes = read_stable_regular_file(
                root / "service-state.json", max_bytes=MAX_INPUT_BYTES
            )
            service = MarketServiceStateArtifact.model_validate_json(before_bytes)
            universe = UniverseSnapshotArtifact.model_validate_json(
                read_stable_regular_file(root / "universe-snapshot.json", max_bytes=MAX_INPUT_BYTES)
            )
            metrics = None
            metrics_error = None
            try:
                metrics = MarketMetricsArtifact.model_validate_json(
                    read_stable_regular_file(
                        root / "market-metrics.json", max_bytes=MAX_INPUT_BYTES
                    )
                )
                _fresh(metrics.generated_at, now, 150)
                _fresh(metrics.candle_cutoff, now, 300)
            except (StableFileError, ValidationError, ValueError) as error:
                if isinstance(error, MarketInputError) and str(error) == "future_timestamp":
                    raise
                metrics = None
                metrics_error = (
                    str(error)
                    if not isinstance(error, ValidationError)
                    else "metrics_schema_invalid"
                )
            after_bytes = read_stable_regular_file(
                root / "service-state.json", max_bytes=MAX_INPUT_BYTES
            )
            if before_bytes != after_bytes:
                if attempt < retries:
                    continue
                raise MarketInputError("market_bundle_changed")
            _fresh(service.generated_at, now, 150)
            _fresh(universe.generated_at, now, 150)
            if universe.status in ("unavailable", "stale"):
                raise MarketInputError("universe_unavailable")
            states = [s for s in service.artifacts if s.name == "universe-snapshot.json"]
            if len(states) != 1 or states[0].status != "ready":
                raise MarketInputError("universe_file_not_ready")
            if states[0].generated_at != universe.generated_at:
                raise MarketInputError("universe_generation_mismatch")
            return MarketInputBundle(service, universe, metrics, metrics_error)
        except (StableFileError, ValidationError) as error:
            if isinstance(error, StableFileError) and str(error) == "input_changed_during_read":
                if attempt < retries:
                    continue
                raise MarketInputError("market_bundle_changed") from error
            raise MarketInputError("required_market_input_invalid") from error
    raise MarketInputError("market_bundle_changed")
