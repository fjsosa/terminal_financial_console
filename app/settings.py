from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DEFAULT_CRYPTO_SYMBOLS, DEFAULT_STOCK_SYMBOLS


@dataclass(slots=True)
class AppSettings:
    crypto_symbols: list[str]
    stock_symbols: list[str]
    timezone: str
    groups: list[dict[str, Any]]


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
    data["groups"] = []
    current_list_key = ""
    current_group: dict | None = None
    current_symbol_item: dict | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))

        if indent == 0 and stripped.startswith("timezone:"):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            data["timezone"] = value
            current_list_key = ""
            current_group = None
            current_symbol_item = None
            continue

        if indent == 0 and stripped in {"symbols:", "crypto_symbols:", "stock_symbols:"}:
            current_list_key = stripped[:-1]
            data.setdefault(current_list_key, [])
            current_group = None
            current_symbol_item = None
            continue

        if indent == 0 and stripped == "groups:":
            current_list_key = ""
            current_group = None
            current_symbol_item = None
            continue

        if current_list_key and indent >= 2 and stripped.startswith("-"):
            value = stripped[1:].strip().strip('"').strip("'")
            if value:
                data[current_list_key].append(value)
            continue

        if indent == 2 and stripped.startswith("- name:"):
            name = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            current_group = {"name": name, "symbols": []}
            data["groups"].append(current_group)
            current_symbol_item = None
            continue

        if indent == 4 and stripped == "symbols:":
            current_symbol_item = None
            continue

        if indent == 6 and stripped.startswith("- symbol:") and current_group is not None:
            symbol = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            current_symbol_item = {"symbol": symbol}
            current_group["symbols"].append(current_symbol_item)
            continue

        if indent == 8 and stripped.startswith("type:") and current_symbol_item is not None:
            symbol_type = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            current_symbol_item["type"] = symbol_type
            continue

        if indent == 0 and ":" in stripped and not stripped.startswith("-"):
            current_list_key = ""

    if not data["groups"]:
        data.pop("groups", None)
    return data


def _extract_symbols_from_groups(groups: object) -> tuple[list[str], list[str]]:
    if not isinstance(groups, list):
        return [], []

    crypto_symbols: list[str] = []
    stock_symbols: list[str] = []
    seen_crypto: set[str] = set()
    seen_stock: set[str] = set()

    for group in groups:
        if not isinstance(group, dict):
            continue
        items = group.get("symbols")
        if not isinstance(items, list):
            continue

        for item in items:
            symbol = ""
            symbol_type = ""

            if isinstance(item, dict):
                symbol = str(
                    item.get("symbol")
                    or item.get("ticker")
                    or item.get("id")
                    or item.get("name")
                    or ""
                ).strip()
                symbol_type = str(item.get("type") or "").strip().lower()
            elif isinstance(item, str):
                symbol = item.strip()
                symbol_type = "crypto" if symbol.upper().endswith("USDT") else "stock"

            symbol = symbol.upper()
            if not symbol:
                continue
            if symbol_type not in {"crypto", "stock"}:
                symbol_type = "crypto" if symbol.endswith("USDT") else "stock"

            if symbol_type == "crypto":
                if symbol not in seen_crypto:
                    seen_crypto.add(symbol)
                    crypto_symbols.append(symbol)
                continue
            if symbol not in seen_stock:
                seen_stock.add(symbol)
                stock_symbols.append(symbol)

    return crypto_symbols, stock_symbols


def _normalize_groups(groups: object) -> list[dict[str, Any]]:
    if not isinstance(groups, list):
        return []
    out: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            continue
        name = str(group.get("name") or f"Group {index}").strip() or f"Group {index}"
        items = group.get("symbols")
        if not isinstance(items, list):
            continue
        normalized_items: list[dict[str, str]] = []
        for item in items:
            symbol = ""
            symbol_type = ""
            if isinstance(item, dict):
                symbol = str(
                    item.get("symbol")
                    or item.get("ticker")
                    or item.get("id")
                    or item.get("name")
                    or ""
                ).strip()
                symbol_type = str(item.get("type") or "").strip().lower()
            elif isinstance(item, str):
                symbol = item.strip()
                symbol_type = "crypto" if symbol.upper().endswith("USDT") else "stock"
            symbol = symbol.upper()
            if not symbol:
                continue
            if symbol_type not in {"crypto", "stock"}:
                symbol_type = "crypto" if symbol.endswith("USDT") else "stock"
            normalized_items.append({"symbol": symbol, "type": symbol_type})
        if normalized_items:
            out.append({"name": name, "symbols": normalized_items})
    return out


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
    groups: list[dict[str, Any]] = []

    # 2) config.yml
    groups = _normalize_groups(cfg.get("groups"))
    has_groups = len(groups) > 0
    if has_groups:
        crypto_symbols = []
        stock_symbols = []

    group_crypto_symbols, group_stock_symbols = _extract_symbols_from_groups(groups)
    if group_crypto_symbols:
        crypto_symbols = group_crypto_symbols
    if group_stock_symbols:
        stock_symbols = group_stock_symbols

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

    if cli_crypto_symbols or cli_stock_symbols or env_crypto_symbols or env_stock_symbols:
        groups = []
    if not groups:
        if crypto_symbols:
            groups.append(
                {
                    "name": "CRYPTO",
                    "symbols": [{"symbol": symbol, "type": "crypto"} for symbol in crypto_symbols],
                }
            )
        if stock_symbols:
            groups.append(
                {
                    "name": "STOCKS",
                    "symbols": [{"symbol": symbol, "type": "stock"} for symbol in stock_symbols],
                }
            )

    return AppSettings(
        crypto_symbols=crypto_symbols,
        stock_symbols=stock_symbols,
        timezone=timezone,
        groups=groups,
    )
