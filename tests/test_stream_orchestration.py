from __future__ import annotations

import asyncio
import unittest

from app.stream_orchestration import consume_feed, refresh_crypto_stream_for_visible_group


class FakeQuoteProvider:
    def __init__(self, symbols=None) -> None:
        self.symbols = list(symbols or [])
        self.set_calls: list[list[str]] = []
        self.stream_raises = False

    def set_symbols(self, symbols: list[str]) -> None:
        self.symbols = list(symbols)
        self.set_calls.append(list(symbols))

    async def stream(self):
        if self.stream_raises:
            self.stream_raises = False
            raise RuntimeError("boom")
        yield {"symbol": "BTCUSDT", "price": 10}


class FakeHost:
    def __init__(self) -> None:
        self.main_visible_items = [("BTCUSDT", "crypto"), ("AAPL", "stock")]
        self.quote_provider = FakeQuoteProvider(["BTCUSDT"])
        self.feed_task: asyncio.Task[None] | None = None
        self.status_text = "INIT"
        self.applied: list[object] = []
        self.logs: list[str] = []

    def _apply_quote(self, quote) -> None:
        self.applied.append(quote)

    def _log(self, message: str) -> None:
        self.logs.append(message)


class StreamOrchestrationTests(unittest.TestCase):
    def test_refresh_stream_no_changes_keeps_existing_task(self) -> None:
        async def run() -> None:
            host = FakeHost()
            host.feed_task = asyncio.create_task(asyncio.sleep(0.01))
            prev = host.feed_task
            await refresh_crypto_stream_for_visible_group(host)
            self.assertIs(host.feed_task, prev)
            await host.feed_task

        asyncio.run(run())

    def test_refresh_stream_updates_symbols_and_starts_task(self) -> None:
        async def run() -> None:
            host = FakeHost()
            host.quote_provider.symbols = ["ETHUSDT"]
            created = []

            def create_task(coro):
                created.append(True)
                coro.close()
                return asyncio.create_task(asyncio.sleep(0))

            await refresh_crypto_stream_for_visible_group(host, create_task_fn=create_task)
            self.assertEqual(host.quote_provider.set_calls[-1], ["BTCUSDT"])
            self.assertIsNotNone(host.feed_task)
            self.assertEqual(len(created), 1)
            await host.feed_task

        asyncio.run(run())

    def test_refresh_stream_with_no_crypto_sets_stocks_only(self) -> None:
        async def run() -> None:
            host = FakeHost()
            host.main_visible_items = [("AAPL", "stock")]
            host.feed_task = asyncio.create_task(asyncio.sleep(10))
            await refresh_crypto_stream_for_visible_group(host)
            self.assertEqual(host.status_text, "STOCKS ONLY")
            self.assertIsNone(host.feed_task)

        asyncio.run(run())

    def test_consume_feed_applies_quotes(self) -> None:
        async def run() -> None:
            host = FakeHost()
            await consume_feed(host, max_cycles=1)
            self.assertEqual(host.status_text, "STREAMING")
            self.assertEqual(len(host.applied), 1)
            self.assertIn("Connected to Binance stream", " ".join(host.logs))

        asyncio.run(run())

    def test_consume_feed_handles_reconnect(self) -> None:
        async def run() -> None:
            host = FakeHost()
            host.quote_provider.stream_raises = True
            await consume_feed(host, reconnect_sleep_seconds=0, max_cycles=1)
            self.assertEqual(host.status_text, "STREAMING")
            self.assertIn("Stream warning", " ".join(host.logs))

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
