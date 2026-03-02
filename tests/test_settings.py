from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.settings import load_settings


class SettingsTests(unittest.TestCase):
    def test_load_settings_reads_groups_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            try:
                workdir = Path(tmp)
                (workdir / "config.yml").write_text(
                    "config_name: Demo\n"
                    "groups:\n"
                    "  - name: Mixed\n"
                    "    symbols:\n"
                    "      - symbol: BTCUSDT\n"
                    "        type: crypto\n"
                    "      - symbol: AAPL\n"
                    "        type: stock\n",
                    encoding="utf-8",
                )
                import os

                os.chdir(workdir)
                settings = load_settings()
                self.assertEqual(settings.config_name, "Demo")
                self.assertIn("BTCUSDT", settings.crypto_symbols)
                self.assertIn("AAPL", settings.stock_symbols)
            finally:
                import os

                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
