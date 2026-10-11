"""Register a prospective protocol from authenticated offline policies after operational acceptance."""

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from prep_watchdeck_attention.formal_protocol import write_protocol
from prep_watchdeck_attention.models import CandidatePolicy
from prep_watchdeck_attention.outcome_export import _digest
from prep_watchdeck_attention.stable_files import read_stable_regular_file

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--attention-copy", type=Path, required=True)
parser.add_argument("--scope", type=Path, required=True)
parser.add_argument("--map-version", required=True)
parser.add_argument("--family-id", required=True)
parser.add_argument("--start-ms", type=int, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
source = args.attention_copy.absolute()
proof = json.loads(
    read_stable_regular_file(source.parent / "copy-manifest.json", max_bytes=16 * 1024 * 1024)
)
expected = proof["files"][source.name]["sha256"]
if proof.get("status") != "COMPLETE" or _digest(source) != expected:
    raise ValueError("policy copy is incomplete or changed")
with sqlite3.connect(f"{source.as_uri()}?mode=ro&immutable=1", uri=True) as connection:
    policies = tuple(
        CandidatePolicy.model_validate_json(row[0])
        for row in connection.execute(
            "SELECT payload FROM candidate_policies WHERE family_id=? ORDER BY id",
            (args.family_id,),
        )
    )
scope = read_stable_regular_file(args.scope, max_bytes=16 * 1024 * 1024)
if _digest(source) != expected:
    raise ValueError("policy copy changed during registration")
print(
    write_protocol(
        args.output,
        policies,
        map_version=args.map_version,
        scope_sha256=hashlib.sha256(scope).hexdigest(),
        start_ms=args.start_ms,
        registered_at_ms=int(datetime.now(UTC).timestamp() * 1000),
    ).model_dump_json(by_alias=True)
)
