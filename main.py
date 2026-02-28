from __future__ import annotations

import argparse

from app.settings import load_settings
from app.ui import run_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Neon terminal quotes dashboard with real-time stream."
    )
    parser.add_argument(
        "--config",
        default="config.yml",
        help="Path to YAML config file (default: config.yml)",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Symbols list, e.g. BTCUSDT ETHUSDT SOLUSDT",
    )
    parser.add_argument(
        "--tz",
        help="IANA timezone, e.g. America/Argentina/Buenos_Aires",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    settings = load_settings(
        config_path=args.config,
        cli_symbols=args.symbols,
        cli_timezone=args.tz,
    )
    run_app(symbols=settings.symbols, timezone=settings.timezone)
