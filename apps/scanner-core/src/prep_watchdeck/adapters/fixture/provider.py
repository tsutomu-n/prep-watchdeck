from __future__ import annotations

import json
from pathlib import Path

from prep_watchdeck.config.templates import load_template
from prep_watchdeck.domain.dto import SnapshotDTO
from prep_watchdeck.domain.enums import DataSource
from prep_watchdeck.domain.screening.rankings import build_rankings


class FixtureProvider:
    def __init__(
        self,
        fixtures_dir: Path,
        config_dir: Path = Path("../../config/scanner-filters"),
    ) -> None:
        self.fixtures_dir = fixtures_dir
        self.config_dir = config_dir

    def build_snapshot(self, *, template: str, fixture_set: str | None = None) -> SnapshotDTO:
        config = load_template(self.config_dir, template)
        name = fixture_set or "basic"
        path = self.fixtures_dir / "snapshots" / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"fixture snapshot not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["source"]["templateName"] = template
        payload["source"]["dataSource"] = DataSource.FIXTURE.value
        payload["source"]["fixtureSet"] = name
        snapshot = SnapshotDTO.model_validate(payload)
        snapshot.rankings = build_rankings(snapshot.rows, top_n=config.ranking.top_n)
        return snapshot
