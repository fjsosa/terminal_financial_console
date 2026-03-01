from __future__ import annotations

import argparse

from app.i18n import tr
from app.settings import load_settings
from app.ui import run_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=tr("Neon terminal quotes dashboard with real-time stream."),
    )
    parser.add_argument(
        "--config",
        default="config.yml",
        help=tr("Path to YAML config file (default: config.yml)"),
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help=tr("Deprecated alias for --crypto-symbols"),
    )
    parser.add_argument(
        "--crypto-symbols",
        nargs="+",
        help=tr("Crypto symbols list, e.g. BTCUSDT ETHUSDT SOLUSDT"),
    )
    parser.add_argument(
        "--stock-symbols",
        nargs="+",
        help=tr("Stock symbols list, e.g. AAPL MSFT NVDA"),
    )
    parser.add_argument(
        "--tz",
        help=tr("IANA timezone, e.g. America/Argentina/Buenos_Aires"),
    )
    parser.add_argument(
        "--lang",
        help=tr("Language code, e.g. es or en"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    settings = load_settings(
        config_path=args.config,
        cli_crypto_symbols=args.crypto_symbols or args.symbols,
        cli_stock_symbols=args.stock_symbols,
        cli_timezone=args.tz,
        cli_language=args.lang,
    )
    run_app(
        crypto_symbols=settings.crypto_symbols,
        stock_symbols=settings.stock_symbols,
        timezone=settings.timezone,
        language=settings.language,
        groups=settings.groups,
        config_path=settings.config_path,
        symbols_from_config=settings.symbols_from_config,
    )
