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


def _save_bundle(directory: Path, result: tuple[dict, ...]) -> None:
    for name, value in zip(
        ("initial-map.json", "initial-roster.json", "qualification-evidence.json"),
        result,
        strict=True,
    ):
        (directory / name).write_text(json.dumps(value))


def _native_fixture(template: dict, number: int) -> tuple[dict, dict]:
    """Synthetic identities are used only in this offline scale regression."""
    item = copy.deepcopy(template)
    asset = f"SCALE{number:03d}"
    symbol = asset + "_USDT"
    item.update(
        venueInstrumentId="mexc:" + symbol,
        venueInstrumentVersionId=200_000 + number,
        sourceSymbol=symbol,
        baseAsset=asset,
        groupId=None,
        mappingMethod="unmapped",
    )
    definition = item["normalizedDefinition"]
    definition.update(sourceSymbol=symbol, baseAsset=asset)
    raw = definition["rawDefinition"]
    raw.update(symbol=symbol, baseCoin=asset)
    raw["watchdeckIdentityEvidence"].update(base_asset=asset, project=asset)
    item["catalogEntry"].update(symbol=symbol, baseCoin=asset)
    item["definitionDigest"] = content_digest(definition)
    review = {
        "sourceSymbol": symbol,
        "rankingRowId": "mexc-native:" + symbol,
        "baseAsset": asset,
        "assetClass": "crypto",
        "identityEvidence": ["https://www.mexc.com/price/" + asset],
        "project": asset,
        "explicitFuturesLinkPresent": True,
        "finding": "Synthetic native identity fixture; no cross-market reference reviewed.",
        "nativeOnly": True,
        "reason": "fixed_reference_unverified",
    }
    return item, review


def _extend_capture(capture: dict, reviews: dict, count: int) -> tuple[dict, dict]:
    enlarged = copy.deepcopy(capture)
    enlarged_reviews = copy.deepcopy(reviews)
    for number in range(len(capture["items"]) + 1, count + 1):
        item, review = _native_fixture(capture["items"][0], number)
        enlarged["items"].append(item)
        enlarged_reviews["items"].append(review)
    audit = enlarged["databaseAudit"]
    audit["currentRoster"] = [
        *[item for item in audit["currentRoster"] if item["venue"] != "mexc"],
        *[{name: item[name] for name in UTILITY["IDENTITY_FIELDS"]} for item in enlarged["items"]],
    ]
    audit["currentMexcDefinitions"] = [
        {
            "instrumentId": item["venueInstrumentId"],
            "currentVersion": item["venueInstrumentVersionId"],
            "validTo": None,
            "normalizedDefinition": copy.deepcopy(item["normalizedDefinition"]),
        }
        for item in enlarged["items"]
    ]
    return enlarged, enlarged_reviews


def test_addition_is_idempotent_and_preserves_original_review_observation(inputs) -> None:
    directory, capture, reviews = inputs
    first = prepare(directory, capture, reviews, capture_scope="production_read_only", now=NOW)
    _save_bundle(directory, first)
    repeated = prepare(directory, capture, reviews, capture_scope="production_read_only", now=NOW)
    assert repeated == first


def test_ten_to_fifty_to_one_hundred_preserves_qualified_rows_and_native_only_coverage(
    inputs,
) -> None:
    directory, capture, reviews = inputs
    first = prepare(directory, capture, reviews, capture_scope="production_read_only", now=NOW)
    _save_bundle(directory, first)
    for count in (50, 100):
        expanded_capture, expanded_reviews = _extend_capture(capture, reviews, count)
        result = prepare(
            directory,
            expanded_capture,
            expanded_reviews,
            capture_scope="production_read_only",
            now=NOW,
        )
        mapping, roster, evidence = result
        assert sum(item["venue"] == "mexc" for item in roster["items"]) == count
        previous_rows = {row["id"]: row for row in first[0]["rows"]}
        assert {
            row["id"]: row for row in mapping["rows"] if row["id"] in previous_rows
        } == previous_rows
        for key, qualification in first[2]["mexcQualification"].items():
            assert evidence["mexcQualification"][key] == qualification
        assert evidence["quantityUnverified"] == first[2]["quantityUnverified"]
        native_rows = [row for row in mapping["rows"] if row["id"].startswith("mexc-native:")]
        assert len(native_rows) == count - 10
        assert all(
            row["reference"] is None
            and row["status"] == "review"
            and row["reason"] == "fixed_reference_unverified"
            and row["evidence"]
            for row in native_rows
        )
        _save_bundle(directory, result)
        assert verify(directory)["review"] == count - 10
        assert (
            prepare(
                directory,
                expanded_capture,
                expanded_reviews,
                capture_scope="production_read_only",
                now=NOW,
            )
            == result
        )


def test_existing_identity_changes_cannot_be_hidden_by_a_fresh_capture(inputs) -> None:
    directory, capture, reviews = inputs
    first = prepare(directory, capture, reviews, capture_scope="production_read_only", now=NOW)
    _save_bundle(directory, first)
    changed = copy.deepcopy(capture)
    item = changed["items"][0]
    item["normalizedDefinition"]["contractMultiplier"] = "123.5"
    item["normalizedDefinition"]["rawDefinition"]["contractSize"] = "123.5"
    item["normalizedDefinition"]["rawDefinition"]["watchdeckQuantityEvidence"][
        "base_per_contract"
    ] = "123.5"
    item["catalogEntry"]["contractSize"] = "123.5"
    item["definitionDigest"] = content_digest(item["normalizedDefinition"])
    changed["databaseAudit"]["currentMexcDefinitions"][0]["normalizedDefinition"] = copy.deepcopy(
        item["normalizedDefinition"]
    )
    with pytest.raises(ValueError, match="requalification"):
        prepare(directory, changed, reviews, capture_scope="production_read_only", now=NOW)
