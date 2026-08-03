from __future__ import annotations

from typing import Protocol

from prep_watchdeck.domain.dto import SnapshotDTO


class SnapshotWriter(Protocol):
    def write(self, snapshot: SnapshotDTO) -> None:
        """Persist a snapshot atomically."""
