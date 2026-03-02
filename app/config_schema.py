from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import DEFAULT_CRYPTO_SYMBOLS, DEFAULT_LANGUAGE, DEFAULT_STOCK_SYMBOLS

DEFAULT_QUICK_ACTIONS = {
    "1": "BTCUSDT",
    "2": "ETHUSDT",
    "3": "SOLUSDT",
}


@dataclass(slots=True)
class SymbolConfig:
    symbol: str
    type: str
    name: str = ""

    @staticmethod
    def _infer_type(symbol: str, symbol_type: str) -> str:
        st = (symbol_type or "").strip().lower()
        if st in {"crypto", "stock"}:
            return st
        return "crypto" if symbol.upper().endswith("USDT") else "stock"

    @classmethod
    def from_raw(cls, item: object) -> SymbolConfig | None:
        if isinstance(item, dict):
            symbol = str(
                item.get("symbol")
                or item.get("ticker")
                or item.get("id")
                or item.get("name")
                or ""
            ).strip().upper()
            if not symbol:
                return None
            symbol_type = cls._infer_type(symbol, str(item.get("type") or ""))
            name = str(item.get("name") or "").strip()
            return cls(symbol=symbol, type=symbol_type, name=name)
        if isinstance(item, str):
            symbol = item.strip().upper()
            if not symbol:
                return None
            return cls(symbol=symbol, type=cls._infer_type(symbol, ""), name="")
        return None

    def to_dict(self) -> dict[str, str]:
        out = {
            "symbol": self.symbol,
            "type": self.type,
        }
        if self.name:
            out["name"] = self.name
        return out


@dataclass(slots=True)
class GroupConfig:
    name: str
    symbols: list[SymbolConfig] = field(default_factory=list)

    @classmethod
    def from_raw(cls, item: object, fallback_name: str) -> GroupConfig | None:
        if not isinstance(item, dict):
            return None
        name = str(item.get("name") or fallback_name).strip() or fallback_name
        raw_symbols = item.get("symbols")
        if not isinstance(raw_symbols, list):
            return None
        symbols: list[SymbolConfig] = []
        for raw in raw_symbols:
            parsed = SymbolConfig.from_raw(raw)
            if parsed is not None:
                symbols.append(parsed)
        if not symbols:
            return None
        return cls(name=name, symbols=symbols)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "symbols": [item.to_dict() for item in self.symbols],
        }


@dataclass(slots=True)
class CalendarConfig:
    name: str
    source: str = "forexfactory"
    region: str = "GLOBAL"
    enabled: bool = True
    default_duration_min: int = 60

    @classmethod
    def from_raw(cls, item: object, fallback_name: str) -> CalendarConfig | None:
        if not isinstance(item, dict):
            return None
        name = str(item.get("name") or fallback_name).strip() or fallback_name
        source = str(item.get("source") or "forexfactory").strip().lower() or "forexfactory"
        region = str(item.get("region") or "GLOBAL").strip() or "GLOBAL"
        enabled = bool(item.get("enabled", True))
        duration = int(item.get("default_duration_min") or 60)
        if duration <= 0:
            duration = 60
        return cls(
            name=name,
            source=source,
            region=region,
            enabled=enabled,
            default_duration_min=duration,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "region": self.region,
            "enabled": self.enabled,
            "default_duration_min": self.default_duration_min,
        }


def default_calendars() -> list[CalendarConfig]:
    return [
        CalendarConfig(name="USA", source="forexfactory", region="USA", enabled=True, default_duration_min=60),
        CalendarConfig(name="ARGENTINA", source="forexfactory", region="ARGENTINA", enabled=True, default_duration_min=60),
        CalendarConfig(
            name="INTERNACIONAL",
            source="forexfactory",
            region="INTERNACIONAL",
            enabled=True,
            default_duration_min=60,
        ),
    ]


@dataclass(slots=True)
class AppConfig:
    config_name: str = ""
    timezone: str = ""
    language: str = DEFAULT_LANGUAGE
    quick_actions: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_QUICK_ACTIONS))
    calendars: list[CalendarConfig] = field(default_factory=default_calendars)
    groups: list[GroupConfig] = field(default_factory=list)
    indicator_groups: list[GroupConfig] = field(default_factory=list)

    @staticmethod
    def _parse_symbols(raw: str | list[str] | None) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            tokens = [str(token).strip() for token in raw]
        else:
            normalized = raw.replace(",", " ")
            tokens = [token.strip() for token in normalized.split()]
        return [token.upper() for token in tokens if token]

    @classmethod
    def _normalize_groups(cls, raw_groups: object, prefix: str) -> list[GroupConfig]:
        if not isinstance(raw_groups, list):
            return []
        out: list[GroupConfig] = []
        for idx, item in enumerate(raw_groups, start=1):
            parsed = GroupConfig.from_raw(item, fallback_name=f"{prefix} {idx}")
            if parsed is not None:
                out.append(parsed)
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> AppConfig:
        data = payload or {}
        config_name = str(data.get("config_name") or data.get("namespace") or "").strip()
        timezone = str(data.get("timezone") or "").strip()
        language = str(data.get("language") or DEFAULT_LANGUAGE).strip().lower() or DEFAULT_LANGUAGE

        quick_actions = dict(DEFAULT_QUICK_ACTIONS)
        raw_quick_actions = data.get("quick_actions")
        if isinstance(raw_quick_actions, dict):
            for key in ("1", "2", "3"):
                value = raw_quick_actions.get(key)
                if value is None:
                    continue
                symbol = str(value).strip().upper()
                if symbol:
                    quick_actions[key] = symbol

        groups = cls._normalize_groups(data.get("groups"), prefix="Group")
        indicator_groups = cls._normalize_groups(data.get("indicator_groups"), prefix="Indicator Group")

        calendars: list[CalendarConfig] = []
        raw_calendars = data.get("calendars")
        if isinstance(raw_calendars, list):
            for idx, item in enumerate(raw_calendars, start=1):
                parsed = CalendarConfig.from_raw(item, fallback_name=f"Calendar {idx}")
                if parsed is not None:
                    calendars.append(parsed)
        if not calendars:
            calendars = default_calendars()

        # Legacy compatibility: if groups are absent, build them from old symbol keys.
        if not groups:
            legacy_crypto = cls._parse_symbols(data.get("crypto_symbols") or data.get("symbols"))
            legacy_stock = cls._parse_symbols(data.get("stock_symbols"))
            if not legacy_crypto:
                legacy_crypto = list(DEFAULT_CRYPTO_SYMBOLS)
            if not legacy_stock:
                legacy_stock = list(DEFAULT_STOCK_SYMBOLS)
            if legacy_crypto:
                groups.append(
                    GroupConfig(
                        name="CRYPTO",
                        symbols=[SymbolConfig(symbol=symbol, type="crypto") for symbol in legacy_crypto],
                    )
                )
            if legacy_stock:
                groups.append(
                    GroupConfig(
                        name="STOCKS",
                        symbols=[SymbolConfig(symbol=symbol, type="stock") for symbol in legacy_stock],
                    )
                )

        return cls(
            config_name=config_name,
            timezone=timezone,
            language=language,
            quick_actions=quick_actions,
            calendars=calendars,
            groups=groups,
            indicator_groups=indicator_groups,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_name": self.config_name,
            "timezone": self.timezone,
            "language": self.language,
            "quick_actions": {k: str(self.quick_actions.get(k) or "") for k in ("1", "2", "3")},
            "calendars": [item.to_dict() for item in self.calendars],
            "indicator_groups": [item.to_dict() for item in self.indicator_groups],
            "groups": [item.to_dict() for item in self.groups],
        }

    @classmethod
    def from_runtime(
        cls,
        *,
        config_name: str,
        timezone: str,
        language: str,
        quick_actions: dict[str, str],
        calendars: list[dict[str, Any]],
        indicator_groups: list[dict[str, Any]],
        market_groups: list[dict[str, Any]],
    ) -> AppConfig:
        payload: dict[str, Any] = {
            "config_name": config_name,
            "timezone": timezone,
            "language": language,
            "quick_actions": quick_actions,
            "calendars": calendars,
            "indicator_groups": indicator_groups,
            "groups": market_groups,
        }
        return cls.from_dict(payload)
