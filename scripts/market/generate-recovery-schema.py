from __future__ import annotations

import argparse
import json
from pathlib import Path

from prep_watchdeck_market.candle_recovery_state import CandleRecoveryState


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    target = root / "schemas" / "candle-recovery-state.schema.json"
    generated = json.dumps(
        CandleRecoveryState.model_json_schema(by_alias=True),
        indent=2,
        ensure_ascii=False,
    ) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") == generated:
        return 0
    if args.check:
        print("stale schema: candle-recovery-state.schema.json")
        return 1
    target.write_text(generated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
