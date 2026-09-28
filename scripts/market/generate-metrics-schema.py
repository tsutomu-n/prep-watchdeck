"""Generate the optional native metrics contract from its validated model."""

import argparse
import json
from pathlib import Path

from prep_watchdeck_market.market_metrics import MarketMetricsArtifact

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
schema = MarketMetricsArtifact.model_json_schema(by_alias=True, mode="serialization")
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
path = root / "schemas" / "market-metrics.schema.json"
content = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
if args.check:
    if not path.exists() or path.read_text() != content:
        raise SystemExit("native metrics schema needs generation")
else:
    path.write_text(content)
