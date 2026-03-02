from __future__ import annotations

from typing import Any, Protocol

from textual import events
from textual.widgets import DataTable, Input

from .screens import CalendarModal, ChartModal, ReadmeModal


class BindingsHost(Protocol):
    screen: Any
    command_mode: bool
    quick_actions: dict[str, str]

    def query_one(self, selector: str, cls: type[Any]) -> Any: ...
    def _pause_group_rotation(self, table_id: str, seconds: int = 60) -> None: ...
    def _cycle_main_group(self, step: int) -> None: ...
    def _cycle_news_group(self, step: int) -> None: ...
    def _cycle_indicator_group(self, step: int) -> None: ...
    def _exit_command_mode(self) -> None: ...
    def _execute_command(self, command: str) -> None: ...
    def _enter_command_mode(self) -> None: ...
    def action_focus_symbol(self, symbol: str) -> None: ...
    def action_show_help_tip(self) -> None: ...
    def exit(self) -> None: ...


NAV_KEYS = {"up", "down", "pageup", "pagedown", "home", "end", "j", "k"}
LEFT_KEYS = {"left", "comma"}
RIGHT_KEYS = {"right", "full_stop", "period"}


def handle_modal_shortcuts(host: BindingsHost, event: events.Key) -> bool:
    if not isinstance(host.screen, (ChartModal, ReadmeModal, CalendarModal)):
        return False

    if isinstance(host.screen, CalendarModal):
        if event.key in {"escape", "q"}:
            host.screen.dismiss(None)
            event.stop()
            return True
    else:
        if event.key in {"escape", "enter", "q"}:
            host.screen.dismiss(None)
            event.stop()
            return True
    # While modal is open, global shortcuts must not affect the app.
    return True


def handle_table_navigation(host: BindingsHost, event: events.Key) -> bool:
    main_table = host.query_one("#crypto_quotes", DataTable)
    indicators_table = host.query_one("#indicators_table", DataTable)
    news_table = host.query_one("#news_table", DataTable)

    if main_table.has_focus:
        if event.key in NAV_KEYS:
            host._pause_group_rotation("crypto_quotes", 60)
        if event.key in LEFT_KEYS or event.character in {"<", ","}:
            host._cycle_main_group(-1)
            event.stop()
            return True
        if event.key in RIGHT_KEYS or event.character in {">", "."}:
            host._cycle_main_group(1)
            event.stop()
            return True

    if news_table.has_focus:
        if event.key in NAV_KEYS:
            host._pause_group_rotation("news_table", 60)
        if event.key in LEFT_KEYS or event.character in {"<", ","}:
            host._cycle_news_group(-1)
            event.stop()
            return True
        if event.key in RIGHT_KEYS or event.character in {">", "."}:
            host._cycle_news_group(1)
            event.stop()
            return True

    if indicators_table.has_focus:
        if event.key in NAV_KEYS:
            host._pause_group_rotation("indicators_table", 60)
        if event.key in LEFT_KEYS or event.character in {"<", ","}:
            host._cycle_indicator_group(-1)
            event.stop()
            return True
        if event.key in RIGHT_KEYS or event.character in {">", "."}:
            host._cycle_indicator_group(1)
            event.stop()
            return True

    return False


def handle_command_mode_keys(host: BindingsHost, event: events.Key) -> bool:
    if not host.command_mode:
        return False

    if event.key == "escape":
        host._exit_command_mode()
        event.stop()
        return True

    if event.key == "enter":
        command_input = host.query_one("#command_input", Input)
        raw = (command_input.value or "").strip()
        if raw.startswith(":"):
            raw = raw[1:].strip()
        if raw:
            host._execute_command(raw)
        command_input.value = ""
        # Preserve current behavior managed in ui state vars.
        if hasattr(host, "_tab_cycle_key"):
            host._tab_cycle_key = None
        if hasattr(host, "_tab_cycle_index"):
            host._tab_cycle_index = -1
        host._exit_command_mode()
        event.stop()
        return True

    # Let Input widget handle typing/submission in command mode.
    return True


def handle_global_shortcuts(host: BindingsHost, event: events.Key) -> bool:
    if event.character == ":" or event.key in {":", "colon"}:
        host._enter_command_mode()
        event.stop()
        return True

    if event.key == "q":
        host.exit()
        return True

    if event.key in {"1", "2", "3"}:
        target = host.quick_actions.get(event.key)
        if target:
            host.action_focus_symbol(target)
        return True

    if event.character == "?":
        host.action_show_help_tip()
        return True

    return False
