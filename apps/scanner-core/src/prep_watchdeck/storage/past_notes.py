from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TWO_MONTHS_MS = 60 * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class PastNote:
    symbol: str
    reason: str
    observed_at: str
    expires_at: str
    note: str

    @property
    def merge_key(self) -> tuple[str, str]:
        return (self.symbol, self.reason)

    def to_json(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "reason": self.reason,
            "observedAt": self.observed_at,
            "expiresAt": self.expires_at,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, value: object) -> PastNote | None:
        if not isinstance(value, dict):
            return None
        candidate = value
        symbol = candidate.get("symbol")
        reason = candidate.get("reason")
        observed_at = candidate.get("observedAt")
        expires_at = candidate.get("expiresAt")
        note = candidate.get("note")
        if not isinstance(symbol, str):
            return None
        if not isinstance(reason, str):
            return None
        if not isinstance(observed_at, str):
            return None
        if not isinstance(expires_at, str):
            return None
        if not isinstance(note, str):
            return None
        return cls(
            symbol=symbol,
            reason=reason,
            observed_at=observed_at,
            expires_at=expires_at,
            note=note,
        )


class PastNoteRepository:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def list_notes(self, *, now_ms: int | None = None) -> list[PastNote]:
        notes = self._read_notes(self.current_path())
        active, archived = self._rotate(notes, now_ms=self._now_ms(now_ms))
        if archived or len(active) != len(notes):
            self._write_current(active)
            self._append_archives(archived)
        return active

    def save_many(self, notes: list[PastNote], *, now_ms: int | None = None) -> list[PastNote]:
        current = self.list_notes(now_ms=now_ms)
        replace_keys = {note.merge_key for note in notes}
        next_notes = [*notes, *[note for note in current if note.merge_key not in replace_keys]]
        active, archived = self._rotate(next_notes, now_ms=self._now_ms(now_ms))
        self._write_current(active)
        self._append_archives(archived)
        return active

    def current_path(self) -> Path:
        return self.root_dir / "current.json"

    def _rotate(
        self, notes: list[PastNote], *, now_ms: int
    ) -> tuple[list[PastNote], list[PastNote]]:
        cutoff_ms = now_ms - TWO_MONTHS_MS
        active: list[PastNote] = []
        archived: list[PastNote] = []
        for note in notes:
            observed_at_ms = _parse_iso_ms(note.observed_at)
            expires_at_ms = _parse_iso_ms(note.expires_at)
            if (
                observed_at_ms is None
                or expires_at_ms is None
                or observed_at_ms <= cutoff_ms
                or expires_at_ms <= now_ms
            ):
                archived.append(note)
            else:
                active.append(note)
        return active, archived

    def _read_notes(self, path: Path) -> list[PastNote]:
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict):
            return []
        raw_notes = payload.get("notes")
        if not isinstance(raw_notes, list):
            return []
        return [note for item in raw_notes if (note := PastNote.from_json(item)) is not None]

    def _write_current(self, notes: list[PastNote]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.current_path().write_text(_notes_json(notes), encoding="utf-8")

    def _append_archives(self, notes: list[PastNote]) -> None:
        for note in notes:
            archive_path = self._archive_path(note)
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            archive_notes = self._read_notes(archive_path)
            deduped = [
                item
                for item in archive_notes
                if not (item.symbol == note.symbol and item.observed_at == note.observed_at)
            ]
            archive_path.write_text(_notes_json([note, *deduped]), encoding="utf-8")

    def _archive_path(self, note: PastNote) -> Path:
        observed_at = _parse_iso_datetime(note.observed_at)
        if observed_at is None:
            month = "unknown"
        else:
            month = f"{observed_at.year:04d}-{observed_at.month:02d}"
        return self.root_dir / "archive" / month / f"past-notes-{month}.json"

    @staticmethod
    def _now_ms(now_ms: int | None) -> int:
        return now_ms if now_ms is not None else int(datetime.now(UTC).timestamp() * 1000)


def make_past_note(*, symbol: str, reason: str, note: str, now_ms: int) -> PastNote:
    return PastNote(
        symbol=symbol.upper(),
        reason=reason,
        observed_at=_format_iso_ms(now_ms),
        expires_at=_format_iso_ms(now_ms + TWO_MONTHS_MS),
        note=note,
    )


def _notes_json(notes: list[PastNote]) -> str:
    return (
        json.dumps({"notes": [note.to_json() for note in notes]}, ensure_ascii=False, indent=2)
        + "\n"
    )


def _parse_iso_ms(value: str) -> int | None:
    dt = _parse_iso_datetime(value)
    if dt is None:
        return None
    return int(dt.timestamp() * 1000)


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _format_iso_ms(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1000, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
