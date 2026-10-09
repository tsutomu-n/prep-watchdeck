"""Read-only, bounded checks for native data and the independent ranking service."""

import argparse
import ipaddress
import json
import math
import os
import re
import stat
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MAX_BYTES = 8 * 1024 * 1024
ARTIFACT_MAX_AGE = 120
RANKING_MAX_AGE = 150
MAX_IDENTITY_DIAGNOSTICS = 20
IDENTIFIER = re.compile(r"[A-Za-z0-9_:.-]{1,200}\Z")
VENUES = {"aster", "bitget", "hyperliquid", "mexc"}
AVAILABILITIES = {"available", "missing", "unsupported", "invalid"}
CODE = re.compile(r"[a-z][a-z0-9_]{0,99}\Z")


class InvalidInput(ValueError):
    """A supplied document cannot be safely interpreted."""


def object_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidInput("invalid_object")
    return value


def list_value(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise InvalidInput("invalid_list")
    return value


def integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidInput("invalid_count")
    return value


def instant(value: Any) -> datetime:
    try:
        if isinstance(value, int) and not isinstance(value, bool):
            result = datetime.fromtimestamp(value / 1000, UTC)
        elif isinstance(value, str):
            result = datetime.fromisoformat(value)
        else:
            raise InvalidInput("invalid_timestamp")
        if result.tzinfo is None or result.utcoffset() is None:
            raise InvalidInput("timestamp_without_timezone")
        return result.astimezone(UTC)
    except (ValueError, OverflowError, OSError):
        raise InvalidInput("invalid_timestamp") from None


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInput("duplicate_json_key")
        result[key] = value
    return result


def invalid_constant(_: str) -> None:
    raise InvalidInput("nonfinite_json_number")


def decode(raw: bytes) -> dict[str, Any]:
    try:
        return object_value(
            json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise InvalidInput("invalid_json") from None


def read_document(path: Path) -> dict[str, Any]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise InvalidInput("unsafe_or_oversized_file")
            raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise InvalidInput("oversized_file")
    except OSError:
        raise InvalidInput("file_unavailable") from None
    return decode(raw)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def health_url(base: str) -> str:
    try:
        url = urlsplit(base)
        if (
            url.scheme != "http"
            or url.username is not None
            or url.password is not None
            or url.path not in ("", "/")
            or url.query
            or url.fragment
            or not ipaddress.ip_address(url.hostname or "").is_loopback
            or (url.port is not None and not 1 <= url.port <= 65535)
        ):
            raise InvalidInput("ranking_url_must_be_loopback_http")
        return base.rstrip("/") + "/health"
    except ValueError:
        raise InvalidInput("ranking_url_must_be_loopback_http") from None


def get_health(url: str) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + 5
    with opener.open(url, timeout=5) as response:
        # Limit each read to the remaining deadline; do not follow redirects or use proxies.
        chunks = []
        size = 0
        while time.monotonic() < deadline:
            if response.fp is None:
                return decode(b"".join(chunks))
            response.fp.raw._sock.settimeout(max(0.001, deadline - time.monotonic()))
            chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                return decode(b"".join(chunks))
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise InvalidInput("oversized_ranking_response")
        raise TimeoutError("ranking_deadline")


def identity(row: dict[str, Any], *, original: bool = False) -> tuple[str, int]:
    name = "instrumentId" if original else "venueInstrumentId"
    version_name = "versionId" if original else "venueInstrumentVersionId"
    identifier = row.get(name)
    version = integer(row.get(version_name))
    venue = row.get("venue")
    if (
        not isinstance(identifier, str)
        or not 1 <= len(identifier) <= 200
        or version < 1
        or venue not in VENUES
        or not identifier.startswith(f"{venue}:")
    ):
        raise InvalidInput("invalid_identity")
    return identifier, version


def check(
    universe: dict[str, Any],
    service: dict[str, Any],
    metrics: dict[str, Any],
    mapping: dict[str, Any],
    ranking: dict[str, Any] | None,
    recovery: dict[str, dict[str, Any] | None],
    *,
    now: datetime,
) -> dict[str, Any]:
    failures: set[str] = set()
    warnings: set[str] = set()

    def freshness(value: Any, maximum: float, label: str) -> dict[str, Any]:
        age = (now - instant(value)).total_seconds()
        if age < 0:
            failures.add(f"{label}_future_timestamp")
        elif age > maximum:
            failures.add(f"{label}_stale")
        return {"ageSeconds": round(age, 3), "maximumSeconds": maximum}

    def artifact(document: dict[str, Any], label: str) -> dict[str, Any]:
        if document.get("schemaVersion") != 1:
            raise InvalidInput("unsupported_artifact_schema")
        result = freshness(document.get("generatedAt"), ARTIFACT_MAX_AGE, label)
        if label != "metrics":
            status = document.get("status")
            if status not in {"ready", "partial", "unavailable", "stale"}:
                raise InvalidInput("invalid_artifact_status")
            result["status"] = status
            if status in {"stale", "unavailable"}:
                failures.add(f"{label}_{status}")
            elif status == "partial":
                warnings.add(f"{label}_partial")
        return result

    artifact_states = {
        "universe": artifact(universe, "universe"),
        "service": artifact(service, "service"),
        "metrics": artifact(metrics, "metrics"),
    }
    if metrics.get("metricVersion") != "native-endpoints-v1":
        raise InvalidInput("unsupported_metric_version")
    artifact_states["candleCutoff"] = freshness(metrics.get("candleCutoff"), 300, "candle_cutoff")
    for component in ("catalog", "l1"):
        state = object_value(service.get(component))
        maximum = state.get("maxAgeSeconds")
        if not isinstance(maximum, (int, float)) or not math.isfinite(maximum) or maximum <= 0:
            raise InvalidInput("invalid_freshness_policy")
        status = state.get("status")
        if status not in {"ready", "partial", "unavailable", "stale"}:
            raise InvalidInput("invalid_freshness_status")
        artifact_states[component] = {"status": status}
        if state.get("latestAt") is not None:
            artifact_states[component].update(freshness(state["latestAt"], maximum, component))
        else:
            failures.add(f"{component}_unavailable")
        if status in {"stale", "unavailable"} or state.get("errorCode"):
            failures.add(f"{component}_unavailable")
        elif status == "partial":
            warnings.add(f"{component}_partial")
    collectors = list_value(service.get("collectors"))
    kinds = set()
    for value in collectors:
        collector = object_value(value)
        kind, status = collector.get("runKind"), collector.get("status")
        if kind not in {"catalog", "l1"} or kind in kinds:
            raise InvalidInput("invalid_or_duplicate_collector")
        kinds.add(kind)
        if status not in {"succeeded", "partial", "failed"}:
            raise InvalidInput("invalid_collector_status")
        if status == "failed":
            failures.add(f"collector_{kind}_failed")
        elif status == "partial":
            warnings.add(f"collector_{kind}_partial")
        integer(collector.get("recordsReceived"))
        integer(collector.get("recordsWritten"))
    if kinds != {"catalog", "l1"}:
        failures.add("collector_missing")
    published = {}
    for value in list_value(service.get("artifacts")):
        state = object_value(value)
        name, status = state.get("name"), state.get("status")
        if not isinstance(name, str) or name in published:
            raise InvalidInput("invalid_or_duplicate_artifact_file")
        if status not in {"ready", "unavailable"}:
            raise InvalidInput("invalid_artifact_file_status")
        published[name] = state
        if status == "unavailable":
            failures.add("core_artifact_unavailable")
    native_file = published.get("universe-snapshot.json")
    if native_file is None:
        failures.add("universe_publication_missing")
    elif native_file.get("generatedAt") != universe.get("generatedAt"):
        warnings.add("universe_publication_generation_changed")

    current = {}
    quality_counts: Counter[str] = Counter()
    venue_counts: Counter[str] = Counter()
    for value in list_value(universe.get("items")):
        item = object_value(value)
        key, version = identity(item)
        if key in current:
            raise InvalidInput("duplicate_universe_identity")
        if item.get("active") is not True or item.get("marketType") != "linear_perpetual":
            raise InvalidInput("unexpected_universe_scope")
        quality = item.get("quality")
        if quality not in {"ready", "partial", "unavailable", "stale"}:
            raise InvalidInput("invalid_universe_quality")
        current[key] = version
        quality_counts[quality] += 1
        venue_counts[item["venue"]] += 1
    if not current:
        failures.add("universe_empty")
    if quality_counts["stale"] or quality_counts["unavailable"]:
        failures.add("native_l1_unavailable")
    if quality_counts["partial"]:
        warnings.add("native_l1_partial")

    if mapping.get("schemaVersion") != "ranking-map-v2":
        raise InvalidInput("unsupported_mapping_schema")
    map_version = mapping.get("version")
    if not isinstance(map_version, str) or not IDENTIFIER.fullmatch(map_version):
        raise InvalidInput("invalid_mapping_version")
    originals = {}
    row_ids = set()
    statuses: Counter[str] = Counter()
    for value in list_value(mapping.get("rows")):
        row = object_value(value)
        row_id, status = row.get("id"), row.get("status")
        if not isinstance(row_id, str) or row_id in row_ids:
            raise InvalidInput("invalid_or_duplicate_mapping_row")
        row_ids.add(row_id)
        if status not in {"verified", "unsupported", "review", "out_of_scope"}:
            raise InvalidInput("invalid_mapping_status")
        statuses[status] += 1
        for value in list_value(row.get("originals")):
            key, version = identity(object_value(value), original=True)
            if key in originals:
                raise InvalidInput("duplicate_mapping_identity")
            originals[key] = version
    if integer(mapping.get("sourceInstrumentCount")) != len(originals):
        raise InvalidInput("mapping_count_mismatch")
    roster_age = (now - instant(mapping.get("rosterGeneratedAt"))).total_seconds()
    if roster_age < 0:
        failures.add("roster_future_timestamp")
    elif roster_age > 86400:
        warnings.add("roster_older_than_24h")
    connections = Counter(
        "removed"
        if key not in current
        else "versionMismatch"
        if version != current[key]
        else "matched"
        for key, version in originals.items()
    )
    connections["unmapped"] = len(current.keys() - originals.keys())
    identity_diagnostics = []
    for key in sorted(current.keys() | originals.keys()):
        mapped_version, current_version = originals.get(key), current.get(key)
        if mapped_version == current_version:
            continue
        if len(identity_diagnostics) >= MAX_IDENTITY_DIAGNOSTICS:
            break
        identity_diagnostics.append(
            {
                # Never echo arbitrary input text, error strings or URLs.
                "instrumentId": key if IDENTIFIER.fullmatch(key) else None,
                "mappedVersionId": mapped_version,
                "currentVersionId": current_version,
                "reason": "unmapped"
                if mapped_version is None
                else ("removed" if current_version is None else "versionMismatch"),
            }
        )
    if any(connections[key] for key in ("versionMismatch", "removed", "unmapped")):
        failures.add("ranking_original_identity_mismatch")
    if statuses["review"]:
        warnings.add("mapping_review_required")

    metric_counts: dict[str, dict[str, dict[str, Any]]] = {}
    seen = set()
    for value in list_value(metrics.get("rows")):
        row = object_value(value)
        key, version = identity(row)
        if key in seen:
            raise InvalidInput("duplicate_metric_identity")
        seen.add(key)
        if current.get(key) != version:
            failures.add("metric_identity_mismatch")
        counts = metric_counts.setdefault(row["venue"], {})
        for name, windows in (("tradeChange", {"15m", "1h", "24h"}), ("oiChange", {"15m", "1h"})):
            values = object_value(row.get(name))
            if set(values) != windows:
                raise InvalidInput("invalid_metric_windows")
            for window, raw_metric in values.items():
                metric = object_value(raw_metric)
                availability, reason = metric.get("availability"), metric.get("reasonCode")
                number = metric.get("value")
                if availability not in AVAILABILITIES:
                    raise InvalidInput("invalid_metric_availability")
                if availability == "available":
                    if (
                        isinstance(number, bool)
                        or not isinstance(number, (int, float))
                        or not math.isfinite(number)
                        or reason is not None
                    ):
                        raise InvalidInput("invalid_available_metric")
                elif (
                    number is not None or not isinstance(reason, str) or not CODE.fullmatch(reason)
                ):
                    raise InvalidInput("invalid_missing_metric")
                entry = counts.setdefault(f"{name}.{window}", {"availability": {}, "reasons": {}})
                bucket = entry["availability"]
                bucket[availability] = bucket.get(availability, 0) + 1
                if reason:
                    entry["reasons"][reason] = entry["reasons"].get(reason, 0) + 1
                    warnings.add("native_metric_unavailable")
                    if reason == "future_timestamp":
                        failures.add("metric_future_timestamp")
                for field in (
                    "startAt",
                    "endAt",
                    "startSourceAt",
                    "endSourceAt",
                    "startObservedAt",
                    "endObservedAt",
                ):
                    if metric.get(field) is not None and instant(metric[field]) > now:
                        failures.add("metric_future_timestamp")
    if seen != current.keys():
        failures.add("metric_identity_mismatch")

    ranking_state: dict[str, Any] = {"available": ranking is not None}
    running_map_version = None
    if ranking is None:
        failures.add("ranking_unavailable")
    else:
        status = ranking.get("status")
        if status not in {"running", "preparing"}:
            raise InvalidInput("invalid_ranking_status")
        ranking_state["status"] = status
        if status != "running" or ranking.get("cutoff") is None:
            failures.add("ranking_preparing")
        else:
            ranking_state.update(freshness(ranking["cutoff"], RANKING_MAX_AGE, "ranking"))
        running_map_version = ranking.get("mapVersion")
        if running_map_version is not None and (
            not isinstance(running_map_version, str)
            or not IDENTIFIER.fullmatch(running_map_version)
        ):
            raise InvalidInput("invalid_ranking_mapping_version")
        if running_map_version != map_version:
            failures.add("ranking_map_version_mismatch")
        if ranking.get("lastError"):
            failures.add("ranking_generation_failed")
        invalid_contracts = list_value(ranking.get("invalidContracts"))
        ranking_state["invalidContracts"] = len(invalid_contracts)
        if invalid_contracts:
            failures.add("ranking_reference_invalid")
        providers = object_value(ranking.get("providers"))
        if set(providers) != {"bybit", "binance"}:
            raise InvalidInput("invalid_ranking_providers")
        ranking_state["providers"] = {}
        for provider, value in providers.items():
            state = object_value(value)
            subscriptions = integer(state.get("subscriptions"))
            provider_connections = integer(state.get("connections"))
            pending = integer(state.get("backfill_pending"))
            ranking_state["providers"][provider] = {
                "subscriptions": subscriptions,
                "connections": provider_connections,
                "backfillPending": pending,
                "errorPresent": bool(state.get("last_error")),
            }
            if state.get("last_error"):
                failures.add(f"ranking_{provider}_provider_error")
            if subscriptions and not provider_connections:
                failures.add(f"ranking_{provider}_disconnected")
            if subscriptions and state.get("last_closed_at") is not None:
                ranking_state["providers"][provider]["streamFreshness"] = freshness(
                    state["last_closed_at"], RANKING_MAX_AGE, f"ranking_{provider}_stream"
                )
            elif subscriptions:
                warnings.add(f"ranking_{provider}_stream_not_observed")
            if pending:
                warnings.add(f"ranking_{provider}_backfill_pending")

    recovery_states = {}
    for name, document in recovery.items():
        if document is None:
            recovery_states[name] = {"available": False}
            warnings.add(f"{name}_state_not_observed")
            continue
        if document.get("schemaVersion") != 1:
            raise InvalidInput("unsupported_recovery_schema")
        execution = document.get("execution")
        if execution not in {"running", "succeeded", "partial", "failed"}:
            raise InvalidInput("invalid_recovery_execution")
        age = (now - instant(document.get("generatedAt"))).total_seconds()
        if age < 0:
            failures.add(f"{name}_future_timestamp")
        maximum = 180 if name == "endpointRecovery" else 1080
        if age > maximum:
            warnings.add(f"{name}_audit_stale")
        summary = object_value(document.get("summary"))
        summary_out = {}
        for field in (
            "targetCount",
            "scannedTargetCount",
            "httpRequests",
            "inserted",
            "failedTargets",
            "deferredTargets",
        ):
            summary_out[field] = integer(summary.get(field))
        for field in ("missingBefore", "newlyPresent", "remaining"):
            summary_out[field] = None if summary.get(field) is None else integer(summary[field])
        recovery_states[name] = {
            "available": True,
            "execution": execution,
            "ageSeconds": round(age, 3),
            "fresh": 0 <= age <= maximum,
            "summary": summary_out,
        }
        if execution == "failed":
            failures.add(f"{name}_failed")
        elif execution in {"partial", "running"} or summary_out["deferredTargets"]:
            warnings.add(f"{name}_incomplete")
        if summary_out["remaining"]:
            warnings.add(f"{name}_native_history_missing")

    return {
        "schemaVersion": "data-operations-v1",
        "checkedAt": now.isoformat(),
        "artifactFreshness": artifact_states,
        "nativeCounts": {
            "total": len(current),
            "byVenue": dict(venue_counts),
            "quality": dict(quality_counts),
        },
        "rankingMap": {
            "version": map_version,
            "runningVersion": running_map_version,
            "versionMatches": None if ranking is None else running_map_version == map_version,
            "identityDiagnostics": identity_diagnostics,
            "identityDiagnosticsTruncated": sum(
                connections[key] for key in ("versionMismatch", "removed", "unmapped")
            )
            > len(identity_diagnostics),
            "rosterAgeSeconds": round(roster_age, 3),
            "rosterStale": roster_age > 86400,
            "statuses": dict(statuses),
            "connections": {
                key: connections[key]
                for key in ("matched", "versionMismatch", "removed", "unmapped")
            },
        },
        "metricCounts": metric_counts,
        "ranking": ranking_state,
        "recovery": recovery_states,
        "operationalFailures": sorted(failures),
        "warnings": sorted(warnings),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-state-dir", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--ranking-url", default="http://127.0.0.1:8769")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    try:
        url = health_url(args.ranking_url)
        root = args.market_state_dir / "artifacts"
        universe = read_document(root / "universe-snapshot.json")
        service = read_document(root / "service-state.json")
        metrics = read_document(root / "market-metrics.json")
        try:
            mapping = read_document(args.mapping)
        except InvalidInput as error:
            if str(error) == "file_unavailable":
                raise InvalidInput("mapping_file_unavailable") from None
            raise
        recovery = {}
        for name, filename in (
            ("candleRecovery", "candle-recovery-state.json"),
            ("endpointRecovery", "candle-endpoint-recovery-state.json"),
        ):
            path = root / filename
            recovery[name] = read_document(path) if path.exists() or path.is_symlink() else None
        try:
            ranking = get_health(url)
        except (urllib.error.URLError, TimeoutError, OSError):
            ranking = None
        now = datetime.now(UTC)
        result = check(universe, service, metrics, mapping, ranking, recovery, now=now)
        code = 1 if result["operationalFailures"] else 0
    except InvalidInput as error:
        result = {
            "schemaVersion": "data-operations-v1",
            "checkedAt": now.isoformat(),
            "operationalFailures": [],
            "warnings": [],
            "inputErrors": [str(error)],
        }
        code = 2
    result["exitCode"] = code
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    else:
        print(f"data-operations exit={code} checkedAt={result['checkedAt']}")
        for kind in ("operationalFailures", "warnings", "inputErrors"):
            for issue in result.get(kind, []):
                print(f"{kind}: {issue}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
