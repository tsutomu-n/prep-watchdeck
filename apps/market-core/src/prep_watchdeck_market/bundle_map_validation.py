"""Reuse the committed Ranking checker against frozen review-bundle inputs."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

MAP_VALIDATOR_SOURCE_FILES = (
    "scripts/ranking/verify-map-evidence.py",
    "apps/ranking-core/src/prep_watchdeck_ranking/__init__.py",
    "apps/ranking-core/src/prep_watchdeck_ranking/mapping.py",
    "apps/ranking-core/src/prep_watchdeck_ranking/models.py",
)
_MAP_FILES = (
    "initial-map.json",
    "initial-roster.json",
    "qualification-evidence.json",
    "validation.json",
)


def validate_map_snapshot(source: dict[str, bytes], mapping: dict[str, bytes]) -> dict[str, Any]:
    """Validate content relationships without requiring a fully qualified candidate.

    Both dictionaries are snapshots already bounded and authenticated by the bundle
    caller. No source or map file is read from the caller's original directories.
    """
    if any(not isinstance(source.get(name), bytes) for name in MAP_VALIDATOR_SOURCE_FILES):
        raise ValueError("bundle_map_validator_source_invalid")
    if any(not isinstance(mapping.get(name), bytes) for name in _MAP_FILES):
        raise ValueError("bundle_map_snapshot_invalid")
    with TemporaryDirectory(prefix="watchdeck-bundle-map-") as directory:
        root = Path(directory)
        for name in MAP_VALIDATOR_SOURCE_FILES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source[name])
        map_directory = root / "map"
        map_directory.mkdir()
        for name in _MAP_FILES:
            (map_directory / name).write_bytes(mapping[name])
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / MAP_VALIDATOR_SOURCE_FILES[0]),
                    "--directory",
                    str(map_directory),
                ],
                cwd=root,
                env={
                    "PYTHONPATH": str(root / "apps/ranking-core/src"),
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                capture_output=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            raise ValueError("bundle_map_semantics_invalid") from None
        if result.returncode:
            raise ValueError("bundle_map_semantics_invalid")
        try:
            summary = json.loads(result.stdout)
        except ValueError:
            raise ValueError("bundle_map_semantics_invalid") from None
        if not isinstance(summary, dict) or not summary:
            raise ValueError("bundle_map_semantics_invalid")
    try:
        validation = json.loads(mapping["validation.json"])
    except ValueError:
        raise ValueError("bundle_map_validation_mismatch") from None
    if not isinstance(validation, dict) or any(
        key not in validation
        or json.dumps(validation[key], sort_keys=True) != json.dumps(value, sort_keys=True)
        for key, value in summary.items()
    ):
        raise ValueError("bundle_map_validation_mismatch")
    return summary
