from __future__ import annotations

import json
from pathlib import Path

from prep_watchdeck.config.templates import load_template
from prep_watchdeck.domain.dto import SnapshotDTO
from prep_watchdeck.domain.enums import DataSource
from prep_watchdeck.domain.screening.rankings import build_rankings
from prep_watchdeck.features.activity_phase import classify_activity_phase
from prep_watchdeck.features.volume_ratio import volume_ratio_15m_metadata


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
        payload["featureVersion"] = "5"
        payload["rulesetVersion"] = "4"
        payload["source"]["fixtureSet"] = name
        snapshot = SnapshotDTO.model_validate(payload)
        for row in snapshot.rows:
            row.activity_phase = classify_activity_phase(
                row.volume_ratio_by_tf.get("15m"),
                row.volume_ratio_by_tf.get("1h"),
                row.volume_ratio_by_tf.get("4h"),
                min_volume_ratio=config.volume.min_volume_ratio,
                strong_volume_ratio=config.volume.strong_volume_ratio,
            )
        snapshot.rankings = build_rankings(snapshot.rows)
        snapshot.summary["volumeRatio15m"] = volume_ratio_15m_metadata(
            config.volume.baseline_window_bars,
            config.volume.volume_ratio_floor_usdt,
        )
        return snapshot
