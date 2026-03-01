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
    "Ticker": "Ticker",
    "Type": "Tipo",
    "Price": "Precio",
    "Volume": "Volumen",
    "Spark": "Spark",
    "Stock": "Accion",
    "Headline": "Titular",
    "Indicator": "Indicador",
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
    "INDICATORS": "INDICADORES",
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
    "Description": "Descripcion",
    "Category": "Categoria",
    "loading description...": "cargando descripcion...",
    "description unavailable": "descripcion no disponible",
    "ECONOMIC CALENDAR": "CALENDARIO ECONOMICO",
    "horizon": "horizonte",
    "now": "ahora",
    "No calendars configured in config.yml.": "No hay calendarios configurados en config.yml.",
    "Add a 'calendars' section with one or more entries.": "Agrega una seccion 'calendars' con una o mas entradas.",
    "Calendars configured: {count}. No events available from source.": "Calendarios configurados: {count}. No hay eventos disponibles desde la fuente.",
    "Check internet connectivity, source availability, and region filters.": "Revisa conectividad a internet, disponibilidad de la fuente y filtros de region.",
    "LIVE ALERT": "ALERTA EN CURSO",
    "FINISHED": "FINALIZADO",
    "SCHEDULED": "PROGRAMADO",
    "event starts in {time}": "el evento esta por comenzar.. en {time}",
    "TODAY EVENTS": "EVENTOS DEL DIA",
    "no calendars configured in config.yml": "no hay calendarios configurados en config.yml",
    "opening calendar modal": "abriendo modal de calendario",
    "Usage: :c calendar": "Uso: :c calendar",
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
