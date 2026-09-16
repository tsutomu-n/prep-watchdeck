"""Read-only roster extraction and explicit, evidence-bearing mapping compilation."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import MAP_SCHEMA_VERSION, RankingMap, content_digest

IDENTITY_FIELDS = (
    "venue",
    "venueInstrumentId",
    "venueInstrumentVersionId",
    "sourceSymbol",
    "baseAsset",
    "quoteAsset",
    "settleAsset",
    "collateralAsset",
    "active",
    "marketType",
    "groupId",
    "mappingMethod",
)


def extract_roster(path: Path) -> dict[str, Any]:
    """Freshness of unrelated charts/selection/service artifacts never gates this read."""
    resolved = path.expanduser().resolve(strict=True)
    if resolved.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("universe roster exceeds size budget")
    payload = json.loads(resolved.read_text())
    if not isinstance(payload.get("items"), list):
        raise ValueError("universe roster has no items")
    entries = []
    for item in payload["items"]:
        if item.get("active") is not True or item.get("marketType") != "linear_perpetual":
            continue
        if item.get("venue") not in ("bitget", "hyperliquid", "aster"):
            raise ValueError("unexpected original venue")
        entries.append({name: item[name] for name in IDENTITY_FIELDS})
    entries.sort(key=lambda item: item["venueInstrumentId"])
    if not entries or len({item["venueInstrumentId"] for item in entries}) != len(entries):
        raise ValueError("empty or duplicate original roster")
    return {
        "sourcePath": str(resolved),
        "generatedAt": payload["generatedAt"],
        "sourceStatus": payload["status"],
        "items": entries,
        "catalogFingerprint": content_digest(entries),
    }


def reference_revision(provider: str, catalog_entry: dict[str, Any]) -> str:
    fields = (
        ("symbol", "symbolId", "baseCoin", "quoteCoin", "settleCoin", "contractType", "launchTime")
        if provider == "bybit"
        else ("symbol", "baseAsset", "quoteAsset", "marginAsset", "contractType", "onboardDate")
    )
    return content_digest({field: catalog_entry.get(field) for field in fields})[:20]


def compile_map(roster: dict[str, Any], decisions: dict[str, Any]) -> RankingMap:
    """Never guesses aliases. The reviewed rows are checked against every original identity."""
    if decisions.get("schemaVersion") != MAP_SCHEMA_VERSION:
        raise ValueError("mapping decisions require explicit ranking-map-v2 qualification")
    entries = roster["items"]
    source = {item["venueInstrumentId"]: item for item in entries}
    if not source or len(source) != len(entries):
        raise ValueError("original roster is empty or contains duplicate instruments")
    if content_digest(entries) != roster["catalogFingerprint"]:
        raise ValueError("original roster fingerprint differs from its contents")
    generated_at = datetime.fromisoformat(roster["generatedAt"])
    if generated_at.tzinfo is None:
        raise ValueError("original roster time must have an explicit timezone")
    mapped = {
        original["instrumentId"]: original
        for row in decisions["rows"]
        for original in row["originals"]
    }
    if set(source) != set(mapped):
        raise ValueError("decisions omit or add original instruments")
    for key, original in source.items():
        adopted = mapped[key]
        if (
            adopted["venue"] != original["venue"]
            or adopted["versionId"] != original["venueInstrumentVersionId"]
            or adopted["symbol"] != original["sourceSymbol"]
            or adopted["baseAsset"] != original["baseAsset"]
        ):
            raise ValueError(f"original contract changed: {key}")
    payload = {
        "schemaVersion": MAP_SCHEMA_VERSION,
        "version": content_digest({"schemaVersion": MAP_SCHEMA_VERSION, "rows": decisions["rows"]})[
            :24
        ],
        "verifiedAt": decisions["verifiedAt"],
        "rosterGeneratedAt": int(generated_at.timestamp() * 1000),
        "rosterFingerprint": roster["catalogFingerprint"],
        "rosterSource": roster["sourcePath"],
        "sourceInstrumentCount": len(source),
        "rows": decisions["rows"],
    }
    return RankingMap.model_validate(payload)


def qualification_summary(mapping: RankingMap) -> dict[str, int | bool]:
    """Report the three independent reviews without relabelling unknown quantities."""
    review = sum(row.status == "review" for row in mapping.rows)
    quantity_review = sum(
        original.multiplier is None for row in mapping.rows for original in row.originals
    )
    widget_review = sum(row.widget.status == "review" for row in mapping.rows)
    return {
        "review": review,
        "quantityReview": quantity_review,
        "widgetReview": widget_review,
        "rankingQualified": review == 0,
        "quantityQualified": quantity_review == 0,
        "widgetQualified": widget_review == 0,
        "qualificationComplete": review == quantity_review == widget_review == 0,
    }
