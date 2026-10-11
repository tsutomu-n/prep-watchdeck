from __future__ import annotations

import json
from pathlib import Path

from prep_watchdeck_market.bundle_files import sha256
from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
from tests.test_research_journal import Clock, native_payload, record


def study(tmp_path: Path) -> tuple[Path, Path]:
    source, output = tmp_path / "study", tmp_path / "finalized"
    source.mkdir()
    output.mkdir()
    with ObservationJournal(source / "daily/journal", clock=Clock()) as journal:
        data = native_payload()
        data["window_start"] = "2026-10-09T00:00:00Z"
        record(journal, data, Clock())
    export_snapshot(source / "daily/journal", source / "daily/snapshots")
    (source / "capture-config.json").write_text(json.dumps({"samples": 1}))
    (output / "capture-completion.json").write_text(
        json.dumps(
            {
                "inputRoot": str(source),
                "serviceResult": "exit-code",
                "exitCode": "exited",
                "exitStatus": 3,
                "evidence": "isolated test process receipt",
            }
        )
    )
    return source, output


def hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def test_quality_exit_three_is_complete_but_ineligible(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.finalizer import finalize_capture

    source, output = study(tmp_path)
    before = hashes(source)
    result = finalize_capture(source, output, deadline_seconds=30)
    assert result["capture_complete"] is True
    assert result["quality_eligible"] is False
    assert result["evaluation_status"] == "NOT_RUN"
    assert result["finalization_status"] == "COMPLETE"
    assert "research_candle_gap" in result["quality_reasons"]
    assert hashes(source) == before
    assert finalize_capture(source, output, deadline_seconds=30) == result


def test_finalizer_deadline_preserves_input_and_reports_incomplete(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.finalizer import finalize_capture

    source, output = study(tmp_path)
    before = hashes(source)
    result = finalize_capture(source, output, deadline_seconds=0)
    assert result["finalization_status"] == "INCOMPLETE"
    assert result["evaluation_status"] == "NOT_RUN"
    assert result["phase"] == "input_manifest"
    assert hashes(source) == before
    completed = finalize_capture(source, output, deadline_seconds=30)
    assert completed["finalization_status"] == "COMPLETE"
    assert completed["quality_eligible"] is False
