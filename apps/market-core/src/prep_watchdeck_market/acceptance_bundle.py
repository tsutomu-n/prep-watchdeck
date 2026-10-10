"""Build a local, unapproved review bundle from an immutable Git commit.

The staged release is separate from the proposed production destination. This tool never
installs units, adopts a map, writes a database or starts an observation.
"""

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAP_FILES = (
    "initial-map.json",
    "initial-roster.json",
    "qualification-evidence.json",
    "validation.json",
)
PRODUCTION_RELEASES = Path("/home/tn/releases/prep-watchdeck")
PRODUCTION_MAPS = Path("/home/tn/releases/prep-watchdeck-ranking-maps")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular_bytes(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INPUT_BYTES:
            raise ValueError("bundle_input_not_bounded_regular_file")
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("bundle_input_too_large")
    return raw


def _object(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("bundle_input_not_object")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in (".", "..") for part in path.parts):
        raise ValueError("bundle_path_invalid")
    return path


def _helper_inputs(manifest_path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    manifest = _object(_regular_bytes(manifest_path))
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > 128:
        raise ValueError("helper_manifest_invalid")
    raw_files = {}
    for name, expected in files.items():
        if not isinstance(name, str) or len(_safe_relative(name).parts) != 1:
            raise ValueError("helper_manifest_path_invalid")
        raw = _regular_bytes(manifest_path.parent / name)
        if _digest(raw) != expected:
            raise ValueError("helper_hash_mismatch")
        raw_files[name] = raw
    return manifest, raw_files


def _source(repository: Path, ref: str) -> tuple[str, dict[str, bytes], dict[str, int]]:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"],
        cwd=repository,
        capture_output=True,
        check=False,
        timeout=15,
    )
    commit = result.stdout.decode().strip()
    if result.returncode or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("bundle_git_ref_invalid")
    result = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=repository,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode or len(result.stdout) > MAX_SOURCE_BYTES:
        raise ValueError("bundle_git_archive_failed")
    files, modes, total = {}, {}, 0
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        for member in archive:
            _safe_relative(member.name)
            if member.isdir():
                continue
            if not member.isfile() or member.size > MAX_INPUT_BYTES:
                raise ValueError("bundle_source_member_invalid")
            total += member.size
            if total > MAX_SOURCE_BYTES:
                raise ValueError("bundle_source_too_large")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("bundle_source_member_invalid")
            files[member.name] = stream.read()
            modes[member.name] = 0o755 if member.mode & 0o111 else 0o644
    return commit, files, modes


def _dependency(path: Path, expected: str, dependencies: dict[str, bytes]) -> str:
    raw = _regular_bytes(path)
    if _digest(raw) != expected:
        raise ValueError("bundle_dependency_hash_mismatch")
    if path.name in dependencies and dependencies[path.name] != raw:
        raise ValueError("bundle_dependency_name_collision")
    dependencies[path.name] = raw
    return path.name


def _run_build(release: Path, log: Path) -> None:
    environment = dict(os.environ)
    environment["UV_PROJECT_ENVIRONMENT"] = str(release / ".venv")
    environment["PYTHONNOUSERSITE"] = "1"
    with log.open("xb") as stream:
        for command, cwd in (
            (["uv", "sync", "--frozen", "--all-packages"], release),
            (["bun", "install", "--frozen-lockfile"], release / "apps/web"),
            (["bun", "run", "build"], release / "apps/web"),
        ):
            result = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=600,
            )
            if result.returncode:
                raise ValueError("bundle_build_failed")


def _runtime_files(release: Path) -> dict[str, str]:
    files = {}
    for relative in (
        ".venv/pyvenv.cfg",
        ".venv/bin/watchdeck-market",
        ".venv/bin/watchdeck-ranking",
        ".venv/bin/watchdeck-attention",
    ):
        files[relative] = _digest(_regular_bytes(release / relative))
        if relative.startswith(".venv/bin/") and not os.access(release / relative, os.X_OK):
            raise ValueError("bundle_runtime_not_executable")
    web = release / "apps/web/build"
    if not (web / "index.js").is_file() or not (release / ".venv/bin/python").is_file():
        raise ValueError("bundle_runtime_missing")
    if not os.access(release / ".venv/bin/python", os.X_OK):
        raise ValueError("bundle_runtime_not_executable")
    for path in sorted(web.rglob("*")):
        if path.is_symlink():
            raise ValueError("bundle_runtime_symlink")
        if path.is_file():
            files[path.relative_to(release).as_posix()] = _digest(_regular_bytes(path))
    return files


def build_bundle(
    repository: Path,
    ref: str,
    helper_manifest: Path,
    map_directory: Path,
    output: Path,
    *,
    build_environment: bool = False,
    reconciliation: Path | None = None,
) -> dict[str, Any]:
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("bundle_output_exists")
    if not output.parent.is_dir() or any(part.is_symlink() for part in output.parents):
        raise ValueError("bundle_output_parent_invalid")
    original_manifest, helper_files = _helper_inputs(helper_manifest)
    policy = _object(helper_files["policy.json"])
    if (
        policy.get("scope") != "mexc_stage50_reobservation"
        or policy.get("promoteTo100") is not False
    ):
        raise ValueError("bundle_policy_scope_invalid")
    commit, source, source_modes = _source(repository, ref)
    canonical = original_manifest["canonicalSource"]
    canonical_path = Path("apps/market-core/src/prep_watchdeck_market/acceptance_evidence.py")
    canonical_raw = source[canonical_path.as_posix()]
    if (
        _digest(canonical_raw) != canonical["sha256"]
        or canonical_raw != helper_files["acceptance_evidence.py"]
    ):
        raise ValueError("bundle_canonical_source_mismatch")
    dependencies: dict[str, bytes] = {}
    base = helper_manifest.parent.parent
    _dependency(base / "complete-mexc-scale.py", policy["completeDriverSha256"], dependencies)
    for name, expected in policy["helpers"].items():
        if len(_safe_relative(name).parts) != 1:
            raise ValueError("bundle_dependency_path_invalid")
        _dependency(base / name, expected, dependencies)
    evidence: dict[str, bytes] = {}
    warning = policy["knownWarningEvidence"]
    warning_name = _dependency(Path(warning["path"]), warning["sha256"], evidence)
    bindings_raw = _regular_bytes(Path(policy["unitBindings"]))
    original_bindings = _object(bindings_raw)
    if _digest(bindings_raw) != policy["unitBindingsSha256"]:
        raise ValueError("bundle_unit_bindings_hash_mismatch")
    settlement = policy.get("settlementException", {})
    if settlement.get("reviewedEvidencePath") is not None:
        name = _dependency(
            Path(settlement["reviewedEvidencePath"]), settlement["reviewedEvidenceSha256"], evidence
        )
        settlement = dict(settlement, reviewedEvidencePath=str(output / "evidence" / name))
    mapping = {name: _regular_bytes(map_directory / name) for name in MAP_FILES}
    version = _object(mapping["initial-map.json"]).get("version")
    if not isinstance(version, str) or re.fullmatch(r"[0-9a-f]{24}", version) is None:
        raise ValueError("bundle_map_version_invalid")
    if _object(mapping["validation.json"]).get("mapVersion") != version:
        raise ValueError("bundle_map_validation_mismatch")
    if _object(mapping["qualification-evidence.json"]).get("mapVersion") != version:
        raise ValueError("bundle_map_evidence_mismatch")
    if reconciliation is not None:
        raw = _regular_bytes(reconciliation)
        if _object(raw).get("schemaVersion") != "candle-gap-reconciliation-v1":
            raise ValueError("bundle_reconciliation_invalid")
        evidence["history-reconciliation.json"] = raw
    output.mkdir(mode=0o700)
    release = output / "releases" / commit[:12]
    release.mkdir(parents=True)
    for name, raw in source.items():
        target = release / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(source_modes[name])
    for directory in ("helper", "maps", "evidence"):
        (output / directory).mkdir()
    for name, raw in helper_files.items():
        if name != "launch-dry-run.json":
            (output / "helper" / name).write_bytes(raw)
    for name, raw in dependencies.items():
        (output / name).write_bytes(raw)
    for name, raw in mapping.items():
        (output / "maps" / name).write_bytes(raw)
    for name, raw in evidence.items():
        (output / "evidence" / name).write_bytes(raw)
    _write_json(output / "evidence/original-helper-manifest.json", original_manifest)
    _write_json(output / "evidence/original-unit-bindings.json", original_bindings)
    # The existing supervisor anchors its output at HERE.parent. Relocate the copied
    # launcher's historical absolute BASE to that same directory; preserve its input.
    launcher = helper_files["launch-stage50.py"]
    old_base = b'BASE = Path("/home/tn/watchdeck-local-archive/mexc-100-scale-20261010-1025")'
    if launcher.count(old_base) != 1:
        raise ValueError("bundle_launcher_layout_unsupported")
    (output / "evidence/original-launch-stage50.py").write_bytes(launcher)
    (output / "helper/launch-stage50.py").write_bytes(
        launcher.replace(old_base, b"BASE = Path(__file__).resolve().parent.parent")
    )
    if build_environment:
        _run_build(release, output / "build.log")
    runtime_files = _runtime_files(release) if build_environment else {}
    if any(_regular_bytes(release / name) != raw for name, raw in source.items()):
        raise ValueError("bundle_tracked_source_changed")
    production_release = PRODUCTION_RELEASES / commit[:12]
    metadata = {
        "commit": commit,
        "release": str(production_release),
        "stagedRelease": str(release),
        "source": "git archive tracked commit",
        "stage": 50,
        "build": "PASS" if build_environment else "NOT_RUN",
        "trackedSourceHashComparison": "PASS",
        "trackedFileCount": len(source),
        "builtAt": datetime.now(UTC).isoformat(),
        "productionInstalled": False,
    }
    _write_json(release / "RELEASE.json", metadata)
    bindings = {
        "schemaVersion": 1,
        "mapVersion": version,
        "status": "DRAFT_REQUIRES_OPERATIONAL_BINDING",
        "units": {
            unit: {"release": str(production_release), "dropinSha256": None}
            for unit in original_bindings.get("units", {})
        },
    }
    _write_json(output / "unit-bindings.draft.json", bindings)
    policy.update(
        approved=False,
        approvalKind="local_bundle_requires_operational_authorization_and_binding",
        futureObservationAlreadyAccepted=False,
        release50=str(production_release),
        commit50=commit,
        releaseMetadataSha25650=_digest(_regular_bytes(release / "RELEASE.json")),
        map50=version,
        recoveryNotBefore=None,
        warningExceptions=[],
        settlementException=dict(settlement, enabled=False),
        unitBindings=str(output / "unit-bindings.draft.json"),
        unitBindingsSha256=_digest(_regular_bytes(output / "unit-bindings.draft.json")),
        knownWarningEvidence={
            "path": str(output / "evidence" / warning_name),
            "sha256": warning["sha256"],
        },
        dataopsChecker={
            "path": str(release / "scripts/market/check-data-operations.py"),
            "sha256": _digest(source["scripts/market/check-data-operations.py"]),
        },
        acceptanceEvidence={
            "path": str(output / "helper/acceptance_evidence.py"),
            "sha256": _digest(canonical_raw),
        },
        rosterCapture={
            "path": str(output / "helper/mexc-readonly-capture.py"),
            "sha256": _digest(helper_files["mexc-readonly-capture.py"]),
        },
        supervisorSha256=_digest(helper_files["supervise-stage50.py"]),
    )
    for collector in policy["collectorCopies"].values():
        filename = Path(collector["path"]).name
        path = output / "helper" / filename
        collector["path"], collector["sha256"] = str(path), _digest(helper_files[filename])
        collector["argv"] = [
            str(production_release / ".venv/bin/python"),
            str(path),
            *collector["argv"][2:],
        ]
    _write_json(output / "helper/policy.json", policy)
    copied_manifest = {
        "schemaVersion": 1,
        "sourceCommit": commit,
        "canonicalSource": {
            "path": str(release / canonical_path),
            "sha256": _digest(canonical_raw),
            "hostCopy": str(output / "helper/acceptance_evidence.py"),
        },
        "files": {
            path.name: _digest(_regular_bytes(path))
            for path in sorted((output / "helper").iterdir())
        },
        "policyApproved": False,
        "productionChanged": False,
    }
    _write_json(output / "helper/source-manifest.json", copied_manifest)
    files = {str(release.relative_to(output) / name): _digest(raw) for name, raw in source.items()}
    files.update(
        {
            (release.relative_to(output) / name).as_posix(): digest
            for name, digest in runtime_files.items()
        }
    )
    for directory in (output, output / "helper", output / "maps", output / "evidence"):
        for path in sorted(directory.iterdir()):
            if path.is_file():
                files[path.relative_to(output).as_posix()] = _digest(_regular_bytes(path))
    files[(release.relative_to(output) / "RELEASE.json").as_posix()] = _digest(
        _regular_bytes(release / "RELEASE.json")
    )
    manifest = {
        "schemaVersion": "acceptance-bundle-v1",
        "sourceCommit": commit,
        "stagedRelease": str(release),
        "plannedProductionRelease": str(production_release),
        "plannedProductionMap": str(PRODUCTION_MAPS / version),
        "mapVersion": version,
        "build": metadata["build"],
        "files": files,
        "trackedSourceModes": source_modes,
        "runtimeFiles": runtime_files,
        "operationalAcceptance": "NOT_ACCEPTED",
        "requiredBeforeObservation": [
            "explicit_operational_authorization",
            "production_release_and_map_adoption",
            "production_destination_environment_build",
            "reviewed_live_unit_bindings_and_protected_controls",
            "post_adoption_recovery_not_before",
            "review_of_unresolved_history_and_map_qualification",
            "new_7200_second_observation",
        ],
    }
    _write_json(output / "BUNDLE.json", manifest)
    verify_bundle(output)
    return manifest


def verify_bundle(output: Path) -> dict[str, Any]:
    output = output.absolute()
    manifest = _object(_regular_bytes(output / "BUNDLE.json"))
    if manifest.get("schemaVersion") != "acceptance-bundle-v1":
        raise ValueError("bundle_schema_invalid")
    files = manifest.get("files")
    commit = manifest.get("sourceCommit")
    if not isinstance(files, dict) or not files or not isinstance(commit, str):
        raise ValueError("bundle_manifest_invalid")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("bundle_commit_invalid")
    release = output / "releases" / commit[:12]
    source_modes = manifest.get("trackedSourceModes")
    if not isinstance(source_modes, dict) or not source_modes:
        raise ValueError("bundle_source_inventory_invalid")
    required = {
        "helper/policy.json",
        "helper/source-manifest.json",
        "unit-bindings.draft.json",
        *("maps/" + name for name in MAP_FILES),
        (release.relative_to(output) / "RELEASE.json").as_posix(),
        *((release.relative_to(output) / name).as_posix() for name in source_modes),
    }
    if not required <= files.keys() or manifest.get("stagedRelease") != str(release):
        raise ValueError("bundle_manifest_incomplete")
    for relative, expected in files.items():
        path = output.joinpath(*_safe_relative(relative).parts)
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError("bundle_path_symlink")
        if _digest(_regular_bytes(path)) != expected:
            raise ValueError("bundle_hash_mismatch")
    for relative, expected in source_modes.items():
        path = release.joinpath(*_safe_relative(relative).parts)
        if expected not in (0o644, 0o755) or stat.S_IMODE(path.stat().st_mode) != expected:
            raise ValueError("bundle_source_mode_mismatch")
    metadata = _object(_regular_bytes(release / "RELEASE.json"))
    metadata_relative = (release.relative_to(output) / "RELEASE.json").as_posix()
    production_release = str(PRODUCTION_RELEASES / commit[:12])
    if (
        metadata.get("commit") != commit
        or metadata.get("trackedFileCount") != len(source_modes)
        or metadata.get("release") != production_release
        or metadata.get("build") not in ("PASS", "NOT_RUN")
        or metadata.get("build") != manifest.get("build")
        or metadata.get("productionInstalled") is not False
        or manifest.get("plannedProductionRelease") != production_release
        or manifest.get("operationalAcceptance") != "NOT_ACCEPTED"
    ):
        raise ValueError("bundle_release_binding_invalid")
    helper_manifest, helper_files = _helper_inputs(output / "helper/source-manifest.json")
    if any(files.get("helper/" + name) != _digest(raw) for name, raw in helper_files.items()):
        raise ValueError("bundle_helper_inventory_invalid")
    canonical = release / "apps/market-core/src/prep_watchdeck_market/acceptance_evidence.py"
    if (
        helper_manifest.get("sourceCommit") != commit
        or helper_manifest["canonicalSource"]["path"] != str(canonical)
        or _regular_bytes(canonical) != helper_files["acceptance_evidence.py"]
    ):
        raise ValueError("bundle_canonical_source_mismatch")
    policy = _object(_regular_bytes(output / "helper/policy.json"))
    if (
        policy.get("approved") is not False
        or policy.get("promoteTo100") is not False
        or policy.get("warningExceptions") != []
        or policy.get("settlementException", {}).get("enabled") is not False
        or policy.get("recoveryNotBefore") is not None
        or policy.get("commit50") != manifest["sourceCommit"]
        or policy.get("map50") != manifest["mapVersion"]
        or policy.get("release50") != production_release
        or policy.get("releaseMetadataSha25650") != files[metadata_relative]
    ):
        raise ValueError("bundle_draft_policy_invalid")
    dependencies = {"complete-mexc-scale.py": policy["completeDriverSha256"], **policy["helpers"]}
    for name, expected in dependencies.items():
        if len(_safe_relative(name).parts) != 1:
            raise ValueError("bundle_dependency_path_invalid")
        if files.get(name) != expected or _digest(_regular_bytes(output / name)) != expected:
            raise ValueError("bundle_dependency_binding_invalid")
    if manifest["build"] == "PASS":
        runtime_files = _runtime_files(release)
        if not runtime_files or runtime_files != manifest.get("runtimeFiles"):
            raise ValueError("bundle_runtime_changed")
        if any(
            files.get((release.relative_to(output) / name).as_posix()) != digest
            for name, digest in runtime_files.items()
        ):
            raise ValueError("bundle_runtime_inventory_invalid")
    checker = release / "scripts/market/check-data-operations.py"
    if policy.get("dataopsChecker") != {
        "path": str(checker),
        "sha256": _digest(_regular_bytes(checker)),
    }:
        raise ValueError("bundle_checker_binding_invalid")
    for name, field in (
        ("initial-map.json", "version"),
        ("qualification-evidence.json", "mapVersion"),
        ("validation.json", "mapVersion"),
    ):
        if _object(_regular_bytes(output / "maps" / name)).get(field) != manifest["mapVersion"]:
            raise ValueError("bundle_map_binding_invalid")
    return {
        "sourceStatus": "PASS",
        "build": manifest["build"],
        "sourceCommit": manifest["sourceCommit"],
        "mapVersion": manifest["mapVersion"],
        "operationalAcceptance": "NOT_ACCEPTED",
        "requiredBeforeObservation": manifest["requiredBeforeObservation"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, help="verify an existing immutable local bundle")
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--ref", help="immutable Git commit to archive")
    parser.add_argument("--helper-manifest", type=Path)
    parser.add_argument("--map-directory", type=Path)
    parser.add_argument("--reconciliation", type=Path)
    parser.add_argument("--output", type=Path, help="new local bundle path; overwrite refused")
    parser.add_argument(
        "--build", action="store_true", help="install locked dependencies and build"
    )
    args = parser.parse_args(argv)
    try:
        if args.verify is not None:
            result = verify_bundle(args.verify)
        else:
            if any(
                item is None
                for item in (
                    args.repository,
                    args.ref,
                    args.helper_manifest,
                    args.map_directory,
                    args.output,
                )
            ):
                parser.error("repository/ref/helper-manifest/map-directory/output are required")
            result = build_bundle(
                args.repository,
                args.ref,
                args.helper_manifest,
                args.map_directory,
                args.output,
                build_environment=args.build,
                reconciliation=args.reconciliation,
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"status": "ERROR", "reason": "acceptance_bundle_failed"}))
        return 2
