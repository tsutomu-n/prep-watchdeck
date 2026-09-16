import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
verify = runpy.run_path(str(ROOT / "scripts/ranking/verify-map-evidence.py"))["verify"]


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
