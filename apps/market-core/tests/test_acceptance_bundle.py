"""A review bundle keeps source, copied evidence and its unapproved policy bound together."""

import hashlib
import json
import shutil
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
    actual_repo = Path(__file__).resolve().parents[3]
    for relative in (
        "scripts/ranking/verify-map-evidence.py",
        "apps/ranking-core/src/prep_watchdeck_ranking/__init__.py",
        "apps/ranking-core/src/prep_watchdeck_ranking/mapping.py",
        "apps/ranking-core/src/prep_watchdeck_ranking/models.py",
    ):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(actual_repo / relative, target)
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
    for name in ("initial-map.json", "initial-roster.json", "qualification-evidence.json"):
        shutil.copyfile(actual_repo / "apps/ranking-core/data" / name, mapping / name)
    write_json(
        mapping / "validation.json",
        {
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
        },
    )
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
    assert policy["map50"] == json.loads((mapping / "initial-map.json").read_text())["version"]
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


def test_offline_test_dependency_is_copied_and_cannot_be_omitted(
    inputs: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, commit, helper, mapping = inputs
    (helper.parent.parent / "test_observer.py").write_text('"""Offline fixture."""\n')
    (helper.parent / "test_collector_clocks.py").write_text('"""Fixture test."""\n')
    source_manifest = json.loads(helper.read_text())
    source_manifest["files"]["test_collector_clocks.py"] = digest(
        helper.parent / "test_collector_clocks.py"
    )
    write_json(helper, source_manifest)
    output = tmp_path / "bundle"
    build_bundle(repo, commit, helper, mapping, output)
    assert (output / "test_observer.py").read_bytes() == (
        helper.parent.parent / "test_observer.py"
    ).read_bytes()
    manifest = json.loads((output / "BUNDLE.json").read_text())
    manifest["offlineTestInputs"] = {}
    del manifest["files"]["test_observer.py"]
    write_json(output / "BUNDLE.json", manifest)
    with pytest.raises(ValueError, match="bundle_offline_test_inventory_invalid"):
        verify_bundle(output)


def test_saved_bundle_regenerates_from_frozen_fixtures(
    inputs: tuple[Path, str, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit, helper, mapping = inputs
    original = tmp_path / "original"
    build_bundle(repo, commit, helper, mapping, original)
    # This layout is a previously generated bundle, including the preserved raw test.
    raw_test = (
        b"from pathlib import Path\nBASE = Path(__file__).resolve().parent\n"
        b'REPOSITORY = Path("/home/tn/projects/.ai-worktrees/'
        b'prep-watchdeck-mexc-100-20261010-1025")\n'
        b'PREVIOUS = Path("/home/tn/releases/prep-watchdeck-ranking-maps/'
        b'94e54510036ac46f710cd568")\n'
        b'REVIEWS = "/home/tn/projects/prep-watchdeck/var/tmp/daytrader-mexc/'
        b'mexc-reviewed-major-identities.json"\n'
    )
    offline = {
        "test_mexc_readonly_capture.py": b"# already rebound offline test\n",
        "evidence/original-test-mexc-readonly-capture.py": raw_test,
        "mexc-production-10-readonly-capture.json": b"{}\n",
        "test-fixtures/reviews.json": b"{}\n",
        **{
            "test-fixtures/map/" + name: b"{}\n"
            for name in ("initial-map.json", "initial-roster.json", "qualification-evidence.json")
        },
    }
    for name, raw in offline.items():
        path = original / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    test = original / "helper/test_recovery_definition_capture.py"
    test.write_text('"""Fixture offline test."""\n')
    manifest_path = original / "helper/source-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][test.name] = digest(test)
    write_json(manifest_path, manifest)
    bundle_manifest = json.loads((original / "BUNDLE.json").read_text())
    bundle_manifest["offlineTestInputs"] = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in offline.items()
    }
    bundle_manifest["files"].update(bundle_manifest["offlineTestInputs"])
    for path in (manifest_path, test):
        bundle_manifest["files"][path.relative_to(original).as_posix()] = digest(path)
    write_json(original / "BUNDLE.json", bundle_manifest)
    original_manifest_bytes = (original / "BUNDLE.json").read_bytes()
    import prep_watchdeck_market.acceptance_bundle as module

    read = module._regular_bytes

    def frozen_only(path: Path) -> bytes:
        assert path.is_relative_to(tmp_path), f"global input read: {path}"
        return read(path)

    monkeypatch.setattr(module, "_regular_bytes", frozen_only)
    for input_bundle, output in (
        (original, tmp_path / "regenerated"),
        (tmp_path / "regenerated", tmp_path / "regenerated-again"),
    ):
        build_bundle(
            repo,
            commit,
            input_bundle / "helper/source-manifest.json",
            input_bundle / "maps",
            output,
        )
        assert verify_bundle(output)["sourceStatus"] == "PASS"
        assert (output / "evidence/original-test-mexc-readonly-capture.py").read_bytes() == raw_test
        assert (output / "test-fixtures/reviews.json").read_bytes() == b"{}\n"
        assert f"releases/{commit[:12]}" in (output / "test_mexc_readonly_capture.py").read_text()
    assert (original / "BUNDLE.json").read_bytes() == original_manifest_bytes


def test_invalid_roster_is_rejected_before_output_creation(
    inputs: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, commit, helper, mapping = inputs
    roster = json.loads((mapping / "initial-roster.json").read_text())
    roster["catalogFingerprint"] = "0" * 64
    write_json(mapping / "initial-roster.json", roster)
    output = tmp_path / "bundle"
    with pytest.raises(ValueError, match="bundle_map_semantics_invalid"):
        build_bundle(repo, commit, helper, mapping, output)
    assert not output.exists()


def test_rehashed_roster_corruption_is_rejected_by_verifier(
    inputs: tuple[Path, str, Path, Path], tmp_path: Path
) -> None:
    repo, commit, helper, mapping = inputs
    output = tmp_path / "bundle"
    build_bundle(repo, commit, helper, mapping, output)
    path = output / "maps/initial-roster.json"
    roster = json.loads(path.read_text())
    roster["catalogFingerprint"] = "0" * 64
    write_json(path, roster)
    manifest = json.loads((output / "BUNDLE.json").read_text())
    manifest["files"]["maps/initial-roster.json"] = digest(path)
    write_json(output / "BUNDLE.json", manifest)
    with pytest.raises(ValueError, match="bundle_map_semantics_invalid"):
        verify_bundle(output)
