from __future__ import annotations

from pathlib import Path

from prep_watchdeck.config.filter_config import FilterConfig, load_filter_config
from prep_watchdeck.constants import TEMPLATES
from prep_watchdeck.errors import ConfigError


def template_path(config_dir: Path, template: str) -> Path:
    if template not in TEMPLATES:
        raise ConfigError(f"unknown template: {template}")
    return config_dir / f"{template}.toml"


def load_template(config_dir: Path, template: str) -> FilterConfig:
    path = template_path(config_dir, template)
    if not path.exists():
        raise ConfigError(f"template file not found: {path}")
    config = load_filter_config(path)
    if config.name != template:
        raise ConfigError(f"template file name mismatch: expected={template} actual={config.name}")
    return config
