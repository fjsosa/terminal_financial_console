from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_SYMBOLS


@dataclass(slots=True)
class AppSettings:
    symbols: list[str]
    timezone: str


def _parse_symbols(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        tokens = [str(token).strip() for token in raw]
    else:
        normalized = raw.replace(",", " ")
        tokens = [token.strip() for token in normalized.split()]
    return [token.upper() for token in tokens if token]


def _load_yaml_config(path: Path) -> dict:
    if not path.exists():
        return {}
    data: dict = {}
    symbols: list[str] = []
    in_symbols = False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("timezone:"):
            value = line.split(":", 1)[1].strip().strip('"').strip("'")
            data["timezone"] = value
            in_symbols = False
            continue

        if line.startswith("symbols:"):
            in_symbols = True
            data["symbols"] = symbols
            continue

        if in_symbols and line.startswith("-"):
            value = line[1:].strip().strip('"').strip("'")
            if value:
                symbols.append(value)
            continue

        # Stop symbol list when another key appears.
        if ":" in line and not line.startswith("-"):
            in_symbols = False

    return data


def load_settings(
    *,
    config_path: str | None,
    cli_symbols: list[str] | None,
    cli_timezone: str | None,
) -> AppSettings:
    path = Path(config_path or "config.yml")
    cfg = _load_yaml_config(path)

    # 1) base defaults
    symbols = list(DEFAULT_SYMBOLS)
    timezone = ""

    # 2) config.yml
    cfg_symbols = _parse_symbols(cfg.get("symbols"))
    if cfg_symbols:
        symbols = cfg_symbols
    cfg_tz = str(cfg.get("timezone", "")).strip()
    if cfg_tz:
        timezone = cfg_tz

    # 3) environment overrides
    env_symbols = _parse_symbols(os.getenv("NEON_SYMBOLS"))
    if env_symbols:
        symbols = env_symbols
    env_tz = (os.getenv("NEON_TZ") or "").strip()
    if env_tz:
        timezone = env_tz

    # 4) CLI overrides (highest priority)
    if cli_symbols:
        symbols = _parse_symbols(cli_symbols)
    if cli_timezone and cli_timezone.strip():
        timezone = cli_timezone.strip()

    return AppSettings(symbols=symbols, timezone=timezone)
