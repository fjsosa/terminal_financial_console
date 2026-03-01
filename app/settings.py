from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DEFAULT_CRYPTO_SYMBOLS, DEFAULT_LANGUAGE, DEFAULT_STOCK_SYMBOLS


@dataclass(slots=True)
class AppSettings:
    crypto_symbols: list[str]
    stock_symbols: list[str]
    timezone: str
    language: str
    groups: list[dict[str, Any]]
    config_path: str
    symbols_from_config: bool


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
    try:
        import yaml  # type: ignore

        with path.open("r", encoding="utf-8") as fh:
            payload = yaml.safe_load(fh) or {}
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    # Fallback parser for minimal compatibility if PyYAML is unavailable.
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
        if stripped.startswith("timezone:"):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            data["timezone"] = value
            current_list_key = ""
            current_group = None
            current_symbol_item = None
            continue

        if stripped.startswith("language:"):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            data["language"] = value
            current_list_key = ""
            current_group = None
            current_symbol_item = None
            continue

        if stripped in {"symbols:", "crypto_symbols:", "stock_symbols:"}:
            current_list_key = stripped[:-1]
            data.setdefault(current_list_key, [])
            current_group = None
            current_symbol_item = None
            continue

        if stripped == "groups:":
            current_list_key = ""
            current_group = None
            current_symbol_item = None
            continue

        if current_list_key and stripped.startswith("-"):
            value = stripped[1:].strip().strip('"').strip("'")
            if value:
                data[current_list_key].append(value)
            continue

        if stripped.startswith("- name:"):
            name = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            current_group = {"name": name, "symbols": []}
            data["groups"].append(current_group)
            current_symbol_item = None
            continue

        if stripped == "symbols:" and current_group is not None:
            current_symbol_item = None
            continue

        if stripped.startswith("- symbol:") and current_group is not None:
            symbol = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            current_symbol_item = {"symbol": symbol}
            current_group["symbols"].append(current_symbol_item)
            continue

        if stripped.startswith("type:") and current_symbol_item is not None:
            symbol_type = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            current_symbol_item["type"] = symbol_type
            continue

        if stripped.startswith("name:") and current_symbol_item is not None:
            symbol_name = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            current_symbol_item["name"] = symbol_name
            continue

        if ":" in stripped and not stripped.startswith("-"):
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
            normalized: dict[str, str] = {"symbol": symbol, "type": symbol_type}
            if isinstance(item, dict):
                item_name = str(item.get("name") or "").strip()
                if item_name:
                    normalized["name"] = item_name
            normalized_items.append(normalized)
        if normalized_items:
            out.append({"name": name, "symbols": normalized_items})
    return out


def load_settings(
) -> AppSettings:
    path = Path("config.yml")
    cfg = _load_yaml_config(path)

    # 1) base defaults
    crypto_symbols = list(DEFAULT_CRYPTO_SYMBOLS)
    stock_symbols = list(DEFAULT_STOCK_SYMBOLS)
    timezone = ""
    language = DEFAULT_LANGUAGE
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
    cfg_lang = str(cfg.get("language", "")).strip().lower()
    if cfg_lang:
        language = cfg_lang

    # Configuration source is only config.yml (no env/CLI overrides).
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
        language=language,
        groups=groups,
        config_path=str(path),
        symbols_from_config=True,
    )
