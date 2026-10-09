from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from prep_watchdeck_market.cli import app
from tests.test_research_journal import Clock, native_payload, record


def test_offline_commands_work_without_database_settings(tmp_path: Path, monkeypatch) -> None:
    from prep_watchdeck_market.research.journal import ObservationJournal

    monkeypatch.delenv("PREP_WATCHDECK_MARKET_DATABASE_URL", raising=False)
    clock = Clock()
    with ObservationJournal(tmp_path / "journal", clock=clock) as journal:
        record(journal, native_payload(), clock)
    runner = CliRunner()
    exported = runner.invoke(
        app,
        [
            "research",
            "export-snapshot",
            "--journal",
            str(tmp_path / "journal"),
            "--output-dir",
            str(tmp_path / "snapshots"),
        ],
    )
    assert exported.exit_code == 0, exported.output
    snapshot = json.loads(exported.output)["path"]
    verified = runner.invoke(app, ["research", "verify-snapshot", "--snapshot", snapshot])
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.output)["observed_evidence"] is False
    quality = runner.invoke(
        app,
        ["research", "quality", "--snapshot", snapshot, "--output-dir", str(tmp_path / "quality")],
    )
    assert quality.exit_code == 0, quality.output
    assert (Path(json.loads(quality.output)["path"]) / "report.json").is_file()


def test_invalid_json_and_settings_do_not_expose_input(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_DATABASE_URL", "private-value-must-not-leak")
    runner = CliRunner()
    observe = runner.invoke(
        app,
        [
            "research",
            "observe",
            "--journal",
            str(tmp_path / "journal"),
            "--instrument",
            "bitget:TESTUSDT",
        ],
    )
    assert observe.exit_code == 2
    assert "private-value" not in observe.output
    assert json.loads(observe.output)["error"] == "research_settings_invalid"
    request = tmp_path / "invalid.json"
    request.write_text('{"secret":"private-value", "secret":NaN}')
    result = runner.invoke(
        app,
        [
            "research",
            "inspect-funding",
            "--manifest",
            str(request),
            "--output-dir",
            str(tmp_path / "report"),
        ],
    )
    assert result.exit_code == 2
    assert "private-value" not in result.output


def test_observe_interrupt_preserves_failure_receipt(tmp_path: Path, monkeypatch) -> None:
    from prep_watchdeck_market import research_cli
    from prep_watchdeck_market.research.files import load_json

    monkeypatch.setenv(
        "PREP_WATCHDECK_MARKET_DATABASE_URL",
        "postgresql://prep_watchdeck_market:synthetic@127.0.0.1:55432/prep_watchdeck_market",
    )

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(research_cli, "read_observation", interrupt)
    result = CliRunner().invoke(
        app,
        [
            "research",
            "observe",
            "--journal",
            str(tmp_path / "journal"),
            "--instrument",
            "bitget:TESTUSDT",
        ],
    )
    assert result.exit_code == 130, result.output
    receipt = next((tmp_path / "journal" / "receipts").glob("*/receipt.json"))
    assert load_json(receipt)["reasons"] == ["research_interrupted"]


def test_fifo_input_is_rejected_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "input"
    os.mkfifo(fifo)
    code = (
        "from pathlib import Path; "
        "from prep_watchdeck_market.research.files import load_json; "
        f"load_json(Path({str(fifo)!r}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=3, check=False
    )
    assert result.returncode != 0
    assert "bundle_file_invalid" in result.stderr


def test_extreme_decimal_exponents_are_bounded() -> None:
    import pytest

    from prep_watchdeck_market.bundle_files import BundleError
    from prep_watchdeck_market.research.models import number

    with pytest.raises(BundleError, match="research_number_invalid"):
        number("1e-100000")


def test_invalid_funding_source_shape_returns_safe_error(tmp_path: Path) -> None:
    manifest = tmp_path / "funding.json"
    for source in (None, "raw-private-value", []):
        manifest.write_text(
            json.dumps(
                {
                    "venue": "bitget",
                    "category": "USDT-FUTURES",
                    "symbol": "TESTUSDT",
                    "window_start": "2026-10-09T00:00:00Z",
                    "window_end": "2026-10-10T00:00:00Z",
                    "sources": [source],
                }
            )
        )
        result = CliRunner().invoke(
            app,
            [
                "research",
                "inspect-funding",
                "--manifest",
                str(manifest),
                "--output-dir",
                str(tmp_path / "report"),
            ],
        )
        assert result.exit_code == 2
        assert json.loads(result.output)["error"] == "research_source_path_invalid"
