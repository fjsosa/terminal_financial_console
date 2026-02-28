from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_CRYPTO_SYMBOLS, DEFAULT_STOCK_SYMBOLS


@dataclass(slots=True)
class AppSettings:
    crypto_symbols: list[str]
    stock_symbols: list[str]
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
    symbols_map = {
        "symbols": [],
        "crypto_symbols": [],
        "stock_symbols": [],
    }
    current_list_key = ""

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("timezone:"):
            value = line.split(":", 1)[1].strip().strip('"').strip("'")
            data["timezone"] = value
            current_list_key = ""
            continue

        if line.startswith("symbols:"):
            current_list_key = "symbols"
            data["symbols"] = symbols_map["symbols"]
            continue

        if line.startswith("crypto_symbols:"):
            current_list_key = "crypto_symbols"
            data["crypto_symbols"] = symbols_map["crypto_symbols"]
            continue

        if line.startswith("stock_symbols:"):
            current_list_key = "stock_symbols"
            data["stock_symbols"] = symbols_map["stock_symbols"]
            continue

        if current_list_key and line.startswith("-"):
            value = line[1:].strip().strip('"').strip("'")
            if value:
                symbols_map[current_list_key].append(value)
            continue

        if ":" in line and not line.startswith("-"):
            current_list_key = ""

    return data


def load_settings(
    *,
    config_path: str | None,
    cli_crypto_symbols: list[str] | None,
    cli_stock_symbols: list[str] | None,
    cli_timezone: str | None,
) -> AppSettings:
    path = Path(config_path or "config.yml")
    cfg = _load_yaml_config(path)

    # 1) base defaults
    crypto_symbols = list(DEFAULT_CRYPTO_SYMBOLS)
    stock_symbols = list(DEFAULT_STOCK_SYMBOLS)
    timezone = ""

    # 2) config.yml
    cfg_crypto_symbols = _parse_symbols(cfg.get("crypto_symbols") or cfg.get("symbols"))
    if cfg_crypto_symbols:
        crypto_symbols = cfg_crypto_symbols

    cfg_stock_symbols = _parse_symbols(cfg.get("stock_symbols"))
    if cfg_stock_symbols:
        stock_symbols = cfg_stock_symbols

    cfg_tz = str(cfg.get("timezone", "")).strip()
    if cfg_tz:
        timezone = cfg_tz

    # 3) environment overrides
    env_crypto_symbols = _parse_symbols(
        os.getenv("NEON_CRYPTO_SYMBOLS") or os.getenv("NEON_SYMBOLS")
    )
    if env_crypto_symbols:
        crypto_symbols = env_crypto_symbols

    env_stock_symbols = _parse_symbols(os.getenv("NEON_STOCK_SYMBOLS"))
    if env_stock_symbols:
        stock_symbols = env_stock_symbols

    env_tz = (os.getenv("NEON_TZ") or "").strip()
    if env_tz:
        timezone = env_tz

    # 4) CLI overrides (highest priority)
    if cli_crypto_symbols:
        crypto_symbols = _parse_symbols(cli_crypto_symbols)
    if cli_stock_symbols:
        stock_symbols = _parse_symbols(cli_stock_symbols)
    if cli_timezone and cli_timezone.strip():
        timezone = cli_timezone.strip()

    return AppSettings(
        crypto_symbols=crypto_symbols,
        stock_symbols=stock_symbols,
        timezone=timezone,
    )
