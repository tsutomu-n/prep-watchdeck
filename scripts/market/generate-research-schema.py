"""Generate research input envelopes and frozen trial rules from their Python contracts."""

import argparse
import json
from pathlib import Path

from prep_watchdeck_market.research.models import ObservationReceipt, ResearchPayload
from prep_watchdeck_market.research.trials import BoundTrial, RegisteredTrial, TrialRules


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).resolve().parents[2] / "schemas"
    )
    args = parser.parse_args()
    changed = []
    for name, model in (
        ("research-payload", ResearchPayload),
        ("research-receipt", ObservationReceipt),
        ("research-trial-rules", TrialRules),
        ("research-registration", RegisteredTrial),
        ("research-trial", BoundTrial),
    ):
        schema = model.model_json_schema(mode="serialization")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        content = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        path = args.output_dir / f"{name}.schema.json"
        if args.check:
            if not path.exists() or path.read_text() != content:
                changed.append(name)
        else:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if changed:
        raise SystemExit("research schemas need generation: " + ", ".join(changed))


if __name__ == "__main__":
    main()
