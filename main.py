from __future__ import annotations

from app.settings import load_settings
from app.ui import run_app

if __name__ == "__main__":
    settings = load_settings()
    run_app(
        crypto_symbols=settings.crypto_symbols,
        stock_symbols=settings.stock_symbols,
        timezone=settings.timezone,
        language=settings.language,
        groups=settings.groups,
        config_path=settings.config_path,
        symbols_from_config=settings.symbols_from_config,
    )
