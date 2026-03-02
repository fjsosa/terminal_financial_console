from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config_loader import dump_app_config, load_app_config, save_app_config
from app.config_schema import AppConfig


class ConfigLoaderTests(unittest.TestCase):
    def test_load_app_config_supports_namespace_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_text(
                "namespace: Legacy Name\n"
                "timezone: America/Argentina/Buenos_Aires\n"
                "language: es\n"
                "groups:\n"
                "  - name: Test\n"
                "    symbols:\n"
                "      - symbol: AAPL\n"
                "        type: stock\n",
                encoding="utf-8",
            )
            cfg = load_app_config(path)
            self.assertEqual(cfg.config_name, "Legacy Name")
            self.assertEqual(cfg.language, "es")
            self.assertEqual(len(cfg.groups), 1)

    def test_load_app_config_builds_legacy_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_text(
                "crypto_symbols:\n"
                "  - BTCUSDT\n"
                "stock_symbols:\n"
                "  - AAPL\n",
                encoding="utf-8",
            )
            cfg = load_app_config(path)
            group_names = [g.name for g in cfg.groups]
            self.assertIn("CRYPTO", group_names)
            self.assertIn("STOCKS", group_names)

    def test_save_and_dump_app_config(self) -> None:
        cfg = AppConfig.from_dict(
            {
                "config_name": "Test",
                "groups": [{"name": "G", "symbols": [{"symbol": "AAPL", "type": "stock"}]}],
            }
        )
        dumped = dump_app_config(cfg)
        self.assertIn("config_name:", dumped)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            self.assertTrue(save_app_config(path, cfg))
            loaded = load_app_config(path)
            self.assertEqual(loaded.config_name, "Test")


if __name__ == "__main__":
    unittest.main()
