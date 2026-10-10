"""Replaceable latest projection and bounded episode history in the existing writer DB."""

import base64
import binascii
import json
import sqlite3
from collections.abc import Sequence

from .discovery_models import POLICY_ID, DiscoveryEpisode, DiscoveryResponse, DiscoveryRow
from .models import MINUTE, InputReference, canonical_json, content_digest

HISTORY_RETENTION_MS = 7 * 24 * 60 * MINUTE
MAX_ENDED_EPISODES = 10_000


class DiscoveryStorage:
    connection: sqlite3.Connection

    def initialize_discovery(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS discovery_latest (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS discovery_states (
                asset_id TEXT PRIMARY KEY, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS discovery_episodes (
                id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, first_observed_at INTEGER NOT NULL,
                ended_at INTEGER, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS discovery_episode_time
                ON discovery_episodes(first_observed_at DESC,id DESC);
            CREATE INDEX IF NOT EXISTS discovery_episode_end ON discovery_episodes(ended_at);
        """)

    def _write_episode(self, episode: DiscoveryEpisode) -> None:
        episode = DiscoveryEpisode.model_validate_json(episode.model_dump_json())
        self.connection.execute(
            "INSERT INTO discovery_episodes VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "ended_at=excluded.ended_at,payload=excluded.payload",
            (
                episode.id,
                episode.asset_id,
                episode.first_observed_at,
                episode.ended_at,
                episode.model_dump_json(by_alias=True),
            ),
        )

    def _episode(self, episode_id: str | None) -> DiscoveryEpisode | None:
        if episode_id is None:
            return None
        row = self.connection.execute(
            "SELECT payload FROM discovery_episodes WHERE id=?", (episode_id,)
        ).fetchone()
        return DiscoveryEpisode.model_validate_json(row[0]) if row else None

    def _latest_discovery(
        self, *, asset_ids: tuple[str, ...] = (), include_rows: bool = True
    ) -> DiscoveryResponse | None:
        projection = "payload"
        if not include_rows:
            projection = "json_set(payload,'$.rows',json('[]'))"
        elif asset_ids:
            # Filter inside SQLite: a four-asset read must not deserialize every native
            # observation in the full-universe projection into Python objects.
            placeholders = ",".join("?" for _ in asset_ids)
            projection = (
                "json_set(payload,'$.rows',json((SELECT json_group_array(json(value)) "
                "FROM json_each(payload,'$.rows') WHERE json_extract(value,'$.assetId') "
                f"IN ({placeholders}))))"
            )
        row = self.connection.execute(
            f"SELECT {projection} FROM discovery_latest WHERE singleton=1",
            asset_ids if include_rows else (),
        ).fetchone()
        return DiscoveryResponse.model_validate_json(row[0]) if row else None

    def _write_projection(self, response: DiscoveryResponse) -> str:
        response = DiscoveryResponse.model_validate_json(response.model_dump_json())
        payload = response.model_dump_json(by_alias=True)
        self.connection.execute(
            "INSERT INTO discovery_latest VALUES (1,?) ON CONFLICT(singleton) DO UPDATE "
            "SET payload=excluded.payload",
            (payload,),
        )
        return payload

    def interrupt_discovery(self, reason: str) -> None:
        """Writer-side failed observation; no condition release or elapsed-time invention."""
        latest = self._latest_discovery()
        if latest is None:
            return
        with self.connection:
            for asset_id, payload in self.connection.execute(
                "SELECT asset_id,payload FROM discovery_states"
            ).fetchall():
                state = json.loads(payload)
                state["interrupted"] = True
                state["state"] = "unknown"
                self.connection.execute(
                    "UPDATE discovery_states SET payload=? WHERE asset_id=?",
                    (canonical_json(state), asset_id),
                )
            for (payload,) in self.connection.execute(
                "SELECT payload FROM discovery_episodes WHERE ended_at IS NULL"
            ).fetchall():
                episode = DiscoveryEpisode.model_validate_json(payload)
                self._write_episode(
                    episode.model_copy(
                        update={
                            "state": "interrupted",
                            "interruption_reason": reason,
                        }
                    )
                )
            self._write_projection(
                latest.model_copy(
                    update={
                        "status": "stale",
                        "reason": reason,
                        "rows": tuple(
                            row.model_copy(
                                update={
                                    "state": "unknown",
                                    "reason": reason,
                                    "confirmation": None,
                                }
                            )
                            for row in latest.rows
                        ),
                    }
                )
            )

    def save_discovery(
        self,
        inputs: InputReference,
        rows: Sequence[DiscoveryRow],
        *,
        restarted: bool = False,
    ) -> bool:
        """Evaluate a strictly new cutoff once; same-cutoff raw refresh never counts again."""
        rows = tuple(DiscoveryRow.model_validate_json(row.model_dump_json()) for row in rows)
        if len({row.asset_id for row in rows}) != len(rows):
            raise ValueError("duplicate discovery row")
        latest = self._latest_discovery(include_rows=False)
        if (
            latest
            and latest.ranking_cutoff is not None
            and inputs.ranking_cutoff < latest.ranking_cutoff
        ):
            return False
        previous_states = {
            asset_id: json.loads(payload)
            for asset_id, payload in self.connection.execute(
                "SELECT asset_id,payload FROM discovery_states"
            ).fetchall()
        }
        new_cutoff = latest is None or latest.ranking_cutoff != inputs.ranking_cutoff
        if not new_cutoff:
            # Refreshes need only condition continuity, not the previous native/raw tree.
            previous_rows = {
                asset_id: json.loads(state)
                for asset_id, state in self.connection.execute(
                    "SELECT json_extract(value,'$.assetId'),json_object("
                    "'identityKey',json_extract(value,'$.identityKey'),"
                    "'state',json_extract(value,'$.state'),"
                    "'reason',json_extract(value,'$.reason'),"
                    "'confirmation',json_extract(value,'$.confirmation'),"
                    "'episodeId',json_extract(value,'$.episodeId')) "
                    "FROM discovery_latest,json_each(payload,'$.rows') WHERE singleton=1"
                )
            }
            # A refresh cannot reconfirm/release the evaluated condition, but missing or
            # ineligible observations must break continuity even within the same cutoff.
            refreshed = []
            present = {row.asset_id for row in rows}
            interruptions = {
                asset_id: "row_missing" for asset_id in previous_states if asset_id not in present
            }
            for row in rows:
                previous = previous_rows.get(row.asset_id)
                old = previous_states.get(row.asset_id)
                same = previous is not None and previous["identityKey"] == row.identity_key
                same_state = bool(
                    old and old["identityKey"] == row.identity_key and old["policyId"] == POLICY_ID
                )
                unavailable = (
                    restarted
                    or row.state == "unknown"
                    or row.raw.identity_status in ("invalid", "excluded")
                    or not all(original.current for original in row.originals)
                )
                reason = "awaiting_new_cutoff" if restarted else row.reason or "identity_ineligible"
                if old and (unavailable or not same_state):
                    interruptions[row.asset_id] = reason if unavailable else "identity_changed"
                state = (
                    "unknown"
                    if unavailable
                    else previous["state"]
                    if same and previous
                    else "unknown"
                )
                episode_id = (
                    previous["episodeId"]
                    if same and previous
                    else old.get("episodeId")
                    if same_state and old
                    else None
                )
                refreshed.append(
                    row.model_copy(
                        update={
                            "state": state,
                            "reason": reason
                            if unavailable
                            else previous["reason"]
                            if same and previous
                            else "awaiting_new_cutoff",
                            "confirmation": previous["confirmation"]
                            if state != "unknown" and same and previous
                            else None,
                            "episode_id": episode_id,
                        }
                    )
                )
            with self.connection:
                for asset_id, reason in interruptions.items():
                    old = previous_states[asset_id]
                    old.update({"state": "unknown", "interrupted": True})
                    self.connection.execute(
                        "UPDATE discovery_states SET payload=? WHERE asset_id=?",
                        (canonical_json(old), asset_id),
                    )
                    episode = self._episode(old.get("episodeId"))
                    if episode and episode.ended_at is None:
                        self._write_episode(
                            episode.model_copy(
                                update={
                                    "state": "interrupted",
                                    "interruption_reason": reason,
                                }
                            )
                        )
                incomplete = bool(interruptions) or any(row.state == "unknown" for row in refreshed)
                self._write_projection(
                    DiscoveryResponse(
                        generation_id=inputs.generation_id,
                        decision_at=inputs.decision_at,
                        ranking_cutoff=inputs.ranking_cutoff,
                        inputs=inputs,
                        status="stale"
                        if latest and latest.status == "stale"
                        else "partial"
                        if incomplete
                        else "ready",
                        reason=latest.reason
                        if latest and latest.status == "stale"
                        else "incomplete_discovery_coverage"
                        if incomplete
                        else None,
                        history_available_from=None,
                        rows=tuple(refreshed),
                        episodes=(),
                    )
                )
            return False
        projected = []
        with self.connection:
            for row in rows:
                old = previous_states.get(row.asset_id)
                episode = self._episode(old.get("episodeId") if old else None)
                same_identity = bool(
                    old and old["identityKey"] == row.identity_key and old["policyId"] == POLICY_ID
                )
                if old and not same_identity and episode and episode.ended_at is None:
                    self._write_episode(
                        episode.model_copy(
                            update={
                                "state": "ended",
                                "ended_at": inputs.decision_at,
                                "end_reason": "identity_changed"
                                if old["policyId"] == POLICY_ID
                                else "policy_changed",
                                "interruption_reason": None,
                            }
                        )
                    )
                    episode = None
                contiguous = bool(
                    same_identity
                    and old
                    and not old["interrupted"]
                    and not restarted
                    and old["cutoff"] + MINUTE == inputs.ranking_cutoff
                    and old["mapVersion"] == inputs.ranking_map_version
                    and old["metricVersion"] == inputs.ranking_metric_version
                    and old["state"] != "unknown"
                )
                confirmation = None
                episode_id = None
                if row.state == "matched":
                    if episode and episode.ended_at is None and same_identity:
                        confirmation = (
                            "continuing"
                            if contiguous and old and old["state"] == "matched"
                            else "reconfirmation"
                        )
                        episode = episode.model_copy(
                            update={
                                "state": "active",
                                "last_confirmed_at": inputs.decision_at,
                                "consecutive_confirmations": episode.consecutive_confirmations + 1
                                if confirmation == "continuing"
                                else 1,
                                "observed_duration_ms": episode.observed_duration_ms
                                + (
                                    inputs.ranking_cutoff - episode.last_ranking_cutoff
                                    if confirmation == "continuing"
                                    else 0
                                ),
                                "last_source_generation_id": inputs.ranking_generation_id,
                                "last_ranking_cutoff": inputs.ranking_cutoff,
                                "direction": row.direction,
                                "interruption_reason": None,
                            }
                        )
                    else:
                        confirmation = (
                            "new"
                            if contiguous and old and old["state"] == "not_matched"
                            else "reconfirmation"
                            if same_identity and old
                            else "initial_confirmation"
                        )
                        episode = DiscoveryEpisode(
                            id=content_digest(
                                {
                                    "policy": POLICY_ID,
                                    "identity": row.identity_key,
                                    "cutoff": inputs.ranking_cutoff,
                                }
                            ),
                            identity_key=row.identity_key,
                            asset_id=row.asset_id,
                            asset=row.asset,
                            reference_key=row.reference_key,
                            originals=row.originals,
                            state="active",
                            start_kind=confirmation,
                            first_observed_at=inputs.decision_at,
                            last_confirmed_at=inputs.decision_at,
                            consecutive_confirmations=1,
                            observed_duration_ms=0,
                            direction=row.direction,
                            first_source_generation_id=inputs.ranking_generation_id,
                            last_source_generation_id=inputs.ranking_generation_id,
                            first_ranking_cutoff=inputs.ranking_cutoff,
                            last_ranking_cutoff=inputs.ranking_cutoff,
                        )
                    self._write_episode(episode)
                    episode_id = episode.id
                elif episode and episode.ended_at is None and same_identity:
                    if row.state == "not_matched":
                        self._write_episode(
                            episode.model_copy(
                                update={
                                    "state": "ended",
                                    "ended_at": inputs.decision_at,
                                    "end_reason": "condition_not_matched",
                                    "interruption_reason": None,
                                }
                            )
                        )
                    else:
                        self._write_episode(
                            episode.model_copy(
                                update={
                                    "state": "interrupted",
                                    "interruption_reason": row.reason,
                                }
                            )
                        )
                        episode_id = episode.id
                state = {
                    "identityKey": row.identity_key,
                    "policyId": POLICY_ID,
                    "state": row.state,
                    "cutoff": inputs.ranking_cutoff,
                    "mapVersion": inputs.ranking_map_version,
                    "metricVersion": inputs.ranking_metric_version,
                    "interrupted": row.state == "unknown",
                    "episodeId": episode_id,
                }
                self.connection.execute(
                    "INSERT INTO discovery_states VALUES (?,?) ON CONFLICT(asset_id) DO UPDATE "
                    "SET payload=excluded.payload",
                    (row.asset_id, canonical_json(state)),
                )
                projected.append(
                    row.model_copy(update={"confirmation": confirmation, "episode_id": episode_id})
                )
            present = {row.asset_id for row in rows}
            missing_active = False
            for asset_id, old in previous_states.items():
                if asset_id in present:
                    continue
                episode = self._episode(old.get("episodeId"))
                if episode and episode.ended_at is None:
                    missing_active = True
                    self._write_episode(
                        episode.model_copy(
                            update={"state": "interrupted", "interruption_reason": "row_missing"}
                        )
                    )
                old.update({"state": "unknown", "interrupted": True})
                self.connection.execute(
                    "UPDATE discovery_states SET payload=? WHERE asset_id=?",
                    (canonical_json(old), asset_id),
                )
            self._prune_discovery(inputs.decision_at)
            incomplete = missing_active or any(row.state == "unknown" for row in projected)
            expected_payload = self._write_projection(
                DiscoveryResponse(
                    generation_id=inputs.generation_id,
                    decision_at=inputs.decision_at,
                    ranking_cutoff=inputs.ranking_cutoff,
                    inputs=inputs,
                    status="partial" if incomplete else "ready",
                    reason="incomplete_discovery_coverage" if incomplete else None,
                    history_available_from=None,
                    rows=tuple(projected),
                    episodes=(),
                )
            )
        saved = self.connection.execute(
            "SELECT payload FROM discovery_latest WHERE singleton=1"
        ).fetchone()
        # The complete payload was schema-validated before writing. Compare the exact
        # committed bytes without keeping another full model graph alive for readback.
        if saved is None or saved[0] != expected_payload:
            raise RuntimeError("discovery projection readback mismatch")
        return True

    def _prune_discovery(self, now: int) -> None:
        self.connection.execute(
            "DELETE FROM discovery_episodes WHERE ended_at IS NOT NULL AND ended_at<?",
            (now - HISTORY_RETENTION_MS,),
        )
        self.connection.execute(
            "DELETE FROM discovery_episodes WHERE id IN (SELECT id FROM discovery_episodes "
            "WHERE ended_at IS NOT NULL ORDER BY ended_at DESC,id DESC LIMIT -1 OFFSET ?)",
            (MAX_ENDED_EPISODES,),
        )

    def discovery_response(
        self,
        *,
        asset_ids: tuple[str, ...] = (),
        limit: int = 50,
        cursor: str | None = None,
    ) -> DiscoveryResponse:
        """A pure DB read; keyset cursor is bound to the selected asset IDs."""
        if len(asset_ids) > 4 or len(set(asset_ids)) != len(asset_ids) or not 1 <= limit <= 50:
            raise ValueError("invalid discovery query")
        scope = content_digest(sorted(asset_ids))
        conditions = []
        params: list[object] = []
        if asset_ids:
            conditions.append("asset_id IN (" + ",".join("?" for _ in asset_ids) + ")")
            params.extend(asset_ids)
        history_where = " WHERE " + " AND ".join(conditions) if conditions else ""
        history = self.connection.execute(
            "SELECT MIN(first_observed_at) FROM discovery_episodes" + history_where, params
        ).fetchone()[0]
        if cursor is not None:
            try:
                decoded = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                first, identity, cursor_scope = decoded
                if (
                    type(first) is not int
                    or not 0 < first <= 2**63 - 1
                    or not isinstance(identity, str)
                    or cursor_scope != scope
                ):
                    raise ValueError("invalid cursor values")
            except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as error:
                raise ValueError("invalid discovery cursor") from error
            conditions.append("(first_observed_at<? OR (first_observed_at=? AND id<?))")
            params.extend((first, first, identity))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        records = self.connection.execute(
            "SELECT payload FROM discovery_episodes"
            + where
            + " ORDER BY first_observed_at DESC,id DESC LIMIT ?",
            [*params, limit + 1],
        ).fetchall()
        episodes = tuple(
            DiscoveryEpisode.model_validate_json(record[0]) for record in records[:limit]
        )
        next_cursor = None
        if len(records) > limit:
            tail = episodes[-1]
            next_cursor = base64.urlsafe_b64encode(
                canonical_json([tail.first_observed_at, tail.id, scope]).encode()
            ).decode()
        latest = self._latest_discovery(asset_ids=asset_ids) or DiscoveryResponse(
            generation_id=None,
            decision_at=None,
            ranking_cutoff=None,
            inputs=None,
            status="unavailable",
            reason="generation_pending",
            history_available_from=None,
            rows=(),
            episodes=(),
        )
        return latest.model_copy(
            update={
                "history_available_from": history,
                "episodes": episodes,
                "next_cursor": next_cursor,
            }
        )
