from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config_repository import persist_yaml_config, serialize_config_yaml


class ConfigRepositoryTests(unittest.TestCase):
    def test_serialize_config_yaml_contains_sections(self) -> None:
        payload = serialize_config_yaml(
            config_name='My "Config"',
            timezone="America/Argentina/Buenos_Aires",
            language="es",
            quick_actions={"1": "AAPL", "2": "BTCUSDT", "3": ""},
            calendars=[
                {
                    "name": "USA",
                    "source": "forexfactory",
                    "region": "USA",
                    "enabled": True,
                    "default_duration_min": 60,
                }
            ],
            indicator_groups=[
                {"name": "Global", "symbols": [{"symbol": "^GSPC", "type": "stock", "name": "S&P 500"}]}
            ],
            market_groups=[
                {"name": "Tech", "symbols": [{"symbol": "AAPL", "type": "stock", "name": "Apple"}]}
            ],
        )
        self.assertIn("config_name:", payload)
        self.assertIn("quick_actions:", payload)
        self.assertIn("calendars:", payload)
        self.assertIn("indicator_groups:", payload)
        self.assertIn("groups:", payload)
        self.assertIn('config_name: My "Config"', payload)

    def test_persist_yaml_config_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            ok = persist_yaml_config(path, "k: v\n")
            self.assertTrue(ok)
            self.assertEqual(path.read_text(encoding="utf-8"), "k: v\n")


if __name__ == "__main__":
    unittest.main()
