"""The tmpfs cannot hide explicit scratch inputs or the writable Ranking state."""

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_scratch_mounts_follow_tmpfs_and_only_ranking_is_writable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "market"
    original.mkdir()
    state = tmp_path / "ranking"
    mapping = tmp_path / "sample-map.json"
    mapping.write_text("{}")
    commands = []
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr("os.execv", lambda executable, command: commands.append(command))
    monkeypatch.setattr(
        "sys.argv",
        [
            "run-isolated.py",
            "--state-dir",
            str(state),
            "--original-state-dir",
            str(original),
            "--mapping",
            str(mapping),
            "--port",
            "19869",
            "--run-seconds",
            "1",
        ],
    )
    runpy.run_path(str(ROOT / "scripts/ranking/run-isolated.py"), run_name="__main__")
    command = commands[0]
    mounts = [
        command[index : index + 3]
        for index, value in enumerate(command)
        if value in ("--bind", "--ro-bind")
    ]
    assert mounts == [
        ["--ro-bind", "/", "/"],
        ["--ro-bind", str(original), str(original)],
        ["--ro-bind", str(mapping), str(mapping)],
        ["--bind", str(state), str(state)],
    ]
    assert command.index("--tmpfs") < command.index(str(original))
    assert command.index("--tmpfs") < command.index(str(state))
    assert state.is_dir()
