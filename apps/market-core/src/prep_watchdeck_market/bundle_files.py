"""Small, immutable, bounded local bundles shared by evidence exporters."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any


class BundleError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or path.as_posix() != value
    ):
        raise BundleError("bundle_path_invalid")
    return path


def read_regular(path: Path, limit: int) -> bytes:
    _check_directory_path(path.absolute().parent)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise BundleError("bundle_file_invalid")
            with os.fdopen(os.dup(descriptor), "rb") as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise BundleError("bundle_file_invalid")
            return data
        finally:
            os.close(descriptor)
    except OSError:
        raise BundleError("bundle_file_invalid") from None


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BundleError("bundle_json_invalid")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> object:
    raise BundleError("bundle_json_invalid")


def strict_json(data: bytes) -> Any:
    try:
        return json.loads(
            data,
            parse_float=Decimal,
            parse_constant=_reject_nonfinite,
            object_pairs_hook=_unique_pairs,
        )
    except (ValueError, UnicodeError):
        raise BundleError("bundle_json_invalid") from None


def sums_bytes(files: Mapping[str, bytes]) -> bytes:
    return "".join(f"{sha256(data)}  {name}\n" for name, data in sorted(files.items())).encode()


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _check_directory_path(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise BundleError("bundle_path_invalid")
        if current.exists() and not current.is_dir():
            raise BundleError("bundle_path_invalid")


def write_bundle(
    output_dir: Path,
    bundle_id: str,
    files: Mapping[str, bytes],
    *,
    validate: Callable[[Path], object] | None = None,
) -> Path:
    """Publish only after all files have been written, read back and validated."""
    if not bundle_id or not all(c in "0123456789abcdef" for c in bundle_id):
        raise BundleError("bundle_path_invalid")
    root = output_dir.expanduser().absolute()
    _check_directory_path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    final = root / bundle_id
    stage = root / f".staging-{bundle_id}"
    if final.exists() or final.is_symlink() or stage.exists() or stage.is_symlink():
        raise BundleError("bundle_path_exists")
    stage.mkdir(mode=0o700)
    try:
        full_files = dict(files)
        if "SHA256SUMS" in full_files:
            raise BundleError("bundle_path_invalid")
        full_files["SHA256SUMS"] = sums_bytes(full_files)
        if sum(len(data) for data in full_files.values()) > 64 * 1024 * 1024:
            raise BundleError("bundle_size_exceeded")
        for name, data in sorted(full_files.items()):
            relative = safe_relative_path(name)
            target = stage.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                # fdopen owns the descriptor after construction.
                raise
            if read_regular(target, len(data)) != data:
                raise BundleError("bundle_readback_failed")
        if validate is not None:
            validate(stage)
        for directory in sorted((p for p in stage.rglob("*") if p.is_dir()), reverse=True):
            _fsync_dir(directory)
        _fsync_dir(stage)
        os.replace(stage, final)
        _fsync_dir(root)
        return final
    except BaseException:
        shutil.rmtree(stage)
        raise
