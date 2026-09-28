import copy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prep_watchdeck_ranking.cli import main
from prep_watchdeck_ranking.mapping import compile_map
from prep_watchdeck_ranking.models import content_digest

from .conftest import CUTOFF, mapping


def input_pair() -> tuple[dict, dict]:
    decisions = mapping("BTC").model_dump(mode="json", by_alias=True)
    original = decisions["rows"][0]["originals"][0]
    items = [
        {
            "venue": original["venue"],
            "venueInstrumentId": original["instrumentId"],
            "venueInstrumentVersionId": original["versionId"],
            "sourceSymbol": original["symbol"],
            "baseAsset": original["baseAsset"],
        }
    ]
    roster = {
        "items": items,
        "generatedAt": datetime.fromtimestamp(CUTOFF / 1000, UTC).isoformat(),
        "sourcePath": "isolated-fixture",
        "catalogFingerprint": content_digest(items),
    }
    return roster, decisions


def test_compilation_binds_every_original_and_is_deterministic() -> None:
    roster, decisions = input_pair()
    first = compile_map(roster, decisions)
    assert first.source_instrument_count == 1
    assert first.version == compile_map(copy.deepcopy(roster), copy.deepcopy(decisions)).version
    decisions["rows"][0]["originals"][0]["versionId"] += 1
    with pytest.raises(ValueError, match="original contract changed"):
        compile_map(roster, decisions)


@pytest.mark.parametrize("corruption", ["duplicate", "fingerprint", "naive_time", "omission"])
def test_corrupt_or_incomplete_roster_cannot_qualify(corruption: str) -> None:
    roster, decisions = input_pair()
    if corruption == "duplicate":
        roster["items"].append(copy.deepcopy(roster["items"][0]))
        roster["catalogFingerprint"] = content_digest(roster["items"])
    elif corruption == "fingerprint":
        roster["catalogFingerprint"] = "stale-proof"
    elif corruption == "naive_time":
        roster["generatedAt"] = "2026-09-12T01:00:00"
    else:
        decisions["rows"] = []
    with pytest.raises(ValueError):
        compile_map(roster, decisions)


@pytest.mark.parametrize("status", ["unsupported", "out_of_scope"])
@pytest.mark.parametrize("missing", ["reason", "evidence"])
def test_exclusion_cannot_replace_missing_qualification(status: str, missing: str) -> None:
    roster, decisions = input_pair()
    row = decisions["rows"][0]
    row.update(status=status, reference=None, reason="reviewed exclusion")
    row["widget"].update(status="unsupported", symbol=None, referenceKey=None)
    row[missing] = None if missing == "reason" else []
    with pytest.raises(ValueError, match="reason and evidence"):
        compile_map(roster, decisions)


def test_review_gate_includes_widget_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roster, decisions = input_pair()
    decisions["rows"][0]["widget"].update(status="review", symbol=None, referenceKey=None)
    candidate = compile_map(roster, decisions)
    path = tmp_path / "map.json"
    path.write_text(candidate.model_dump_json(by_alias=True))
    monkeypatch.setattr(
        "sys.argv", ["watchdeck-ranking", "validate-map", str(path), "--require-reviewed"]
    )
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 1


@pytest.mark.parametrize("missing", ["reason", "evidence"])
def test_widget_unsupported_cannot_replace_unreviewed_contract(missing: str) -> None:
    roster, decisions = input_pair()
    widget = decisions["rows"][0]["widget"]
    widget.update(
        status="unsupported",
        symbol=None,
        referenceKey=None,
        reason="reference contract absent from reviewed Widget catalog",
        evidence=["reviewed-widget-catalog"],
    )
    assert compile_map(roster, decisions).rows[0].reference is not None
    widget[missing] = None if missing == "reason" else []
    with pytest.raises(ValueError, match="unsupported Widget requires a reason and evidence"):
        compile_map(roster, decisions)
