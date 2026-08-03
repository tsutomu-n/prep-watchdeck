from __future__ import annotations

import os
from pathlib import Path

from prep_watchdeck.domain.service_models import ServiceStateSnapshot


class AtomicServiceStateWriter:
    def __init__(self, latest_path: Path) -> None:
        self.latest_path = latest_path

    def write(self, snapshot: ServiceStateSnapshot) -> None:
        self.latest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = snapshot.model_dump_json(by_alias=True, indent=2)
        tmp_path = self.latest_path.with_suffix(f"{self.latest_path.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, self.latest_path)
