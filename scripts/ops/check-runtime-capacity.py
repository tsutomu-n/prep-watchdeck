#!/usr/bin/env python3
"""Measure explicit local state roots without collecting, pruning or repairing data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

GIB = 1024**3
DAY = 86400
REQUIRED_SCOPES = {"market", "ranking", "attention", "postgres", "outcome_archive"}


def canonical_path(path: Path) -> Path:
    if ".." in path.parts:
        raise ValueError("paths cannot contain parent traversal")
    path = Path(os.path.abspath(path.expanduser()))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("paths and parents cannot be symlinks")
    return path


def intersect(left: Path, right: Path) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


def measure(root: Path, excluded: tuple[Path, ...] = ()) -> dict[str, object]:
    categories = dict.fromkeys(("sqlite", "wal", "immutable", "archive", "other"), 0)
    unknown: list[str] = []

    def visit(path: Path) -> None:
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    current = Path(entry.path)
                    if current in excluded:
                        continue
                    if entry.is_symlink():
                        unknown.append(str(current))
                    elif entry.is_dir(follow_symlinks=False):
                        visit(current)
                    elif entry.is_file(follow_symlinks=False):
                        relative = current.relative_to(root)
                        kind = (
                            "sqlite"
                            if entry.name.endswith(".sqlite3")
                            else "wal"
                            if entry.name.endswith(("-wal", "-shm")) or "pg_wal" in relative.parts
                            else "archive"
                            if "archive" in relative.parts
                            else "immutable"
                            if "artifacts" in relative.parts
                            else "other"
                        )
                        categories[kind] += entry.stat(follow_symlinks=False).st_size
        except OSError:
            unknown.append(str(path))

    visit(root)
    return {
        "root": str(root),
        "knownBytes": sum(categories.values()),
        "bytesByKind": categories,
        "complete": not unknown,
        "unknownPaths": unknown,
        "excludedRoots": [str(path) for path in excluded if path.is_relative_to(root)],
    }


def trusted_postgres(
    path: Path, *, root: Path, sampled_at: datetime, device: int
) -> dict[str, object]:
    path = canonical_path(path)
    if not path.is_file():
        raise ValueError("trusted supplement must be a regular file")
    raw = path.read_bytes()
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != "runtime-capacity-supplement-v1"
        or type(value.get("filesystemDevice")) is not int
        or value["filesystemDevice"] != device
        or not isinstance(value.get("sampledAt"), str)
    ):
        raise ValueError("trusted supplement schema or filesystem device differs")
    timestamp = datetime.fromisoformat(value["sampledAt"])
    if timestamp.utcoffset() is None or not 0 <= (sampled_at - timestamp).total_seconds() <= 60:
        raise ValueError("trusted supplement must match this sample within 60 seconds")
    measurements = value.get("measurements")
    if not isinstance(measurements, dict) or set(measurements) != {"postgres"}:
        raise ValueError("trusted supplement must measure the requested PostgreSQL root")
    entry = measurements["postgres"]
    if (
        not isinstance(entry, dict)
        or not isinstance(entry.get("root"), str)
        or canonical_path(Path(entry["root"])) != root
        or type(entry.get("knownBytes")) is not int
        or entry["knownBytes"] < 0
        or entry.get("complete") is not True
    ):
        raise ValueError("trusted PostgreSQL observation is incomplete or has a different root")
    return {
        "root": str(root),
        "knownBytes": entry["knownBytes"],
        "bytesByKind": {"postgres_physical_including_wal": entry["knownBytes"]},
        "complete": True,
        "unknownPaths": [],
        "measurementMethod": "explicitly_trusted_physical_observation",
        "sampledAt": value["sampledAt"],
        "supplementSha256": hashlib.sha256(raw).hexdigest(),
    }


def capacity_projection(samples: list[dict], *, staging_bytes: int = 0) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "not_validated",
        "days": 30,
        "observationDurationSeconds": 0,
        "reason": "insufficient_samples",
        "scope": "diagnostic_only",
        "assumptions": [
            "linear_net_growth_including_normal_maintenance",
            "outcome_growth_must_be_remeasured_after_activation",
        ],
    }
    if len(samples) < 2:
        return result
    first, last = samples[0], samples[-1]
    duration = (
        datetime.fromisoformat(last["sampledAt"]) - datetime.fromisoformat(first["sampledAt"])
    ).total_seconds()
    result["observationDurationSeconds"] = duration
    if duration <= 0:
        result["reason"] = "invalid_sample_period"
        return result
    roots = set(first["stateBytes"])
    if not REQUIRED_SCOPES.issubset(roots) or any(
        not REQUIRED_SCOPES.issubset(sample["stateBytes"]) for sample in samples
    ):
        result["reason"] = "incomplete_measurement_scope"
        return result
    if roots != set(last["stateBytes"]) or any(
        first["stateBytes"][key]["root"] != last["stateBytes"][key]["root"] for key in roots
    ):
        result["reason"] = "measurement_scope_changed"
        return result
    if first.get("filesystemDevice") != last.get("filesystemDevice"):
        result["reason"] = "measurement_filesystem_changed"
        return result
    if not all(sample["measurementCoverage"] == "complete" for sample in samples):
        result["reason"] = "incomplete_measurement"
        return result
    if not all(sample.get("stagingCoverage") == "complete" for sample in samples):
        result["reason"] = "incomplete_staging_scope"
        return result
    growth = max(
        0,
        sum(
            last["stateBytes"][key]["knownBytes"] - first["stateBytes"][key]["knownBytes"]
            for key in roots
        ),
    )
    daily = growth * DAY / duration
    staging_bytes = max(staging_bytes, int(last.get("stagingBytes", 0)))
    required = 50 * GIB + 30 * daily + staging_bytes
    result.update(
        netGrowthBytes=growth,
        dailyGrowthBytes=daily,
        projectedGrowthBytes=30 * daily,
        stagingBytes=staging_bytes,
        requiredAvailableBytes=required,
        sevenDayReserveSatisfied=last["filesystemAvailableBytes"] >= 50 * GIB + 7 * daily,
    )
    if duration < DAY:
        result.update(reason="sample_period_below_24h", scope="diagnostic_only")
    else:
        result.update(
            status="forecast"
            if last["filesystemAvailableBytes"] >= required
            else "insufficient_capacity",
            reason=None,
            scope="forecast_not_30day_measurement",
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for core in ("market", "ranking", "attention"):
        parser.add_argument(f"--{core}-state", type=Path, required=True)
    parser.add_argument("--postgres-root", type=Path)
    parser.add_argument("--outcome-archive", type=Path)
    parser.add_argument("--trusted-supplement", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--staging-bytes", type=int, default=0)
    parser.add_argument("--copy-staging-bytes", type=int, default=0)
    parser.add_argument("--export-staging-bytes", type=int)
    parser.add_argument("--restore-staging-bytes", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        roots = {
            core: canonical_path(getattr(args, f"{core}_state"))
            for core in ("market", "ranking", "attention")
        }
        for name, requested in (
            ("postgres", args.postgres_root),
            ("outcome_archive", args.outcome_archive),
        ):
            if requested is not None:
                roots[name] = canonical_path(requested)
        output = canonical_path(args.output)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    for root in roots.values():
        if root == Path(root.anchor) or not root.is_dir():
            parser.error("state roots must be existing non-symlink directories")
    core_roots = [roots[core] for core in ("market", "ranking", "attention")]
    if any(
        intersect(left, right)
        for index, left in enumerate(core_roots)
        for right in core_roots[index + 1 :]
    ):
        parser.error("core state roots must be disjoint")
    extras = [
        root for name, root in roots.items() if name not in {"market", "ranking", "attention"}
    ]
    if any(
        intersect(left, right) for index, left in enumerate(extras) for right in extras[index + 1 :]
    ) or any(root.is_relative_to(extra) for root in core_roots for extra in extras):
        parser.error("extra scopes cannot overlap each other or contain core state roots")
    if (
        output.exists()
        or any(intersect(output, root) for root in roots.values())
        or any(
            value < 0
            for value in (
                args.staging_bytes,
                args.copy_staging_bytes,
                args.export_staging_bytes or 0,
                args.restore_staging_bytes,
            )
        )
    ):
        parser.error("output must be new and outside all state roots; staging cannot be negative")
    devices = {root.stat().st_dev for root in roots.values()}
    if len(devices) != 1:
        parser.error("this report requires all state roots on one measured filesystem")
    device = devices.pop()
    sampled_at = datetime.now(UTC)
    try:
        pg = None
        if args.trusted_supplement is not None:
            if "postgres" not in roots:
                raise ValueError("trusted supplement requires --postgres-root")
            pg = trusted_postgres(
                args.trusted_supplement,
                root=roots["postgres"],
                sampled_at=sampled_at,
                device=device,
            )
        previous = None
        if args.previous is not None:
            previous = json.loads(canonical_path(args.previous).read_text())
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.error(str(error))
    state = {
        name: pg
        if name == "postgres" and pg is not None
        else measure(
            root,
            tuple(
                other for other in roots.values() if other != root and other.is_relative_to(root)
            ),
        )
        for name, root in roots.items()
    }
    copy_floor = sum(
        sum(state[core]["bytesByKind"].get(kind, 0) for kind in ("sqlite", "wal", "immutable"))
        for core in ("ranking", "attention")
    )
    staging = {
        "copy": max(copy_floor, args.copy_staging_bytes),
        "export": args.export_staging_bytes,
        "restore": max(
            copy_floor + (state.get("postgres") or {}).get("knownBytes", 0),
            args.restore_staging_bytes,
        ),
    }
    staging["additionalReserve"] = max(
        0, args.staging_bytes - sum(value for value in staging.values() if value is not None)
    )
    known_staging = sum(value for value in staging.values() if value is not None)
    fs = os.statvfs(roots["market"])
    report = {
        "schemaVersion": "runtime-capacity-v1",
        "sampledAt": sampled_at.isoformat(),
        "stateBytes": state,
        "filesystemDevice": device,
        "filesystemAvailableBytes": fs.f_bavail * fs.f_frsize,
        "measurementCoverage": "complete"
        if REQUIRED_SCOPES.issubset(state) and all(value["complete"] for value in state.values())
        else "partial",
        "missingScopes": sorted(REQUIRED_SCOPES - set(state)),
        "stagingCoverage": "complete" if args.export_staging_bytes is not None else "partial",
        "stagingBytesByKind": staging,
        "stagingBytes": known_staging if args.export_staging_bytes is not None else None,
        "knownStagingBytes": known_staging,
        "stagingAssumption": "simultaneous_copy_export_restore_with_measured_copy_restore_floors",
        "postgresLogicalBytes": None,
        "postgresLogicalStatus": "not_measured_by_filesystem_scan",
    }
    samples = [] if previous is None else [previous]
    report["projection"] = capacity_projection([*samples, report], staging_bytes=known_staging)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with output.open("x") as stream:
        os.chmod(output, 0o600)
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "output": str(output),
                "coverage": report["measurementCoverage"],
                "projection": report["projection"]["status"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
