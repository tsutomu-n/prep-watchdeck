"""Catalog identity and freshness are independent of native price quality."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .mapping import extract_roster
from .models import CATALOG_MAX_AGE_MS, RankingMap, RosterHealth, RosterStatus


class RosterSourceError(ValueError):
    def __init__(self, status: RosterStatus) -> None:
        super().__init__(f"roster_{status}")
        self.status = status


def check_catalog(roster: dict[str, Any], service: dict[str, Any], now: int) -> int:
    """Prove a complete catalog without treating L1-only warnings as listing failures."""
    if service["catalog"]["status"] == "stale":
        raise RosterSourceError("source_stale")
    if (
        roster["sourceStatus"] not in ("ready", "partial")
        or set(roster.get("sourceQualityReasons", [])) - {"contains_non_ready_instruments"}
        or service["status"] not in ("ready", "partial")
        or set(service.get("qualityReasons", [])) - {"l1_partial", "l1_stale", "l1_unavailable"}
        or service["catalog"]["status"] != "ready"
    ):
        raise RosterSourceError("source_incomplete")

    def timestamp(value: str, maximum_age: float = 1800) -> int:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise RosterSourceError("source_invalid")
        observed = int(stamp.timestamp() * 1000)
        if not 0 <= now - observed <= min(maximum_age * 1000, CATALOG_MAX_AGE_MS):
            raise RosterSourceError("source_stale")
        return observed

    snapshot_at = timestamp(roster["generatedAt"])
    service_at = timestamp(service["generatedAt"])
    catalog_at = timestamp(
        service["catalog"]["latestAt"], service["catalog"].get("maxAgeSeconds", 1800)
    )
    runs = [run for run in service["collectors"] if run["runKind"] == "catalog"]
    if (
        len(runs) != 1
        or runs[0]["status"] != "succeeded"
        or runs[0]["recordsReceived"] != len(roster["items"])
        or runs[0]["recordsWritten"] != len(roster["items"])
    ):
        raise RosterSourceError("source_incomplete")
    completed_at = timestamp(runs[0]["completedAt"])
    # Mixed generations cannot lend a newer successful run to an older snapshot.
    if completed_at != catalog_at or catalog_at > min(snapshot_at, service_at):
        raise RosterSourceError("source_invalid")
    return catalog_at


def check_roster(mapping: RankingMap, artifacts: Path, now: int) -> RosterHealth:
    """Read once per artifact; disclose pending identity changes without adopting them."""
    try:
        service_path = artifacts / "service-state.json"
        if service_path.stat().st_size > 1024 * 1024:
            raise RosterSourceError("source_invalid")
        service = json.loads(service_path.read_text())
        roster = extract_roster(artifacts / "universe-snapshot.json")
        observed = check_catalog(roster, service, now)
        current = {item["venueInstrumentId"]: item for item in roster["items"]}
        adopted = {item.instrument_id: item for row in mapping.rows for item in row.originals}
        added = tuple(sorted(current.keys() - adopted.keys()))
        removed = tuple(sorted(adopted.keys() - current.keys()))
        changed = tuple(
            key
            for key in sorted(current.keys() & adopted.keys())
            if (
                current[key]["venueInstrumentVersionId"] != adopted[key].version_id
                or current[key]["venue"] != adopted[key].venue
                or current[key]["sourceSymbol"] != adopted[key].symbol
                or current[key]["baseAsset"] != adopted[key].base_asset
            )
        )
        matched = (
            roster["catalogFingerprint"] == mapping.roster_fingerprint
            and len(current) == mapping.source_instrument_count
            and not (added or removed or changed)
        )
        return RosterHealth(
            status="ready" if matched else "review_required",
            catalog_observed_at=observed,
            source_instruments=len(current),
            added_instrument_ids=added,
            removed_instrument_ids=removed,
            changed_instrument_ids=changed,
            market_data_issue_ids=roster["marketDataIssueIds"],
        )
    except RosterSourceError as exc:
        return RosterHealth(status=exc.status)
    except OSError:
        return RosterHealth(status="source_unavailable")
    except (ValueError, KeyError, TypeError, AttributeError):
        return RosterHealth(status="source_invalid")
