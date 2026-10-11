"""Finite, resumable offline capture finalization with immutable input bindings."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from prep_watchdeck_market.bundle_files import BundleError
from prep_watchdeck_market.research.files import isolated_root, load_json


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise BundleError("research_path_invalid")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _atomic(path: Path, value: object) -> None:
    temporary = path.parent / f".{path.name}-{uuid4().hex}"
    with temporary.open("x") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _manifest(root: Path, deadline: float) -> dict[str, str]:
    files = {}
    for path in sorted(root.rglob("*")):
        if time.monotonic() >= deadline:
            raise TimeoutError
        if path.is_symlink():
            raise BundleError("research_path_invalid")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = _digest(path)
    return files


def finalize_capture(
    input_root: Path, output_root: Path, *, deadline_seconds: int
) -> dict[str, object]:
    source = input_root.absolute()
    if not source.is_dir() or any(part.is_symlink() for part in (source, *source.parents)):
        raise BundleError("research_path_invalid")
    output = isolated_root(output_root, (source,))
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(output / "finalizer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BundleError("research_finalizer_running") from None
        return _finalize(source, output, deadline_seconds)
    finally:
        os.close(descriptor)


def _finalize(source: Path, output: Path, seconds: int) -> dict[str, object]:
    deadline = time.monotonic() + seconds
    result: dict[str, Any] = {
        "schema_version": 1,
        "input_root": str(source),
        "capture_complete": None,
        "quality_eligible": None,
        "evaluation_status": "NOT_RUN",
        "finalization_status": "INCOMPLETE",
        "phase": "input_manifest",
    }
    checkpoint = output / "checkpoint.json"
    saved = load_json(checkpoint) if checkpoint.exists() else {"completed_phases": {}}
    phases = saved["completed_phases"]
    try:
        if seconds < 0:
            raise BundleError("research_deadline_invalid")
        files = _manifest(source, deadline)
        proof = load_json(output / "capture-completion.json")
        if proof.get("inputRoot") != str(source):
            raise BundleError("research_completion_identity_mismatch")
        binding = {
            "input_root": str(source),
            "files": files,
            "completion_sha256": _digest(output / "capture-completion.json"),
        }
        manifest = output / "input-manifest.json"
        if manifest.exists() and load_json(manifest) != binding:
            raise BundleError("research_input_changed")
        if not manifest.exists():
            _atomic(manifest, binding)
        for name, digest in phases.items():
            if _digest(output / f"{name}.json") != digest:
                raise BundleError("research_finalizer_checkpoint_changed")
        config = load_json(source / "capture-config.json")
        expected = config["samples"]
        if type(expected) is not int or not 1 <= expected <= 1440:
            raise BundleError("research_sample_count_invalid")
        snapshots = list((source / "daily/snapshots").glob("*/manifest.json"))
        if len(snapshots) != 1:
            raise BundleError("research_finalizer_snapshot_ambiguous")
        snapshot = snapshots[0].parent

        def phase(name: str) -> dict[str, Any]:
            result["phase"] = name
            path = output / f"{name}.json"
            if name not in phases:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                _atomic(
                    checkpoint,
                    {
                        "input_manifest_sha256": _digest(manifest),
                        "completed_phases": phases,
                        "phase": name,
                    },
                )
                action = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        __name__,
                        "--phase",
                        name,
                        "--snapshot",
                        str(snapshot),
                        "--source",
                        str(source),
                        "--output",
                        str(output),
                    ],
                    timeout=remaining,
                    capture_output=True,
                    check=False,
                )
                if action.returncode:
                    raise BundleError("research_finalizer_phase_failed")
                phases[name] = _digest(path)
                _atomic(
                    checkpoint,
                    {
                        "input_manifest_sha256": _digest(manifest),
                        "completed_phases": phases,
                        "phase": name,
                    },
                )
            return load_json(path)

        verification = phase("verify")
        quality = phase("quality")
        clean = (proof.get("serviceResult"), proof.get("exitCode"), proof.get("exitStatus")) == (
            "success",
            "exited",
            0,
        )
        quality_exit = (
            proof.get("serviceResult"),
            proof.get("exitCode"),
            proof.get("exitStatus"),
        ) == ("exit-code", "exited", 3) and not verification["qualified_for_ab"]
        complete = verification["observations"] == expected and (clean or quality_exit)
        result.update(
            capture_complete=complete,
            quality_eligible=verification["qualified_for_ab"],
            quality_reasons=verification["reasons"],
            quality=quality,
            observations=verification["observations"],
            expected_observations=expected,
            replay_valid=verification["replay_valid"],
            process=proof,
            input_manifest_sha256=_digest(manifest),
        )
        if complete and verification["qualified_for_ab"]:
            evaluation = phase("evaluate")
            result.update(evaluation_status=evaluation["status"], evaluation=evaluation)
        else:
            result["evaluation_reason"] = "quality_ineligible" if complete else "capture_incomplete"
        if _manifest(source, deadline) != files:
            raise BundleError("research_input_changed")
        result.update(finalization_status="COMPLETE", phase="complete")
    except (TimeoutError, subprocess.TimeoutExpired, KeyboardInterrupt):
        result["reason"] = "deadline_or_interruption"
    _atomic(output / "summary.json", result)
    return result


def _worker(name: str, snapshot: Path, source: Path, output: Path) -> None:
    if name == "verify":
        from prep_watchdeck_market.research.snapshot import verify_snapshot

        checked = verify_snapshot(snapshot)
        value = {
            "snapshot_sha256": checked.snapshot_sha256,
            "observations": len(checked.observations),
            "replay_valid": checked.replay_valid,
            "qualified_for_ab": checked.qualified_for_ab,
            "reasons": list(checked.reasons),
        }
    elif name == "quality":
        from prep_watchdeck_market.research.quality import quality_report

        value = quality_report(snapshot)
    elif name == "evaluate":
        from prep_watchdeck_market.research.evaluation import evaluate_trial
        from prep_watchdeck_market.research.trials import bind_trial

        config = load_json(source / "capture-config.json")
        registration = Path(config["registration"])
        if not registration.is_relative_to(source):
            raise BundleError("research_registration_outside_input")
        trial = bind_trial(registration, snapshot, output / "trials")
        result = evaluate_trial(trial, snapshot, output / "results")
        value = {**load_json(result / "result.json"), "bundle": str(result)}
    else:
        raise BundleError("research_finalizer_phase_invalid")
    _atomic(output / f"{name}.json", value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("verify", "quality", "evaluate"), required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    _worker(arguments.phase, arguments.snapshot, arguments.source, arguments.output)
