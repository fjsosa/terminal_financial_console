from __future__ import annotations

from typing import Any, Protocol

from .constants import SYMBOL_TYPES
from .i18n import tr


class RuntimeConfigHost(Protocol):
    market_groups: list[dict[str, Any]]
    symbol_names: dict[tuple[str, str], str]
    quick_actions: dict[str, str]

    def _normalize_symbol_type(self, symbol: str, symbol_type: str) -> str: ...
    def _find_group_index(self, group_name: str) -> int | None: ...
    def _find_symbol_entry(self, symbol: str) -> tuple[int, int, dict[str, Any]] | None: ...
    def _apply_market_groups_change(self, resolve_missing_names: bool = False) -> None: ...
    def _persist_config(self) -> bool: ...
    def _clear_quick_actions_for_symbol(self, symbol: str) -> None: ...
    def _log(self, message: str) -> None: ...


class RuntimeConfigCommands:
    def __init__(self, host: RuntimeConfigHost) -> None:
        self.host = host

    def add_symbol(self, tokens: list[str]) -> None:
        app = self.host
        if len(tokens) < 4:
            app._log(f"[yellow]{tr('Usage:')}[/] :add <symbol> <crypto|stock> <group> [name]")
            return
        symbol = tokens[1].strip().upper()
        symbol_type = app._normalize_symbol_type(symbol, tokens[2])
        group_name = tokens[3].strip()
        name = " ".join(tokens[4:]).strip()
        if symbol_type not in SYMBOL_TYPES:
            app._log(f"[yellow]{tr('Add failed:')}[/] {tr('type must be crypto or stock')}")
            return
        if not symbol or not group_name:
            app._log(f"[yellow]{tr('Add failed:')}[/] {tr('symbol and group are required')}")
            return
        if app._find_symbol_entry(symbol):
            app._log(f"[yellow]{tr('Add failed:')}[/] {tr('symbol already exists')}: {symbol}")
            return
        group_idx = app._find_group_index(group_name)
        if group_idx is None:
            app._log(f"[yellow]{tr('Add failed:')}[/] {tr('group not found')}: {group_name}")
            return
        item: dict[str, str] = {"symbol": symbol, "type": symbol_type}
        if name:
            item["name"] = name
            app.symbol_names[(symbol, symbol_type)] = name
        symbols = app.market_groups[group_idx].setdefault("symbols", [])
        if not isinstance(symbols, list):
            app._log(f"[yellow]{tr('Add failed:')}[/] {tr('invalid group schema')}: {group_name}")
            return
        symbols.append(item)
        app._apply_market_groups_change(resolve_missing_names=not bool(name))
        if not app._persist_config():
            app._log(f"[yellow]{tr('Add warning:')}[/] {tr('could not persist config.yml')}")
            return
        app._log(
            f"[#2ec4b6]CONFIG[/] {tr('added')} {symbol} ({symbol_type}) {tr('to group')} '{group_name}'"
        )

    def delete_symbol(self, tokens: list[str]) -> None:
        app = self.host
        if len(tokens) != 2:
            app._log(f"[yellow]{tr('Usage:')}[/] :del <symbol>")
            return
        symbol = tokens[1].strip().upper()
        found = app._find_symbol_entry(symbol)
        if not found:
            app._log(f"[yellow]{tr('Delete failed:')}[/] {tr('symbol not found')}: {symbol}")
            return
        group_idx, item_idx, item = found
        group_name = str(app.market_groups[group_idx].get("name") or "")
        symbols = app.market_groups[group_idx].get("symbols")
        if not isinstance(symbols, list):
            app._log(f"[yellow]{tr('Delete failed:')}[/] {tr('invalid group schema')}")
            return
        item_type = app._normalize_symbol_type(symbol, str(item.get("type") or ""))
        symbols.pop(item_idx)
        if not symbols:
            app.market_groups.pop(group_idx)
            app._log(f"[#6f8aa8]CONFIG[/] {tr('removed empty group')} '{group_name}'")
        app.symbol_names.pop((symbol, item_type), None)
        app._clear_quick_actions_for_symbol(symbol)
        app._apply_market_groups_change(resolve_missing_names=False)
        if not app._persist_config():
            app._log(f"[yellow]{tr('Delete warning:')}[/] {tr('could not persist config.yml')}")
            return
        app._log(f"[#2ec4b6]CONFIG[/] {tr('deleted')} {symbol} {tr('from group')} '{group_name}'")

    def move_symbol(self, tokens: list[str]) -> None:
        app = self.host
        if len(tokens) < 3:
            app._log(f"[yellow]{tr('Usage:')}[/] :mv <symbol> <group>")
            return
        symbol = tokens[1].strip().upper()
        destination_name = " ".join(tokens[2:]).strip()
        found = app._find_symbol_entry(symbol)
        if not found:
            app._log(f"[yellow]{tr('Move failed:')}[/] {tr('symbol not found')}: {symbol}")
            return
        from_group_idx, item_idx, item = found
        to_group_idx = app._find_group_index(destination_name)
        if to_group_idx is None:
            app._log(
                f"[yellow]{tr('Move failed:')}[/] {tr('destination group not found')}: {destination_name}"
            )
            return
        if to_group_idx == from_group_idx:
            app._log(f"[#6f8aa8]CONFIG[/] {symbol} {tr('already in group')} '{destination_name}'")
            return

        source_name = str(app.market_groups[from_group_idx].get("name") or "")
        symbols_src = app.market_groups[from_group_idx].get("symbols")
        symbols_dst = app.market_groups[to_group_idx].setdefault("symbols", [])
        if not isinstance(symbols_src, list) or not isinstance(symbols_dst, list):
            app._log(f"[yellow]{tr('Move failed:')}[/] {tr('invalid group schema')}")
            return
        moved = dict(item)
        symbols_src.pop(item_idx)
        symbols_dst.append(moved)
        if not symbols_src:
            app.market_groups.pop(from_group_idx)
            app._log(f"[#6f8aa8]CONFIG[/] {tr('removed empty group')} '{source_name}'")
        app._apply_market_groups_change(resolve_missing_names=False)
        if not app._persist_config():
            app._log(f"[yellow]{tr('Move warning:')}[/] {tr('could not persist config.yml')}")
            return
        app._log(
            f"[#2ec4b6]CONFIG[/] {tr('moved')} {symbol} {tr('from group')} '{source_name}' "
            f"{tr('to group')} '{destination_name}'"
        )

    def edit_symbol(self, tokens: list[str]) -> None:
        app = self.host
        if len(tokens) < 3:
            app._log(
                f"[yellow]{tr('Usage:')}[/] :edit <symbol> group=<name> type=<crypto|stock> "
                "name=<label>"
            )
            return
        symbol = tokens[1].strip().upper()
        found = app._find_symbol_entry(symbol)
        if not found:
            app._log(f"[yellow]{tr('Edit failed:')}[/] {tr('symbol not found')}: {symbol}")
            return
        group_idx, item_idx, item = found
        updates: dict[str, str] = {}
        for part in tokens[2:]:
            if "=" not in part:
                app._log(
                    f"[yellow]{tr('Edit failed:')}[/] "
                    f"{tr('invalid token')}: '{part}', {tr('expected key=value')}"
                )
                return
            key, value = part.split("=", 1)
            k = key.strip().lower()
            v = value.strip()
            if k not in {"group", "type", "name"}:
                app._log(f"[yellow]{tr('Edit failed:')}[/] {tr('unsupported field')} '{k}'")
                return
            updates[k] = v
        destination_group = updates.get("group")
        if destination_group:
            dest_idx = app._find_group_index(destination_group)
            if dest_idx is None:
                app._log(f"[yellow]{tr('Edit failed:')}[/] {tr('group not found')}: {destination_group}")
                return
        new_type = updates.get("type")
        if new_type and app._normalize_symbol_type(symbol, new_type) not in SYMBOL_TYPES:
            app._log(f"[yellow]{tr('Edit failed:')}[/] {tr('type must be crypto or stock')}")
            return

        resolve_names = False
        if "type" in updates:
            normalized = app._normalize_symbol_type(symbol, updates["type"])
            item["type"] = normalized
        if "name" in updates:
            name_value = updates["name"].strip()
            if name_value:
                item["name"] = name_value
                symbol_type = app._normalize_symbol_type(symbol, str(item.get("type") or ""))
                app.symbol_names[(symbol, symbol_type)] = name_value
            else:
                item.pop("name", None)
                resolve_names = True

        if destination_group:
            dest_idx = app._find_group_index(destination_group)
            assert dest_idx is not None
            if dest_idx != group_idx:
                src_symbols = app.market_groups[group_idx].get("symbols")
                dst_symbols = app.market_groups[dest_idx].setdefault("symbols", [])
                if not isinstance(src_symbols, list) or not isinstance(dst_symbols, list):
                    app._log(f"[yellow]{tr('Edit failed:')}[/] {tr('invalid group schema')}")
                    return
                moved = dict(item)
                src_symbols.pop(item_idx)
                dst_symbols.append(moved)
                if not src_symbols:
                    app.market_groups.pop(group_idx)

        app._apply_market_groups_change(resolve_missing_names=resolve_names)
        if not app._persist_config():
            app._log(f"[yellow]{tr('Edit warning:')}[/] {tr('could not persist config.yml')}")
            return
        app._log(f"[#2ec4b6]CONFIG[/] {tr('updated')} {symbol}")
