from __future__ import annotations

import unittest

from app.config_schema import AppConfig, CalendarConfig, GroupConfig, SymbolConfig


class ConfigSchemaTests(unittest.TestCase):
    def test_symbol_config_from_raw_dict_and_string(self) -> None:
        stock = SymbolConfig.from_raw({"symbol": "aapl", "type": "stock", "name": "Apple"})
        self.assertIsNotNone(stock)
        assert stock is not None
        self.assertEqual(stock.symbol, "AAPL")
        self.assertEqual(stock.type, "stock")
        self.assertEqual(stock.name, "Apple")

        crypto = SymbolConfig.from_raw("btcusdt")
        self.assertIsNotNone(crypto)
        assert crypto is not None
        self.assertEqual(crypto.symbol, "BTCUSDT")
        self.assertEqual(crypto.type, "crypto")

    def test_group_and_calendar_from_raw(self) -> None:
        group = GroupConfig.from_raw(
            {
                "name": "Tech",
                "symbols": [{"symbol": "AAPL", "type": "stock"}, {"symbol": "MSFT", "type": "stock"}],
            },
            fallback_name="Group 1",
        )
        self.assertIsNotNone(group)
        assert group is not None
        self.assertEqual(group.name, "Tech")
        self.assertEqual(len(group.symbols), 2)

        cal = CalendarConfig.from_raw(
            {"name": "USA", "source": "forexfactory", "region": "USA", "enabled": True, "default_duration_min": 90},
            fallback_name="Calendar 1",
        )
        self.assertIsNotNone(cal)
        assert cal is not None
        self.assertEqual(cal.default_duration_min, 90)

    def test_app_config_legacy_and_to_dict_roundtrip(self) -> None:
        cfg = AppConfig.from_dict(
            {
                "namespace": "Legacy",
                "language": "es",
                "crypto_symbols": ["BTCUSDT"],
                "stock_symbols": ["AAPL"],
                "quick_actions": {"1": "AAPL"},
            }
        )
        self.assertEqual(cfg.config_name, "Legacy")
        self.assertTrue(len(cfg.groups) >= 2)

        payload = cfg.to_dict()
        self.assertIn("groups", payload)
        self.assertIn("quick_actions", payload)
        self.assertEqual(payload["quick_actions"]["1"], "AAPL")

    def test_app_config_from_runtime(self) -> None:
        cfg = AppConfig.from_runtime(
            config_name="Runtime",
            timezone="America/Argentina/Buenos_Aires",
            language="es",
            quick_actions={"1": "AAPL", "2": "BTCUSDT", "3": ""},
            calendars=[{"name": "USA", "source": "forexfactory", "region": "USA", "enabled": True, "default_duration_min": 60}],
            indicator_groups=[{"name": "IDX", "symbols": [{"symbol": "^GSPC", "type": "stock"}]}],
            market_groups=[{"name": "Main", "symbols": [{"symbol": "AAPL", "type": "stock"}]}],
        )
        self.assertEqual(cfg.config_name, "Runtime")
        self.assertEqual(cfg.timezone, "America/Argentina/Buenos_Aires")
        self.assertEqual(cfg.groups[0].name, "Main")


if __name__ == "__main__":
    unittest.main()
