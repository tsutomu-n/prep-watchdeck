import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
verify = runpy.run_path(str(ROOT / "scripts/ranking/verify-map-evidence.py"))["verify"]
verify_mexc_original = runpy.run_path(str(ROOT / "scripts/ranking/verify-map-evidence.py"))[
    "verify_mexc_original"
]


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("quantity_missing", "original quantity review ledger differs"),
        ("quantity_duplicate", "original quantity review ledger differs"),
        ("identity_missing", "independent ranking qualification absent"),
        ("reference_changed", "independent ranking qualification absent"),
    ],
)
def test_independent_qualification_cannot_lose_its_evidence(
    tmp_path: Path, fault: str, message: str
) -> None:
    for name in ("initial-map.json", "initial-roster.json", "qualification-evidence.json"):
        (tmp_path / name).write_bytes((ROOT / "apps/ranking-core/data" / name).read_bytes())
    verify(tmp_path)
    path = tmp_path / "qualification-evidence.json"
    evidence = json.loads(path.read_text())
    if fault == "quantity_missing":
        evidence["quantityUnverified"].pop()
    elif fault == "quantity_duplicate":
        evidence["quantityUnverified"].append(evidence["quantityUnverified"][0])
    elif fault == "identity_missing":
        evidence["rankingQualification"]["crypto:CHEEMS"]["identityEvidence"] = []
    else:
        evidence["rankingQualification"]["crypto:CHEEMS"]["referenceKey"] = "other-contract"
    path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match=message):
        verify(tmp_path)


@pytest.mark.parametrize("fault", [None, "size_as_price", "changed_version", "quantity_changed"])
def test_mexc_exact_version_price_identity_is_independent_of_contract_size(
    fault: str | None,
) -> None:
    from prep_watchdeck_ranking.models import OriginalInstrument, content_digest

    from .conftest import reference

    ref = reference("DOGEUSDT")
    original = OriginalInstrument(
        venue="mexc",
        instrument_id="mexc:DOGE_USDT",
        version_id=17,
        symbol="DOGE_USDT",
        base_asset="DOGE",
        multiplier=1,
    )
    entry = {
        "symbol": "DOGE_USDT",
        "baseCoin": "DOGE",
        "quoteCoin": "USDT",
        "settleCoin": "USDT",
        "futureType": 1,
        "state": 0,
        "type": 1,
        "contractSize": 100,
    }
    definition = {
        "venue": "mexc",
        "sourceSymbol": "DOGE_USDT",
        "baseAsset": "DOGE",
        "quantityUnit": "contracts",
        "contractMultiplier": "100",
        "rawDefinition": {
            **entry,
            "watchdeckIdentityEvidence": {
                "identity_price_multiplier": "1",
            },
        },
    }
    proof = {
        "versionId": 17,
        "symbol": "DOGE_USDT",
        "baseAsset": "DOGE",
        "priceMultiplier": 1,
        "referenceKey": ref.key,
        "catalogEntryDigest": content_digest(entry),
        "definitionDigest": content_digest(definition),
        "normalizedDefinition": definition,
        "observedAt": "2026-10-10T00:00:00Z",
        "identityEvidence": ["isolated-fixture-identity"],
        "priceEvidence": ["isolated-fixture-price-definition"],
        "identity": {"assetClass": "crypto", "project": "Dogecoin"},
        "baseQuantityPerContract": "100",
    }
    evidence = {
        "catalogs": {"mexc": {"DOGE_USDT": entry}},
        "mexcQualification": {"mexc:DOGE_USDT": proof},
    }
    if fault == "size_as_price":
        original = original.model_copy(update={"multiplier": 100})
        proof["priceMultiplier"] = 100
    elif fault == "changed_version":
        original = original.model_copy(update={"version_id": 18})
    elif fault == "quantity_changed":
        proof["baseQuantityPerContract"] = "1"
    if fault:
        with pytest.raises(ValueError, match="MEXC"):
            verify_mexc_original(original, ref, evidence)
    else:
        verify_mexc_original(original, ref, evidence)
