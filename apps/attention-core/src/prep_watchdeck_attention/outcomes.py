"""Prospective settlement from explicitly supplied offline, closed reference bars."""

import hashlib
import json
import math
from collections import OrderedDict, defaultdict
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal, Protocol

from prep_watchdeck_ranking.models import MinuteBar
from pydantic import Field, model_validator

from .models import (
    MINUTE,
    AttentionResponse,
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
        timestamps = [bar.end for bar in data.bars] + [point.at for point in data.native]
        self._scope = (min(timestamps), max(timestamps)) if timestamps else None
        self.reference_keys = frozenset(bar.reference_key for bar in data.bars)
        grouped: dict[str, list[MinuteBar]] = defaultdict(list)
        for bar in data.bars:
            grouped[bar.reference_key].append(bar)
        self._bars = {
            key: tuple(sorted(values, key=lambda b: b.end)) for key, values in grouped.items()
        }
        native: dict[str, list[NativeOutcomePoint]] = defaultdict(list)
        for point in data.native:
            native[point.asset_id].append(point)
        self._native = {
            key: tuple(sorted(values, key=lambda p: p.at)) for key, values in native.items()
        }

    @classmethod
    def from_payload(cls, payload: object) -> "FixtureBarReader":
        return cls(OutcomeInput.model_validate(payload))

    @classmethod
    def from_file(cls, path: Path) -> "FixtureBarReader":
        from .stable_files import read_stable_regular_file

        if path.is_dir():
            return cls.from_archive(path)
        raw = read_stable_regular_file(path, max_bytes=128 * 1024 * 1024)
        if json.loads(raw).get("schemaVersion") == "attention-outcome-bundle-v1":
            return PartitionedFixtureBarReader(path, OutcomeBundle.model_validate_json(raw))
        return cls(OutcomeInput.model_validate_json(raw))

    @classmethod
    def from_files(cls, paths: Sequence[Path]) -> "FixtureBarReader":
        if not paths:
            raise ValueError("at least one offline outcome input is required")
        if len(paths) == 1:
            return cls.from_file(paths[0])
        readers = []
        for path in paths:
            reader = cls.from_file(path)
            if isinstance(reader, PartitionedFixtureBarReader):
                reader._cache.clear()
            readers.append(reader)
        return JoinedFixtureBarReader(tuple(readers))

    @classmethod
    def from_archive(cls, root: Path) -> "FixtureBarReader":
        from .stable_files import read_stable_regular_file

        if any(p.is_symlink() for p in (root, *root.parents)):
            raise ValueError("archive must not be a symlink")
        completions = sorted(root.glob("day-*/archive-completion.json"))
        completions += sorted(root.glob("day-*/edition-*/archive-completion.json"))
        completions += sorted(root.glob("edition-*/archive-completion.json"))
        if (root / "archive-completion.json").is_file():
            completions.append(root / "archive-completion.json")
        paths = []
        days: set[int] = set()
        # The most recent verified edition for each day is authoritative; older editions remain.
        for completion in reversed(sorted(completions)):
            payload = json.loads(read_stable_regular_file(completion, max_bytes=16 * 1024 * 1024))
            if payload.get("status") != "COMPLETE":
                continue
            day = payload["dayMs"]
            if day in days:
                continue
            days.add(day)
            for entry in payload["bundles"]:
                relative = Path(entry["bundle"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("archive bundle path escapes its edition")
                path = completion.parent / relative
                raw = read_stable_regular_file(path, max_bytes=16 * 1024 * 1024)
                if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                    raise ValueError("archive bundle hash differs")
                manifest = OutcomeBundle.model_validate_json(raw)
                if (
                    manifest.map_version != entry["mapVersion"]
                    or manifest.after_ms != day
                    or manifest.through_ms != day + 1440 * MINUTE
                ):
                    raise ValueError("archive bundle map differs")
                paths.append(path)
        return cls.from_files(paths)

    def for_generation(self, inputs: InputReference) -> "FixtureBarReader | None":
        cutoff = outcome_cutoff(inputs.decision_at)
        return (
            self
            if (
                inputs.ranking_map_version == self.map_version
                and self._scope is not None
                and self._scope[0] <= cutoff <= self._scope[1]
            )
            else None
        )

    def iter_generations(
        self, store: AttentionStore
    ) -> Iterator[tuple[InputReference, tuple[FeatureSnapshotRow, ...], AttentionResponse]]:
        if self._scope is None:
            return
        for generation in store.iter_evidence_generations(
            start_ms=self._scope[0] - MINUTE + 1, end_ms=self._scope[1] + 1
        ):
            if self.for_generation(generation[0]) is not None:
                yield generation

    def bars(self, reference_key: str, *, after: int, through: int) -> Sequence[MinuteBar]:
        return tuple(b for b in self._bars.get(reference_key, ()) if after < b.end <= through)

    def native_points(
        self, asset_id: str, *, after: int, through: int
    ) -> tuple[NativeOutcomePoint, ...]:
        return tuple(p for p in self._native.get(asset_id, ()) if after < p.at <= through)


class OutcomeBundleFile(Contract):
    name: str = Field(pattern=r"^[A-Za-z0-9._-]+\.json$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_keys: tuple[str, ...]
    asset_ids: tuple[str, ...]
    after_ms: int
    through_ms: int


class OutcomeBundle(Contract):
    schema_version: Literal["attention-outcome-bundle-v1"]
    map_version: str
    after_ms: int
    through_ms: int
    copy_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    files: tuple[OutcomeBundleFile, ...] = Field(min_length=1, max_length=2048)


class PartitionedFixtureBarReader(FixtureBarReader):
    """Bounded fragments form one input, so settlement cannot erase other fragments."""

    def __init__(self, path: Path, manifest: OutcomeBundle) -> None:
        from .stable_files import read_stable_regular_file

        self.map_version = manifest.map_version
        self.manifest = manifest
        proof = path.parent / "copy-manifest.json"
        if not proof.exists():
            proof = path.parent.parent / "copy-manifest.json"
        raw = read_stable_regular_file(proof, max_bytes=16 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != manifest.copy_manifest_sha256:
            raise ValueError("outcome copy manifest hash differs")
        if json.loads(raw).get("status") != "COMPLETE":
            raise ValueError("outcome source copy is incomplete")
        self._directory = path.parent
        self._reference_files: dict[str, list[OutcomeBundleFile]] = defaultdict(list)
        self._native_files: dict[str, list[OutcomeBundleFile]] = defaultdict(list)
        self._cache: OrderedDict[Path, FixtureBarReader] = OrderedDict()
        names: set[str] = set()
        for entry in manifest.files:
            if entry.name in names:
                raise ValueError("duplicate outcome fragment")
            names.add(entry.name)
            reader = self._load(entry)
            if reader.map_version != self.map_version or reader.reference_keys != set(
                entry.reference_keys
            ):
                raise ValueError("outcome fragment reference binding differs")
            if set(reader._native) != set(entry.asset_ids):
                raise ValueError("outcome fragment native binding differs")
            if not manifest.after_ms <= entry.after_ms < entry.through_ms <= manifest.through_ms:
                raise ValueError("outcome fragment window differs")
            if any(
                not entry.after_ms < bar.end <= entry.through_ms for bar in reader.data.bars
            ) or any(
                not entry.after_ms < point.at <= entry.through_ms for point in reader.data.native
            ):
                raise ValueError("outcome fragment contains a point outside its window")
            for keys, index in (
                (entry.reference_keys, self._reference_files),
                (entry.asset_ids, self._native_files),
            ):
                for key in keys:
                    if any(
                        old.after_ms < entry.through_ms and entry.after_ms < old.through_ms
                        for old in index[key]
                    ):
                        raise ValueError("overlapping identity across outcome fragments")
                    index[key].append(entry)
        self.reference_keys = frozenset(self._reference_files)

    def for_generation(self, inputs: InputReference) -> "FixtureBarReader | None":
        return (
            self
            if (
                inputs.ranking_map_version == self.map_version
                and self.manifest.after_ms < inputs.decision_at <= self.manifest.through_ms
            )
            else None
        )

    def iter_generations(
        self, store: AttentionStore
    ) -> Iterator[tuple[InputReference, tuple[FeatureSnapshotRow, ...], AttentionResponse]]:
        for generation in store.iter_evidence_generations(
            start_ms=self.manifest.after_ms + 1, end_ms=self.manifest.through_ms + 1
        ):
            if self.for_generation(generation[0]) is not None:
                yield generation

    def _load(self, entry: OutcomeBundleFile) -> FixtureBarReader:
        from .stable_files import read_stable_regular_file

        cache_key = self._directory / entry.name
        if cache_key not in self._cache:
            raw = read_stable_regular_file(
                self._directory / entry.name, max_bytes=128 * 1024 * 1024
            )
            if hashlib.sha256(raw).hexdigest() != entry.sha256:
                raise ValueError("outcome fragment hash differs")
            self._cache[cache_key] = FixtureBarReader(OutcomeInput.model_validate_json(raw))
            if len(self._cache) > 2:
                self._cache.popitem(last=False)
        self._cache.move_to_end(cache_key)
        return self._cache[cache_key]

    def bars(self, reference_key: str, *, after: int, through: int) -> Sequence[MinuteBar]:
        return tuple(
            sorted(
                (
                    bar
                    for entry in self._reference_files.get(reference_key, ())
                    if entry.after_ms < through and after < entry.through_ms
                    for bar in self._load(entry).bars(reference_key, after=after, through=through)
                ),
                key=lambda b: b.end,
            )
        )

    def native_points(
        self, asset_id: str, *, after: int, through: int
    ) -> tuple[NativeOutcomePoint, ...]:
        return tuple(
            sorted(
                (
                    point
                    for entry in self._native_files.get(asset_id, ())
                    if entry.after_ms < through and after < entry.through_ms
                    for point in self._load(entry).native_points(
                        asset_id, after=after, through=through
                    )
                ),
                key=lambda p: p.at,
            )
        )


class JoinedFixtureBarReader(FixtureBarReader):
    """Compose authenticated day inputs without mixing map or reference revisions."""

    def __init__(self, readers: tuple[FixtureBarReader, ...]) -> None:
        if any(not isinstance(reader, PartitionedFixtureBarReader) for reader in readers):
            raise ValueError("multiple inputs require window-bound outcome bundles")
        self._readers = readers
        self.reference_keys = frozenset(key for reader in readers for key in reader.reference_keys)
        cache: OrderedDict[Path, FixtureBarReader] = OrderedDict()
        for reader in readers:
            if isinstance(reader, PartitionedFixtureBarReader):
                reader._cache.clear()
                reader._cache = cache
        self.map_version = ""  # Settlement always selects an exact map below.

    def for_generation(self, inputs: InputReference) -> "FixtureBarReader | None":
        if not any(reader.for_generation(inputs) is not None for reader in self._readers):
            return None
        readers = tuple(
            reader for reader in self._readers if reader.map_version == inputs.ranking_map_version
        )
        scoped = JoinedFixtureBarReader.__new__(JoinedFixtureBarReader)
        scoped._readers = readers
        scoped.reference_keys = frozenset(
            key for reader in readers for key in reader.reference_keys
        )
        scoped.map_version = inputs.ranking_map_version
        return scoped

    def iter_generations(
        self, store: AttentionStore
    ) -> Iterator[tuple[InputReference, tuple[FeatureSnapshotRow, ...], AttentionResponse]]:
        windows = [
            reader.manifest
            for reader in self._readers
            if isinstance(reader, PartitionedFixtureBarReader)
        ]
        for generation in store.iter_evidence_generations(
            start_ms=min(window.after_ms for window in windows) + 1,
            end_ms=max(window.through_ms for window in windows) + 1,
        ):
            if any(reader.for_generation(generation[0]) is not None for reader in self._readers):
                yield generation

    def bars(self, reference_key: str, *, after: int, through: int) -> Sequence[MinuteBar]:
        points = {}
        for reader in self._readers:
            for bar in reader.bars(reference_key, after=after, through=through):
                old = points.get(bar.end)
                if old is not None and old != bar:
                    raise ValueError("conflicting archived reference evidence; select one edition")
                points[bar.end] = bar
        return tuple(points[key] for key in sorted(points))

    def native_points(
        self, asset_id: str, *, after: int, through: int
    ) -> tuple[NativeOutcomePoint, ...]:
        points = {}
        for reader in self._readers:
            for point in reader.native_points(asset_id, after=after, through=through):
                old = points.get(point.at)
                if old is not None and old != point:
                    raise ValueError("conflicting archived native evidence; select one edition")
                points[point.at] = point
        return tuple(points[key] for key in sorted(points))


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
    inputs, features, _ = store.evidence_generation(generation_id)
    if isinstance(ranking_store, FixtureBarReader):
        scoped = ranking_store.for_generation(inputs)
        if scoped is None:
            return ()
        ranking_store = scoped
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
