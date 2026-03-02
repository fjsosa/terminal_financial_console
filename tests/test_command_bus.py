from __future__ import annotations

import unittest

from app.commands import CommandBus, CommandContext


class Host:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.called = False

    def _log(self, message: str) -> None:
        self.logs.append(message)


class CommandBusTests(unittest.TestCase):
    def test_register_alias_and_dispatch(self) -> None:
        bus = CommandBus()
        host = Host()

        def handler(ctx: CommandContext) -> None:
            ctx.host.called = True

        bus.register("hello", handler, aliases=("hi",))
        bus.dispatch(CommandContext(host=host, raw="hi", tokens=["hi"]))
        self.assertTrue(host.called)

    def test_unknown_command_logs(self) -> None:
        bus = CommandBus()
        host = Host()
        bus.dispatch(CommandContext(host=host, raw="unknown", tokens=["unknown"]))
        self.assertTrue(any("Command unknown" in m for m in host.logs))


if __name__ == "__main__":
    unittest.main()
