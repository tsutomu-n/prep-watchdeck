from pathlib import Path

from prep_watchdeck.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]

PATH_ENV_NAMES = (
    "PREP_WATCHDECK_STATE_DIR",
    "PREP_WATCHDECK_DATA_DIR",
    "PREP_WATCHDECK_OUT_DIR",
    "PREP_WATCHDECK_CACHE_DB_PATH",
    "PREP_WATCHDECK_PAST_NOTES_DIR",
    "PREP_WATCHDECK_LOCK_FILE",
    "PREP_WATCHDECK_SERVICE_STATE_PATH",
    "PREP_WATCHDECK_TICKER_RUNTIME_PATH",
)


def test_settings_keep_repo_var_defaults_without_state_dir(monkeypatch) -> None:
    clear_path_env(monkeypatch)

    settings = Settings()

    assert settings.state_dir == REPO_ROOT / "var"
    assert settings.data_dir == REPO_ROOT / "var"
    assert settings.out_dir == REPO_ROOT / "var/snapshots"
    assert settings.cache_db_path == REPO_ROOT / "var/watchdeck.duckdb"
    assert settings.past_notes_dir == REPO_ROOT / "var/past-notes"
    assert settings.lock_file == REPO_ROOT / "var/scanner.lock"
    assert settings.service_state_path == REPO_ROOT / "var/snapshots/service-state.json"
    assert settings.ticker_runtime_path == REPO_ROOT / "var/snapshots/ticker-runtime.json"
    assert settings.vpi_config_path == REPO_ROOT / "config/vpi-lite-plus.toml"


def test_settings_derive_runtime_paths_from_state_dir(monkeypatch, tmp_path: Path) -> None:
    clear_path_env(monkeypatch)
    state_dir = tmp_path / "watchdeck-state"
    monkeypatch.setenv("PREP_WATCHDECK_STATE_DIR", str(state_dir))

    settings = Settings()

    assert settings.state_dir == state_dir
    assert settings.data_dir == state_dir
    assert settings.out_dir == state_dir / "snapshots"
    assert settings.cache_db_path == state_dir / "watchdeck.duckdb"
    assert settings.past_notes_dir == state_dir / "past-notes"
    assert settings.lock_file == state_dir / "scanner.lock"
    assert settings.service_state_path == state_dir / "snapshots" / "service-state.json"
    assert settings.ticker_runtime_path == state_dir / "snapshots" / "ticker-runtime.json"


def test_individual_path_overrides_win_over_state_dir(monkeypatch, tmp_path: Path) -> None:
    clear_path_env(monkeypatch)
    state_dir = tmp_path / "state"
    custom_snapshot_dir = tmp_path / "custom-snapshots"
    custom_db = tmp_path / "custom.duckdb"
    monkeypatch.setenv("PREP_WATCHDECK_STATE_DIR", str(state_dir))
    monkeypatch.setenv("PREP_WATCHDECK_OUT_DIR", str(custom_snapshot_dir))
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_DB_PATH", str(custom_db))

    settings = Settings()

    assert settings.state_dir == state_dir
    assert settings.data_dir == state_dir
    assert settings.out_dir == custom_snapshot_dir
    assert settings.cache_db_path == custom_db
    assert settings.past_notes_dir == state_dir / "past-notes"
    assert settings.service_state_path == state_dir / "snapshots" / "service-state.json"


def test_relative_individual_overrides_keep_scanner_cwd_semantics(monkeypatch) -> None:
    clear_path_env(monkeypatch)
    monkeypatch.setenv("PREP_WATCHDECK_OUT_DIR", "custom-snapshots")
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_DB_PATH", "custom.duckdb")

    settings = Settings()

    assert settings.out_dir == Path.cwd() / "custom-snapshots"
    assert settings.cache_db_path == Path.cwd() / "custom.duckdb"


def test_programmatic_state_dir_uses_the_same_derivation(tmp_path: Path) -> None:
    state_dir = tmp_path / "programmatic-state"

    settings = Settings(state_dir=state_dir)

    assert settings.out_dir == state_dir / "snapshots"
    assert settings.cache_db_path == state_dir / "watchdeck.duckdb"
    assert settings.ticker_runtime_path == state_dir / "snapshots" / "ticker-runtime.json"


def test_relative_state_dir_is_resolved_from_repo_root(monkeypatch) -> None:
    clear_path_env(monkeypatch)
    monkeypatch.setenv("PREP_WATCHDECK_STATE_DIR", "custom-state")

    settings = Settings()

    assert settings.state_dir == REPO_ROOT / "custom-state"
    assert settings.out_dir == REPO_ROOT / "custom-state/snapshots"
    assert settings.cache_db_path == REPO_ROOT / "custom-state/watchdeck.duckdb"


def clear_path_env(monkeypatch) -> None:
    for name in PATH_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
