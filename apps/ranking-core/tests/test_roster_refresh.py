"""A roster refresh cannot admit partial catalogs or silently rewrite asset bindings."""

import copy
import json
import runpy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
UTILITY = runpy.run_path(str(ROOT / "scripts/ranking/refresh-roster-candidate.py"))
prepare = UTILITY["prepare"]
output_directory = UTILITY["output_directory"]
NOW = int(datetime(2026, 10, 2, 5, 0, tzinfo=UTC).timestamp() * 1000)


@pytest.fixture(scope="module")
def inputs() -> dict[str, Any]:
    data = ROOT / "apps/ranking-core/data"
    mapping = json.loads((data / "initial-map.json").read_text())
    old_roster = json.loads((data / "initial-roster.json").read_text())
    evidence = json.loads((data / "qualification-evidence.json").read_text())
    timestamp = datetime.fromtimestamp(NOW / 1000, UTC).isoformat()
    roster: dict[str, Any] = {**copy.deepcopy(old_roster), "generatedAt": timestamp}
    service = {
        "status": "ready",
        "generatedAt": timestamp,
        "catalog": {"status": "ready", "latestAt": timestamp},
        "l1": {"status": "ready", "latestAt": timestamp},
        "collectors": [
            {
                "runKind": "catalog",
                "status": "succeeded",
                "recordsReceived": len(roster["items"]),
                "recordsWritten": len(roster["items"]),
            }
        ],
    }
    return {
        "roster": roster,
        "service": service,
        "previous_roster": old_roster,
        "previous_map": mapping,
        "previous_evidence": evidence,
        "catalogs": {"observedAt": timestamp, "catalogs": evidence["catalogs"], "complete": True},
        "definitions": {
            "observedAt": timestamp,
            "sessionReadOnly": True,
            "databaseTarget": {
                "host": "127.0.0.1",
                "port": 55432,
                "database": "prep_watchdeck_market",
            },
            "items": [
                {
                    "instrumentId": i["venueInstrumentId"],
                    "currentVersion": i["venueInstrumentVersionId"],
                    "currentDefinition": {
                        "active": i["active"],
                        "market_type": i["marketType"],
                        "base_asset": i["baseAsset"],
                        "quote_asset": i["quoteAsset"],
                        "settle_asset": i["settleAsset"],
                        "collateral_asset": i["collateralAsset"],
                    },
                }
                for i in roster["items"]
            ],
        },
        "decisions": copy.deepcopy(mapping),
        "reviews": {},
        "now": NOW,
    }


@pytest.mark.parametrize("failure", ["partial", "truncated", "stale", "mutable_audit"])
def test_incomplete_or_stale_evidence_cannot_remove_contracts(inputs: dict, failure: str) -> None:
    value = copy.deepcopy(inputs)
    if failure == "partial":
        value["service"]["catalog"]["status"] = "partial"
    elif failure == "truncated":
        value["service"]["collectors"][0]["recordsReceived"] -= 1
    elif failure == "stale":
        value["catalogs"]["observedAt"] = NOW - 1_801_000
    else:
        value["definitions"]["sessionReadOnly"] = False
    with pytest.raises(ValueError):
        prepare(**value)


def test_new_version_does_not_requalify_changed_quantity(inputs: dict) -> None:
    value = copy.deepcopy(inputs)
    entry = value["roster"]["items"][0]
    old_version = entry["venueInstrumentVersionId"]
    entry["venueInstrumentVersionId"] += 100_000
    from prep_watchdeck_ranking.models import content_digest

    value["roster"]["catalogFingerprint"] = content_digest(value["roster"]["items"])
    proof = value["definitions"]["items"][0]
    proof.update(
        currentVersion=entry["venueInstrumentVersionId"],
        previousVersion=old_version,
        normalizedDefinitionChanges={"contract_multiplier": ["1", "1000"]},
    )
    with pytest.raises(ValueError, match="contract identity or quantity changed"):
        prepare(**value)


def test_catalog_refresh_cannot_switch_fixed_provider(inputs: dict) -> None:
    value = copy.deepcopy(inputs)
    row = next(row for row in value["decisions"]["rows"] if row["status"] == "verified")
    row["reference"]["revision"] = "different-contract"
    row["widget"].update(status="review", symbol=None, referenceKey=None)
    with pytest.raises(ValueError, match="approved fixed reference"):
        prepare(**value)


def test_candidate_output_never_overwrites_live_or_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="overlaps"):
        output_directory(ROOT / "apps/ranking-core/data/candidate", [])
    with pytest.raises(ValueError, match="overlaps"):
        output_directory(Path.home() / ".local/share/prep-watchdeck-ranking/candidate", [])
    candidate = tmp_path / "new-candidate"
    assert output_directory(candidate, []) == candidate
    candidate.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        output_directory(candidate, [])
