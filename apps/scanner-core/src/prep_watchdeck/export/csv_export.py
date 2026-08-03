from __future__ import annotations

import csv
from pathlib import Path

from prep_watchdeck.models import ScannerRow


def export_rows_csv(path: Path, rows: list[ScannerRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "symbol",
                "ts",
                "category",
                "direction",
                "label",
                "priority_score",
                "change_15m",
                "turnover_15m",
                "volume_ratio_15m",
                "risk_tags",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "symbol": row.symbol,
                    "ts": row.ts,
                    "category": row.category,
                    "direction": row.direction,
                    "label": row.label,
                    "priority_score": row.priority_score,
                    "change_15m": row.change_pct_by_tf.get("15m"),
                    "turnover_15m": row.turnover_usdt_by_tf.get("15m"),
                    "volume_ratio_15m": row.volume_ratio_by_tf.get("15m"),
                    "risk_tags": ",".join(row.risk_tags),
                }
            )
