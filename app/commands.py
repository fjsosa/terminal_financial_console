from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Callable, Protocol

from .command_handlers import RuntimeConfigCommands, RuntimeConfigHost
from .i18n import tr


class CommandHost(RuntimeConfigHost, Protocol):
    def _log(self, message: str) -> None: ...

    def action_reset(self) -> None: ...
    def action_refresh_news(self) -> None: ...
    def action_open_calendar(self) -> None: ...
    def action_show_help_tip(self) -> None: ...
    def exit(self) -> None: ...


@dataclass(slots=True)
class CommandContext:
    host: CommandHost
    raw: str
    tokens: list[str]


CommandHandler = Callable[[CommandContext], None]


class CommandBus:
    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, name: str, handler: CommandHandler, aliases: tuple[str, ...] = ()) -> None:
        key = name.strip().lower()
        if not key:
            return
        self._handlers[key] = handler
        for alias in aliases:
            alias_key = alias.strip().lower()
            if alias_key:
                self._handlers[alias_key] = handler

    def dispatch(self, ctx: CommandContext) -> None:
        if not ctx.tokens:
            return
        cmd = ctx.tokens[0].strip().lower()
        handler = self._handlers.get(cmd)
        if handler is None:
            ctx.host._log(f"[yellow]Command unknown:[/] :{ctx.raw}")
            return
        handler(ctx)


def _handle_quit(ctx: CommandContext) -> None:
    ctx.host.exit()


def _handle_reset(ctx: CommandContext) -> None:
    ctx.host.action_reset()


def _handle_news_refresh(ctx: CommandContext) -> None:
    ctx.host.action_refresh_news()


def _handle_calendar(ctx: CommandContext) -> None:
    # Supports both `:c` and `:c calendar` and `:calendar`.
    cmd = ctx.tokens[0].strip().lower()
    if cmd == "calendar":
        ctx.host.action_open_calendar()
        return
    if len(ctx.tokens) == 1:
        ctx.host.action_open_calendar()
        return
    if len(ctx.tokens) >= 2 and ctx.tokens[1].strip().lower() == "calendar":
        ctx.host.action_open_calendar()
        return
    ctx.host._log(f"[yellow]{tr('Usage: :c calendar')}[/]")


def _handle_help(ctx: CommandContext) -> None:
    ctx.host.action_show_help_tip()


def _handle_add_symbol(ctx: CommandContext) -> None:
    RuntimeConfigCommands(ctx.host).add_symbol(ctx.tokens)


def _handle_del_symbol(ctx: CommandContext) -> None:
    RuntimeConfigCommands(ctx.host).delete_symbol(ctx.tokens)


def _handle_move_symbol(ctx: CommandContext) -> None:
    RuntimeConfigCommands(ctx.host).move_symbol(ctx.tokens)


def _handle_edit_symbol(ctx: CommandContext) -> None:
    RuntimeConfigCommands(ctx.host).edit_symbol(ctx.tokens)


def build_default_command_bus() -> CommandBus:
    bus = CommandBus()
    bus.register("q", _handle_quit)
    bus.register("r", _handle_reset)
    bus.register("n", _handle_news_refresh)
    bus.register("c", _handle_calendar, aliases=("calendar",))
    bus.register("?", _handle_help)
    bus.register("add", _handle_add_symbol)
    bus.register("del", _handle_del_symbol)
    bus.register("mv", _handle_move_symbol)
    bus.register("edit", _handle_edit_symbol)
    return bus


def cmd_add_symbol(app: CommandHost, tokens: list[str]) -> None:
    _handle_add_symbol(CommandContext(host=app, raw=" ".join(tokens), tokens=tokens))


def cmd_del_symbol(app: CommandHost, tokens: list[str]) -> None:
    _handle_del_symbol(CommandContext(host=app, raw=" ".join(tokens), tokens=tokens))


def cmd_move_symbol(app: CommandHost, tokens: list[str]) -> None:
    _handle_move_symbol(CommandContext(host=app, raw=" ".join(tokens), tokens=tokens))


def cmd_edit_symbol(app: CommandHost, tokens: list[str]) -> None:
    _handle_edit_symbol(CommandContext(host=app, raw=" ".join(tokens), tokens=tokens))


def execute_command(app: CommandHost, command: str) -> None:
    raw = command.strip()
    if not raw:
        return
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        app._log(f"[yellow]Command parse error:[/] {exc}")
        return
    ctx = CommandContext(host=app, raw=raw, tokens=tokens)
    DEFAULT_COMMAND_BUS.dispatch(ctx)


DEFAULT_COMMAND_BUS = build_default_command_bus()
