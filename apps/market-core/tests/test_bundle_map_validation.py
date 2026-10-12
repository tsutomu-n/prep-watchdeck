"""Frozen map bytes must retain their roster, catalog and qualification meaning."""

import json
from pathlib import Path
from typing import Any

import pytest

from prep_watchdeck_market.bundle_map_validation import (
    MAP_VALIDATOR_SOURCE_FILES,
    validate_map_snapshot,
)


@pytest.fixture
def snapshots() -> tuple[dict[str, bytes], dict[str, bytes]]:
    repository = Path(__file__).resolve().parents[3]
    source = {name: (repository / name).read_bytes() for name in MAP_VALIDATOR_SOURCE_FILES}
    directory = repository / "apps/ranking-core/data"
    mapping = {
        name: (directory / name).read_bytes()
        for name in ("initial-map.json", "initial-roster.json", "qualification-evidence.json")
    }
    validation = {
        "mapVersion": "d8d57399f2baa663005c35d8",
        "instruments": 1106,
        "rows": 577,
        "states": {"verified": 536, "unsupported": 41},
        "widgetBindings": 532,
        "review": 0,
        "quantityReview": 3,
        "widgetReview": 3,
        "rankingQualified": True,
        "quantityQualified": False,
        "widgetQualified": False,
        "qualificationComplete": False,
        "adoption": "candidate_only",
    }
    mapping["validation.json"] = json.dumps(validation).encode()
    return source, mapping


def test_consistent_partial_candidate_keeps_its_unqualified_state(
    snapshots: tuple[dict[str, bytes], dict[str, bytes]],
) -> None:
    source, mapping = snapshots
    summary = validate_map_snapshot(source, mapping)
    assert summary["mapVersion"] == "d8d57399f2baa663005c35d8"
    assert summary["qualificationComplete"] is False
    assert summary["quantityReview"] == 3
    assert json.loads(mapping["validation.json"])["adoption"] == "candidate_only"


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("initial-roster.json", "bundle_map_semantics_invalid"),
        ("qualification-evidence.json", "bundle_map_semantics_invalid"),
        ("validation.json", "bundle_map_validation_mismatch"),
    ],
)
def test_matching_version_labels_do_not_accept_inconsistent_contents(
    snapshots: tuple[dict[str, bytes], dict[str, bytes]], name: str, reason: str
) -> None:
    source, mapping = snapshots
    changed: dict[str, Any] = json.loads(mapping[name])
    if name == "initial-roster.json":
        changed["catalogFingerprint"] = "0" * 64
    elif name == "qualification-evidence.json":
        decisions = json.loads(mapping["initial-map.json"])
        reference = next(
            row["reference"]
            for row in decisions["rows"]
            if row["reference"] is not None and row["reference"]["provider"] == "bybit"
        )
        changed["catalogs"]["bybit"][reference["symbol"]]["baseCoin"] = "WRONG_ASSET"
    else:
        changed["quantityReview"] = 0
    mapping[name] = json.dumps(changed).encode()
    with pytest.raises(ValueError, match=reason):
        validate_map_snapshot(source, mapping)
