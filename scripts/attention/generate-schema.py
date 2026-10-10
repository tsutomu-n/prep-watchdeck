"""Generate all public Attention schemas from the strict Python contracts."""

import argparse
import json
from pathlib import Path

from prep_watchdeck_attention.discovery_models import DiscoveryResponse, DiscoverySummary
from prep_watchdeck_attention.models import (
    AttentionEvaluationReport,
    AttentionResponse,
    ShadowAllocation,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).resolve().parents[2] / "schemas"
    )
    args = parser.parse_args()
    if not args.check:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    changed = []
    for name, model in (
        ("attention-response", AttentionResponse),
        ("attention-evaluation", AttentionEvaluationReport),
        ("attention-shadow-allocation", ShadowAllocation),
        ("discovery-response", DiscoveryResponse),
        ("discovery-summary", DiscoverySummary),
    ):
        schema = model.model_json_schema(by_alias=True, mode="serialization")
        schema["$schema"] = "http://json-schema.org/draft-07/schema#"
        content = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        path = args.output_dir / f"{name}.schema.json"
        if args.check:
            if not path.exists() or path.read_text() != content:
                changed.append(name)
        else:
            path.write_text(content)
    if changed:
        raise SystemExit("attention schemas need generation: " + ", ".join(changed))


if __name__ == "__main__":
    main()
