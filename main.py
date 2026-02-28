from __future__ import annotations

import argparse

from app.ui import run_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Neon terminal quotes dashboard with real-time stream."
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Symbols list, e.g. BTCUSDT ETHUSDT SOLUSDT",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_app(symbols=args.symbols)

