from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from prep_watchdeck.domain.dto import SnapshotDTO


class AtomicSnapshotWriter:
    def __init__(self, latest_path: Path, *, archive: bool = True) -> None:
        self.latest_path = latest_path
        self.archive = archive

    def write(self, snapshot: SnapshotDTO) -> None:
        self.latest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = snapshot.model_dump_json(by_alias=True, indent=2)
        if self.archive:
            self._write_archive(snapshot, payload)
        self._write_latest(payload)

    def _write_latest(self, payload: str) -> None:
        tmp_path = self.latest_path.with_suffix(f"{self.latest_path.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, self.latest_path)

    def _write_archive(self, snapshot: SnapshotDTO, payload: str) -> None:
        date_part = datetime.fromtimestamp(snapshot.generated_at / 1000, UTC).strftime("%Y-%m-%d")
        archive_path = self.latest_path.parent / "archive" / date_part / f"{snapshot.run_id}.json"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = archive_path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, archive_path)
