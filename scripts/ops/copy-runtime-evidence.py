#!/usr/bin/env python3
"""Online SQLite backups and generation-checked immutable Attention evidence copies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path


def regular(path: Path) -> None:
    if not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("expected a regular non-symlink input")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def online_backup(source: Path, destination: Path, deadline: float) -> dict[str, object]:
    regular(source)
    if destination.exists():
        raise ValueError("backup destination already exists")
    with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=5) as reader:
        reader.execute("PRAGMA query_only=ON")
        with sqlite3.connect(destination) as copy:
            os.chmod(destination, 0o600)

            def progress(_status: int, _remaining: int, _total: int) -> None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("SQLite backup deadline exceeded")

            reader.backup(copy, pages=512, progress=progress, sleep=0.05)
            if copy.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise ValueError("SQLite backup integrity check failed")
    return {
        "sha256": digest(destination),
        "bytes": destination.stat().st_size,
        "method": "sqlite_online_backup",
        "source": str(source),
    }


def copy_runtime_evidence(
    ranking: Path, attention: Path, output: Path, *, deadline_seconds: int = 600
) -> dict[str, object]:
    roots = [ranking.absolute(), attention.absolute()]
    target = output.absolute()
    if (
        deadline_seconds <= 0
        or any(
            target == root or target.is_relative_to(root) or root.is_relative_to(target)
            for root in roots
        )
        or any(part.is_symlink() for part in (target, *target.parents))
    ):
        raise ValueError("output must be new and disjoint from live inputs")
    files: dict[str, object] = {}
    previous = None
    if target.exists():
        regular(target / "copy-manifest.json")
        previous = json.loads((target / "copy-manifest.json").read_text())
        if previous.get("status") != "INCOMPLETE":
            raise ValueError("only an incomplete owned copy can be resumed")
        files = previous["files"]
        actual = {
            path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()
        }
        if actual != set(files) | {"copy-manifest.json"}:
            raise ValueError("incomplete copy contains undeclared files")
        for name, entry in files.items():
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("invalid checkpoint file")
            regular(target / name)
            if digest(target / name) != entry["sha256"]:
                raise ValueError("incomplete copy hash changed")
    else:
        target.mkdir(parents=True, mode=0o700)
    started = datetime.now(UTC).isoformat()
    deadline = time.monotonic() + deadline_seconds
    manifest: dict[str, object] = {
        "schemaVersion": "runtime-evidence-copy-v1",
        "startedAt": started,
        "status": "INCOMPLETE",
        "crossDatabaseTransaction": False,
        "files": {},
    }
    if previous is not None:
        manifest["startedAt"] = previous["startedAt"]
    try:
        for core, root in zip(("ranking", "attention"), roots, strict=True):
            name = f"{core}.sqlite3"
            if name in files:
                if files[name]["source"] != str(root / name):
                    raise ValueError("backup input identity changed")
            else:
                files[name] = online_backup(root / name, target / name, deadline)
        with sqlite3.connect(
            f"{(target / 'ranking.sqlite3').as_uri()}?mode=ro&immutable=1", uri=True
        ) as conn:
            stored_map = conn.execute("SELECT value FROM metadata WHERE key='map'").fetchone()
            if stored_map is None:
                raise ValueError("Ranking map missing from backup")
            mapping = json.loads(stored_map[0])
            manifest["rankingMapVersion"] = mapping["version"]
            manifest["rankingBarWindow"] = conn.execute(
                "SELECT MIN(end),MAX(end),COUNT(*) FROM minute_bars"
            ).fetchone()
            if "ranking-map.json" not in files:
                (target / "ranking-map.json").write_text(stored_map[0])
            os.chmod(target / "ranking-map.json", 0o600)
            files["ranking-map.json"] = {"sha256": digest(target / "ranking-map.json")}
        (target / "artifacts").mkdir(mode=0o700, exist_ok=True)
        maps: set[str] = set()
        count = 0
        with sqlite3.connect(
            f"{(target / 'attention.sqlite3').as_uri()}?mode=ro&immutable=1", uri=True
        ) as conn:
            manifest["attentionWindow"] = conn.execute(
                "SELECT MIN(decision_at),MAX(decision_at),COUNT(*) FROM input_generations"
            ).fetchone()
            for generation, raw in conn.execute(
                "SELECT id,response FROM input_generations ORDER BY id"
            ):
                if time.monotonic() >= deadline:
                    raise TimeoutError("immutable copy deadline exceeded")
                payload = json.loads(raw)
                maps.add(payload["inputs"]["rankingMapVersion"])
                name = hashlib.sha256(generation.encode()).hexdigest() + ".json"
                source = roots[1] / "artifacts" / name
                regular(source)
                data = source.read_bytes()
                if json.loads(data) != payload:
                    raise ValueError("immutable artifact and SQLite generation differ")
                destination = target / "artifacts" / name
                expected = hashlib.sha256(data).hexdigest()
                if not destination.exists():
                    with destination.open("xb") as stream:
                        os.chmod(destination, 0o600)
                        stream.write(data)
                if digest(destination) != expected:
                    raise ValueError("immutable artifact copy hash mismatch")
                files[f"artifacts/{name}"] = {"sha256": expected, "generationId": generation}
                count += 1
        manifest.update(
            status="COMPLETE",
            completedAt=datetime.now(UTC).isoformat(),
            attentionMapVersions=sorted(maps),
            immutableGenerations=count,
            files=files,
        )
    except (OSError, ValueError, TimeoutError, sqlite3.Error, KeyError) as error:
        manifest.update(errorType=type(error).__name__, files=files)
        raise
    finally:
        temporary = target / ".copy-manifest.tmp"
        with temporary.open("x") as stream:
            os.chmod(temporary, 0o600)
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, target / "copy-manifest.json")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranking-state", type=Path, required=True)
    parser.add_argument("--attention-state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=int, default=600)
    args = parser.parse_args()
    manifest = copy_runtime_evidence(
        args.ranking_state,
        args.attention_state,
        args.output,
        deadline_seconds=args.deadline_seconds,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": manifest["status"],
                "generations": manifest["immutableGenerations"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
