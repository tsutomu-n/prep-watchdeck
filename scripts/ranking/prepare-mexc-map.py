"""Append reviewed MEXC identities from an explicitly scoped persisted catalog capture.

Legacy rows, references, quantity reviews, Widgets and observation dates remain intact.
This is additive source qualification, never a complete live roster refresh or deployment.
"""

import argparse
import copy
import json
import runpy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prep_watchdeck_ranking.mapping import IDENTITY_FIELDS, compile_map
from prep_watchdeck_ranking.models import content_digest

ROOT = Path(__file__).resolve().parents[2]
VERIFY = runpy.run_path(str(ROOT / "scripts/ranking/verify-map-evidence.py"))["verify"]
OUTPUT_DIRECTORY = runpy.run_path(str(ROOT / "scripts/ranking/refresh-roster-candidate.py"))[
    "output_directory"
]
PRODUCTION_DATABASE_TARGET = {
    "host": "127.0.0.1",
    "port": 55432,
    "database": "prep_watchdeck_market",
}


def validate_capture_scope(
    capture: dict[str, Any],
    previous_roster: dict[str, Any],
    *,
    capture_scope: str,
    now: datetime,
) -> dict[str, Any]:
    """Bind production IDs to a recent read-only DB snapshot, never an isolated ID remap."""
    observed = datetime.fromisoformat(capture["observedAt"])
    if observed.tzinfo is None:
        raise ValueError("MEXC capture must identify a timezone-aware observation")
    declared_scope = capture.get("captureScope", "isolated")
    if capture_scope != declared_scope:
        raise ValueError("MEXC capture scope requires an explicit matching invocation")
    if capture_scope == "isolated":
        if capture.get("isolated") is not True:
            raise ValueError("MEXC isolated capture must identify an isolated observation")
        return {
            "captureScope": "isolated",
            "versionScope": "isolated persisted catalog; production versions require requalification",
        }
    if capture_scope != "production_read_only" or capture.get("isolated") is not False:
        raise ValueError("unsupported MEXC capture scope")
    if now.tzinfo is None or not 0 <= (now - observed).total_seconds() <= 1800:
        raise ValueError("MEXC production capture is stale or from the future")
    audit = capture.get("databaseAudit", {})
    if (
        audit.get("sessionReadOnly") is not True
        or audit.get("databaseTarget") != PRODUCTION_DATABASE_TARGET
    ):
        raise ValueError("MEXC production versions require the dedicated read-only database audit")
    current = audit["currentRoster"]
    expected = [
        *previous_roster["items"],
        *[{name: item[name] for name in IDENTITY_FIELDS} for item in capture["items"]],
    ]

    def by_id(values: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {item["venueInstrumentId"]: item for item in values}

    if (
        len(by_id(current)) != len(current)
        or len(by_id(expected)) != len(expected)
        or by_id(current) != by_id(expected)
    ):
        raise ValueError(
            "current production roster differs; legacy identities require requalification"
        )
    definitions = audit["currentMexcDefinitions"]
    definition_by_id = {item["instrumentId"]: item for item in definitions}
    if len(definition_by_id) != len(definitions) or set(definition_by_id) != {
        item["venueInstrumentId"] for item in capture["items"]
    }:
        raise ValueError("production MEXC definition audit must cover every captured identity")
    for item in capture["items"]:
        proof = definition_by_id[item["venueInstrumentId"]]
        if (
            proof["currentVersion"] != item["venueInstrumentVersionId"]
            or "validTo" not in proof
            or proof["validTo"] is not None
            or proof["normalizedDefinition"] != item["normalizedDefinition"]
            or content_digest(proof["normalizedDefinition"]) != item["definitionDigest"]
        ):
            raise ValueError("production MEXC current version or stored definition differs")
    return {
        "captureScope": "production_read_only",
        "versionScope": "production persisted catalog; exact current versions read in a read-only session",
        "databaseAudit": copy.deepcopy(audit),
        "databaseAuditDigest": content_digest(audit),
    }


def prepare(
    directory: Path,
    capture: dict[str, Any],
    reviews: dict[str, Any],
    *,
    capture_scope: str = "isolated",
    now: datetime | None = None,
) -> tuple[dict, ...]:
    """Require exact persisted IDs and separately reviewed cross-market price identities."""
    VERIFY(directory)
    saved = json.loads((directory / "initial-map.json").read_text())
    roster = json.loads((directory / "initial-roster.json").read_text())
    evidence = json.loads((directory / "qualification-evidence.json").read_text())
    observed = datetime.fromisoformat(capture["observedAt"])
    scope_evidence = validate_capture_scope(
        capture, roster, capture_scope=capture_scope, now=now or datetime.now(UTC)
    )
    if capture.get("versionsAssignedBy") != "persist_catalog":
        raise ValueError("MEXC versions must be assigned by the native catalog store")
    if capture.get("complete") is not True or not capture.get("payloadHash"):
        raise ValueError("MEXC capture must retain complete native catalog provenance")
    review_by_symbol = {item["sourceSymbol"]: item for item in reviews["items"]}
    if len(review_by_symbol) != len(reviews["items"]):
        raise ValueError("duplicate MEXC identity review")
    items = capture["items"]
    if len(items) != len(review_by_symbol) or {item["sourceSymbol"] for item in items} != set(
        review_by_symbol
    ):
        raise ValueError("MEXC capture and explicit identity reviews differ")
    existing_ids = {entry["venueInstrumentId"] for entry in roster["items"]}
    rows = {row["id"]: row for row in saved["rows"]}
    evidence["catalogs"]["mexc"] = {}
    qualifications: dict[str, dict] = {}
    for item in items:
        symbol = item["sourceSymbol"]
        review = review_by_symbol[symbol]
        key = item["venueInstrumentId"]
        row = rows[review["rankingRowId"]]
        if (
            item["venue"] != "mexc"
            or key != "mexc:" + symbol
            or key in existing_ids
            or type(item["venueInstrumentVersionId"]) is not int
            or item["venueInstrumentVersionId"] <= 0
            or item["baseAsset"] != review["baseAsset"]
            or review["assetClass"] != "crypto"
            or not review.get("identityEvidence")
            or not review.get("project")
            or review.get("explicitFuturesLinkPresent") is not True
            or row["status"] != "verified"
            or row["asset"] != review["baseAsset"]
            or item["active"] is not True
            or item["marketType"] != "linear_perpetual"
            or any(
                item[name] != "USDT" for name in ("quoteAsset", "settleAsset", "collateralAsset")
            )
        ):
            raise ValueError("MEXC original differs from explicit reviewed asset binding")
        definition = item["normalizedDefinition"]
        raw = definition["rawDefinition"]
        identity = raw["watchdeckIdentityEvidence"]
        entry = item["catalogEntry"]
        if (
            content_digest(definition) != item["definitionDigest"]
            or identity.get("identity_price_multiplier") != "1"
            or identity.get("base_asset") != item["baseAsset"]
            or identity.get("asset_class") != "crypto"
            or identity.get("price_unit") != "quote_per_base"
            or any(raw.get(name) != value for name, value in entry.items())
            or any(
                definition.get(name) != item[name]
                for name in (
                    "venue",
                    "sourceSymbol",
                    "baseAsset",
                    "quoteAsset",
                    "settleAsset",
                    "active",
                    "marketType",
                    "collateralAsset",
                )
            )
            or definition.get("quantityUnit") != "contracts"
        ):
            raise ValueError("MEXC normalized definition differs from captured native evidence")
        original = {
            "venue": "mexc",
            "instrumentId": key,
            "versionId": item["venueInstrumentVersionId"],
            "symbol": symbol,
            "baseAsset": item["baseAsset"],
            "multiplier": 1,
        }
        row["originals"].append(original)
        row["originals"].sort(key=lambda value: value["instrumentId"])
        row["evidence"].extend(review["identityEvidence"])
        roster["items"].append({name: item[name] for name in IDENTITY_FIELDS})
        evidence["catalogs"]["mexc"][symbol] = entry
        qualifications[key] = {
            "versionId": original["versionId"],
            "symbol": symbol,
            "baseAsset": original["baseAsset"],
            "priceMultiplier": 1,
            "baseQuantityPerContract": raw["watchdeckQuantityEvidence"]["base_per_contract"],
            "referenceKey": ":".join(
                row["reference"][name]
                for name in (
                    "provider",
                    "symbol",
                    "revision",
                )
            ),
            "catalogEntryDigest": content_digest(entry),
            "definitionDigest": item["definitionDigest"],
            "normalizedDefinition": copy.deepcopy(definition),
            "observedAt": capture["observedAt"],
            "identity": {"assetClass": "crypto", "project": review["project"]},
            "identityEvidence": review["identityEvidence"],
            "priceEvidence": [identity["documentation_url"], identity["classification_url"]],
            "finding": review["finding"],
        }
        existing_ids.add(key)
    roster["items"].sort(key=lambda value: value["venueInstrumentId"])
    roster["catalogFingerprint"] = content_digest(roster["items"])
    # Do not lend this new MEXC observation time to the older three-Venue capture.
    saved["verifiedAt"] = int(observed.timestamp() * 1000)
    mapping = compile_map(roster, saved)
    evidence.update(mapVersion=mapping.version, verifiedAt=mapping.verified_at)
    evidence["mexcQualification"] = qualifications
    evidence.setdefault("catalogIdentityIndex", {})["mexc"] = {
        symbol: {
            field: entry[field]
            for field in (
                "symbol",
                "baseCoin",
                "quoteCoin",
                "settleCoin",
                "futureType",
                "state",
                "type",
                "contractSize",
            )
            if field in entry
        }
        for symbol, entry in evidence["catalogs"]["mexc"].items()
    }
    evidence["mexcAddition"] = {
        "observedAt": capture["observedAt"],
        "previousMapVersion": saved["version"],
        "previousVerifiedAt": json.loads((directory / "initial-map.json").read_text())[
            "verifiedAt"
        ],
        "nativeCatalogPayloadHash": capture["payloadHash"],
        "captureDigest": content_digest(capture),
        "coverage": copy.deepcopy(capture["coverage"]),
        "legacyRosterObservationPreserved": True,
        "fixedReferencesPreserved": True,
        "widgetQualificationsPreserved": True,
        **scope_evidence,
        "adoption": "candidate_only",
    }
    return mapping.model_dump(mode="json", by_alias=True), roster, evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-directory", required=True, type=Path)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--reviews", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument(
        "--capture-scope", choices=("isolated", "production_read_only"), default="isolated"
    )
    args = parser.parse_args()
    output = OUTPUT_DIRECTORY(args.output_directory, [args.capture, args.reviews])
    result = prepare(
        args.previous_directory,
        json.loads(args.capture.read_text()),
        json.loads(args.reviews.read_text()),
        capture_scope=args.capture_scope,
    )
    output.mkdir(parents=True, mode=0o700)
    for name, value in zip(
        ("initial-map.json", "initial-roster.json", "qualification-evidence.json"),
        result,
        strict=True,
    ):
        (output / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"outputDirectory": str(output), **VERIFY(output)}))


if __name__ == "__main__":
    main()
