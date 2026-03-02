from __future__ import annotations

from pathlib import Path
from typing import Any

from .config_loader import dump_app_config, save_app_config
from .config_schema import AppConfig


class YamlConfigRepository:
    def serialize_runtime_config(
        self,
        *,
        config_name: str,
        timezone: str,
        language: str,
        quick_actions: dict[str, str],
        calendars: list[dict[str, Any]],
        indicator_groups: list[dict[str, Any]],
        market_groups: list[dict[str, Any]],
    ) -> str:
        config = AppConfig.from_runtime(
            config_name=config_name,
            timezone=timezone,
            language=language,
            quick_actions=quick_actions,
            calendars=calendars,
            indicator_groups=indicator_groups,
            market_groups=market_groups,
        )
        return dump_app_config(config)

    def persist_runtime_config(
        self,
        *,
        path: str | Path,
        config_name: str,
        timezone: str,
        language: str,
        quick_actions: dict[str, str],
        calendars: list[dict[str, Any]],
        indicator_groups: list[dict[str, Any]],
        market_groups: list[dict[str, Any]],
    ) -> bool:
        config = AppConfig.from_runtime(
            config_name=config_name,
            timezone=timezone,
            language=language,
            quick_actions=quick_actions,
            calendars=calendars,
            indicator_groups=indicator_groups,
            market_groups=market_groups,
        )
        return save_app_config(path, config)


def serialize_config_yaml(
    *,
    config_name: str,
    timezone: str,
    language: str,
    quick_actions: dict[str, str],
    calendars: list[dict[str, Any]],
    indicator_groups: list[dict[str, Any]],
    market_groups: list[dict[str, Any]],
) -> str:
    return YamlConfigRepository().serialize_runtime_config(
        config_name=config_name,
        timezone=timezone,
        language=language,
        quick_actions=quick_actions,
        calendars=calendars,
        indicator_groups=indicator_groups,
        market_groups=market_groups,
    )


def persist_yaml_config(path: str | Path, payload: str) -> bool:
    # Kept for compatibility with existing callers/tests.
    try:
        Path(path).write_text(payload, encoding="utf-8")
        return True
    except Exception:
        return False


def persist_runtime_config(
    *,
    path: str | Path,
    config_name: str,
    timezone: str,
    language: str,
    quick_actions: dict[str, str],
    calendars: list[dict[str, Any]],
    indicator_groups: list[dict[str, Any]],
    market_groups: list[dict[str, Any]],
) -> bool:
    return YamlConfigRepository().persist_runtime_config(
        path=path,
        config_name=config_name,
        timezone=timezone,
        language=language,
        quick_actions=quick_actions,
        calendars=calendars,
        indicator_groups=indicator_groups,
        market_groups=market_groups,
    )
