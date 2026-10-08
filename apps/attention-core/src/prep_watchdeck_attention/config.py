"""Dedicated state and fixed loopback endpoints."""

import os
from dataclasses import dataclass
from pathlib import Path


def no_symlink_path(path: Path) -> Path:
    path = Path(os.path.abspath(path.expanduser()))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlink path is not allowed")
    return path


def isolated_attention_state(state: Path, market_state: Path, ranking_state: Path) -> Path:
    state = no_symlink_path(state)
    if state == Path(state.anchor) or state == Path.home().resolve():
        raise ValueError("attention state must be a dedicated directory")
    repo_var = Path(__file__).resolve().parents[4] / "var"
    for other in (market_state, ranking_state, repo_var):
        other = other.expanduser().resolve()
        if state == other or state.is_relative_to(other) or other.is_relative_to(state):
            raise ValueError("attention state must not overlap Market, Ranking or repo var")
    return state


def validate_loopback_port(port: int, *, reserved: set[int]) -> int:
    if isinstance(port, bool) or not 1024 <= port <= 65535 or port in reserved:
        raise ValueError("use a dedicated unprivileged loopback port")
    return port


@dataclass(frozen=True, slots=True)
class AttentionSettings:
    state_dir: Path
    market_state_dir: Path
    ranking_state_dir: Path
    ranking_port: int = 8769
    port: int = 8770
    evidence_interval_minutes: int = 5

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state_dir",
            isolated_attention_state(self.state_dir, self.market_state_dir, self.ranking_state_dir),
        )
        validate_loopback_port(self.ranking_port, reserved={5432, 55432})
        validate_loopback_port(self.port, reserved={5432, 55432, 8769, self.ranking_port})
        if self.evidence_interval_minutes != 5:
            raise ValueError("attention-v1 evidence cadence is five minutes")

    @classmethod
    def from_env(cls) -> "AttentionSettings":
        root = Path.home() / ".local/share"
        return cls(
            Path(
                os.environ.get(
                    "PREP_WATCHDECK_ATTENTION_STATE_DIR", root / "prep-watchdeck-attention"
                )
            ),
            Path(os.environ.get("PREP_WATCHDECK_MARKET_STATE_DIR", root / "prep-watchdeck-market")),
            Path(
                os.environ.get("PREP_WATCHDECK_RANKING_STATE_DIR", root / "prep-watchdeck-ranking")
            ),
            ranking_port=int(os.environ.get("PREP_WATCHDECK_RANKING_PORT", "8769")),
            port=int(os.environ.get("PREP_WATCHDECK_ATTENTION_PORT", "8770")),
        )
