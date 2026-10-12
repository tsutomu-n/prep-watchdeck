import runpy
import subprocess
import sys
from pathlib import Path

from prep_watchdeck_attention.config import AttentionSettings

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/attention/run-isolated.py"


def test_runner_has_only_attention_writable_and_rejects_unsafe_arguments(tmp_path):
    market, ranking, state = (tmp_path / name for name in ("market", "ranking", "attention"))
    market.mkdir()
    ranking.mkdir()
    settings = AttentionSettings(state, market, ranking, port=18770, ranking_port=18769)
    command = runpy.run_path(str(SCRIPT))["build_command"](settings, 1, "/usr/bin/bwrap")
    assert command.count("--bind") == 1
    assert command[command.index("--bind") + 1 : command.index("--bind") + 3] == [str(state)] * 2
    assert command.index("--tmpfs") < command.index("--bind")
    assert command.count("--ro-bind") == 3
    assert "--clearenv" in command and "--die-with-parent" in command
    for extra in (("--state-dir", str(market)), ("--port", "8769"), ("--host", "0.0.0.0")):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--state-dir",
                str(state),
                "--market-state-dir",
                str(market),
                "--ranking-state-dir",
                str(ranking),
                *extra,
            ],
            capture_output=True,
        )
        assert result.returncode == 2
        assert not state.exists()
