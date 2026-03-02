from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config_loader import load_app_config


@dataclass(slots=True)
class AppSettings:
    crypto_symbols: list[str]
    stock_symbols: list[str]
    timezone: str
    language: str
    config_name: str
    calendars: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    indicator_groups: list[dict[str, Any]]
    quick_actions: dict[str, str]
    config_path: str
    symbols_from_config: bool


def _extract_symbols_from_groups(groups: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    crypto_symbols: list[str] = []
    stock_symbols: list[str] = []
    seen_crypto: set[str] = set()
    seen_stock: set[str] = set()

    for group in groups:
        items = group.get("symbols")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            symbol_type = str(item.get("type") or "").strip().lower()
            if not symbol:
                continue
            if symbol_type == "crypto":
                if symbol not in seen_crypto:
                    seen_crypto.add(symbol)
                    crypto_symbols.append(symbol)
                continue
            if symbol_type == "stock":
                if symbol not in seen_stock:
                    seen_stock.add(symbol)
                    stock_symbols.append(symbol)
                continue
            # Defensive fallback for malformed configs.
            if symbol.endswith("USDT"):
                if symbol not in seen_crypto:
                    seen_crypto.add(symbol)
                    crypto_symbols.append(symbol)
            else:
                if symbol not in seen_stock:
                    seen_stock.add(symbol)
                    stock_symbols.append(symbol)

    return crypto_symbols, stock_symbols


def load_settings() -> AppSettings:
    path = Path("config.yml")
    app_config = load_app_config(path)

    groups = [group.to_dict() for group in app_config.groups]
    indicator_groups = [group.to_dict() for group in app_config.indicator_groups]
    calendars = [calendar.to_dict() for calendar in app_config.calendars]

    crypto_symbols, stock_symbols = _extract_symbols_from_groups(groups)

    return AppSettings(
        crypto_symbols=crypto_symbols,
        stock_symbols=stock_symbols,
        timezone=app_config.timezone,
        language=app_config.language,
        config_name=app_config.config_name,
        calendars=calendars,
        groups=groups,
        indicator_groups=indicator_groups,
        quick_actions=dict(app_config.quick_actions),
        config_path=str(path),
        symbols_from_config=True,
    )
