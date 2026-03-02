from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import yaml

from .config_schema import AppConfig


def load_app_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        return AppConfig.from_dict({})
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return AppConfig.from_dict(payload)


def dump_app_config(config: AppConfig) -> str:
    return yaml.safe_dump(config.to_dict(), sort_keys=False, allow_unicode=True)


def save_app_config(path: str | Path, config: AppConfig) -> bool:
    file_path = Path(path)
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    payload = dump_app_config(config)
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(file_path)
        return True
    except Exception:
        with contextlib.suppress(Exception):
            if tmp_path.exists():
                tmp_path.unlink()
        return False
