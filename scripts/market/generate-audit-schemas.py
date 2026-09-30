from __future__ import annotations

import argparse
import json
from pathlib import Path

from prep_watchdeck_market.candle_audit_artifacts import (
    AuditDetailPage,
    AuditIndex,
    AuditReport,
    AuditRequest,
)

MODELS = {
    "audit-request.schema.json": AuditRequest,
    "candle-audit-report.schema.json": AuditReport,
    "candle-audit-index.schema.json": AuditIndex,
    "candle-audit-detail.schema.json": AuditDetailPage,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2] / "schemas"
    stale = []
    for name, model in MODELS.items():
        target = root / name
        generated = json.dumps(
            model.model_json_schema(by_alias=True), indent=2, ensure_ascii=False
        ) + "\n"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != generated:
                stale.append(name)
        else:
            target.write_text(generated, encoding="utf-8")
    for name in stale:
        print(f"stale schema: {name}")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
