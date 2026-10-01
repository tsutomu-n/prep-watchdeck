"""Bounded, read-only native endpoint observation; publish only to isolated /tmp state.

Run with the existing market package environment. The configured application credential
is constrained by a read-only session; this does not certify a dedicated read-only role.
No production artifact, selection, note, schema, or collector state is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from dotenv import dotenv_values
from psycopg.rows import dict_row

from prep_watchdeck_market.artifacts import write_artifact_atomic
from prep_watchdeck_market.config import require_production_database_target
from prep_watchdeck_market.market_metrics import (
    METRICS_SQL,
    build_market_metrics,
    candle_cutoff,
)

TABLES = ("venue_instrument_versions", "latest_market_state", "market_state_1m", "candle_1m")
OPTIONS = (
    "-c default_transaction_read_only=on -c statement_timeout=5000 "
    "-c transaction_timeout=8000 -c lock_timeout=1000"
)
SELECT_CONTRACTS = """
SELECT venue_instrument_version_id, venue, source_symbol, base_asset
FROM (
    SELECT venue_instrument_version_id, venue, source_symbol, base_asset,
           row_number() OVER (
               PARTITION BY venue ORDER BY CASE base_asset
                   WHEN 'BTC' THEN 0 WHEN 'ETH' THEN 1 ELSE 2 END, source_symbol
           ) AS position
    FROM venue_instrument_versions
    WHERE valid_to IS NULL AND active = true AND base_asset IN ('BTC', 'ETH', 'SOL')
) candidates
WHERE position <= 3
ORDER BY venue, position
"""
CURRENT_VERSION_FILTER = "WHERE vi.valid_to IS NULL AND vi.active = true"
if METRICS_SQL.count(CURRENT_VERSION_FILTER) != 1:
    raise ValueError("metrics query changed; requalify the bounded endpoint probe")
BOUNDED_METRICS_SQL = METRICS_SQL.replace(
    CURRENT_VERSION_FILTER,
    "WHERE vi.valid_to IS NULL AND vi.active = true "
    "AND vi.venue_instrument_version_id = ANY(%s::bigint[])",
)
RECENT_CANDLES_SQL = """
SELECT venue_instrument_version_id, bucket_at, close_price, finality, source_at, observed_at
FROM candle_1m
WHERE venue_instrument_version_id = ANY(%s::bigint[])
  AND bucket_at >= %s AND bucket_at < %s
ORDER BY venue_instrument_version_id, bucket_at
"""


def isolated_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    temporary_root = Path("/tmp").resolve()
    forbidden = (
        Path.home() / ".local/share/prep-watchdeck-market",
        Path.home() / ".local/share/prep-watchdeck-ranking",
        Path("/home/tn/releases"),
    )
    if path == temporary_root or not path.is_relative_to(temporary_root):
        raise ValueError("isolated output must be a dedicated directory below /tmp")
    for live in forbidden:
        live = live.resolve()
        if path.is_relative_to(live) or live.is_relative_to(path):
            raise ValueError("isolated output overlaps live state or release")
    return path


def encode(value: Any) -> str:
    def convert(item: Any) -> str:
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError("unsupported evidence type")

    return json.dumps(value, default=convert, allow_nan=False, ensure_ascii=False, sort_keys=True)


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encode(value) + "\n", encoding="utf-8")
    temporary.replace(path)


def calculations(rows: list[dict[str, Any]], artifact: Any) -> list[dict[str, Any]]:
    checks = []
    for raw, projected in zip(rows, artifact.rows, strict=True):
        for family, windows in (("oi", ("15m", "1h")), ("trade", ("15m", "1h", "24h"))):
            values = projected.oi_change if family == "oi" else projected.trade_change
            for window in windows:
                metric = values[window]
                if family == "oi":
                    baseline, current = raw[f"oi_{window}_base"], raw["l_oi_base"]
                    unit = "base"
                else:
                    baseline, current = raw[f"c_{window}_close"], raw["c_end_close"]
                    unit = raw["quote_asset"]
                exact = None
                agrees = metric.value is None
                if metric.availability == "available":
                    if baseline is None or current is None or Decimal(baseline) <= 0:
                        raise ValueError("available projection lacks an independent baseline")
                    exact = Decimal(100) * (Decimal(current) / Decimal(baseline) - Decimal(1))
                    agrees = math.isclose(float(exact), metric.value, rel_tol=1e-10, abs_tol=1e-8)
                    if not agrees:
                        raise ValueError("native endpoint arithmetic differs from projection")
                checks.append(
                    {
                        "identity": projected.venue_instrument_id,
                        "version": projected.venue_instrument_version_id,
                        "family": family,
                        "window": window,
                        "unit": unit,
                        "availability": metric.availability,
                        "reason": metric.reason_code,
                        "baselineDecimal": baseline,
                        "currentDecimal": current,
                        "independentPercentDecimal": exact,
                        "projectedPercent": metric.value,
                        "agrees": agrees,
                    }
                )
    return checks


def derive_arrivals(samples_path: Path, versions: list[int]) -> list[dict[str, Any]]:
    """Bound arrival conservatively when snapshot acquisition time is unknown."""
    arrivals: dict[tuple[int, datetime], dict[str, Any]] = {}
    last_absent: dict[tuple[int, datetime], tuple[datetime, datetime]] = {}
    if not samples_path.exists():
        return []
    for line in samples_path.read_text(encoding="utf-8").splitlines():
        sample = json.loads(line)
        started = datetime.fromisoformat(sample["readStartedAt"])
        finished = datetime.fromisoformat(sample["readFinishedAt"])
        minute = started.replace(second=0, microsecond=0)
        present = {
            (c["venue_instrument_version_id"], datetime.fromisoformat(c["bucket_at"])): c
            for c in sample["recentCandles"]
        }
        for version in versions:
            for delta in (2, 1):
                bucket = minute - timedelta(minutes=delta)
                key = (version, bucket)
                if key not in present:
                    last_absent[key] = (started, finished)
                    continue
                if key in arrivals:
                    continue
                candle = present[key]
                end_at = bucket + timedelta(minutes=1)
                previous = last_absent.get(key)
                arrivals[key] = {
                    "version": version,
                    "bucketAt": bucket,
                    "bucketEndAt": end_at,
                    "firstSeenByProbeAt": finished,
                    "lastAbsentQueryStartedAt": None if previous is None else previous[0],
                    "lastAbsentQueryFinishedAt": None if previous is None else previous[1],
                    "censoredAtFirstObservation": previous is None,
                    "arrivalLowerSeconds": None
                    if previous is None
                    else (previous[0] - end_at).total_seconds(),
                    "arrivalUpperSeconds": (finished - end_at).total_seconds(),
                    "snapshotTimeUnknownWithinQueryInterval": True,
                    "sourceAt": candle["source_at"],
                    "observedAt": candle["observed_at"],
                    "finality": candle["finality"],
                    "closeDecimal": candle["close_price"],
                    "databaseCommitTime": None,
                }
    return list(arrivals.values())


def summarize_samples(
    samples_path: Path, arrivals: list[dict[str, Any]], manifest: dict[str, Any]
) -> dict[str, Any]:
    samples = (
        [json.loads(line) for line in samples_path.read_text().splitlines()]
        if samples_path.exists()
        else []
    )

    def distribution(values: list[float]) -> dict[str, Any]:
        ordered = sorted(values)
        return {
            "count": len(ordered),
            "minimum": ordered[0] if ordered else None,
            "p50": statistics.median(ordered) if ordered else None,
            "p95": ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None,
            "maximum": ordered[-1] if ordered else None,
        }

    def metric_counts(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str, str], Counter[str]] = {}
        for check in checks:
            key = (check["identity"].split(":", 1)[0], check["family"], check["window"])
            counts = groups.setdefault(key, Counter())
            counts["denominator"] += 1
            counts["availableNumerator"] += check["availability"] == "available"
            if check["reason"]:
                counts[check["reason"]] += 1
        return [
            {"venue": key[0], "family": key[1], "window": key[2], **dict(counts)}
            for key, counts in sorted(groups.items())
        ]

    checks = [check for sample in samples for check in sample["calculations"]]
    last = samples[-1] if samples else {"calculations": [], "readStartedAt": None}
    previous: dict[tuple[str, str, str], tuple[str, str | None]] = {}
    transitions = []
    for sample in samples:
        for check in sample["calculations"]:
            key = (check["identity"], check["family"], check["window"])
            current = (check["availability"], check["reason"])
            if key in previous and previous[key] != current:
                transitions.append(
                    {
                        "sample": sample["sample"],
                        "readStartedAt": sample["readStartedAt"],
                        "identity": key[0],
                        "family": key[1],
                        "window": key[2],
                        "before": previous[key],
                        "after": current,
                    }
                )
            previous[key] = current
    bounded = [arrival for arrival in arrivals if not arrival["censoredAtFirstObservation"]]
    censored = [arrival for arrival in arrivals if arrival["censoredAtFirstObservation"]]
    return {
        "status": manifest["status"],
        "sampleCount": len(samples),
        "uniqueIdentities": len({check["identity"] for check in checks}),
        "availableArithmeticMatches": sum(check["availability"] == "available" for check in checks),
        "missingNullChecks": sum(check["availability"] != "available" for check in checks),
        "allProjectionChecksAgree": all(check["agrees"] for check in checks),
        "queryReadSeconds": distribution(
            [
                (
                    datetime.fromisoformat(sample["readFinishedAt"])
                    - datetime.fromisoformat(sample["readStartedAt"])
                ).total_seconds()
                for sample in samples
            ]
        ),
        "minimumObservedIntervalSeconds": manifest.get("minimumObservedIntervalSeconds"),
        "sampleCountsPerVenueMetric": metric_counts(checks),
        "lastCountsPerVenueMetric": metric_counts(last["calculations"]),
        "lastReadStartedAt": last["readStartedAt"],
        "lastIdentityMetricStates": last["calculations"],
        "availabilityTransitions": transitions,
        "identitiesWithAvailabilityChanges": sorted({change["identity"] for change in transitions}),
        "arrivals": {
            "observations": len(arrivals),
            "withPriorAbsenceCount": len(bounded),
            "withPriorAbsenceLowerSeconds": distribution(
                [arrival["arrivalLowerSeconds"] for arrival in bounded]
            ),
            "withPriorAbsenceUpperSeconds": distribution(
                [arrival["arrivalUpperSeconds"] for arrival in bounded]
            ),
            "initiallyPresentCensoredCount": len(censored),
            "initiallyPresentCensoredLowerSeconds": None,
            "initiallyPresentCensoredUpperSeconds": distribution(
                [arrival["arrivalUpperSeconds"] for arrival in censored]
            ),
            "percentileMethod": "p50 median; p95 nearest rank; commit time itself is unknown",
            "scope": "up to 3 current contracts per venue; last 2 completed minutes per sample",
        },
        "databaseCommitTime": "not_observed",
        "providerAvailableTime": "not_observed",
        "dedicatedReadOnlyRole": "not_established",
        "productionWrites": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--seconds", type=int, default=360)
    arguments = parser.parse_args()
    state = isolated_path(arguments.state_dir)
    evidence = isolated_path(arguments.evidence_dir)
    if state.is_relative_to(evidence) or evidence.is_relative_to(state):
        raise ValueError("state and evidence must use separate sibling directories")
    if not 0 <= arguments.seconds <= 360:
        raise ValueError("observation duration must be between 0 and 360 seconds")
    evidence.mkdir(parents=True, exist_ok=True)
    samples_path = evidence / "samples.jsonl"
    if samples_path.exists():
        raise ValueError("evidence already exists; use a new directory")
    manifest = {
        "startedAt": datetime.now(UTC),
        "status": "running",
        "productionWrites": False,
        "credentialScope": "existing application credential constrained by read-only session",
        "dedicatedReadOnlyRole": "not_established",
        "connectionLimit": 1,
        "contractsPerVenueLimit": 3,
        "minimumIntervalSeconds": 5,
        "durationLimitSeconds": arguments.seconds,
        "statementTimeoutMilliseconds": 5000,
        "transactionTimeoutMilliseconds": 8000,
        "candleLagSeconds": 180,
        "candleMaximumAgeSeconds": 300,
        "databaseCommitLatency": "not_observed",
        "sourceScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    write_json(evidence / "manifest.json", manifest)
    versions: list[int] = []
    availability: Counter[str] = Counter()
    sample_count = 0
    first_mono = time.monotonic()
    last_started: float | None = None
    minimum_interval: float | None = None
    try:
        # Parse internally; never copy the URL or environment contents into evidence/logs.
        settings = dotenv_values(arguments.env_file)
        database_url = settings.get("PREP_WATCHDECK_MARKET_DATABASE_URL")
        if not database_url:
            raise ValueError("configured database URL is missing")
        require_production_database_target(database_url)
        with psycopg.connect(
            database_url,
            options=OPTIONS,
            application_name="prep-watchdeck-pf02-read-only-probe",
            connect_timeout=5,
            autocommit=True,
            row_factory=dict_row,
        ) as connection:
            target = connection.execute(
                "SELECT current_database() AS database, inet_server_addr()::text AS address, "
                "inet_server_port() AS internal_port, "
                "current_setting('transaction_read_only') AS read_only, "
                "current_setting('default_transaction_read_only') AS default_read_only"
            ).fetchone()
            if (
                target is None
                or target["database"] != "prep_watchdeck_market"
                or target["read_only"] != "on"
                or target["default_read_only"] != "on"
            ):
                raise ValueError("database read-only preflight failed")
            # A container can expose external 55432 while its server reports internal 5432.
            manifest["databaseTarget"] = {
                "configuredHost": "127.0.0.1",
                "configuredPort": 55432,
                "database": target["database"],
                "serverReportedAddress": target["address"],
                "serverInternalPort": target["internal_port"],
                "sessionReadOnly": True,
            }
            permissions = connection.execute(
                "SELECT name, has_table_privilege(current_user, name, 'SELECT') AS can_select "
                "FROM unnest(%s::text[]) AS name",
                (list(TABLES),),
            ).fetchall()
            if not all(item["can_select"] for item in permissions):
                raise ValueError("required read permission is unavailable")
            manifest["selectPrivileges"] = permissions
            contracts = connection.execute(SELECT_CONTRACTS).fetchall()
            if not contracts or any(
                count > 3 for count in Counter(c["venue"] for c in contracts).values()
            ):
                raise ValueError("bounded current contracts are unavailable")
            versions = [item["venue_instrument_version_id"] for item in contracts]
            manifest["contracts"] = contracts
            write_json(evidence / "manifest.json", manifest)
            while True:
                started_mono = time.monotonic()
                if last_started is not None:
                    interval = started_mono - last_started
                    minimum_interval = (
                        interval if minimum_interval is None else min(minimum_interval, interval)
                    )
                last_started = started_mono
                now = datetime.now(UTC)
                cutoff = candle_cutoff(now)
                minute = now.replace(second=0, microsecond=0)
                with connection.transaction():
                    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    rows = connection.execute(
                        BOUNDED_METRICS_SQL, (*((cutoff,) * 4), versions)
                    ).fetchall()
                    candles = connection.execute(
                        RECENT_CANDLES_SQL,
                        (versions, minute - timedelta(minutes=2), minute),
                    ).fetchall()
                finished_at = datetime.now(UTC)
                artifact = build_market_metrics(rows, now=now)
                checks = calculations(rows, artifact)
                availability.update(
                    f"{c['family']}:{c['availability']}:{c['reason']}" for c in checks
                )
                write_artifact_atomic(state / "artifacts/market-metrics.json", artifact)
                with samples_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        encode(
                            {
                                "sample": sample_count,
                                "readStartedAt": now,
                                "readFinishedAt": finished_at,
                                "elapsedSeconds": time.monotonic() - started_mono,
                                "generationId": artifact.generation_id,
                                "candleCutoff": cutoff,
                                "nativeRows": rows,
                                "calculations": checks,
                                "recentCandles": candles,
                            }
                        )
                        + "\n"
                    )
                sample_count += 1
                if sample_count == 1:
                    print(
                        encode(
                            {"event": "projection_ready", "contracts": len(contracts), "sample": 1}
                        ),
                        flush=True,
                    )
                elapsed = time.monotonic() - first_mono
                if elapsed >= arguments.seconds:
                    break
                delay = max(0, 5 - (time.monotonic() - started_mono))
                remaining = arguments.seconds - (time.monotonic() - first_mono)
                if remaining <= delay:
                    time.sleep(max(0, remaining))
                    break
                time.sleep(delay)
        manifest["status"] = "pass"
    except Exception as error:
        # Exception messages can include DSNs or connection contents; retain class only.
        manifest["status"] = "blocked"
        manifest["failureClass"] = type(error).__name__
        print(encode({"event": "probe_stopped", "failureClass": type(error).__name__}), flush=True)
    arrivals = derive_arrivals(samples_path, versions)
    manifest.update(
        {
            "finishedAt": datetime.now(UTC),
            "sampleCount": sample_count,
            "elapsedSeconds": time.monotonic() - first_mono,
            "minimumObservedIntervalSeconds": minimum_interval,
            "availabilityCounts": dict(availability),
            "arrivalObservations": len(arrivals),
            "arrivalIntervalsWithPriorAbsence": sum(
                not a["censoredAtFirstObservation"] for a in arrivals
            ),
        }
    )
    write_json(evidence / "arrivals.json", arrivals)
    write_json(evidence / "manifest.json", manifest)
    write_json(evidence / "summary.json", summarize_samples(samples_path, arrivals, manifest))
    print(encode({"event": "complete", **manifest}), flush=True)
    return 0 if manifest["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
