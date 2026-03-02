from __future__ import annotations

from typing import Any, Protocol

from textual.widgets import DataTable, Input

from .command_completion import autocomplete as autocomplete_command_core
from .i18n import tr


class CommandUiHost(Protocol):
    command_mode: bool
    command_buffer: str
    market_groups: list[dict[str, Any]]
    main_group_items: list[tuple[str, list[tuple[str, str]]]]
    _tab_cycle_key: tuple[Any, ...] | None
    _tab_cycle_index: int

    def query_one(self, selector: str, cls: type[Any]) -> Any: ...
    def _render_status_line(self) -> None: ...
    def _ui_palette(self) -> dict[str, str]: ...
    def _log(self, message: str) -> None: ...


def enter_command_mode(host: CommandUiHost) -> None:
    host.command_mode = True
    host.command_buffer = ""
    host._tab_cycle_key = None
    host._tab_cycle_index = -1
    host._log(f"[{host._ui_palette()['warn']}]COMMAND[/] {tr('COMMAND mode enabled')}")
    command_input = host.query_one("#command_input", Input)
    command_input.display = True
    command_input.value = ":"
    command_input.focus()
    host._render_status_line()


def exit_command_mode(host: CommandUiHost) -> None:
    host.command_mode = False
    host.command_buffer = ""
    host._tab_cycle_key = None
    host._tab_cycle_index = -1
    host._log(f"[{host._ui_palette()['warn']}]COMMAND[/] {tr('COMMAND mode disabled')}")
    command_input = host.query_one("#command_input", Input)
    command_input.value = ""
    command_input.display = False
    host.query_one("#crypto_quotes", DataTable).focus()
    host._render_status_line()


def autocomplete_command(host: CommandUiHost) -> None:
    if not host.command_mode:
        return
    command_input = host.query_one("#command_input", Input)
    result = autocomplete_command_core(
        raw_value=command_input.value or "",
        market_groups=host.market_groups,
        main_group_items=host.main_group_items,
        tab_cycle_key=host._tab_cycle_key,
        tab_cycle_index=host._tab_cycle_index,
    )
    host._tab_cycle_key = result.tab_cycle_key
    host._tab_cycle_index = result.tab_cycle_index

    if result.no_candidates:
        host._log("[#6f8aa8]COMMAND[/] no completion candidates")
        return
    if result.suggestions_preview:
        host._log(f"[#6f8aa8]COMMAND[/] suggestions: {result.suggestions_preview}")
    if result.value is None:
        return
    command_input.value = result.value
    host.command_buffer = command_input.value[1:]
    host._render_status_line()
