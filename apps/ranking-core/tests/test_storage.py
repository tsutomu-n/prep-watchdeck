from pathlib import Path

import pytest
from pydantic import ValidationError

from prep_watchdeck_ranking.models import MINUTE, MinuteBar, RankingMap
from prep_watchdeck_ranking.storage import Store, atomic_json, isolated_state

from .conftest import CUTOFF, candle, mapping, reference


def test_overlap_rejected_in_both_directions_before_writing(tmp_path: Path) -> None:
    original = tmp_path / "market"
    for state in [original, original / "ranking", tmp_path]:
        with pytest.raises(ValueError, match="overlap"):
            isolated_state(state, original)
    assert not original.exists()


def test_symlink_overlap_and_database_escape_rejected(tmp_path: Path) -> None:
    original = tmp_path / "market"
    original.mkdir()
    link = tmp_path / "ranking-link"
    link.symlink_to(original, target_is_directory=True)
    with pytest.raises(ValueError, match="overlap"):
        Store(link, original)
    separate = tmp_path / "ranking"
    separate.mkdir()
    (separate / "ranking.sqlite3-wal").symlink_to(original / "important")
    with pytest.raises(ValueError, match="escape"):
        Store(separate, original)
    assert list(original.iterdir()) == []


def test_atomic_json_does_not_follow_temporary_symlink(tmp_path: Path) -> None:
    protected = tmp_path / "important"
    protected.write_text("preserve")
    (tmp_path / "snapshot.json.tmp").symlink_to(protected)
    with pytest.raises(OSError):
        atomic_json(tmp_path / "snapshot.json", {"new": True})
    assert protected.read_text() == "preserve"


def test_original_absence_does_not_block_saved_map_or_prices(store: Store) -> None:
    store.set_map(mapping("BTC"))
    store.put([candle(reference(), CUTOFF)], CUTOFF)
    assert store.get_map() == mapping("BTC")
    assert store.latest(reference().key) == CUTOFF


def test_duplicate_upsert_and_pruning_are_bounded(store: Store) -> None:
    bar = candle(reference(), CUTOFF)
    store.put([bar, bar, candle(reference(), CUTOFF - 3000 * MINUTE)], CUTOFF)
    assert len(store.window(reference().key, 0, CUTOFF)) == 2
    store.prune(CUTOFF, {reference().key})
    assert len(store.window(reference().key, 0, CUTOFF)) == 1


def test_future_unclosed_candle_is_not_persisted(store: Store) -> None:
    with pytest.raises(ValueError, match="future"):
        store.put([candle(reference(), CUTOFF + MINUTE)], CUTOFF)
    assert store.latest(reference().key) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"close": float("nan")},
        {"close": float("inf")},
        {"low": 200},
        {"open": 0},
        {"quoteTurnover": -1},
        {"end": CUTOFF + 1},
    ],
)
def test_invalid_bars_are_rejected(changes: dict) -> None:
    payload = candle(reference(), CUTOFF).model_dump(by_alias=True) | changes
    with pytest.raises(ValidationError):
        MinuteBar.model_validate(payload)


def test_mapping_requires_complete_unique_original_identity() -> None:
    payload = mapping("BTC").model_dump(by_alias=True)
    payload["sourceInstrumentCount"] = 2
    with pytest.raises(ValidationError, match="missing"):
        RankingMap.model_validate(payload)


def test_widget_cannot_silently_change_reference_exchange() -> None:
    payload = mapping("BTC").model_dump(mode="json", by_alias=True)
    payload["rows"][0]["widget"]["symbol"] = "BINANCE:BTCUSDT.P"
    with pytest.raises(ValidationError, match="differs"):
        RankingMap.model_validate(payload)
