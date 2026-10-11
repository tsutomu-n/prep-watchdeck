#!/usr/bin/env python3
"""Measure explicit local state roots without collecting, pruning or repairing data."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

GIB = 1024**3
DAY = 86400


def measure(root: Path) -> dict[str, object]:
    categories = dict.fromkeys(("sqlite", "wal", "immutable", "archive", "other"), 0)
    unknown: list[str] = []

    def visit(path: Path) -> None:
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    current = Path(entry.path)
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
                            if entry.name.endswith(("-wal", "-shm"))
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
    }


def capacity_projection(samples: list[dict], *, staging_bytes: int = 0) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "not_validated",
        "days": 30,
        "observationDurationSeconds": 0,
        "reason": "insufficient_samples",
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
    if roots != set(last["stateBytes"]) or any(
        first["stateBytes"][key]["root"] != last["stateBytes"][key]["root"] for key in roots
    ):
        result["reason"] = "measurement_scope_changed"
        return result
    if not all(sample["measurementCoverage"] == "complete" for sample in samples):
        result["reason"] = "incomplete_measurement"
        return result
    growth = max(
        0,
        sum(
            last["stateBytes"][key]["knownBytes"] - first["stateBytes"][key]["knownBytes"]
            for key in roots
        ),
    )
    daily = growth * DAY / duration
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
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--staging-bytes", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    roots = {
        core: getattr(args, f"{core}_state").absolute()
        for core in ("market", "ranking", "attention")
    }
    for root in roots.values():
        if any(part.is_symlink() for part in (root, *root.parents)) or not root.is_dir():
            parser.error("state roots must be existing non-symlink directories")
    output = args.output.absolute()
    if (
        output.exists()
        or any(
            output.is_relative_to(root) or root.is_relative_to(output) for root in roots.values()
        )
        or args.staging_bytes < 0
    ):
        parser.error("output must be new and outside all state roots; staging cannot be negative")
    devices = {root.stat().st_dev for root in roots.values()}
    if len(devices) != 1:
        parser.error("this report requires all state roots on one measured filesystem")
    state = {core: measure(root) for core, root in roots.items()}
    fs = os.statvfs(roots["market"])
    report = {
        "schemaVersion": "runtime-capacity-v1",
        "sampledAt": datetime.now(UTC).isoformat(),
        "stateBytes": state,
        "filesystemAvailableBytes": fs.f_bavail * fs.f_frsize,
        "measurementCoverage": "complete"
        if all(value["complete"] for value in state.values())
        else "partial",
        "postgresLogicalBytes": None,
        "postgresLogicalStatus": "not_measured_by_filesystem_scan",
    }
    samples = [] if args.previous is None else [json.loads(args.previous.read_text())]
    report["projection"] = capacity_projection([*samples, report], staging_bytes=args.staging_bytes)
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
