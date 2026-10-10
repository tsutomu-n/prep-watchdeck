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
_VERIFICATION = runpy.run_path(str(ROOT / "scripts/ranking/verify-map-evidence.py"))
VERIFY = _VERIFICATION["verify"]
VERIFY_MEXC_ORIGINAL = _VERIFICATION["verify_mexc_original"]
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

    def by_id(values: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {item["venueInstrumentId"]: item for item in values}

    previous = by_id(previous_roster["items"])
    captured_items = [{name: item[name] for name in IDENTITY_FIELDS} for item in capture["items"]]
    captured = by_id(captured_items)
    if len(captured) != len(captured_items) or any(
        key in previous and item != previous[key] for key, item in captured.items()
    ):
        raise ValueError("existing MEXC identities require independent requalification")
    expected = {**previous, **captured}
    if len(by_id(current)) != len(current) or by_id(current) != expected:
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
    existing = {entry["venueInstrumentId"]: entry for entry in roster["items"]}
    rows = {row["id"]: row for row in saved["rows"]}
    evidence["catalogs"].setdefault("mexc", {})
    qualifications = evidence.setdefault("mexcQualification", {})
    added = 0
    for item in items:
        symbol = item["sourceSymbol"]
        review = review_by_symbol[symbol]
        key = item["venueInstrumentId"]
        row = rows.get(review["rankingRowId"])
        native_only = review.get("nativeOnly") is True
        if (
            item["venue"] != "mexc"
            or key != "mexc:" + symbol
            or type(item["venueInstrumentVersionId"]) is not int
            or item["venueInstrumentVersionId"] <= 0
            or item["baseAsset"] != review["baseAsset"]
            or review["assetClass"] != "crypto"
            or not review.get("identityEvidence")
            or not review.get("project")
            or review.get("explicitFuturesLinkPresent") is not True
            or (not native_only and (row is None or row["status"] != "verified"))
            or (row is not None and row["asset"] != review["baseAsset"])
            or (
                native_only
                and (
                    review["rankingRowId"] != "mexc-native:" + symbol
                    or not review.get("reason")
                    or (row is not None and row["reference"] is not None)
                )
            )
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
        if key in existing:
            previous = qualifications.get(key, {})
            if (
                {name: item[name] for name in IDENTITY_FIELDS} != existing[key]
                or previous.get("definitionDigest") != item["definitionDigest"]
                or previous.get("normalizedDefinition") != definition
                or row is None
                or original not in row["originals"]
                or previous.get("identity")
                != {"assetClass": "crypto", "project": review["project"]}
            ):
                raise ValueError("existing MEXC definition requires independent requalification")
            # A fresh observation is not permission to rewrite an approved review or
            # to lend the new capture time to older evidence.
            continue
        if row is None:
            row = {
                "id": review["rankingRowId"],
                "asset": review["baseAsset"],
                "status": "review",
                "reason": review["reason"],
                "originals": [],
                "reference": None,
                "widget": {
                    "status": "review",
                    "symbol": None,
                    "reason": "fixed_reference_unverified",
                    "evidence": list(review["identityEvidence"]),
                    "referenceKey": None,
                },
                "evidence": [],
            }
            saved["rows"].append(row)
            rows[row["id"]] = row
            evidence["remaining"].append({"id": row["id"], "reason": row["reason"]})
        row["originals"].append(original)
        row["originals"].sort(key=lambda value: value["instrumentId"])
        row["evidence"] = list(dict.fromkeys([*row["evidence"], *review["identityEvidence"]]))
        roster["items"].append({name: item[name] for name in IDENTITY_FIELDS})
        evidence["catalogs"]["mexc"][symbol] = entry
        qualifications[key] = {
            "versionId": original["versionId"],
            "symbol": symbol,
            "baseAsset": original["baseAsset"],
            "priceMultiplier": 1,
            "baseQuantityPerContract": raw["watchdeckQuantityEvidence"]["base_per_contract"],
            "referenceKey": (
                ":".join(row["reference"][name] for name in ("provider", "symbol", "revision"))
                if row["reference"] is not None
                else None
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
        existing[key] = {name: item[name] for name in IDENTITY_FIELDS}
        added += 1
    if not added:
        return saved, roster, evidence
    roster["items"].sort(key=lambda value: value["venueInstrumentId"])
    roster["catalogFingerprint"] = content_digest(roster["items"])
    # Do not lend this new MEXC observation time to the older three-Venue capture.
    saved["verifiedAt"] = int(observed.timestamp() * 1000)
    mapping = compile_map(roster, saved)
    evidence.update(mapVersion=mapping.version, verifiedAt=mapping.verified_at)
    evidence["mexcQualification"] = qualifications
    for row in mapping.rows:
        for original in row.originals:
            if original.venue == "mexc":
                VERIFY_MEXC_ORIGINAL(original, row.reference, evidence)
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
    if evidence.get("mexcAddition"):
        evidence.setdefault("mexcAdditionHistory", []).append(
            copy.deepcopy(evidence["mexcAddition"])
        )
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
