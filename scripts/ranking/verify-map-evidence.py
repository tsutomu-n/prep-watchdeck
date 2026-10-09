"""Audit every saved original identity and reference/Widget binding without network access."""

import argparse
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from prep_watchdeck_ranking.mapping import compile_map, qualification_summary, reference_revision
from prep_watchdeck_ranking.models import content_digest


def verify_mexc_original(original, reference, evidence: dict) -> None:
    """Bind the reviewed price identity to its exact captured native version.

    The native contractSize remains separate quantity provenance. It must never
    become the integer multiplier used to identify the asset behind a price.
    """
    proof = evidence.get("mexcQualification", {}).get(original.instrument_id, {})
    entry = evidence["catalogs"]["mexc"].get(original.symbol, {})
    identity = proof.get("identity", {})
    definition = proof.get("normalizedDefinition", {})
    raw = definition.get("rawDefinition", {})
    if (
        proof.get("versionId") != original.version_id
        or proof.get("symbol") != original.symbol
        or proof.get("baseAsset") != original.base_asset
        or proof.get("priceMultiplier") != original.multiplier
        or proof.get("referenceKey") != (reference.key if reference else None)
        or proof.get("catalogEntryDigest") != content_digest(entry)
        or proof.get("definitionDigest") != content_digest(definition)
        or definition.get("venue") != "mexc"
        or definition.get("sourceSymbol") != original.symbol
        or definition.get("baseAsset") != original.base_asset
        or definition.get("quantityUnit") != "contracts"
        or raw.get("watchdeckIdentityEvidence", {}).get("identity_price_multiplier") != "1"
        or any(raw.get(name) != value for name, value in entry.items())
        or not proof.get("observedAt")
        or not proof.get("identityEvidence")
        or not proof.get("priceEvidence")
        or identity.get("assetClass") != "crypto"
        or not identity.get("project")
        or entry.get("symbol") != original.symbol
        or entry.get("baseCoin") != original.base_asset
        or entry.get("quoteCoin") != "USDT"
        or entry.get("settleCoin") != "USDT"
        or entry.get("futureType") != 1
        or entry.get("state") != 0
        or entry.get("type") != 1
        or original.multiplier != 1
    ):
        raise ValueError(f"MEXC exact price identity evidence differs: {original.instrument_id}")
    try:
        contract_size = Decimal(str(entry["contractSize"]))
        captured_size = Decimal(str(proof["baseQuantityPerContract"]))
        normalized_size = Decimal(str(definition["contractMultiplier"]))
    except (KeyError, InvalidOperation):
        raise ValueError("MEXC base quantity evidence absent") from None
    if (
        not contract_size.is_finite()
        or contract_size <= 0
        or captured_size != contract_size
        or normalized_size != contract_size
    ):
        raise ValueError("MEXC base quantity evidence differs from native contractSize")


def verify(directory: Path) -> dict:
    saved = json.loads((directory / "initial-map.json").read_text())
    roster = json.loads((directory / "initial-roster.json").read_text())
    evidence = json.loads((directory / "qualification-evidence.json").read_text())
    mapping = compile_map(roster, saved)
    if mapping.version != saved["version"] or mapping.version != evidence["mapVersion"]:
        raise ValueError("map, roster and evidence versions differ")
    if mapping.verified_at != evidence["verifiedAt"]:
        raise ValueError("qualification times differ")
    for row in mapping.rows:
        for original in row.originals:
            entry = evidence["catalogs"][original.venue].get(original.symbol)
            if entry is None and row.status != "review":
                raise ValueError(f"original catalog evidence absent: {original.instrument_id}")
            if original.venue == "mexc" and row.status != "review":
                verify_mexc_original(original, row.reference, evidence)
        if row.reference is None:
            continue
        ref = row.reference
        entry = evidence["catalogs"][ref.provider][ref.symbol]
        if reference_revision(ref.provider, entry) != ref.revision:
            raise ValueError(f"reference revision changed: {ref.key}")
        if ref.provider == "bybit":
            valid = (
                entry["status"] == "Trading"
                and entry["contractType"] == "LinearPerpetual"
                and entry["baseCoin"] == ref.base_asset
                and entry["quoteCoin"] == entry["settleCoin"] == "USDT"
                and entry["symbolType"] in ("", "innovation")
            )
        else:
            valid = (
                entry["status"] == "TRADING"
                and entry["contractType"] == "PERPETUAL"
                and entry["baseAsset"] == ref.base_asset
                and entry["quoteAsset"] == entry["marginAsset"] == "USDT"
                and (
                    entry["underlyingType"] == "COIN"
                    or (ref.symbol == "BTCDOMUSDT" and entry["underlyingType"] == "INDEX")
                )
            )
        if not valid:
            raise ValueError(f"reference catalog contract differs: {ref.key}")
        if row.widget.status == "supported":
            widget = evidence["widgetMetadata"][row.widget.symbol]
            if (
                widget["source_id"].lower() != ref.provider
                or row.widget.symbol != widget["source_id"] + ":" + widget["symbol"]
                or widget["type"] != "swap"
                or "perpetual" not in widget["typespecs"]
                or widget["currency_code"] != "USDT"
            ):
                raise ValueError(f"Widget catalog contract differs: {row.id}")
    states = Counter(row.status for row in mapping.rows)
    unresolved = {row.id for row in mapping.rows if row.status == "review"}
    if unresolved != {row["id"] for row in evidence["remaining"]}:
        raise ValueError("unresolved ledger differs from map")
    unknown_quantities = {
        original.instrument_id: row.id
        for row in mapping.rows
        for original in row.originals
        if original.multiplier is None
    }
    quantity_records = evidence["quantityUnverified"]
    if (
        len(quantity_records) != len(unknown_quantities)
        or {record["instrumentId"]: record["rowId"] for record in quantity_records}
        != unknown_quantities
        or any(
            not record.get("reason") or not record.get("evidence") for record in quantity_records
        )
    ):
        raise ValueError("original quantity review ledger differs from map")
    for row in mapping.rows:
        if row.status != "verified" or not any(o.multiplier is None for o in row.originals):
            continue
        qualification = evidence["rankingQualification"].get(row.id, {})
        if (
            row.reference is None
            or qualification.get("referenceKey") != row.reference.key
            or set(qualification.get("originalInstrumentIds", []))
            != {original.instrument_id for original in row.originals}
            or not qualification.get("identityEvidence")
            or not qualification.get("referenceEvidence")
        ):
            raise ValueError(f"independent ranking qualification absent: {row.id}")
    return {
        "mapVersion": mapping.version,
        "instruments": mapping.source_instrument_count,
        "rows": len(mapping.rows),
        "states": states,
        "widgetBindings": sum(row.widget.status == "supported" for row in mapping.rows),
        **qualification_summary(mapping),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "apps/ranking-core/data",
    )
    args = parser.parse_args()
    print(json.dumps(verify(args.directory)))
