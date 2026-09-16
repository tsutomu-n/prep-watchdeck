"""Audit every saved original identity and reference/Widget binding without network access."""

import argparse
import json
from collections import Counter
from pathlib import Path

from prep_watchdeck_ranking.mapping import compile_map, qualification_summary, reference_revision


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
