"""Single-writer immutable evidence. Only this package's dedicated state is writable."""

import fcntl
import hashlib
import json
import os
import sqlite3
import stat
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from .config import isolated_attention_state, no_symlink_path
from .discovery_storage import DiscoveryStorage
from .models import (
    MINUTE,
    AttentionEvaluationReport,
    AttentionResponse,
    CandidatePolicy,
    FeatureSnapshotRow,
    InputReference,
    OutcomeRow,
    ShadowAllocation,
    canonical_json,
    content_digest,
)

SCHEMA_VERSION = "1"


def _regular_or_absent(path: Path) -> None:
    no_symlink_path(path)
    if path.exists():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("state file must be a single regular file")


def atomic_json(path: Path, payload: object) -> None:
    _regular_or_absent(path)
    data = canonical_json(payload).encode()
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class AttentionStore(DiscoveryStorage):
    def __init__(
        self,
        state_dir: Path,
        *,
        market_state_dir: Path | None = None,
        ranking_state_dir: Path | None = None,
    ) -> None:
        default_root = Path.home() / ".local/share"
        self.state = isolated_attention_state(
            state_dir,
            market_state_dir
            or Path(
                os.environ.get(
                    "PREP_WATCHDECK_MARKET_STATE_DIR", default_root / "prep-watchdeck-market"
                )
            ),
            ranking_state_dir
            or Path(
                os.environ.get(
                    "PREP_WATCHDECK_RANKING_STATE_DIR", default_root / "prep-watchdeck-ranking"
                )
            ),
        )
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in (
            "attention.sqlite3",
            "attention.sqlite3-wal",
            "attention.sqlite3-shm",
            "attention.sqlite3-journal",
            "writer.lock",
        ):
            _regular_or_absent(self.state / name)
        self.artifacts = no_symlink_path(self.state / "artifacts")
        self.artifacts.mkdir(exist_ok=True, mode=0o700)
        self._lock = os.open(
            self.state / "writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self._lock)
            self._lock = -1
            raise RuntimeError("attention writer already active") from exc
        try:
            self.connection = sqlite3.connect(self.state / "attention.sqlite3")
            if self.connection.execute(
                "SELECT name FROM sqlite_master WHERE name='metadata'"
            ).fetchone():
                existing = self.connection.execute(
                    "SELECT value FROM metadata WHERE key='schema'"
                ).fetchone()
                if not existing or existing[0] != SCHEMA_VERSION:
                    raise ValueError("unknown attention database schema")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA busy_timeout=5000")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS input_generations (
                    id TEXT PRIMARY KEY, decision_at INTEGER NOT NULL, cutoff INTEGER NOT NULL,
                    evidence INTEGER NOT NULL CHECK(evidence IN (0,1)),
                    inputs TEXT NOT NULL, response TEXT NOT NULL, fingerprint TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feature_rows (
                    generation_id TEXT NOT NULL REFERENCES input_generations(id),
                    asset_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(generation_id,asset_id)
                );
                CREATE TABLE IF NOT EXISTS component_rows (
                    generation_id TEXT NOT NULL REFERENCES input_generations(id),
                    asset_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(generation_id,asset_id)
                );
                CREATE TABLE IF NOT EXISTS outcome_rows (
                    generation_id TEXT NOT NULL REFERENCES input_generations(id),
                    asset_id TEXT NOT NULL, horizon INTEGER NOT NULL, family TEXT NOT NULL,
                    edition INTEGER NOT NULL, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    PRIMARY KEY(generation_id,asset_id,horizon,family,edition),
                    FOREIGN KEY(generation_id,asset_id)
                        REFERENCES feature_rows(generation_id,asset_id)
                );
                CREATE TABLE IF NOT EXISTS candidate_policies (
                    id TEXT PRIMARY KEY, family_id TEXT NOT NULL,
                    hash TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidate_runs (
                    id TEXT PRIMARY KEY, family_id TEXT NOT NULL, payload TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, stale INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS shadow_allocations (
                    generation_id TEXT NOT NULL REFERENCES input_generations(id),
                    policy_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(generation_id,policy_id)
                );
                CREATE INDEX IF NOT EXISTS input_time ON input_generations(decision_at);
                CREATE INDEX IF NOT EXISTS input_latest_order
                    ON input_generations(decision_at DESC,id DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS evidence_cutoff
                    ON input_generations(cutoff) WHERE evidence=1;
            """)
            existing = self.connection.execute(
                "SELECT value FROM metadata WHERE key='schema'"
            ).fetchone()
            if existing and existing[0] != SCHEMA_VERSION:
                raise ValueError("unknown attention database schema")
            with self.connection:
                self.connection.execute(
                    "INSERT OR IGNORE INTO metadata VALUES ('schema',?)", (SCHEMA_VERSION,)
                )
            self.initialize_discovery()
        except BaseException:
            if hasattr(self, "connection"):
                self.connection.close()
            os.close(self._lock)
            self._lock = -1
            raise

    def save_generation(
        self,
        inputs: InputReference,
        features: Sequence[FeatureSnapshotRow],
        response: AttentionResponse,
        *,
        evidence: bool,
    ) -> bool:
        inputs = InputReference.model_validate_json(inputs.model_dump_json())
        response = AttentionResponse.model_validate_json(response.model_dump_json())
        features = tuple(
            FeatureSnapshotRow.model_validate_json(row.model_dump_json()) for row in features
        )
        if response.inputs != inputs or {f.asset_id for f in features} != {
            r.asset_id for r in response.rows
        }:
            raise ValueError("generation feature/response identity mismatch")
        if len(features) != len(response.rows) or any(
            f.decision_at != inputs.decision_at for f in features
        ):
            raise ValueError("generation feature time/identity mismatch")
        if evidence and inputs.ranking_cutoff % (5 * MINUTE):
            raise ValueError("evidence requires an exact five-minute input boundary")
        payload = response.model_dump(mode="json", by_alias=True)
        complete = {
            "inputs": inputs.model_dump(mode="json", by_alias=True),
            "features": [
                f.model_dump(mode="json", by_alias=True)
                for f in sorted(features, key=lambda r: r.asset_id)
            ],
            "response": payload,
            "evidence": evidence,
        }
        fingerprint = content_digest(complete)
        saved = self.connection.execute(
            "SELECT fingerprint FROM input_generations WHERE id=?", (inputs.generation_id,)
        ).fetchone()
        if saved and saved[0] != fingerprint:
            raise ValueError("immutable generation conflict")
        if not saved:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO input_generations VALUES (?,?,?,?,?,?,?)",
                    (
                        inputs.generation_id,
                        inputs.decision_at,
                        inputs.ranking_cutoff,
                        int(evidence),
                        canonical_json(complete["inputs"]),
                        canonical_json(payload),
                        fingerprint,
                    ),
                )
                if evidence:
                    self.connection.executemany(
                        "INSERT INTO feature_rows VALUES (?,?,?)",
                        [
                            (inputs.generation_id, row.asset_id, row.model_dump_json(by_alias=True))
                            for row in features
                        ],
                    )
                    self.connection.executemany(
                        "INSERT INTO component_rows VALUES (?,?,?)",
                        [
                            (inputs.generation_id, row.asset_id, row.model_dump_json(by_alias=True))
                            for row in response.rows
                        ],
                    )
                for allocation in response.shadow_allocations:
                    if allocation.generation_id != inputs.generation_id:
                        raise ValueError("allocation generation mismatch")
                    self.connection.execute(
                        "INSERT INTO shadow_allocations VALUES (?,?,?)",
                        (
                            inputs.generation_id,
                            allocation.policy.id,
                            allocation.model_dump_json(by_alias=True),
                        ),
                    )
        readback = self.connection.execute(
            "SELECT response,fingerprint FROM input_generations WHERE id=?", (inputs.generation_id,)
        ).fetchone()
        if (
            not readback
            or readback[1] != fingerprint
            or content_digest(json.loads(readback[0])) != content_digest(payload)
        ):
            raise RuntimeError("attention database readback mismatch")
        saved_inputs = self.connection.execute(
            "SELECT inputs FROM input_generations WHERE id=?", (inputs.generation_id,)
        ).fetchone()
        if not saved_inputs or json.loads(saved_inputs[0]) != complete["inputs"]:
            raise RuntimeError("attention input readback mismatch")
        if evidence:
            for table, expected in (
                ("feature_rows", complete["features"]),
                (
                    "component_rows",
                    [
                        r.model_dump(mode="json", by_alias=True)
                        for r in sorted(response.rows, key=lambda r: r.asset_id)
                    ],
                ),
            ):
                records = self.connection.execute(
                    f"SELECT payload FROM {table} WHERE generation_id=? ORDER BY asset_id",
                    (inputs.generation_id,),
                ).fetchall()
                if [json.loads(record[0]) for record in records] != expected:
                    raise RuntimeError("attention evidence readback mismatch")
        allocations = self.connection.execute(
            "SELECT payload FROM shadow_allocations WHERE generation_id=? ORDER BY policy_id",
            (inputs.generation_id,),
        ).fetchall()
        if [json.loads(record[0]) for record in allocations] != [
            a.model_dump(mode="json", by_alias=True)
            for a in sorted(response.shadow_allocations, key=lambda a: a.policy.id)
        ]:
            raise RuntimeError("attention allocation readback mismatch")
        # A failed file publication may be retried for the exact committed generation.
        immutable = (
            self.artifacts / f"{hashlib.sha256(inputs.generation_id.encode()).hexdigest()}.json"
        )
        if immutable.exists():
            _regular_or_absent(immutable)
            if immutable.read_bytes() != canonical_json(payload).encode():
                raise ValueError("immutable artifact conflict")
        else:
            atomic_json(immutable, payload)
        atomic_json(self.artifacts / "current.json", payload)
        return not bool(saved)

    def has_evidence_cutoff(self, cutoff: int) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM input_generations WHERE cutoff=? AND evidence=1", (cutoff,)
            ).fetchone()
            is not None
        )

    def latest_response(self) -> AttentionResponse | None:
        row = self.connection.execute(
            "SELECT response FROM input_generations ORDER BY decision_at DESC,id DESC LIMIT 1"
        ).fetchone()
        return AttentionResponse.model_validate_json(row[0]) if row else None

    def evidence_generations(
        self,
    ) -> list[tuple[InputReference, tuple[FeatureSnapshotRow, ...], AttentionResponse]]:
        result = []
        for identity, inputs, response in self.connection.execute(
            "SELECT id,inputs,response FROM input_generations "
            "WHERE evidence=1 ORDER BY decision_at,id"
        ).fetchall():
            features = self.connection.execute(
                "SELECT payload FROM feature_rows WHERE generation_id=? ORDER BY asset_id",
                (identity,),
            ).fetchall()
            result.append(
                (
                    InputReference.model_validate_json(inputs),
                    tuple(FeatureSnapshotRow.model_validate_json(r[0]) for r in features),
                    AttentionResponse.model_validate_json(response),
                )
            )
        return result

    def put_outcome(self, outcome: OutcomeRow) -> OutcomeRow:
        outcome = OutcomeRow.model_validate_json(outcome.model_dump_json())
        key = (outcome.generation_id, outcome.asset_id, outcome.horizon_minutes, outcome.family)
        row = self.connection.execute(
            "SELECT payload FROM outcome_rows WHERE generation_id=? AND asset_id=? "
            "AND horizon=? AND family=? ORDER BY edition DESC LIMIT 1",
            key,
        ).fetchone()
        edition = 1
        if row:
            previous = OutcomeRow.model_validate_json(row[0])
            # Re-observing the same inputs does not invent a correction or change settlement time.
            stable = {"edition", "settled_at"}
            if previous.model_dump(exclude=stable) == outcome.model_dump(exclude=stable):
                return previous
            edition = previous.edition + 1
        outcome = outcome.model_copy(update={"edition": edition})
        if row:
            latest = self.connection.execute(
                "SELECT payload FROM candidate_runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if latest:
                # Invalidate the projection first. A crash may leave a conservative stale
                # report, but never a falsely current report after a committed correction.
                report = AttentionEvaluationReport.model_validate_json(latest[0])
                atomic_json(
                    self.artifacts / "evaluation.json",
                    report.model_copy(update={"stale": True}).model_dump(
                        mode="json", by_alias=True
                    ),
                )
        with self.connection:
            self.connection.execute(
                "INSERT INTO outcome_rows VALUES (?,?,?,?,?,?,?)",
                (*key, edition, outcome.model_dump_json(by_alias=True), outcome.input_fingerprint),
            )
            if row:
                self.connection.execute("UPDATE candidate_runs SET stale=1")
        return outcome

    def latest_outcomes(self) -> tuple[OutcomeRow, ...]:
        rows = self.connection.execute("""SELECT a.payload FROM outcome_rows a WHERE a.edition=(
          SELECT MAX(b.edition) FROM outcome_rows b WHERE b.generation_id=a.generation_id
          AND b.asset_id=a.asset_id AND b.horizon=a.horizon AND b.family=a.family)
          ORDER BY a.generation_id,a.asset_id,a.horizon,a.family""").fetchall()
        return tuple(OutcomeRow.model_validate_json(row[0]) for row in rows)

    def freeze_family(self, policies: Sequence[CandidatePolicy]) -> None:
        if (
            not policies
            or len({p.family_id for p in policies}) != 1
            or len({p.id for p in policies}) != len(policies)
        ):
            raise ValueError("one complete candidate family is required")
        family = policies[0].family_id
        records = {p.id: content_digest(p.model_dump(mode="json", by_alias=True)) for p in policies}
        marker = f"family:{family}"
        fingerprint = content_digest(records)
        old = self.connection.execute(
            "SELECT value FROM metadata WHERE key=?", (marker,)
        ).fetchone()
        if old and old[0] != fingerprint:
            raise ValueError("frozen candidate family conflict; create a new family/version")
        with self.connection:
            for policy in policies:
                existing = self.connection.execute(
                    "SELECT hash FROM candidate_policies WHERE id=?", (policy.id,)
                ).fetchone()
                if existing and existing[0] != records[policy.id]:
                    raise ValueError("frozen policy conflict")
                self.connection.execute(
                    "INSERT OR IGNORE INTO candidate_policies VALUES (?,?,?,?)",
                    (policy.id, family, records[policy.id], policy.model_dump_json(by_alias=True)),
                )
            self.connection.execute(
                "INSERT OR IGNORE INTO metadata VALUES (?,?)", (marker, fingerprint)
            )

    def policies(self, family_id: str | None = None) -> tuple[CandidatePolicy, ...]:
        query = "SELECT payload FROM candidate_policies"
        params: tuple[str, ...] = ()
        if family_id is not None:
            query += " WHERE family_id=?"
            params = (family_id,)
        rows = self.connection.execute(query + " ORDER BY id", params).fetchall()
        return tuple(CandidatePolicy.model_validate_json(row[0]) for row in rows)

    def save_evaluation(self, report: AttentionEvaluationReport) -> None:
        payload = report.model_dump_json(by_alias=True)
        fingerprint = content_digest(report.model_dump(mode="json", by_alias=True))
        old = self.connection.execute(
            "SELECT fingerprint,stale FROM candidate_runs WHERE id=?", (report.run_id,)
        ).fetchone()
        if old and old[0] != fingerprint:
            raise ValueError("immutable evaluation conflict")
        if old and old[1]:
            raise ValueError("stale evaluation must be recomputed with current outcomes")
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO candidate_runs VALUES (?,?,?,?,0)",
                (report.run_id, report.family_id, payload, fingerprint),
            )
        atomic_json(
            self.artifacts / "evaluation.json", report.model_dump(mode="json", by_alias=True)
        )

    def evaluations(self) -> tuple[AttentionEvaluationReport, ...]:
        rows = self.connection.execute(
            "SELECT payload,stale FROM candidate_runs ORDER BY id"
        ).fetchall()
        return tuple(
            AttentionEvaluationReport.model_validate_json(row[0]).model_copy(
                update={"stale": bool(row[1])}
            )
            for row in rows
        )

    def latest_allocation(self, policy_id: str) -> ShadowAllocation | None:
        row = self.connection.execute(
            """SELECT a.payload FROM shadow_allocations a
          JOIN input_generations g ON g.id=a.generation_id
          WHERE a.policy_id=? ORDER BY g.decision_at DESC,g.id DESC LIMIT 1""",
            (policy_id,),
        ).fetchone()
        return ShadowAllocation.model_validate_json(row[0]) if row else None

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.state.glob("attention.sqlite3*") if p.is_file())

    def close(self) -> None:
        if self._lock >= 0:
            self.connection.close()
            fcntl.flock(self._lock, fcntl.LOCK_UN)
            os.close(self._lock)
            self._lock = -1
