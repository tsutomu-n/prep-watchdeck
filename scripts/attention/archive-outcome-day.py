"""Archive a closed UTC day before Ranking retention expires, using owned temporary copies."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from prep_watchdeck_attention.outcome_export import DAY, export_outcome_input


def archive_day(ranking: Path, attention: Path, archive: Path, *, day_ms: int) -> Path:
    if day_ms <= 0 or day_ms % DAY or day_ms + DAY > int(time.time() * 1000):
        raise ValueError("archive requires a completed UTC day")
    ranking, attention, archive = (p.absolute() for p in (ranking, attention, archive))
    if any(p.is_symlink() for p in (archive, *archive.parents)) or any(
        archive == p or archive.is_relative_to(p) or p.is_relative_to(archive)
        for p in (ranking, attention)
    ):
        raise ValueError("archive must be disjoint from live state")
    archive.mkdir(parents=True, mode=0o700, exist_ok=True)
    result = archive / f"day-{day_ms}"
    if result.exists():
        raise ValueError("archive edition already exists; original is preserved")
    needed = sum(
        (p / name).stat().st_size
        for p, name in ((ranking, "ranking.sqlite3"), (attention, "attention.sqlite3"))
    )
    if shutil.disk_usage(archive).free < needed * 2 + 50 * 1024**3:
        raise ValueError("insufficient capacity for copies, exports and 50 GiB reserve")
    helper = Path(__file__).resolve().parents[1] / "ops/copy-runtime-evidence.py"
    spec = importlib.util.spec_from_file_location("runtime_evidence_copy", helper)
    if spec is None or spec.loader is None:
        raise ValueError("copy helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Only copies created inside this owned temporary directory are removed on exit.
    with tempfile.TemporaryDirectory(prefix=".outcome-copy-", dir=archive) as scratch:
        copied = Path(scratch) / "copy"
        proof = module.copy_runtime_evidence(ranking, attention, copied, deadline_seconds=1200)
        with sqlite3.connect(
            f"{(copied / 'attention.sqlite3').as_uri()}?mode=ro&immutable=1", uri=True
        ) as conn:
            maps = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT json_extract(inputs,'$.rankingMapVersion') FROM input_generations "
                    "WHERE evidence=1 AND decision_at>? AND decision_at<=?",
                    (day_ms, day_ms + DAY),
                )
            }
        if not maps or any(not isinstance(value, str) or not value for value in maps):
            raise ValueError("day lacks exact saved map evidence")
        result.mkdir(mode=0o700)
        bundles = []
        for map_version in sorted(maps):
            name = hashlib.sha256(map_version.encode()).hexdigest()
            output = export_outcome_input(
                copied / "ranking.sqlite3",
                copied / "attention.sqlite3",
                result / name,
                map_version=map_version,
                after_ms=day_ms,
                through_ms=day_ms + DAY,
            )
            bundles.append(
                {
                    "mapVersion": map_version,
                    "bundle": str(output.relative_to(result)),
                    "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                }
            )
        # Preserve the manifest authenticating source copies after their temporary lifecycle ends.
        (result / "copy-manifest.json").write_bytes((copied / "copy-manifest.json").read_bytes())
        completion = result / "archive-completion.json"
        completion.write_text(
            json.dumps(
                {
                    "status": "COMPLETE",
                    "completedAt": datetime.now(UTC).isoformat(),
                    "currentRankingMapVersion": proof["rankingMapVersion"],
                    "dayMs": day_ms,
                    "bundles": bundles,
                    "sourceCopyMethod": "sqlite_online_backup",
                    "temporaryCopiesRetained": False,
                    "crossDatabaseTransaction": False,
                },
                indent=2,
            )
            + "\n"
        )
        return completion


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranking-state", type=Path, required=True)
    parser.add_argument("--attention-state", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--day-ms", type=int, help="default: previous completed UTC day")
    args = parser.parse_args()
    day = args.day_ms if args.day_ms is not None else int(time.time() * 1000) // DAY * DAY - DAY
    print(archive_day(args.ranking_state, args.attention_state, args.archive, day_ms=day))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
