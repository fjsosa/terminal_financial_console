from __future__ import annotations

import unittest

from app.startup_mount import (
    configure_tables,
    initialize_mount_state,
    refresh_theme_panels,
    schedule_mount_intervals,
)


class FakeTable:
    def __init__(self) -> None:
        self.cursor_type = ""
        self.zebra_stripes = False
        self.show_horizontal_scrollbar = True
        self.columns: list[tuple[str, int | None]] = []
        self.rows: list[tuple[tuple[object, ...], str | None, int | None]] = []

    def add_column(self, label: str, width: int | None = None):
        self.columns.append((label, width))
        return f"col:{label}"

    def add_row(self, *values, key: str | None = None, height: int | None = None):
        self.rows.append((values, key, height))
        return f"row:{key}"


class FakeLog:
    def __init__(self) -> None:
        self.max_lines = 0


class FakeStatic:
    def __init__(self) -> None:
        self.last = ""

    def update(self, value) -> None:
        self.last = str(value)


class FakeInput:
    def __init__(self) -> None:
        self.value = "x"
        self.display = True


class FakeHost:
    def __init__(self) -> None:
        self.main_group_items = [("G1", [("BTCUSDT", "crypto"), ("AAPL", "stock")])]
        self.indicator_group_items = [("IDX", [("^GSPC", "stock")])]

        self.main_col_keys = {}
        self.main_row_keys: list[str] = []
        self.alerts_col_keys = {}
        self.alerts_row_keys: list[str] = []
        self.indicator_col_keys = {}
        self.indicator_row_keys: list[str] = []
        self.news_col_keys = {}
        self.news_row_keys: list[str] = []

        self.main_updates = 0
        self.alert_updates = 0
        self.indicator_updates = 0
        self.news_updates = 0
        self.status_renders = 0
        self.clock_updates = 0
        self.logs: list[str] = []
        self.name_resolve_task = None

        self.tables = {
            "#crypto_quotes": FakeTable(),
            "#stock_quotes": FakeTable(),
            "#indicators_table": FakeTable(),
            "#news_table": FakeTable(),
            "#events": FakeLog(),
            "#news_header": FakeStatic(),
            "#command_input": FakeInput(),
        }
        self.intervals: list[tuple[float | int, object]] = []

    def query_one(self, selector: str):
        return self.tables[selector]

    def _update_main_group_panel(self) -> None:
        self.main_updates += 1

    def _update_alerts_panel(self) -> None:
        self.alert_updates += 1

    def _update_indicators_panel(self) -> None:
        self.indicator_updates += 1

    def _update_news_panel(self) -> None:
        self.news_updates += 1

    def _render_status_line(self) -> None:
        self.status_renders += 1

    def _update_clock(self) -> None:
        self.clock_updates += 1

    def _log(self, message: str) -> None:
        self.logs.append(message)

    def _load_cached_descriptions(self) -> None:
        self.logs.append("load_desc")

    def _load_cached_symbol_names(self) -> None:
        self.logs.append("load_names")

    async def _resolve_names_background(self):
        return None

    def _ui_palette(self):
        return {"accent": "cyan"}

    def set_interval(self, seconds, callback):
        self.intervals.append((seconds, callback))

    def _rotate_ticker_mode(self):
        return None

    def _schedule_news_refresh(self):
        return None

    def _schedule_calendar_refresh(self):
        return None

    def _rotate_news_group(self):
        return None

    def _rotate_main_group(self):
        return None

    def _rotate_indicator_group(self):
        return None

    def _schedule_stock_refresh(self):
        return None

    def _schedule_indicator_refresh(self):
        return None

    def _animate_ticker(self):
        return None


class StartupMountTests(unittest.TestCase):
    def test_configure_tables(self) -> None:
        host = FakeHost()
        configure_tables(host, alerts_table_size=15, news_group_size=7, max_events=120, tr_fn=lambda s: s)

        self.assertEqual(len(host.main_row_keys), 2)
        self.assertEqual(len(host.alerts_row_keys), 15)
        self.assertEqual(len(host.indicator_row_keys), 1)
        self.assertEqual(len(host.news_row_keys), 7)
        self.assertEqual(host.tables["#events"].max_lines, 120)
        self.assertEqual(host.main_updates, 1)
        self.assertEqual(host.alert_updates, 1)
        self.assertEqual(host.indicator_updates, 1)

    def test_initialize_mount_state(self) -> None:
        host = FakeHost()
        created = []

        def create_task(coro):
            created.append(coro)
            coro.close()
            return "task"

        initialize_mount_state(host, tr_fn=lambda s: s, create_task_fn=create_task)
        self.assertEqual(host.name_resolve_task, "task")
        self.assertIn("Booting market stream...", " ".join(host.logs))
        self.assertIn("NAMES", " ".join(host.logs))
        self.assertEqual(host.tables["#command_input"].value, "")
        self.assertFalse(host.tables["#command_input"].display)
        self.assertIn("NEWS // finviz.com", host.tables["#news_header"].last)
        self.assertEqual(host.status_renders, 1)

    def test_schedule_mount_intervals(self) -> None:
        host = FakeHost()
        schedule_mount_intervals(
            host,
            ticker_mode_seconds=60,
            news_refresh_seconds=600,
            calendar_refresh_seconds=3600,
            news_group_rotate_seconds=10,
            stock_group_rotate_seconds=15,
            stocks_refresh_seconds=20,
        )
        self.assertEqual(len(host.intervals), 10)

    def test_refresh_theme_panels(self) -> None:
        host = FakeHost()
        refresh_theme_panels(host)
        self.assertEqual(host.news_updates, 1)
        self.assertEqual(host.main_updates, 1)
        self.assertEqual(host.indicator_updates, 1)
        self.assertEqual(host.alert_updates, 1)
        self.assertEqual(host.status_renders, 1)
        self.assertEqual(host.clock_updates, 1)


if __name__ == "__main__":
    unittest.main()
