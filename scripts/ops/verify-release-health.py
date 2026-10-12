"""Read-only functional verification after release cutover or rollback."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

UNITS = {
    "prep-watchdeck-market.service": "apps/market-core",
    "prep-watchdeck-web.service": "apps/web",
    "prep-watchdeck-ranking.service": "",
    "prep-watchdeck-attention.service": "",
}


def instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(UTC)


def publication_blockers(artifact: dict[str, Any], *, after: datetime, now: datetime) -> list[str]:
    errors = []
    try:
        generated = instant(artifact.get("generatedAt"))
        if not after <= generated <= now or (now - generated).total_seconds() > 150:
            errors.append("market_artifact_stale")
        l1 = artifact.get("l1")
        if not isinstance(l1, dict):
            raise ValueError("L1 publication missing")
        latest = instant(l1.get("latestAt"))
        if (
            l1.get("status") != "ready"
            or l1.get("errorCode") is not None
            or not after <= latest <= now
            or (now - latest).total_seconds() > min(float(l1["maxAgeSeconds"]), 120)
        ):
            errors.append("market_l1_unhealthy")
        rows = artifact.get("collectors")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("collector publication invalid")
        cycles = [row for row in rows if row.get("runKind") == "l1"]
        if len(cycles) != 1:
            errors.append("market_l1_cycle_missing")
        else:
            row = cycles[0]
            started, completed = instant(row.get("startedAt")), instant(row.get("completedAt"))
            count = row.get("recordsWritten")
            if (
                row.get("status") != "succeeded"
                or row.get("errorCode") is not None
                or not after <= started <= completed <= generated
                or type(count) is not int
                or count <= 0
            ):
                errors.append("market_l1_cycle_unhealthy")
    except (ValueError, TypeError, KeyError, OverflowError):
        errors.append("market_publication_invalid")
    return errors


def binding_blockers(
    unit: str,
    properties: dict[str, str],
    *,
    release: Path,
    process_cwd: Path,
    argv: list[str],
) -> list[str]:
    expected = release / UNITS[unit]
    errors = []
    if (
        properties.get("ActiveState") != "active"
        or properties.get("SubState") != "running"
        or not properties.get("MainPID", "").isdigit()
        or int(properties.get("MainPID", "0")) <= 0
    ):
        errors.append("unit_inactive")
    if properties.get("WorkingDirectory") != str(expected):
        errors.append("configured_source_mismatch")
    executable_matches = any(arg.startswith(str(release) + "/") for arg in argv)
    if unit == "prep-watchdeck-web.service":
        executable_matches = (
            bool(argv)
            and Path(argv[0]).name == "bun"
            and argv[1:]
            == [
                "run",
                "start",
            ]
        )
    if process_cwd != expected or not executable_matches:
        errors.append("process_source_mismatch")
    return errors


def http_document(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise ValueError("HTTP health unavailable")
        raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("HTTP health document too large")
        value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("HTTP health document invalid")
    return value


def verify(release: Path, map_version: str, after: datetime) -> dict[str, Any]:
    unit_reports = {}
    blockers = []
    for unit in UNITS:
        try:
            raw = subprocess.check_output(
                [
                    "systemctl",
                    "--user",
                    "show",
                    unit,
                    "--property=ActiveState,SubState,MainPID,NRestarts,WorkingDirectory",
                ],
                text=True,
                timeout=10,
            )
            properties = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
            process = Path("/proc") / properties["MainPID"]
            cwd = Path(os.readlink(process / "cwd"))
            argv = [v.decode() for v in (process / "cmdline").read_bytes().split(b"\0") if v]
            errors = binding_blockers(unit, properties, release=release, process_cwd=cwd, argv=argv)
            unit_reports[unit] = {
                "properties": properties,
                "processCwd": str(cwd),
                "sourceBinding": "PASS" if not errors else "FAIL",
            }
            blockers.extend(f"{unit}:{error}" for error in errors)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            blockers.append(f"{unit}:process_observation_unavailable")
    documents = {}
    for name, url in (
        ("web", "http://127.0.0.1:5173/api/health"),
        ("ranking", "http://127.0.0.1:8769/health"),
        ("attention", "http://127.0.0.1:8770/health"),
    ):
        try:
            documents[name] = http_document(url)
        except (OSError, ValueError):
            blockers.append(f"{name}:http_health_unavailable")
    web, ranking, attention = (documents.get(name, {}) for name in ("web", "ranking", "attention"))
    now = datetime.now(UTC)
    if web.get("ok") is not True:
        blockers.append("web:health_failed")
    if (
        ranking.get("status") != "running"
        or ranking.get("mapVersion") != map_version
        or ranking.get("cycles", 0) <= 0
        or ranking.get("lastError") is not None
        or ranking.get("invalidContracts")
    ):
        blockers.append("ranking:health_failed")
    attempt = attention.get("lastAttemptAt")
    if (
        attention.get("status") not in {"ready", "partial"}
        or attention.get("cycles", 0) <= 0
        or attention.get("providerRequests") != 0
        or attention.get("mode") != "shadow_only"
        or type(attempt) is not int
        or not 0 <= now.timestamp() * 1000 - attempt <= 150_000
    ):
        blockers.append("attention:health_failed")
    try:
        market = json.loads(
            (
                Path.home() / ".local/share/prep-watchdeck-market/artifacts/service-state.json"
            ).read_text()
        )
        if not isinstance(market, dict):
            raise ValueError("market publication invalid")
        now = datetime.now(UTC)
        blockers.extend(publication_blockers(market, after=after, now=now))
        documents["market"] = market
    except (OSError, ValueError, TypeError):
        blockers.append("market:artifact_unavailable")
    return {
        "schemaVersion": "release-functional-health-v1",
        "checkedAt": now.isoformat(),
        "expectedRelease": str(release),
        "mapVersion": map_version,
        "freshAfter": after.isoformat(),
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "units": unit_reports,
        "health": documents,
        "scope": "functional_health_not_complete_data_or_long_term_acceptance",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-release", type=Path, required=True)
    parser.add_argument("--map-version", required=True)
    parser.add_argument("--after", type=instant)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(
        args.expected_release.absolute(),
        args.map_version,
        args.after or datetime.now(UTC) - timedelta(seconds=150),
    )
    if args.output is not None:
        path = args.output.absolute()
        protected = [
            Path.home() / ".local/share" / f"prep-watchdeck-{name}"
            for name in ("market", "ranking", "attention", "outcome-archive")
        ]
        protected.append(args.expected_release.absolute())
        if (
            ".." in path.parts
            or any(p.is_symlink() for p in (path, *path.parents))
            or any(path == root or path.is_relative_to(root) for root in protected)
        ):
            parser.error("output must be a new regular file outside runtime states")
        with path.open("x") as stream:
            os.chmod(path, 0o600)
            json.dump(report, stream, indent=2)
            stream.write("\n")
    print(json.dumps({key: report[key] for key in ("status", "blockers", "checkedAt")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
