"""Prospective settlement from explicitly supplied offline, closed reference bars."""

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

from prep_watchdeck_ranking.models import MinuteBar
from pydantic import Field, model_validator

from .models import (
    MINUTE,
    Contract,
    FeatureSnapshotRow,
    InputReference,
    OriginalReference,
    OutcomeRow,
    content_digest,
    outcome_cutoff,
)
from .storage import AttentionStore


class ReferenceBarReader(Protocol):
    def bars(self, reference_key: str, *, after: int, through: int) -> Sequence[MinuteBar]: ...


class NativeOutcomePoint(Contract):
    asset_id: str
    at: int
    originals: tuple[OriginalReference, ...]
    mark_dispersion_bps: float | None = Field(default=None, ge=0)
    oi_change_abs: float | None = Field(default=None, ge=0)
    status: Literal["ready", "unavailable"]


class OutcomeInput(Contract):
    schema_version: Literal["attention-outcome-input-v1"]
    map_version: str
    bars: tuple[MinuteBar, ...]
    native: tuple[NativeOutcomePoint, ...] = ()

    @model_validator(mode="after")
    def unique_bars(self) -> "OutcomeInput":
        keys = [(b.reference_key, b.end) for b in self.bars]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate offline reference bar")
        native = [(p.asset_id, p.at) for p in self.native]
        if len(native) != len(set(native)) or any(p.at % MINUTE for p in self.native):
            raise ValueError("invalid offline native minute observations")
        return self


class FixtureBarReader:
    """No active SQLite or external request. The export is one immutable validated input."""

    def __init__(self, data: OutcomeInput) -> None:
        self.data = data
        self.map_version = data.map_version
        self.reference_keys = frozenset(bar.reference_key for bar in data.bars)

    @classmethod
    def from_payload(cls, payload: object) -> "FixtureBarReader":
        return cls(OutcomeInput.model_validate(payload))

    @classmethod
    def from_file(cls, path: Path) -> "FixtureBarReader":
        from .stable_files import read_stable_regular_file

        return cls(
            OutcomeInput.model_validate_json(
                read_stable_regular_file(path, max_bytes=128 * 1024 * 1024)
            )
        )

    def bars(self, reference_key: str, *, after: int, through: int) -> Sequence[MinuteBar]:
        return tuple(
            b
            for b in self.data.bars
            if b.reference_key == reference_key and after < b.end <= through
        )

    def native_points(
        self, asset_id: str, *, after: int, through: int
    ) -> tuple[NativeOutcomePoint, ...]:
        return tuple(
            p for p in self.data.native if p.asset_id == asset_id and after < p.at <= through
        )


def _reference_outcome(
    inputs: InputReference,
    feature: FeatureSnapshotRow,
    reader: ReferenceBarReader,
    horizon: Literal[15, 60],
    now_ms: int,
) -> tuple[OutcomeRow, tuple[MinuteBar, ...], float | None]:
    cutoff = outcome_cutoff(inputs.decision_at)
    through = cutoff + horizon * MINUTE
    base = dict(
        generation_id=inputs.generation_id,
        asset_id=feature.asset_id,
        reference_key=feature.reference_key,
        horizon_minutes=horizon,
        cutoff=cutoff,
        through=through,
        settled_at=now_ms,
    )
    fingerprint_data: dict[str, object] = {
        "inputs": inputs.model_dump(mode="json"),
        "feature": feature.model_dump(mode="json"),
        "horizon": horizon,
    }

    def unavailable(
        status: str, reason: str
    ) -> tuple[OutcomeRow, tuple[MinuteBar, ...], float | None]:
        return (
            OutcomeRow.model_validate(
                base
                | {
                    "status": status,
                    "reason": reason,
                    "input_fingerprint": content_digest(fingerprint_data | {"reason": reason}),
                }
            ),
            (),
            None,
        )

    if now_ms < through:
        return unavailable("pending", "horizon_pending")
    if feature.identity_status in ("invalid", "excluded") or feature.reference_key is None:
        return unavailable("unscorable", "reference_ineligible")
    if getattr(reader, "map_version", inputs.ranking_map_version) != inputs.ranking_map_version:
        return unavailable("unscorable", "map_changed")
    keys = getattr(reader, "reference_keys", ())
    if feature.reference_key not in keys and any(
        k.rsplit(":", 1)[0] == feature.reference_key.rsplit(":", 1)[0] for k in keys
    ):
        return unavailable("unscorable", "reference_revision_changed")
    baseline = tuple(reader.bars(feature.reference_key, after=cutoff - MINUTE, through=cutoff))
    fingerprint_data["baseline"] = [b.model_dump(mode="json") for b in baseline]
    if (
        len(baseline) != 1
        or baseline[0].reference_key != feature.reference_key
        or baseline[0].end != cutoff
    ):
        return unavailable("unscorable", "reference_baseline_unavailable")
    price = baseline[0].close
    bars = tuple(
        sorted(
            reader.bars(feature.reference_key, after=cutoff, through=through), key=lambda b: b.end
        )
    )
    fingerprint_data["bars"] = [b.model_dump(mode="json") for b in bars]
    if any(b.reference_key != feature.reference_key for b in bars):
        return unavailable("unscorable", "reference_revision_changed")
    if [b.end for b in bars] != list(range(cutoff + MINUTE, through + MINUTE, MINUTE)):
        return unavailable("unscorable", "future_bar_gap")
    max_return = max(abs(100 * (v / price - 1)) for b in bars for v in (b.high, b.low))
    close_return = 100 * (bars[-1].close / price - 1)
    return (
        OutcomeRow.model_validate(
            base
            | {
                "status": "ready",
                "reason": None,
                "max_abs_return": max_return,
                "close_return": close_return,
                "input_fingerprint": content_digest(fingerprint_data),
            }
        ),
        bars,
        price,
    )


def _native_outcome(
    inputs: InputReference,
    feature: FeatureSnapshotRow,
    reader: ReferenceBarReader,
    horizon: Literal[15, 60],
    now_ms: int,
) -> OutcomeRow:
    cutoff = outcome_cutoff(inputs.decision_at)
    through = cutoff + horizon * MINUTE
    base = dict(
        generation_id=inputs.generation_id,
        asset_id=feature.asset_id,
        reference_key=feature.reference_key,
        horizon_minutes=horizon,
        family="native",
        cutoff=cutoff,
        through=through,
        settled_at=now_ms,
    )
    status = "unscorable"
    reason = "native_minute_path_unavailable"
    points: tuple[NativeOutcomePoint, ...] = ()
    dispersion = None
    oi = None
    if now_ms < through:
        status, reason = "pending", "horizon_pending"
    elif feature.identity_status in ("invalid", "excluded"):
        reason = "native_ineligible"
    elif len({o.venue for o in feature.original_instrument_versions if o.current}) < 2:
        reason = "insufficient_native_venues"
    elif isinstance(reader, FixtureBarReader):
        points = tuple(
            sorted(
                reader.native_points(feature.asset_id, after=cutoff, through=through),
                key=lambda p: p.at,
            )
        )
        expected = {(o.instrument_id, o.version_id) for o in feature.original_instrument_versions}
        if reader.map_version != inputs.ranking_map_version:
            reason = "map_changed"
        elif [p.at for p in points] != list(range(cutoff + MINUTE, through + MINUTE, MINUTE)):
            reason = "native_minute_path_unavailable"
        elif any(
            {(o.instrument_id, o.version_id) for o in p.originals} != expected for p in points
        ):
            reason = "native_revision_changed"
        elif any(
            p.status != "ready"
            or len({o.venue for o in p.originals if o.current}) < 2
            or p.mark_dispersion_bps is None
            or (horizon == 60 and p.oi_change_abs is None)
            for p in points
        ):
            reason = "native_path_partial"
        else:
            dispersion = max(
                p.mark_dispersion_bps for p in points if p.mark_dispersion_bps is not None
            )
            oi = (
                max(p.oi_change_abs for p in points if p.oi_change_abs is not None)
                if horizon == 60
                else None
            )
            status, reason = "ready", None
    return OutcomeRow.model_validate(
        base
        | {
            "status": status,
            "reason": reason,
            "native_dispersion_max": dispersion,
            "oi_change_abs_max": oi,
            "input_fingerprint": content_digest(
                {
                    "inputs": inputs.model_dump(mode="json"),
                    "originals": [o.model_dump() for o in feature.original_instrument_versions],
                    "points": [p.model_dump(mode="json") for p in points],
                    "reason": reason,
                }
            ),
        }
    )


def settle_generation_outcomes(
    store: AttentionStore,
    ranking_store: ReferenceBarReader,
    *,
    generation_id: str,
    now_ms: int,
) -> tuple[OutcomeRow, ...]:
    matches = [g for g in store.evidence_generations() if g[0].generation_id == generation_id]
    if len(matches) != 1:
        raise ValueError("outcomes require one saved evidence generation")
    inputs, features, _ = matches[0]
    if now_ms < inputs.decision_at:
        raise ValueError("settlement clock precedes decision")
    results = []
    for horizon in (15, 60):
        reference = [
            (f, *_reference_outcome(inputs, f, ranking_store, horizon, now_ms)) for f in features
        ]
        ready = sorted(
            (
                r.max_abs_return
                for _, r, _, _ in reference
                if r.status == "ready" and r.max_abs_return is not None
            ),
            reverse=True,
        )
        threshold = ready[max(0, math.ceil(len(ready) * 0.1) - 1)] if ready else None
        # Threshold is fixed across this generation's full realized, scorable cross-section.
        for f, row, bars, price in reference:
            if row.status == "ready" and threshold is not None and price is not None:
                first = next(
                    (
                        b.end
                        for b in bars
                        if max(
                            abs(100 * (b.high / price - 1)),
                            abs(100 * (b.low / price - 1)),
                        )
                        >= threshold
                    ),
                    None,
                )
                row = row.model_copy(
                    update={
                        "time_to_top_decile_move": (first - inputs.decision_at) / 1000
                        if first is not None
                        else None,
                        "input_fingerprint": content_digest(
                            {"path": row.input_fingerprint, "topDecileThreshold": threshold}
                        ),
                    }
                )
            results.append(store.put_outcome(row))
            results.append(
                store.put_outcome(_native_outcome(inputs, f, ranking_store, horizon, now_ms))
            )
    return tuple(results)
