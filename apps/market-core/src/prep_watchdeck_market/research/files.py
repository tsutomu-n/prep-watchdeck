"""Local-only path, size and strict JSON boundaries for research artifacts."""

from __future__ import annotations

import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from prep_watchdeck_market.bundle_files import (
    BundleError,
    json_bytes,
    read_regular,
    safe_relative_path,
    sha256,
    strict_json,
    sums_bytes,
)
from prep_watchdeck_market.research.models import MAX_FILE_BYTES, MAX_SNAPSHOT_BYTES


def isolated_root(path: Path, excluded_roots: tuple[Path, ...] = ()) -> Path:
    root = Path(os.path.abspath(path.expanduser()))
    if root == Path(root.anchor) or root == Path.home().absolute():
        raise BundleError("research_state_overlap")
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise BundleError("research_path_invalid")
    state = Path.home() / ".local/share"
    excluded = list(excluded_roots)
    for core in ("market", "ranking", "attention"):
        excluded.append(
            Path(
                os.environ.get(
                    f"PREP_WATCHDECK_{core.upper()}_STATE_DIR", state / f"prep-watchdeck-{core}"
                )
            )
            .expanduser()
            .resolve()
        )
    excluded.append(Path(__file__).resolve().parents[5] / "var")
    for other in excluded:
        other = other.expanduser().resolve()
        if root == other or root.is_relative_to(other) or other.is_relative_to(root):
            raise BundleError("research_state_overlap")
    return root


def model_bytes(model: BaseModel) -> bytes:
    return json_bytes(model.model_dump(mode="json"))


def plain_json(value: Any) -> Any:
    """Keep decoded exact decimals as strings when publishing caller-supplied JSON."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise BundleError("research_json_invalid")
        return str(value)
    if isinstance(value, dict):
        return {key: plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_json(item) for item in value]
    return value


def load_json(path: Path, limit: int = MAX_FILE_BYTES) -> Any:
    try:
        return strict_json(read_regular(path, limit))
    except (RecursionError, TypeError, ValueError):
        raise BundleError("research_json_invalid") from None


def load_model[T: BaseModel](path: Path, model: type[T]) -> T:
    try:
        return model.model_validate(load_json(path))
    except (ValidationError, TypeError):
        raise BundleError("research_schema_invalid") from None


def checked_files(root: Path, expected: dict[str, str]) -> dict[str, bytes]:
    if len(expected) > 4_010:
        raise BundleError("research_size_exceeded")
    files: dict[str, bytes] = {}
    total = 0
    for name, digest in expected.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise BundleError("research_hash_invalid")
        safe_relative_path(name)
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise BundleError("research_hash_invalid")
        data = read_regular(root / name, MAX_FILE_BYTES)
        total += len(data)
        if total > MAX_SNAPSHOT_BYTES:
            raise BundleError("research_size_exceeded")
        if sha256(data) != digest:
            raise BundleError("research_hash_mismatch")
        files[name] = data
    return files


def read_leaf(root: Path, name: str) -> bytes:
    data = read_regular(root / name, MAX_FILE_BYTES)
    if read_regular(root / "SHA256SUMS", 4096) != sums_bytes({name: data}):
        raise BundleError("research_hash_mismatch")
    if {entry.name for entry in root.iterdir()} != {name, "SHA256SUMS"}:
        raise BundleError("research_unexpected_file")
    return data
