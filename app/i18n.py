from __future__ import annotations

import gettext
from datetime import datetime
from pathlib import Path

try:
    from babel.dates import format_datetime
except Exception:  # pragma: no cover - optional dependency
    format_datetime = None


_LANG = "en"
_LOCALE = "en_US"
_TRANSLATION = gettext.NullTranslations()

# Fallback dictionary while .mo catalogs are not yet compiled.
_ES_FALLBACK = {
    "Neon terminal quotes dashboard with real-time stream.": "Panel terminal Neon de cotizaciones en tiempo real.",
    "Path to YAML config file (default: config.yml)": "Ruta al archivo YAML de configuracion (default: config.yml)",
    "Deprecated alias for --crypto-symbols": "Alias obsoleto de --crypto-symbols",
    "Crypto symbols list, e.g. BTCUSDT ETHUSDT SOLUSDT": "Lista de simbolos crypto, ej. BTCUSDT ETHUSDT SOLUSDT",
    "Stock symbols list, e.g. AAPL MSFT NVDA": "Lista de simbolos de acciones, ej. AAPL MSFT NVDA",
    "IANA timezone, e.g. America/Argentina/Buenos_Aires": "Zona horaria IANA, ej. America/Argentina/Buenos_Aires",
    "Language code, e.g. es or en": "Codigo de idioma, ej. es o en",
    "Ticker": "Ticker",
    "Type": "Tipo",
    "Price": "Precio",
    "Volume": "Volumen",
    "Spark": "Spark",
    "Stock": "Accion",
    "Headline": "Titular",
    "Source": "Fuente",
    "Age": "Edad",
    "Loading headlines...\nPlease wait": "Cargando noticias...\nEspera por favor",
    "MAIN TABLE": "TABLA PRINCIPAL",
    "ALERTS TABLE": "TABLA DE ALERTAS",
    "ALERTAS": "ALERTAS",
    "group": "grupo",
    "updated": "actualizado",
    "previous group": "grupo anterior",
    "next group": "grupo siguiente",
    "STOCKS": "ACCIONES",
    "status: normal": "estado: normal",
    "status: enter command": "estado: ingresar comando",
    "Waiting for market data...": "Esperando datos de mercado...",
    "Booting market stream...": "Iniciando stream de mercado...",
    "Commands:": "Comandos:",
    "Tip:": "Tip:",
    "No headlines available\nTry refresh [n]": "No hay noticias disponibles\nProba refrescar [n]",
    "COMMAND mode enabled": "Modo COMMAND habilitado",
    "COMMAND mode disabled": "Modo COMMAND deshabilitado",
    "Initializing subsystems": "Inicializando subsistemas",
    "Market core online": "Nucleo de mercado en linea",
    "RUNNING": "EJECUTANDO",
    "READY": "LISTO",
    "NEON MARKET OS // BOOT SEQUENCE": "NEON MARKET OS // SECUENCIA DE ARRANQUE",
    "loading historical candles and trend buffers...": "cargando velas historicas y buffers de tendencia...",
    "booting market interfaces [crypto, stocks, news]": "iniciando interfaces de mercado [crypto, stocks, news]",
    "Syncing crypto history": "Sincronizando historico crypto",
    "Syncing stock history": "Sincronizando historico de acciones",
}


def _locale_for_lang(lang: str) -> str:
    base = (lang or "en").split("_")[0].split("-")[0].lower()
    return "es_AR" if base == "es" else "en_US"


def set_language(lang: str) -> None:
    global _LANG, _LOCALE, _TRANSLATION
    base = (lang or "en").split("_")[0].split("-")[0].lower()
    _LANG = base or "en"
    _LOCALE = _locale_for_lang(_LANG)

    localedir = Path(__file__).resolve().parent / "locales"
    try:
        _TRANSLATION = gettext.translation(
            domain="neon",
            localedir=str(localedir),
            languages=[_LANG],
            fallback=True,
        )
    except Exception:
        _TRANSLATION = gettext.NullTranslations()


def get_language() -> str:
    return _LANG


def get_locale() -> str:
    return _LOCALE


def tr(message: str) -> str:
    translated = _TRANSLATION.gettext(message)
    if translated != message:
        return translated
    if _LANG.startswith("es"):
        return _ES_FALLBACK.get(message, message)
    return message


def format_time_local(dt: datetime, tzinfo=None) -> str:
    if format_datetime is not None:
        try:
            return format_datetime(
                dt,
                format="HH:mm:ss",
                locale=_LOCALE,
                tzinfo=tzinfo,
            )
        except Exception:
            pass
    return dt.strftime("%H:%M:%S")
