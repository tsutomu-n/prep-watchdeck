"""Production map qualification requires current DB evidence without upgrading legacy reviews."""

import copy
import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from prep_watchdeck_ranking.mapping import compile_map, qualification_summary
from prep_watchdeck_ranking.models import content_digest

ROOT = Path(__file__).resolve().parents[3]
UTILITY = runpy.run_path(str(ROOT / "scripts/ranking/prepare-mexc-map.py"))
prepare = UTILITY["prepare"]
verify = UTILITY["VERIFY"]
NOW = datetime(2026, 10, 10, 1, 0, tzinfo=UTC)


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, dict, dict]:
    data = ROOT / "apps/ranking-core/data"
    mapping, roster, evidence = [
        json.loads((data / name).read_text())
        for name in ("initial-map.json", "initial-roster.json", "qualification-evidence.json")
    ]
    captured = []
    reviews = []
    for item in roster["items"]:
        if item["venue"] != "mexc":
            continue
        proof = evidence["mexcQualification"][item["venueInstrumentId"]]
        row = next(
            row
            for row in mapping["rows"]
            if any(o["instrumentId"] == item["venueInstrumentId"] for o in row["originals"])
        )
        captured.append(
            {
                **item,
                "venueInstrumentVersionId": item["venueInstrumentVersionId"] + 100_000,
                "normalizedDefinition": proof["normalizedDefinition"],
                "definitionDigest": proof["definitionDigest"],
                "catalogEntry": evidence["catalogs"]["mexc"][item["sourceSymbol"]],
            }
        )
        reviews.append(
            {
                "sourceSymbol": item["sourceSymbol"],
                "rankingRowId": row["id"],
                "baseAsset": item["baseAsset"],
                "assetClass": "crypto",
                "identityEvidence": proof["identityEvidence"],
                "project": proof["identity"]["project"],
                "explicitFuturesLinkPresent": True,
                "finding": proof["finding"],
            }
        )
    roster["items"] = [item for item in roster["items"] if item["venue"] != "mexc"]
    roster["catalogFingerprint"] = content_digest(roster["items"])
    for row in mapping["rows"]:
        row["originals"] = [item for item in row["originals"] if item["venue"] != "mexc"]
    mapping = compile_map(roster, mapping).model_dump(mode="json", by_alias=True)
    evidence.update(mapVersion=mapping["version"])
    for name, value in zip(
        ("initial-map.json", "initial-roster.json", "qualification-evidence.json"),
        (mapping, roster, evidence),
        strict=True,
    ):
        (tmp_path / name).write_text(json.dumps(value))
    capture = {
        "observedAt": NOW.isoformat(),
        "captureScope": "production_read_only",
        "isolated": False,
        "versionsAssignedBy": "persist_catalog",
        "complete": True,
        "payloadHash": evidence["mexcAddition"]["nativeCatalogPayloadHash"],
        "coverage": evidence["mexcAddition"]["coverage"],
        "items": captured,
        "databaseAudit": {
            "sessionReadOnly": True,
            "databaseTarget": UTILITY["PRODUCTION_DATABASE_TARGET"],
            "currentRoster": [
                *roster["items"],
                *[{name: item[name] for name in UTILITY["IDENTITY_FIELDS"]} for item in captured],
            ],
            "currentMexcDefinitions": [
                {
                    "instrumentId": item["venueInstrumentId"],
                    "currentVersion": item["venueInstrumentVersionId"],
                    "validTo": None,
                    "normalizedDefinition": copy.deepcopy(item["normalizedDefinition"]),
                }
                for item in captured
            ],
        },
    }
    return tmp_path, capture, {"items": reviews}


def test_production_ids_bind_to_current_definitions_and_preserve_legacy_reviews(
    inputs: tuple[Path, dict, dict],
) -> None:
    directory, capture, reviews = inputs
    old = json.loads((directory / "initial-map.json").read_text())
    old_evidence = json.loads((directory / "qualification-evidence.json").read_text())
    result = prepare(directory, capture, reviews, capture_scope="production_read_only", now=NOW)
    mapping, roster, evidence = result
    compiled = compile_map(roster, mapping)
    assert qualification_summary(compiled)["quantityReview"] == 3
    assert qualification_summary(compiled)["widgetReview"] == 3
    assert evidence["quantityUnverified"] == old_evidence["quantityUnverified"]
    assert (
        roster["generatedAt"]
        == json.loads((directory / "initial-roster.json").read_text())["generatedAt"]
    )
    for previous, current in zip(old["rows"], mapping["rows"], strict=True):
        assert {k: v for k, v in previous.items() if k not in ("originals", "evidence")} == {
            k: v for k, v in current.items() if k not in ("originals", "evidence")
        }
        assert previous["originals"] == [o for o in current["originals"] if o["venue"] != "mexc"]
    assert evidence["mexcAddition"]["databaseAudit"] == capture["databaseAudit"]
    assert evidence["mexcAddition"]["captureScope"] == "production_read_only"
    for name, value in zip(
        ("initial-map.json", "initial-roster.json", "qualification-evidence.json"),
        result,
        strict=True,
    ):
        (directory / name).write_text(json.dumps(value))
    assert verify(directory)["quantityReview"] == 3


@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "isolated",
        "mutable",
        "target",
        "stale",
        "legacy_drift",
        "version",
        "definition",
        "closed",
    ],
)
def test_production_capture_rejects_unbound_or_unsafe_evidence(
    inputs: tuple[Path, dict, dict], fault: str
) -> None:
    directory, capture, reviews = inputs
    audit = capture["databaseAudit"]
    scope = "production_read_only"
    if fault == "scope":
        scope = "isolated"
    elif fault == "isolated":
        capture["isolated"] = True
    elif fault == "mutable":
        audit["sessionReadOnly"] = False
    elif fault == "target":
        audit["databaseTarget"] = {**audit["databaseTarget"], "port": 5432}
    elif fault == "stale":
        capture["observedAt"] = (NOW - timedelta(seconds=1801)).isoformat()
    elif fault == "legacy_drift":
        audit["currentRoster"][0] = {**audit["currentRoster"][0], "venueInstrumentVersionId": -1}
    elif fault == "version":
        audit["currentMexcDefinitions"][0]["currentVersion"] += 1
    elif fault == "definition":
        audit["currentMexcDefinitions"][0]["normalizedDefinition"]["contractMultiplier"] = "0.5"
    else:
        audit["currentMexcDefinitions"][0]["validTo"] = NOW.isoformat()
    with pytest.raises(ValueError):
        prepare(directory, capture, reviews, capture_scope=scope, now=NOW)


def test_isolated_capture_remains_candidate_only(inputs: tuple[Path, dict, dict]) -> None:
    directory, capture, reviews = inputs
    capture.pop("captureScope")
    capture.pop("databaseAudit")
    capture["isolated"] = True
    _mapping, _roster, evidence = prepare(directory, capture, reviews, now=NOW)
    assert evidence["mexcAddition"]["captureScope"] == "isolated"
    assert "production versions require requalification" in evidence["mexcAddition"]["versionScope"]
    assert evidence["mexcAddition"]["adoption"] == "candidate_only"
