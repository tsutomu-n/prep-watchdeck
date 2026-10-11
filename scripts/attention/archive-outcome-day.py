"""Resume owned archive editions and catch up closed UTC days before Ranking retention."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from prep_watchdeck_attention.models import MINUTE
from prep_watchdeck_attention.outcome_export import DAY, export_outcome_input
from prep_watchdeck_attention.outcomes import FixtureBarReader, OutcomeBundle
from prep_watchdeck_attention.stable_files import read_stable_regular_file
from prep_watchdeck_attention.storage import atomic_json


class ArchiveWindowExpiredError(ValueError):
    """The retained source no longer covers this required closed day."""


class ArchiveCatchupError(ValueError):
    def __init__(self, completed: tuple[Path, ...], failures: tuple[dict, ...]) -> None:
        self.completed = completed
        self.failures = failures
        super().__init__(f"archive catchup incomplete: {len(failures)} expired day(s)")


def _roots(ranking: Path, attention: Path, archive: Path) -> tuple[Path, Path, Path]:
    if any(".." in path.parts for path in (ranking, attention, archive)):
        raise ValueError("input and output paths cannot contain parent traversal")
    ranking, attention, archive = (p.absolute() for p in (ranking, attention, archive))
    if any(p.is_symlink() for p in (archive, *archive.parents)) or any(
        archive == p or archive.is_relative_to(p) or p.is_relative_to(archive)
        for p in (ranking, attention)
    ):
        raise ValueError("archive must be disjoint from live state")
    archive.mkdir(parents=True, mode=0o700, exist_ok=True)
    return ranking, attention, archive


@contextmanager
def _archive_lock(archive: Path) -> Iterator[None]:
    fd = os.open(archive / ".archive.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _ledger(archive: Path) -> dict:
    path = archive / "archive-ledger.json"
    if path.exists():
        payload = json.loads(read_stable_regular_file(path, max_bytes=16 * 1024 * 1024))
        if payload.get("schemaVersion") != "attention-archive-ledger-v1":
            raise ValueError("archive ledger schema differs")
        return payload
    return {"schemaVersion": "attention-archive-ledger-v1", "days": {}}


def _record(archive: Path, day_ms: int, status: str, **details: object) -> None:
    ledger = _ledger(archive)
    ledger["days"][str(day_ms)] = {"status": status, **details}
    ledger["firstDayMs"] = min(day_ms, ledger.get("firstDayMs", day_ms))
    atomic_json(archive / "archive-ledger.json", ledger)


def _verified_completion(path: Path, day_ms: int) -> dict:
    raw = read_stable_regular_file(path, max_bytes=16 * 1024 * 1024)
    completion = json.loads(raw)
    if completion.get("status") != "COMPLETE" or completion.get("dayMs") != day_ms:
        raise ValueError("archive completion differs")
    proof = read_stable_regular_file(path.parent / "copy-manifest.json", max_bytes=16 * 1024 * 1024)
    if json.loads(proof).get("status") != "COMPLETE":
        raise ValueError("archive source copy is incomplete")
    for entry in completion["bundles"]:
        relative = Path(entry["bundle"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("archive bundle path escapes its edition")
        bundle = path.parent / relative
        data = read_stable_regular_file(bundle, max_bytes=16 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("archive bundle hash differs")
        manifest = OutcomeBundle.model_validate_json(data)
        if (
            manifest.map_version != entry["mapVersion"]
            or manifest.after_ms != day_ms
            or manifest.through_ms != day_ms + DAY
            or manifest.copy_manifest_sha256 != hashlib.sha256(proof).hexdigest()
        ):
            raise ValueError("archive bundle day/map/source differs")
        FixtureBarReader.from_file(bundle)
    return completion


def _sync_tree(root: Path) -> None:
    paths = list(root.rglob("*"))
    for path in paths:
        if path.is_symlink():
            raise ValueError("archive edition contains a symlink")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    for path in (root, root.parent):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _archive_day(ranking: Path, attention: Path, archive: Path, *, day_ms: int) -> Path:
    if day_ms <= 0 or day_ms % DAY or day_ms + DAY > int(time.time() * 1000):
        raise ValueError("archive requires a completed UTC day")
    day_root = archive / f"day-{day_ms}"
    if any(p.is_symlink() for p in (day_root, *day_root.parents)):
        raise ValueError("archive day cannot be a symlink")
    existing = [day_root / "archive-completion.json"]
    existing += sorted(day_root.glob("edition-*/archive-completion.json"), reverse=True)
    for completion in existing:
        if completion.exists():
            try:
                _verified_completion(completion, day_ms)
            except (OSError, ValueError) as error:
                _record(
                    archive, day_ms, "FAILED", errorType=type(error).__name__, reason=str(error)
                )
                raise
            _record(archive, day_ms, "COMPLETE", completion=str(completion.relative_to(archive)))
            return completion
    day_root.mkdir(mode=0o700, exist_ok=True)
    edition = 1
    while (day_root / f"edition-{edition:06d}").exists():
        edition += 1
    result = day_root / f"edition-{edition:06d}"
    result.mkdir(mode=0o700)
    _record(archive, day_ms, "INCOMPLETE", edition=str(result.relative_to(archive)))
    try:
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
        # Only temporary copies created by this invocation are removed on exit.
        with tempfile.TemporaryDirectory(prefix=".outcome-copy-", dir=archive) as scratch:
            copied = Path(scratch) / "copy"
            proof = module.copy_runtime_evidence(ranking, attention, copied, deadline_seconds=1200)
            with sqlite3.connect(
                f"{(copied / 'attention.sqlite3').as_uri()}?mode=ro&immutable=1", uri=True
            ) as conn:
                maps = {
                    row[0]
                    for row in conn.execute(
                        "SELECT DISTINCT json_extract(inputs,'$.rankingMapVersion') "
                        "FROM input_generations WHERE evidence=1 AND decision_at>? AND decision_at<=?",
                        (day_ms - 60 * MINUTE, day_ms + DAY),
                    )
                }
                count = conn.execute(
                    "SELECT COUNT(*) FROM input_generations WHERE evidence=1 "
                    "AND decision_at>? AND decision_at<=?",
                    (day_ms, day_ms + DAY),
                ).fetchone()[0]
                earliest = conn.execute(
                    "SELECT MIN(MAX(?, ((g.decision_at+?-1)/?)*?)) FROM feature_rows f "
                    "JOIN input_generations g ON g.id=f.generation_id "
                    "WHERE g.evidence=1 AND g.decision_at>? AND g.decision_at<=? "
                    "AND json_extract(f.payload,'$.referenceKey') IS NOT NULL",
                    (day_ms + MINUTE, MINUTE, MINUTE, MINUTE, day_ms - 60 * MINUTE, day_ms + DAY),
                ).fetchone()[0]
            if any(not isinstance(value, str) or not value for value in maps):
                raise ValueError("day lacks exact saved map evidence")
            oldest = proof["rankingBarWindow"][0]
            if earliest is not None and (oldest is None or oldest > earliest):
                raise ArchiveWindowExpiredError(
                    "required Ranking bar window expired or unavailable; day not archived"
                )
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
                # Verification is part of publication, not a later hopeful read.
                FixtureBarReader.from_file(output)
                bundles.append(
                    {
                        "mapVersion": map_version,
                        "bundle": str(output.relative_to(result)),
                        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                    }
                )
            with (result / "copy-manifest.json").open("xb") as stream:
                stream.write((copied / "copy-manifest.json").read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            _sync_tree(result)
            completion = result / "archive-completion.json"
            atomic_json(
                completion,
                {
                    "status": "COMPLETE",
                    "completedAt": datetime.now(UTC).isoformat(),
                    "currentRankingMapVersion": proof["rankingMapVersion"],
                    "dayMs": day_ms,
                    "bundles": bundles,
                    "evidenceGenerations": count,
                    "sourceCopyMethod": "sqlite_online_backup",
                    "temporaryCopiesRetained": False,
                    "crossDatabaseTransaction": False,
                },
            )
            _verified_completion(completion, day_ms)
            _record(archive, day_ms, "COMPLETE", completion=str(completion.relative_to(archive)))
            return completion
    except Exception as error:
        _record(
            archive,
            day_ms,
            "FAILED",
            edition=str(result.relative_to(archive)),
            errorType=type(error).__name__,
            reason=str(error),
        )
        raise


def archive_day(ranking: Path, attention: Path, archive: Path, *, day_ms: int) -> Path:
    ranking, attention, archive = _roots(ranking, attention, archive)
    with _archive_lock(archive):
        return _archive_day(ranking, attention, archive, day_ms=day_ms)


def archive_closed_days(
    ranking: Path, attention: Path, archive: Path, *, through_day_ms: int | None = None
) -> tuple[Path, ...]:
    ranking, attention, archive = _roots(ranking, attention, archive)
    last = int(time.time() * 1000) // DAY * DAY - DAY if through_day_ms is None else through_day_ms
    with _archive_lock(archive):
        with sqlite3.connect(
            f"{(attention / 'attention.sqlite3').as_uri()}?mode=ro", uri=True
        ) as conn:
            first = conn.execute(
                "SELECT MIN(decision_at) FROM input_generations WHERE evidence=1"
            ).fetchone()[0]
        ledger = _ledger(archive)
        days = [
            int(path.name.removeprefix("day-"))
            for path in archive.glob("day-*")
            if path.is_dir() and path.name.removeprefix("day-").isdigit()
        ]
        starts = days + ([(first - 1) // DAY * DAY] if first is not None else [])
        if "firstDayMs" in ledger:
            starts.append(ledger["firstDayMs"])
        if not starts:
            raise ValueError("no saved evidence or archive checkpoint for catchup")
        # Preserve failed days while still rescuing later, recoverable windows.
        completed = []
        failures = []
        for day in range(min(starts), last + DAY, DAY):
            try:
                completed.append(_archive_day(ranking, attention, archive, day_ms=day))
            except ArchiveWindowExpiredError as error:
                failures.append({"dayMs": day, "status": "FAILED", "reason": str(error)})
        if failures:
            raise ArchiveCatchupError(tuple(completed), tuple(failures))
        return tuple(completed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranking-state", type=Path, required=True)
    parser.add_argument("--attention-state", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--day-ms", type=int, help="explicit single completed UTC day")
    args = parser.parse_args()
    try:
        if args.day_ms is not None:
            result = [
                archive_day(
                    args.ranking_state, args.attention_state, args.archive, day_ms=args.day_ms
                )
            ]
        else:
            result = archive_closed_days(args.ranking_state, args.attention_state, args.archive)
    except ArchiveCatchupError as error:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "completedDays": [str(p) for p in error.completed],
                    "failedDays": error.failures,
                }
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"status": "COMPLETE", "days": [str(path) for path in result]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
