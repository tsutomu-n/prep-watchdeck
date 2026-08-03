from __future__ import annotations

import json
from pathlib import Path

from prep_watchdeck.domain.dto import SnapshotDTO


def export_snapshot_schema(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = SnapshotDTO.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://prep-watchdeck.local/schemas/scanner-snapshot.schema.json"
    schema["title"] = "PrepWatchdeck ScannerSnapshot"
    out.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
