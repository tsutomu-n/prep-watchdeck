"""Export bounded actual outcome inputs from completed offline SQLite copies."""

import argparse
from pathlib import Path

from prep_watchdeck_attention.outcome_export import export_outcome_input

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ranking-copy", type=Path, required=True)
parser.add_argument("--attention-copy", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--map-version", required=True)
parser.add_argument("--after-ms", type=int, required=True)
parser.add_argument("--through-ms", type=int, required=True)
args = parser.parse_args()
print(
    export_outcome_input(
        args.ranking_copy,
        args.attention_copy,
        args.output,
        map_version=args.map_version,
        after_ms=args.after_ms,
        through_ms=args.through_ms,
    )
)
