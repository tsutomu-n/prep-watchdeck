"""Read-only freshness proof for an unchanged, reviewed original roster."""

import json
from datetime import datetime
from pathlib import Path

from .mapping import extract_roster
from .models import RankingMap


def check_roster(mapping: RankingMap, artifacts: Path, now: int) -> tuple[int | None, str | None]:
    """Only complete, recent catalog collection can renew observation time, never identity."""
    try:
        service_path = artifacts / "service-state.json"
        if service_path.stat().st_size > 1024 * 1024:
            raise ValueError("service_artifact_too_large")
        service = json.loads(service_path.read_text())
        roster = extract_roster(artifacts / "universe-snapshot.json")

        def timestamp(value: str, maximum_age: float = 1800) -> int:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None:
                raise ValueError("roster_time_without_timezone")
            observed = int(stamp.timestamp() * 1000)
            if not 0 <= now - observed <= min(maximum_age, 1800) * 1000:
                raise ValueError("roster_source_stale")
            return observed

        if (
            roster["sourceStatus"] != "ready"
            or roster["sourceQualityReasons"]
            or service["status"] != "ready"
            or service.get("qualityReasons")
            or service["catalog"]["status"] != "ready"
        ):
            raise ValueError("roster_source_incomplete")
        observed = timestamp(roster["generatedAt"])
        timestamp(service["generatedAt"])
        timestamp(service["catalog"]["latestAt"], service["catalog"]["maxAgeSeconds"])
        runs = [run for run in service["collectors"] if run["runKind"] == "catalog"]
        if (
            len(runs) != 1
            or runs[0]["status"] != "succeeded"
            or runs[0]["recordsReceived"] != len(roster["items"])
            or runs[0]["recordsWritten"] != len(roster["items"])
        ):
            raise ValueError("roster_catalog_incomplete")
        timestamp(runs[0]["completedAt"])
        if (
            roster["catalogFingerprint"] != mapping.roster_fingerprint
            or len(roster["items"]) != mapping.source_instrument_count
        ):
            raise ValueError("roster_identity_changed_requires_review")
        return observed, None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return None, str(exc)[:160]
