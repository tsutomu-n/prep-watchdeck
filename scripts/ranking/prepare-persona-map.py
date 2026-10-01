"""Copy reviewed identities into a bounded, explicitly versioned persona sample map."""

import argparse
import hashlib
import json
from pathlib import Path

from prep_watchdeck_ranking.models import RankingMap
from prep_watchdeck_ranking.storage import atomic_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--asset", action="append", default=[])
    args = parser.parse_args()
    source = args.mapping.resolve(strict=True)
    state = args.state_dir.resolve()
    for forbidden in (
        Path.home() / ".local/share/prep-watchdeck-ranking",
        Path.home() / ".local/share/prep-watchdeck-market",
        Path.home() / "releases",
        source.parent,
    ):
        root = forbidden.resolve()
        if state.is_relative_to(root) or root.is_relative_to(state):
            parser.error("sample output must be isolated from production and source mapping")
    raw = source.read_bytes()
    mapping = RankingMap.model_validate_json(raw)
    assets = set(args.asset or ["BTC", "ETH", "PEPE", "BTCDOM"])
    if not 1 <= len(assets) <= 6:
        parser.error("use at most six explicitly selected assets")
    rows = tuple(row for row in mapping.rows if row.asset in assets)
    if {row.asset for row in rows} != assets:
        parser.error("requested asset missing from reviewed map")
    row_hash = hashlib.sha256(
        json.dumps([row.model_dump(by_alias=True) for row in rows], sort_keys=True).encode()
    ).hexdigest()
    sample = RankingMap.model_validate(
        mapping.model_copy(
            update={
                "version": f"persona-sample-{row_hash[:20]}",
                "rows": rows,
                "source_instrument_count": sum(len(row.originals) for row in rows),
            }
        ).model_dump()
    )
    if source.read_bytes() != raw:
        parser.error("source mapping changed during capture")
    state.mkdir(parents=True, exist_ok=True)
    if any((state / name).exists() for name in ("sample-map.json", "sample-scope.json")):
        parser.error("sample output exists; choose a new state directory")
    atomic_json(state / "sample-map.json", sample.model_dump(mode="json", by_alias=True))
    atomic_json(
        state / "sample-scope.json",
        {
            "sourceMappingPath": str(source),
            "sourceMapVersion": mapping.version,
            "sourceSha256": hashlib.sha256(raw).hexdigest(),
            "sampleMapVersion": sample.version,
            "assets": sorted(assets),
            "rows": len(rows),
            "originals": sample.source_instrument_count,
            "identityValuesRewritten": False,
            "purpose": "bounded actual public data persona acceptance; not whole-universe ranking acceptance",
        },
    )
    print(json.dumps({"mapVersion": sample.version, "assets": sorted(assets)}))


if __name__ == "__main__":
    main()
