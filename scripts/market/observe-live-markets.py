"""Observe public loopback artifacts and mirror their unchanged values into isolated state.

This observer issues GET requests only. Its first-seen timestamps describe artifact
delivery, never database visibility or commit time. It does not operate any service.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ARTIFACTS = {
    "universe": "universe-snapshot.json",
    "chart": "market-chart.json",
    "selected": "selected-market.json",
    "service": "service-state.json",
}
MAX_BYTES = 32 * 1024 * 1024


class ObservationError(Exception):
    def __init__(self, code: str, status: int | None = None, url: str | None = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.url = url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ObservationError("redirect_rejected", code)


def stamp() -> str:
    return datetime.now(UTC).isoformat()


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def timestamp(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.timestamp()
    except (AttributeError, TypeError, ValueError) as cause:
        raise ObservationError("invalid_timestamp") from cause


def assert_isolated(path: Path) -> None:
    protected = (
        Path.home() / ".local/share/prep-watchdeck-market",
        Path.home() / ".local/share/prep-watchdeck-ranking",
        Path.home() / "releases",
    )
    for root in protected:
        resolved = root.resolve()
        if path == resolved or path.is_relative_to(resolved) or resolved.is_relative_to(path):
            raise ValueError("output must be outside production state and releases")


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def get_json(opener, url: str, budget_seconds: float) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    try:
        with opener.open(url, timeout=max(0.1, min(8.0, budget_seconds))) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ObservationError("response_size_limit")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ObservationError("invalid_response_shape")
            return value, {
                "url": url,
                "httpStatus": response.status,
                "receivedAt": stamp(),
                "latencyMs": round((time.monotonic() - started) * 1000, 3),
                "responseBytes": len(raw),
                "responseSha256": hashlib.sha256(raw).hexdigest(),
            }
    except urllib.error.HTTPError as cause:
        raise ObservationError("http_error", cause.code, url) from cause
    except (urllib.error.URLError, TimeoutError, OSError) as cause:
        raise ObservationError("http_unavailable", url=url) from cause
    except (json.JSONDecodeError, UnicodeDecodeError) as cause:
        raise ObservationError("invalid_response_json", url=url) from cause


def validate_bundle(bundle: dict[str, Any], received_at: float) -> dict[str, Any]:
    if set(bundle) != set(ARTIFACTS):
        raise ObservationError("invalid_bundle_keys")
    ages = {}
    for key, value in bundle.items():
        if not isinstance(value, dict) or value.get("schemaVersion") != 1:
            raise ObservationError("unsupported_artifact_schema")
        age = received_at - timestamp(value.get("generatedAt"))
        maximum = 15 if key == "selected" else 120
        ages[key] = {"seconds": round(age, 3), "maximumSeconds": maximum}
        if abs(age) > maximum:
            raise ObservationError(f"{key}_artifact_stale")
    universe = bundle["universe"]
    if not isinstance(universe.get("items"), list):
        raise ObservationError("invalid_universe_items")
    identities = []
    for item in universe["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("venueInstrumentId"), str):
            raise ObservationError("invalid_universe_identity")
        version = item.get("venueInstrumentVersionId")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ObservationError("invalid_universe_version")
        identities.append(item["venueInstrumentId"])
    if len(identities) != len(set(identities)):
        raise ObservationError("duplicate_universe_identity")
    states = {
        row.get("name"): row
        for row in bundle["service"].get("artifacts", [])
        if isinstance(row, dict)
    }
    for key in ("universe", "chart", "selected"):
        state = states.get(ARTIFACTS[key], {})
        if state.get("status") != "ready" or state.get("generatedAt") != bundle[key]["generatedAt"]:
            raise ObservationError("mixed_artifact_generation")
    return ages


def connection_counts(rows: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    by_venue: dict[str, Counter[str]] = {}
    multiple = 0
    for row in rows:
        matching_venues: Counter[str] = Counter()
        for original in row.get("originals", []):
            identifier = original.get("instrumentId")
            native = current.get(identifier)
            result = (
                "missing"
                if native is None
                else (
                    "version_mismatch"
                    if native["venueInstrumentVersionId"] != original.get("versionId")
                    else "matched"
                )
            )
            venue = original.get("venue", "unknown")
            counts[result] += 1
            by_venue.setdefault(venue, Counter())[result] += 1
            if result == "matched":
                matching_venues[venue] += 1
        multiple += any(count > 1 for count in matching_venues.values())
    return {
        "assetRows": len(rows),
        "originalLinks": sum(counts.values()),
        "connections": {key: counts[key] for key in ("matched", "version_mismatch", "missing")},
        "byVenue": {venue: dict(values) for venue, values in by_venue.items()},
        "sameVenueMultipleCurrentCandidateRows": multiple,
    }


def roster_summary(universe: dict[str, Any], mapping: dict[str, Any], ranking: dict[str, Any]):
    current = {
        item["venueInstrumentId"]: item
        for item in universe["items"]
        if item.get("active") is True and item.get("marketType") == "linear_perpetual"
    }
    rows = mapping["rows"]
    originals = {item["instrumentId"] for row in rows for item in row.get("originals", [])}
    ranked = [row for row in ranking.get("rows", []) if isinstance(row.get("rank"), int)]
    top = sorted(ranked, key=lambda row: row["rank"])[:20]
    return {
        "currentActiveContracts": len(current),
        "currentByVenue": dict(Counter(item["venue"] for item in current.values())),
        "mapVersion": mapping["version"],
        "mapRows": len(rows),
        "mapCryptoRows": sum(row.get("status") != "out_of_scope" for row in rows),
        "cryptoRowClassification": "map status other than out_of_scope; no symbol inference",
        "referenceSupportedRows": sum(
            row.get("status") == "verified" and row.get("reference") is not None for row in rows
        ),
        "referenceUnsupportedRows": sum(row.get("reference") is None for row in rows),
        "mappingStatuses": dict(Counter(row.get("status", "unknown") for row in rows)),
        "currentAdditionalNotInMap": len(current.keys() - originals),
        "all": connection_counts(rows, current),
        "top20": {
            "conditions": {
                key: ranking.get(key)
                for key in (
                    "period",
                    "order",
                    "minTurnover",
                    "cutoff",
                    "generationId",
                    "mapVersion",
                    "dailyReferenceJst",
                )
            },
            "assetIds": [row["id"] for row in top],
            **connection_counts(top, current),
        },
    }


def age_statistics(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "minimum": round(ordered[0], 3),
        "p50": round(ordered[math.ceil(len(ordered) * 0.5) - 1], 3),
        "p95": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        "maximum": round(ordered[-1], 3),
    }


def delivery_summary(universe, received_at, first_seen, previous_sample, selected_ids):
    now = timestamp(received_at)
    by_venue = {}
    probes = []
    for row in universe["items"]:
        if row.get("active") is not True:
            continue
        venue = row.get("venue", "unknown")
        stats = by_venue.setdefault(
            venue,
            {
                "rows": 0,
                "sourceMissing": 0,
                "observedMissing": 0,
                "sourceAges": [],
                "observedAges": [],
                "sourceToObserved": [],
                "qualities": Counter(),
            },
        )
        stats["rows"] += 1
        stats["qualities"][str(row.get("quality", "unknown"))] += 1
        source = timestamp(row["sourceAt"]) if row.get("sourceAt") else None
        observed = timestamp(row["observedAt"]) if row.get("observedAt") else None
        for name, value in (("source", source), ("observed", observed)):
            if value is None:
                stats[f"{name}Missing"] += 1
            else:
                stats[f"{name}Ages"].append(now - value)
        if source is not None and observed is not None:
            stats["sourceToObserved"].append(observed - source)
        identifier = row["venueInstrumentId"]
        if identifier not in selected_ids:
            continue
        revision = digest(
            {
                key: row.get(key)
                for key in (
                    "venueInstrumentVersionId",
                    "cycleAt",
                    "sourceAt",
                    "observedAt",
                    "sourcePayloadHash",
                )
            }
        )
        key = (identifier, revision)
        if key not in first_seen:
            first_seen[key] = {
                "firstSeenAt": received_at,
                "previousObservationAt": previous_sample,
                "leftCensored": previous_sample is None,
            }
        probes.append(
            {
                "venueInstrumentId": identifier,
                "venueInstrumentVersionId": row["venueInstrumentVersionId"],
                "sourceAt": row.get("sourceAt"),
                "observedAt": row.get("observedAt"),
                "cycleAt": row.get("cycleAt"),
                "sourcePayloadHash": row.get("sourcePayloadHash"),
                "artifactGeneratedAt": universe["generatedAt"],
                "artifactRowRevision": revision,
                **first_seen[key],
            }
        )
    for stats in by_venue.values():
        for key in ("sourceAges", "observedAges", "sourceToObserved"):
            stats[key + "Seconds"] = age_statistics(stats.pop(key))
        stats["qualities"] = dict(stats["qualities"])
    return {"byVenue": by_venue, "probes": probes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--web-port", type=int, default=5173)
    parser.add_argument("--ranking-port", type=int, default=8769)
    parser.add_argument("--duration-seconds", type=float, default=360)
    parser.add_argument("--interval-seconds", type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.duration_seconds <= 360 or not 5 <= args.interval_seconds <= 60:
        parser.error("duration must be 1..360s and interval 5..60s")
    if any(
        not 1024 <= port <= 65535 or port in (5432, 55432)
        for port in (args.web_port, args.ranking_port)
    ):
        parser.error("use explicit unprivileged loopback HTTP ports")
    state = args.state_dir.expanduser().resolve()
    evidence = args.evidence_dir.expanduser().resolve()
    assert_isolated(state)
    assert_isolated(evidence)
    if state.is_relative_to(evidence) or evidence.is_relative_to(state):
        parser.error("state and evidence directories must be separate")
    if any(
        (evidence / name).exists() for name in ("summary.json", "observations.jsonl", "ready.json")
    ):
        parser.error("evidence output already exists; choose a new directory")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (state / "artifacts").is_symlink():
        parser.error("isolated artifacts directory must not be a symlink")
    (state / "artifacts").mkdir(exist_ok=True, mode=0o700)
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    mapping_path = args.mapping.expanduser().resolve(strict=True)
    if mapping_path.stat().st_size > MAX_BYTES:
        parser.error("mapping exceeds size budget")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    bundle_url = f"http://127.0.0.1:{args.web_port}/api/market-data"
    ranking_url = f"http://127.0.0.1:{args.ranking_port}/rankings?period=15m&dailyReferenceJst=00%3A00&order=turnover&minTurnover=0"
    first_seen = {}
    selected_ids = set()
    previous_sample = None
    latest = None
    failures = Counter()
    samples = 0
    valid = 0
    started = stamp()
    deadline = time.monotonic() + args.duration_seconds
    descriptor = os.open(
        state / ".live-observer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w") as lock, (evidence / "observations.jsonl").open("x") as log:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while time.monotonic() < deadline:
            cycle_started = time.monotonic()
            samples += 1
            event = {"sample": samples, "startedAt": stamp(), "measurement": "artifact_delivery"}
            try:
                requests = []
                event["requests"] = requests
                for attempt in range(2):
                    before_map = mapping_path.read_bytes()
                    mapping = json.loads(before_map)
                    first, timing = get_json(opener, bundle_url, deadline - time.monotonic())
                    requests.append(timing)
                    ranking, timing = get_json(opener, ranking_url, deadline - time.monotonic())
                    requests.append(timing)
                    bundle, timing = get_json(opener, bundle_url, deadline - time.monotonic())
                    requests.append(timing)
                    if before_map == mapping_path.read_bytes() and digest(
                        first["universe"]
                    ) == digest(bundle["universe"]):
                        break
                else:
                    raise ObservationError("universe_or_mapping_changed")
                if not isinstance(mapping.get("rows"), list) or mapping.get(
                    "version"
                ) != ranking.get("mapVersion"):
                    raise ObservationError("adopted_map_version_mismatch")
                received_at = requests[-1]["receivedAt"]
                ages = validate_bundle(bundle, timestamp(received_at))
                if not selected_ids:
                    for venue in ("bitget", "hyperliquid", "aster", "mexc"):
                        rows = [
                            row
                            for row in bundle["universe"]["items"]
                            if row.get("active") and row.get("venue") == venue
                        ]
                        rows.sort(
                            key=lambda row: (
                                not bool(row.get("sourceAt") and row.get("observedAt")),
                                row["venueInstrumentId"],
                            )
                        )
                        selected_ids.update(row["venueInstrumentId"] for row in rows[:3])
                event.update(
                    {
                        "status": "observed",
                        "requests": requests,
                        "coherenceAttempts": attempt + 1,
                        "mapSha256": hashlib.sha256(before_map).hexdigest(),
                        "mapVersion": mapping["version"],
                        "artifactAges": ages,
                        "artifactGeneratedAt": {
                            key: value["generatedAt"] for key, value in bundle.items()
                        },
                        "artifactSha256": {key: digest(value) for key, value in bundle.items()},
                        "rankingSchemaVersion": ranking.get("schemaVersion"),
                        "rankingGenerationId": ranking.get("generationId"),
                        "pf01": roster_summary(bundle["universe"], mapping, ranking),
                        "delivery": delivery_summary(
                            bundle["universe"],
                            received_at,
                            first_seen,
                            previous_sample,
                            selected_ids,
                        ),
                    }
                )
                for key, filename in ARTIFACTS.items():
                    atomic_json(state / "artifacts" / filename, bundle[key])
                valid += 1
                previous_sample = received_at
                latest = event
                if valid == 1:
                    atomic_json(evidence / "initial-bundle.json", bundle)
                    atomic_json(evidence / "mapping.snapshot.json", mapping)
                    atomic_json(evidence / "initial-ranking.json", ranking)
                    atomic_json(
                        evidence / "ready.json",
                        {
                            "status": "ready",
                            "stateDir": str(state),
                            "receivedAt": received_at,
                            "measurement": "artifact_delivery",
                            "timestampsRewritten": False,
                            "mapVersion": mapping["version"],
                            "artifactSha256": event["artifactSha256"],
                        },
                    )
            except ObservationError as cause:
                failures[cause.code] += 1
                event.update(
                    {
                        "status": "unavailable",
                        "errorCode": cause.code,
                        "httpStatus": cause.status,
                        "failedUrl": cause.url,
                    }
                )
            except (KeyError, TypeError, ValueError) as cause:
                failures["invalid_shape"] += 1
                event.update(
                    {
                        "status": "unavailable",
                        "errorCode": "invalid_shape",
                        "errorType": type(cause).__name__,
                    }
                )
            log.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
            log.flush()
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(
                    min(
                        max(0, args.interval_seconds - (time.monotonic() - cycle_started)),
                        remaining,
                    )
                )
        summary = {
            "schemaVersion": 1,
            "status": "observed" if valid else "unavailable",
            "measurement": "artifact_delivery",
            "startedAt": started,
            "endedAt": stamp(),
            "stateDir": str(state),
            "mappingPath": str(mapping_path),
            "observerSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "durationSeconds": args.duration_seconds,
            "intervalSeconds": args.interval_seconds,
            "samples": samples,
            "validSamples": valid,
            "failures": dict(failures),
            "timestampsRewritten": False,
            "productionRequests": "GET only",
            "productionDatabaseAccess": False,
            "serviceOperations": False,
            "limitations": [
                "First-seen is artifact delivery, not database visibility or commit time.",
                "Finite samples do not establish long-term freshness or owner acceptance.",
                "Missing source timestamps and unmatched map versions remain missing.",
            ],
            "latest": latest,
        }
        atomic_json(evidence / "summary.json", summary)
        print(
            json.dumps(
                {
                    "status": summary["status"],
                    "validSamples": valid,
                    "samples": samples,
                    "failures": dict(failures),
                    "evidenceDir": str(evidence),
                }
            )
        )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
