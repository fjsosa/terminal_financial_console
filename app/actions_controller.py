from __future__ import annotations

from typing import Any, Protocol

from .i18n import tr


class ActionsHost(Protocol):
    command_mode: bool
    screen: Any
    crypto_symbols: list[str]
    stock_symbols: list[str]
    indicator_symbols: list[str]
    symbol_data: dict[str, Any]
    stock_data: dict[str, Any]
    indicator_data: dict[str, Any]
    crypto_candles_by_tf: dict[str, dict[str, Any]]
    stock_candles_by_tf: dict[str, dict[str, Any]]
    stock_candles: dict[str, Any]

    def _refresh_main_row(self, symbol: str, symbol_type: str) -> None: ...
    def _update_main_group_panel(self) -> None: ...
    def _update_indicators_panel(self) -> None: ...
    def _update_alerts_panel(self) -> None: ...
    def _schedule_news_refresh(self) -> None: ...
    def _log(self, message: str) -> None: ...
    def _ui_palette(self) -> dict[str, str]: ...
    def _build_calendar_text(self) -> Any: ...
    def call_after_refresh(self, callback: Any) -> None: ...
    def push_screen(self, screen: Any) -> None: ...
    def _enter_command_mode(self) -> None: ...
    def _exit_command_mode(self) -> None: ...
    def exit(self) -> None: ...


def open_calendar_modal(host: ActionsHost, calendar_modal_cls: type[Any]) -> None:
    host._log(
        f"[{host._ui_palette()['accent']}]CALENDAR[/] "
        f"{tr('opening calendar modal')}"
    )
    host.call_after_refresh(lambda: host.push_screen(calendar_modal_cls(host._build_calendar_text)))


def refresh_news_action(host: ActionsHost) -> None:
    host._log("[#2ec4b6]NEWS[/] manual refresh requested")
    host._schedule_news_refresh()


def quick_quit(host: ActionsHost, *, modal_types: tuple[type[Any], ...]) -> None:
    if isinstance(host.screen, modal_types):
        host.screen.dismiss(None)
        return
    if not host.command_mode:
        host.exit()


def enter_command_mode_action(host: ActionsHost) -> None:
    if not host.command_mode:
        host._enter_command_mode()


def exit_command_mode_action(host: ActionsHost, *, chart_modal_type: type[Any]) -> None:
    if isinstance(host.screen, chart_modal_type):
        host.screen.dismiss(None)
        return
    if host.command_mode:
        host._exit_command_mode()


def reset_local_buffers(
    host: ActionsHost,
    *,
    symbol_state_factory: type[Any],
    stock_state_factory: type[Any],
) -> None:
    for symbol in host.crypto_symbols:
        host.symbol_data[symbol] = symbol_state_factory(symbol=symbol)
        host._refresh_main_row(symbol, "crypto")
        for tf in host.crypto_candles_by_tf:
            host.crypto_candles_by_tf[tf][symbol].clear()
    for symbol in host.stock_symbols:
        host.stock_data[symbol] = stock_state_factory(symbol=symbol)
        host.stock_candles[symbol].clear()
        for tf in host.stock_candles_by_tf:
            host.stock_candles_by_tf[tf][symbol].clear()
        host._refresh_main_row(symbol, "stock")
    for symbol in host.indicator_symbols:
        host.indicator_data[symbol] = stock_state_factory(symbol=symbol)
    host._update_main_group_panel()
    host._update_indicators_panel()
    host._update_alerts_panel()
    host._log("[cyan]Local buffers reset[/]")
