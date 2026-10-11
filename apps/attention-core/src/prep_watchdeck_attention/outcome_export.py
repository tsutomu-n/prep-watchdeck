"""Immutable offline outcome fragments from authenticated, completed SQLite copies."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from prep_watchdeck_ranking.models import MinuteBar

from .models import MINUTE, FeatureSnapshotRow, outcome_cutoff
from .outcomes import NativeOutcomePoint, OutcomeBundle, OutcomeBundleFile, OutcomeInput
from .stable_files import read_stable_regular_file

MAX_FRAGMENT = 128 * 1024 * 1024
DAY = 1440 * MINUTE


def _digest(path: Path) -> str:
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("copy must be a regular non-symlink file")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write(path: Path, data: bytes) -> str:
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    digest = hashlib.sha256(data).hexdigest()
    if _digest(path) != digest:
        raise ValueError("export readback differs")
    return digest


def export_outcome_input(
    ranking_copy: Path,
    attention_copy: Path,
    output_root: Path,
    *,
    map_version: str,
    after_ms: int,
    through_ms: int,
) -> Path:
    if any(".." in path.parts for path in (ranking_copy, attention_copy, output_root)):
        raise ValueError("input and output paths cannot contain parent traversal")
    ranking, attention, output = (p.absolute() for p in (ranking_copy, attention_copy, output_root))
    if ranking.parent != attention.parent:
        raise ValueError("inputs must share a completed copy manifest")
    sources = [ranking.parent]
    for core in ("market", "ranking", "attention"):
        sources.append(
            Path(
                os.environ.get(
                    f"PREP_WATCHDECK_{core.upper()}_STATE_DIR",
                    Path.home() / f".local/share/prep-watchdeck-{core}",
                )
            ).absolute()
        )
    if any(".." in path.parts for path in sources):
        raise ValueError("state roots cannot contain parent traversal")
    if (
        output.exists()
        or any(p.is_symlink() for p in (output, *output.parents))
        or any(output == p or output.is_relative_to(p) or p.is_relative_to(output) for p in sources)
    ):
        raise ValueError("export must be new and disjoint from copies and live state")
    if any(ranking.is_relative_to(p) or attention.is_relative_to(p) for p in sources[1:]):
        raise ValueError("export cannot read a live database")
    if (
        type(after_ms) is not int
        or type(through_ms) is not int
        or not (
            0 < after_ms < through_ms
            and after_ms % MINUTE == through_ms % MINUTE == 0
            and through_ms - after_ms <= DAY
        )
    ):
        raise ValueError("export requires a closed minute-aligned window of at most 24h")
    proof_path = ranking.parent / "copy-manifest.json"
    proof = json.loads(read_stable_regular_file(proof_path, max_bytes=16 * 1024 * 1024))
    if proof.get("status") != "COMPLETE":
        raise ValueError("copy is incomplete")
    expected = {p: proof["files"][p.name]["sha256"] for p in (ranking, attention)}
    if any(_digest(p) != sha for p, sha in expected.items()):
        raise ValueError("copy hash differs")
    output.mkdir(parents=True, mode=0o700)
    fragments: list[OutcomeBundleFile] = []
    provenance: list[dict[str, object]] = []
    with (
        closing(sqlite3.connect(f"{ranking.as_uri()}?mode=ro&immutable=1", uri=True)) as rank,
        closing(sqlite3.connect(f"{attention.as_uri()}?mode=ro&immutable=1", uri=True)) as att,
    ):
        stored = rank.execute("SELECT value FROM metadata WHERE key='map'").fetchone()
        if stored is None:
            raise ValueError("copy map metadata is missing")
        source_map = json.loads(stored[0])["version"]
        evidence_maps = {
            row[0]
            for row in att.execute(
                "SELECT DISTINCT json_extract(inputs,'$.rankingMapVersion') FROM input_generations "
                "WHERE evidence=1 AND decision_at>? AND decision_at<=?",
                (after_ms - 60 * MINUTE, through_ms),
            )
        }
        if map_version not in evidence_maps:
            raise ValueError("export scope has no exact saved map generation")
        native_by_reference: dict[str, list[NativeOutcomePoint]] = defaultdict(list)
        reference_keys: set[str] = set()
        seen: set[tuple[str, int]] = set()
        for raw, generation_id in att.execute(
            "SELECT f.payload,g.id FROM feature_rows f "
            "JOIN input_generations g ON g.id=f.generation_id "
            "WHERE g.evidence=1 AND g.decision_at>? AND g.decision_at<=? "
            "AND json_extract(g.inputs,'$.rankingMapVersion')=? ORDER BY g.decision_at,f.asset_id",
            (after_ms - 60 * MINUTE, through_ms, map_version),
        ):
            row = FeatureSnapshotRow.model_validate_json(raw)
            if row.reference_key:
                reference_keys.add(row.reference_key)
            at = outcome_cutoff(row.decision_at)
            if not after_ms < at <= through_ms:
                continue
            key = (row.asset_id, at)
            if key in seen:
                raise ValueError("native availability minute has conflicting observations")
            seen.add(key)
            reference = row.reference_key or ""
            if row.reference_key:
                reference_keys.add(row.reference_key)
            mark, oi = row.mark_dispersion_bps, row.oi_change1h_median
            ready = (
                row.identity_status in {"ready", "partial"}
                and row.fresh_native_venue_count >= 2
                and mark.status == "ready"
                and mark.observed_at is not None
                and mark.value is not None
            )
            point = NativeOutcomePoint(
                asset_id=row.asset_id,
                at=at,
                originals=row.original_instrument_versions,
                mark_dispersion_bps=mark.value if ready else None,
                oi_change_abs=abs(oi.value)
                if oi.status == "ready" and oi.value is not None
                else None,
                status="ready" if ready else "unavailable",
            )
            native_by_reference[reference].append(point)
            provenance.append(
                {
                    "assetId": row.asset_id,
                    "at": at,
                    "generationId": generation_id,
                    "availableAt": row.decision_at,
                    "sourceFeatureSha256": hashlib.sha256(raw.encode()).hexdigest(),
                    "mark": mark.model_dump(mode="json", by_alias=True),
                    "oi": oi.model_dump(mode="json", by_alias=True),
                }
            )
        # A source copy may predate through_ms. Missing bars remain gaps at settlement.
        windows = range(after_ms // DAY * DAY, through_ms, DAY)
        for day in windows:
            lower, upper = max(after_ms, day), min(through_ms, day + DAY)
            keys = sorted(reference_keys)
            groups = [keys[index : index + 64] for index in range(0, len(keys), 64)]
            groups.append(
                [""]
            )  # Preserve ineligible/native-only assets without inventing references.
            for group_index, group in enumerate(groups):
                bars = []
                native = [
                    point
                    for reference in group
                    for point in native_by_reference[reference]
                    if lower < point.at <= upper
                ]
                for reference in group:
                    if not reference:
                        continue
                    records = rank.execute(
                        "SELECT end,open,high,low,close,quote_turnover FROM minute_bars "
                        "WHERE reference_key=? AND end>? AND end<=? ORDER BY end",
                        (reference, lower, upper),
                    )
                    bars.extend(
                        MinuteBar(
                            reference_key=reference,
                            end=end,
                            open=opened,
                            high=high,
                            low=low,
                            close=close,
                            quote_turnover=turnover,
                        )
                        for end, opened, high, low, close, turnover in records
                    )
                if not bars and not native:
                    continue
                data = OutcomeInput(
                    schema_version="attention-outcome-input-v1",
                    map_version=map_version,
                    bars=tuple(bars),
                    native=tuple(native),
                )
                raw = (data.model_dump_json(by_alias=True) + "\n").encode()
                if len(raw) > MAX_FRAGMENT:
                    raise ValueError("outcome fragment exceeds 128 MiB; narrow the export window")
                name = f"day-{day}-group-{group_index}.json"
                sha = _write(output / name, raw)
                fragments.append(
                    OutcomeBundleFile(
                        name=name,
                        sha256=sha,
                        reference_keys=tuple(sorted({b.reference_key for b in bars})),
                        asset_ids=tuple(sorted({p.asset_id for p in native})),
                        after_ms=lower,
                        through_ms=upper,
                    )
                )
    if any(_digest(p) != sha for p, sha in expected.items()):
        raise ValueError("copy hash changed during export")
    _write(
        output / "native-provenance.json",
        (
            json.dumps(
                {
                    "scope": "retained_five_minute_evidence_not_complete_native_minute_paths",
                    "rankingCopyCurrentMapVersion": source_map,
                    "exportedGenerationMapVersion": map_version,
                    "barIdentity": "exact_saved_reference_key_revision",
                    "availabilityRounding": "ceiling_preserves_original_clock",
                    "points": provenance,
                },
                separators=(",", ":"),
            )
            + "\n"
        ).encode(),
    )
    _write(
        output / "copy-manifest.json",
        read_stable_regular_file(proof_path, max_bytes=16 * 1024 * 1024),
    )
    manifest = OutcomeBundle(
        schema_version="attention-outcome-bundle-v1",
        map_version=map_version,
        after_ms=after_ms,
        through_ms=through_ms,
        copy_manifest_sha256=_digest(proof_path),
        files=tuple(fragments),
    )
    result = output / "outcome-bundle.json"
    _write(result, (manifest.model_dump_json(by_alias=True, indent=2) + "\n").encode())
    return result
