"""A review bundle keeps source, copied evidence and its unapproved policy bound together."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from prep_watchdeck_market.acceptance_bundle import build_bundle, verify_bundle


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, str, Path, Path]:
    repo, helper, mapping = (tmp_path / name for name in ("repo", "helper", "map"))
    for path in (repo, helper, mapping):
        path.mkdir()
    canonical = repo / "apps/market-core/src/prep_watchdeck_market/acceptance_evidence.py"
    checker = repo / "scripts/market/check-data-operations.py"
    canonical.parent.mkdir(parents=True)
    checker.parent.mkdir(parents=True)
    canonical.write_text('"""Fixture canonical source."""\n')
    checker.write_text('"""Fixture checker."""\n')
    checker.chmod(0o755)
    for args in (
        ("init", "-q"),
        ("add", "."),
        (
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@localhost",
            "commit",
            "-qm",
            "source",
        ),
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / ".env").write_text("PRIVATE_FIXTURE_DO_NOT_COPY=1\n")
    for name in (
        "supervise-stage50.py",
        "launch-stage50.py",
        "observe-production.py",
        "capture-funding-artifacts.py",
        "mexc-readonly-capture.py",
    ):
        (helper / name).write_text('"""Fixture helper."""\n')
    (helper / "launch-stage50.py").write_text(
        "from pathlib import Path\n"
        'BASE = Path("/home/tn/watchdeck-local-archive/mexc-100-scale-20261010-1025")\n'
    )
    (helper / "acceptance_evidence.py").write_bytes(canonical.read_bytes())
    for name in ("complete-mexc-scale.py", "continue-stage100.py"):
        (tmp_path / name).write_text('"""Fixture legacy runtime dependency."""\n')
    for name in ("known.json", "bindings.json"):
        write_json(tmp_path / name, {"schemaVersion": 1, "units": {}})
    policy = {
        "scope": "mexc_stage50_reobservation",
        "approved": False,
        "promoteTo100": False,
        "release50": "/old/release",
        "commit50": "0" * 40,
        "map50": "0" * 24,
        "helpers": {"continue-stage100.py": digest(tmp_path / "continue-stage100.py")},
        "completeDriverSha256": digest(tmp_path / "complete-mexc-scale.py"),
        "unitBindings": str(tmp_path / "bindings.json"),
        "unitBindingsSha256": digest(tmp_path / "bindings.json"),
        "knownWarningEvidence": {
            "path": str(tmp_path / "known.json"),
            "sha256": digest(tmp_path / "known.json"),
        },
        "warningExceptions": [],
        "settlementException": {"enabled": False},
        "collectorCopies": {
            name: {
                "path": str(helper / file),
                "sha256": digest(helper / file),
                "argv": ["/old/python", str(helper / file), "--output", "{output}/" + name],
            }
            for name, file in (
                ("observer", "observe-production.py"),
                ("funding", "capture-funding-artifacts.py"),
            )
        },
    }
    write_json(helper / "policy.json", policy)
    manifest = {
        "files": {p.name: digest(p) for p in helper.iterdir()},
        "canonicalSource": {
            "path": str(canonical),
            "sha256": digest(canonical),
            "hostCopy": str(helper / "acceptance_evidence.py"),
        },
    }
    write_json(helper / "source-manifest.json", manifest)
    for name in ("initial-map.json", "initial-roster.json"):
        write_json(mapping / name, {"version": "b" * 24})
    write_json(mapping / "qualification-evidence.json", {"mapVersion": "b" * 24})
    write_json(mapping / "validation.json", {"mapVersion": "b" * 24, "adoption": "candidate_only"})
    return repo, commit, helper / "source-manifest.json", mapping


def test_bundle_uses_only_committed_source_and_pins_one_draft_policy(
    inputs: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, commit, helper, mapping = inputs
    output = tmp_path / "bundle"
    result = build_bundle(repo, commit, helper, mapping, output)
    release = Path(result["stagedRelease"])
    assert not (release / ".env").exists()
    assert (release / "scripts/market/check-data-operations.py").read_text().startswith('"""')
    policy = json.loads((output / "helper/policy.json").read_text())
    assert policy["commit50"] == commit
    assert policy["map50"] == "b" * 24
    assert policy["approved"] is False
    assert policy["warningExceptions"] == []
    assert policy["recoveryNotBefore"] is None
    assert Path(policy["dataopsChecker"]["path"]).is_relative_to(output)
    assert (release / "scripts/market/check-data-operations.py").stat().st_mode & 0o111
    assert (
        "BASE = Path(__file__).resolve().parent.parent"
        in (output / "helper/launch-stage50.py").read_text()
    )
    assert verify_bundle(output)["sourceStatus"] == "PASS"
    assert verify_bundle(output)["operationalAcceptance"] == "NOT_ACCEPTED"


def test_changed_helper_is_rejected_before_creating_output(
    inputs: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, commit, helper, mapping = inputs
    (helper.parent / "supervise-stage50.py").write_text("changed\n")
    output = tmp_path / "bundle"
    with pytest.raises(ValueError, match="helper_hash_mismatch"):
        build_bundle(repo, commit, helper, mapping, output)
    assert not output.exists()


def test_existing_bundle_is_preserved(inputs: tuple[Path, str, Path, Path], tmp_path: Path) -> None:
    repo, commit, helper, mapping = inputs
    output = tmp_path / "bundle"
    output.mkdir()
    marker = output / "keep"
    marker.write_text("original")
    with pytest.raises(FileExistsError):
        build_bundle(repo, commit, helper, mapping, output)
    assert marker.read_text() == "original"


@pytest.mark.parametrize("relative", ["helper/policy.json", "maps/initial-map.json"])
def test_mutated_bundle_file_is_rejected(
    inputs: tuple[Path, str, Path, Path], tmp_path: Path, relative: str
) -> None:
    repo, commit, helper, mapping = inputs
    output = tmp_path / "bundle"
    build_bundle(repo, commit, helper, mapping, output)
    (output / relative).write_text("{}\n")
    with pytest.raises(ValueError, match="bundle_hash_mismatch"):
        verify_bundle(output)


def test_incomplete_inventory_cannot_report_pass(
    inputs: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, commit, helper, mapping = inputs
    output = tmp_path / "bundle"
    build_bundle(repo, commit, helper, mapping, output)
    manifest = json.loads((output / "BUNDLE.json").read_text())
    del manifest["files"]["maps/initial-map.json"]
    write_json(output / "BUNDLE.json", manifest)
    with pytest.raises(ValueError, match="bundle_manifest_incomplete"):
        verify_bundle(output)


def test_omitted_legacy_dependency_cannot_report_pass(
    inputs: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, commit, helper, mapping = inputs
    output = tmp_path / "bundle"
    build_bundle(repo, commit, helper, mapping, output)
    manifest = json.loads((output / "BUNDLE.json").read_text())
    del manifest["files"]["complete-mexc-scale.py"]
    write_json(output / "BUNDLE.json", manifest)
    (output / "complete-mexc-scale.py").unlink()
    with pytest.raises(ValueError, match="bundle_dependency_binding_invalid"):
        verify_bundle(output)
