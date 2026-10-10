"""Verify the frozen, reviewed MEXC 10/50/100 source bundles entirely offline.

This validates source admission evidence, not persisted production version IDs,
external reference identity, live freshness, or staged runtime acceptance.
"""

import argparse
import hashlib
import json
import runpy
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from prep_watchdeck_market.identity import resolve_market_groups
from prep_watchdeck_market.sources import mexc

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIRECTORY = ROOT / "apps/market-core/data/mexc-reviewed-20261010"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def verify(directory: Path) -> dict:
    snapshot = read_json(directory / "snapshot.json")
    payloads = {}
    for name, proof in snapshot["sources"].items():
        raw = (directory / proof["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != proof["rawSha256"]:
            raise ValueError(f"frozen {name} payload hash differs")
        payloads[name] = json.loads(raw)
        if len(payloads[name]["data"]) != proof["count"]:
            raise ValueError(f"frozen {name} payload count differs")
    catalog = {row["symbol"]: row for row in payloads["catalog"]["data"]}
    ticker = {row["symbol"]: row for row in payloads["ticker"]["data"]}
    evidence = read_json(directory / "reviewed-evidence.json")
    proofs = {row["sourceSymbol"]: row for row in evidence["items"]}
    if len(proofs) != len(evidence["items"]) or len(proofs) != 90:
        raise ValueError("additional native identity evidence must cover exactly 90 assets")
    decisions = read_json(directory / "selection-decisions.json")
    selected = [row for row in decisions["items"] if row["decision"] == "accepted"]
    if [row["sourceSymbol"] for row in selected] != list(proofs):
        raise ValueError("reviewed identities differ from frozen candidate selection")
    amounts = [Decimal(str(row["amount24"])) for row in decisions["items"]]
    if amounts != sorted(amounts, reverse=True):
        raise ValueError("frozen candidates must follow descending native turnover")
    for decision in decisions["items"]:
        if (
            Decimal(str(ticker[decision["sourceSymbol"]]["amount24"]))
            != Decimal(decision["amount24"])
            or not decision["reason"]
        ):
            raise ValueError("candidate order evidence or decision reason differs")
    registries = {}
    for count in (10, 50, 100):
        manifest = read_json(directory / f"manifest-{count}.json")
        source = directory / manifest["registry"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["registrySha256"]:
            raise ValueError(f"fixed registry {count} hash differs")
        registry = runpy.run_path(str(source))["MEXC_REVIEWED_IDENTITIES"]
        registries[count] = registry
        if len(registry) != count or list(registry) != manifest["symbols"]:
            raise ValueError(f"fixed registry {count} manifest differs")
        if manifest["productionContractVersionIds"] is not None:
            raise ValueError("source bundles cannot claim persisted production IDs")
        reviews = read_json(directory / manifest["identityReviews"])["items"]
        if [row["sourceSymbol"] for row in reviews] != list(registry):
            raise ValueError(f"fixed registry {count} ranking reviews differ")
        if any(
            row.get("nativeOnly") is not True
            or row["rankingRowId"] != "mexc-native:" + row["sourceSymbol"]
            or row.get("reason") != "fixed_reference_unverified"
            for row in reviews[10:]
        ):
            raise ValueError("additional assets must retain unreviewed external references")
        with patch.object(mexc, "MEXC_REVIEWED_IDENTITIES", registry):
            batch = mexc.parse_mexc_catalog(
                payloads["catalog"],
                observed_at=datetime.fromisoformat(snapshot["sources"]["catalog"]["observedAt"]),
            )
        if {row.source_symbol for row in batch.instruments} != set(registry) or not all(
            row.active for row in batch.instruments
        ):
            raise ValueError(f"frozen catalog cannot admit exactly {count} active assets")
        peers = [
            replace(
                instrument,
                venue=venue,
                source_symbol=instrument.source_symbol,
                quantity_unit="base",
                contract_multiplier=Decimal("1"),
                raw_definition={},
            )
            for instrument in batch.instruments
            for venue in ("bitget", "aster")
        ]
        resolutions = resolve_market_groups([*batch.instruments, *peers])
        groups = {item.venue_instrument_id: item.group_id for item in resolutions}
        for instrument in batch.instruments:
            native_only = instrument.source_symbol in proofs
            expected_group = (
                f"native:{instrument.venue_instrument_id}:linear-perp"
                if native_only
                else f"crypto:{instrument.base_asset}:linear-perp"
            )
            if groups[instrument.venue_instrument_id] != expected_group:
                raise ValueError(f"native identity grouping differs: {instrument.source_symbol}")
            if native_only and sum(item.group_id == expected_group for item in resolutions) != 1:
                raise ValueError(f"native identity is not a singleton: {instrument.source_symbol}")
    if any(registries[count] != dict(list(registries[100].items())[:count]) for count in (10, 50)):
        raise ValueError("stages must preserve prior identity definitions verbatim")
    for symbol, proof in proofs.items():
        identity = registries[100][symbol]
        entry = catalog[symbol]
        if (
            identity["base_asset"] != proof["nativeToken"]
            or identity["base_asset"] != proof["assetName"]
            or identity["project"] != proof["project"]
            or identity["classification_url"] != proof["page"]["url"]
            or identity["reviewed_at"] != proof["reviewedAt"]
            or identity["asset_class"] != "crypto"
            or identity["price_unit"] != "quote_per_base"
            or identity["identity_price_multiplier"] != "1"
            or identity.get("identity_scope") != "native_only"
            or proof.get("identityScope") != "native_only"
            or proof["exactFuturesLinkPresent"] is not True
            or proof["futuresBinding"]["symbol"] != symbol
            or proof["futuresBinding"]["bc"] != identity["base_asset"]
            or not proof["classificationFinding"]
            or not proof["descriptionSha256"]
            or not proof["page"]["rawSha256"]
            or any(entry[name] != value for name, value in proof["catalogBinding"].items())
            or Decimal(proof["baseQuantityPerContract"]) != Decimal(str(entry["contractSize"]))
        ):
            raise ValueError(f"native identity review differs: {symbol}")
    return {
        "scope": "offline_source_evidence_only",
        "registryCounts": [len(registries[count]) for count in (10, 50, 100)],
        "additionalReviewed": len(proofs),
        "nativeOnlyAdditional": len(proofs),
        "nativeOnlySingletonGroups": len(proofs),
        "existingCrossVenueGroupsPreserved": 10,
        "candidateDecisions": decisions["decisionCounts"],
        "productionVersionIds": "not_claimed",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    print(json.dumps(verify(parser.parse_args().directory)))
