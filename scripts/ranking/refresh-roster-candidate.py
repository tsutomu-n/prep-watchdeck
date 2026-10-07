"""Build an isolated roster refresh from current identities and explicit reviewed decisions.

This utility never fetches prices, changes a fixed reference, or adopts a live map.
Read-only catalog/definition evidence must be captured before running it.
"""

import argparse
import copy
import json
import runpy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prep_watchdeck_ranking.mapping import IDENTITY_FIELDS, compile_map, extract_roster
from prep_watchdeck_ranking.models import content_digest
from prep_watchdeck_ranking.roster import check_catalog

ROOT = Path(__file__).resolve().parents[2]
IDENTITY_DEFINITION_FIELDS = (
    "active",
    "asset_class",
    "market_type",
    "execution_model",
    "base_asset",
    "quote_asset",
    "settle_asset",
    "collateral_asset",
    "quantity_unit",
    "contract_multiplier",
)
CATALOG_IDENTITY_FIELDS = {
    "bybit": (
        "symbol",
        "symbolId",
        "baseCoin",
        "quoteCoin",
        "settleCoin",
        "contractType",
        "launchTime",
        "status",
        "symbolType",
        "fullName",
        "underlyingTicker",
    ),
    "binance": (
        "symbol",
        "baseAsset",
        "quoteAsset",
        "marginAsset",
        "contractType",
        "onboardDate",
        "status",
        "underlyingType",
        "underlyingSubType",
    ),
    "aster": (
        "symbol",
        "baseAsset",
        "quoteAsset",
        "marginAsset",
        "contractType",
        "status",
        "underlyingType",
        "underlyingSubType",
        "symbolType",
    ),
    "bitget": ("symbol", "baseCoin", "quoteCoin", "symbolType", "symbolStatus"),
    "hyperliquid": ("name", "isDelisted", "szDecimals"),
}


def recent(value: str | int, now: int, maximum_age: int) -> None:
    if isinstance(value, str) and datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("refresh evidence time must include a timezone")
    observed = (
        value if isinstance(value, int) else int(datetime.fromisoformat(value).timestamp() * 1000)
    )
    if not 0 <= now - observed <= maximum_age * 1000:
        raise ValueError("refresh evidence is stale or from the future")


def prepare(
    roster: dict[str, Any],
    service: dict[str, Any],
    previous_roster: dict[str, Any],
    previous_map: dict[str, Any],
    previous_evidence: dict[str, Any],
    catalogs: dict[str, Any],
    definitions: dict[str, Any],
    decisions: dict[str, Any],
    reviews: dict[str, Any],
    *,
    now: int,
    maximum_age: int = 1800,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Retain approved bindings; require proof for version changes and every new identity."""
    previous = compile_map(previous_roster, previous_map)
    if previous.version != previous_map["version"]:
        raise ValueError("previous approved map differs from its roster")
    if previous_evidence["mapVersion"] != previous.version:
        raise ValueError("previous approved evidence differs from its map")
    check_catalog(roster, service, now)
    recent(roster["generatedAt"], now, maximum_age)
    recent(service["generatedAt"], now, maximum_age)
    recent(service["catalog"]["latestAt"], now, maximum_age)
    recent(catalogs["observedAt"], now, maximum_age)
    recent(definitions["observedAt"], now, maximum_age)
    if definitions.get("sessionReadOnly") is not True or definitions.get("databaseTarget") != {
        "host": "127.0.0.1",
        "port": 55432,
        "database": "prep_watchdeck_market",
    }:
        raise ValueError("definition audit must be captured in a read-only session")
    if set(catalogs["catalogs"]) != {"aster", "bitget", "hyperliquid", "bybit", "binance"}:
        raise ValueError("refresh requires complete official catalog evidence")
    if catalogs.get("complete") is not True:
        raise ValueError("official catalog capture must confirm complete pagination")

    old = {entry["venueInstrumentId"]: entry for entry in previous_roster["items"]}
    current = {entry["venueInstrumentId"]: entry for entry in roster["items"]}
    if len(current) != len(roster["items"]):
        raise ValueError("duplicate current identity")
    audit = {entry["instrumentId"]: entry for entry in definitions["items"]}
    if set(audit) != set(current) or len(audit) != len(definitions["items"]):
        raise ValueError("definition audit must cover every current instrument exactly")
    changes = []
    for key, entry in current.items():
        proof = audit[key]
        if proof["currentVersion"] != entry["venueInstrumentVersionId"]:
            raise ValueError("definition audit does not bind the current version")
        projection = {
            "active": "active",
            "market_type": "marketType",
            "base_asset": "baseAsset",
            "quote_asset": "quoteAsset",
            "settle_asset": "settleAsset",
            "collateral_asset": "collateralAsset",
        }
        if any(
            proof["currentDefinition"][field] != entry[name] for field, name in projection.items()
        ):
            raise ValueError("definition audit differs from the current roster identity")
        if key not in old:
            if not reviews.get("instruments", {}).get(key, {}).get("identityEvidence"):
                raise ValueError(f"new original identity requires explicit evidence: {key}")
            continue
        changed_fields = [name for name in IDENTITY_FIELDS if old[key][name] != entry[name]]
        if any(name != "venueInstrumentVersionId" for name in changed_fields):
            raise ValueError(f"original asset identity changed; independent requalification: {key}")
        if changed_fields:
            if proof.get("previousVersion") != old[key]["venueInstrumentVersionId"]:
                raise ValueError("definition audit does not bind the previous version")
            if any(
                name in proof["normalizedDefinitionChanges"] for name in IDENTITY_DEFINITION_FIELDS
            ):
                raise ValueError(f"original contract identity or quantity changed: {key}")
            changes.append(proof)

    adopted = copy.deepcopy(decisions)
    adopted["verifiedAt"] = now
    candidate = compile_map(roster, adopted)
    previous_rows = {row.id: row for row in previous.rows}
    old_originals = {item.instrument_id: item for row in previous.rows for item in row.originals}
    for row in candidate.rows:
        old_row = previous_rows.get(row.id)
        if old_row is None:
            review = reviews.get("rows", {}).get(row.id, {})
            if not review.get("identityEvidence") or not review.get("referenceEvidence"):
                raise ValueError(f"new row requires explicit asset and reference review: {row.id}")
        if old_row is not None and old_row.status == "verified":
            if row.reference != old_row.reference:
                raise ValueError(f"refresh cannot change an approved fixed reference: {row.id}")
        elif row.status == "verified":
            review = reviews.get("rows", {}).get(row.id, {})
            if not review.get("identityEvidence") or not review.get("referenceEvidence"):
                raise ValueError(f"new reference requires independent qualification: {row.id}")
        for original in row.originals:
            old_original = old_originals.get(original.instrument_id)
            if old_original is not None:
                if original.multiplier != old_original.multiplier:
                    raise ValueError("refresh cannot infer or change original quantity conversion")
                original_row = next(
                    r.id
                    for r in previous.rows
                    if original.instrument_id in {item.instrument_id for item in r.originals}
                )
                if row.id != original_row:
                    raise ValueError("refresh cannot move an approved original asset identity")
            elif original.multiplier is not None:
                proof = reviews["instruments"][original.instrument_id]
                if not proof.get("quantityEvidence"):
                    raise ValueError("new quantity conversion requires explicit evidence")

    used: dict[str, set[str]] = {venue: set() for venue in catalogs["catalogs"]}
    for row in candidate.rows:
        for original in row.originals:
            used[original.venue].add(original.symbol)
        if row.reference is not None:
            used[row.reference.provider].add(row.reference.symbol)
    retained = {
        venue: {symbol: entries[symbol] for symbol in sorted(used[venue])}
        for venue, entries in catalogs["catalogs"].items()
    }
    identity_index = {
        venue: {
            symbol: {
                field: entry[field] for field in CATALOG_IDENTITY_FIELDS[venue] if field in entry
            }
            for symbol, entry in entries.items()
        }
        for venue, entries in catalogs["catalogs"].items()
    }
    evidence = copy.deepcopy(previous_evidence)
    evidence.update(mapVersion=candidate.version, verifiedAt=now, catalogs=retained)
    evidence["catalogIdentityIndex"] = identity_index
    evidence["catalogCapture"] = {
        "observedAt": catalogs["observedAt"],
        "complete": True,
        "sources": catalogs.get("sources", {}),
        "fullCatalogHashes": {
            venue: content_digest(entries) for venue, entries in catalogs["catalogs"].items()
        },
        "completeCounts": {venue: len(entries) for venue, entries in catalogs["catalogs"].items()},
        "retainedFullEntryCounts": {venue: len(entries) for venue, entries in retained.items()},
        "identityIndexDigest": content_digest(identity_index),
    }
    evidence["indexComponents"].extend(reviews.get("indexComponents", []))
    evidence["widgetMetadata"].update(reviews.get("widgetMetadata", {}))
    evidence["widgetObservations"] = reviews.get("widgetObservations", {})
    evidence["remaining"] = [
        {"id": row.id, "reason": row.reason} for row in candidate.rows if row.status == "review"
    ]
    evidence["quantityUnverified"] = [
        entry for entry in evidence["quantityUnverified"] if entry["instrumentId"] in current
    ] + reviews.get("quantityUnverified", [])
    evidence["rankingQualification"].update(reviews.get("rankingQualification", {}))
    evidence["rosterRefresh"] = {
        "observedAt": datetime.fromtimestamp(now / 1000, UTC).isoformat(),
        "previousMapVersion": previous.version,
        "previousRosterFingerprint": previous.roster_fingerprint,
        "officialCatalogObservedAt": catalogs["observedAt"],
        "catalogDigest": content_digest(catalogs["catalogs"]),
        "definitionAuditDigest": content_digest(definitions),
        "addedInstrumentIds": sorted(set(current) - set(old)),
        "removedInstrumentIds": sorted(set(old) - set(current)),
        "versionChanges": changes,
        "reviewedChanges": reviews.get("instruments", {}),
        "rowQualifications": reviews.get("rows", {}),
        "fixedReferencesPreserved": True,
        "quantityConversionsPreserved": True,
        "adoption": "candidate_only",
    }
    return candidate.model_dump(mode="json", by_alias=True), roster, evidence


def output_directory(value: Path, inputs: list[Path]) -> Path:
    result = value.expanduser().resolve()
    forbidden = [
        ROOT,
        Path.home() / ".local/share/prep-watchdeck-market",
        Path.home() / ".local/share/prep-watchdeck-ranking",
        Path.home() / "releases",
        *[path.expanduser().resolve().parent for path in inputs],
    ]
    if result == Path(result.anchor) or result == Path.home():
        raise ValueError("candidate output must be a dedicated directory")
    if any(result.is_relative_to(path) or path.is_relative_to(result) for path in forbidden):
        raise ValueError("candidate output overlaps source, input evidence or live state")
    if result.exists():
        raise ValueError("candidate output already exists; choose a new directory")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "snapshot",
        "service",
        "previous-roster",
        "previous-map",
        "previous-evidence",
        "catalogs",
        "definitions",
        "decisions",
        "reviews",
        "output-directory",
    ):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    names = (
        "service",
        "previous_roster",
        "previous_map",
        "previous_evidence",
        "catalogs",
        "definitions",
        "decisions",
        "reviews",
    )
    result = output_directory(
        args.output_directory, [args.snapshot, *[getattr(args, n) for n in names]]
    )
    inputs = {name: json.loads(getattr(args, name).read_text()) for name in names}
    mapping, roster, evidence = prepare(
        extract_roster(args.snapshot), **inputs, now=int(datetime.now(UTC).timestamp() * 1000)
    )
    result.mkdir(parents=True, mode=0o700)
    for name, value in (
        ("initial-map.json", mapping),
        ("initial-roster.json", roster),
        ("qualification-evidence.json", evidence),
    ):
        path = result / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)
    verify = runpy.run_path(str(ROOT / "scripts/ranking/verify-map-evidence.py"))["verify"]
    print(json.dumps({"outputDirectory": str(result), **verify(result)}))


if __name__ == "__main__":
    main()
