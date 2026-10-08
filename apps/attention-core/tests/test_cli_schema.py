import subprocess
import sys
from pathlib import Path

from prep_watchdeck_attention.cli import freeze_default_family
from prep_watchdeck_attention.storage import AttentionStore


def test_schema_check_mode_detects_drift(tmp_path):
    script = Path(__file__).resolve().parents[3] / "scripts/attention/generate-schema.py"
    command = [sys.executable, str(script), "--output-dir", str(tmp_path / "schemas")]
    assert subprocess.run([*command, "--check"], capture_output=True).returncode != 0
    assert subprocess.run(command, capture_output=True).returncode == 0
    assert subprocess.run([*command, "--check"], capture_output=True).returncode == 0
    target = tmp_path / "schemas/attention-response.schema.json"
    target.write_text("{}")
    assert subprocess.run([*command, "--check"], capture_output=True).returncode != 0


def test_freeze_is_idempotent_and_cannot_silently_change_family(tmp_path):
    import pytest

    with_store = AttentionStore(tmp_path / "attention")
    try:
        policies = freeze_default_family(with_store, "example")
        assert len(policies) == 16
        assert {p.horizon_minutes for p in policies} == {15, 60}
        assert freeze_default_family(with_store, "example") == policies
        with pytest.raises(ValueError, match="frozen"):
            freeze_default_family(with_store, "example", delta=0.2)
        changed = policies[0].model_copy(update={"version": "changed"})
        with pytest.raises(ValueError, match="conflict"):
            with_store.freeze_family((changed, *policies[1:]))
    finally:
        with_store.close()


def test_status_does_not_create_state_on_unavailable_loopback(tmp_path):
    # Port 1 is invalid before a request; status must not create even a writer lock.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "prep_watchdeck_attention.cli",
            "status",
            "--state-dir",
            str(tmp_path / "state"),
            "--port",
            "1",
        ],
        capture_output=True,
    )
    assert result.returncode == 2
    assert not (tmp_path / "state").exists()
