"""Generate the independent ranking contracts from their validated Python models."""

import argparse
import json
from pathlib import Path

from prep_watchdeck_ranking.models import RankingMap, RankingResponse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true", help="fail if the saved contracts differ")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
changed = []
for name, model in [("ranking-map", RankingMap), ("ranking-response", RankingResponse)]:
    schema = model.model_json_schema(by_alias=True, mode="serialization")
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    path = root / "schemas" / f"{name}.schema.json"
    content = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not path.exists() or path.read_text() != content:
            changed.append(str(path))
    else:
        path.write_text(content)
if changed:
    raise SystemExit("ranking schemas need generation: " + ", ".join(changed))
