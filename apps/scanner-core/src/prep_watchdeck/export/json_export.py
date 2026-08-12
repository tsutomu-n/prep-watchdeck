from __future__ import annotations

import json
from pathlib import Path

from prep_watchdeck.constants import SCHEMA_VERSION
from prep_watchdeck.models import ScannerRow


def _dump(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")


def scanner_rows_payload(
    *,
    run_id: str,
    generated_at: int,
    template_name: str,
    product_type: str,
    rows: list[ScannerRow],
) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "generatedAt": generated_at,
        "templateName": template_name,
        "productType": product_type,
        "rows": [row.model_dump(mode="json") for row in rows],
    }


def summary_payload(run_id: str, rows: list[ScannerRow]) -> dict[str, object]:
    counts = {"WATCH": 0, "CAUTION": 0, "NO_TRADE": 0, "LOW_PRIORITY": 0}
    for row in rows:
        counts[row.category] += 1
    return {"schemaVersion": SCHEMA_VERSION, "runId": run_id, "counts": counts}


def export_json_bundle(
    *,
    out_dir: Path,
    run_id: str,
    generated_at: int,
    template_name: str,
    product_type: str,
    rows: list[ScannerRow],
    top_n: int,
    exclude_no_trade: bool,
) -> None:
    _dump(
        out_dir / "scanner_rows.json",
        scanner_rows_payload(
            run_id=run_id,
            generated_at=generated_at,
            template_name=template_name,
            product_type=product_type,
            rows=rows,
        ),
    )
    _ = top_n, exclude_no_trade
    rankings = {
        "noTrade": [
            {
                "symbol": row.symbol,
                "category": row.category,
                "priorityScore": row.priority_score,
                "changePct": row.change_pct_by_tf.get("15m"),
                "volumeRatio": row.volume_ratio_by_tf.get("15m"),
                "turnoverUsdt": row.turnover_usdt_by_tf.get("15m"),
                "label": row.label,
            }
            for row in rows
            if row.category == "NO_TRADE"
        ]
    }
    _dump(
        out_dir / "rankings.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "templateName": template_name,
            **rankings,
        },
    )
    _dump(
        out_dir / "no_trade_rows.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "rows": [row.model_dump(mode="json") for row in rows if row.category == "NO_TRADE"],
        },
    )
    _dump(out_dir / "summary.json", summary_payload(run_id, rows))
