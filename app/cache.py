from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


CACHE_DIR = Path.home() / ".cache" / "neon_quotes"
HISTORY_DIR = CACHE_DIR / "history"
NAMES_FILE = CACHE_DIR / "names.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def history_cache_path(symbol: str, symbol_type: str) -> Path:
    return HISTORY_DIR / f"{symbol_type}_{symbol.upper()}.json"


def load_symbol_history_cache(symbol: str, symbol_type: str, ttl_seconds: int) -> dict[str, Any] | None:
    path = history_cache_path(symbol, symbol_type)
    payload = _read_json(path)
    if not payload:
        return None
    ts = int(payload.get("ts", 0))
    if not ts:
        return None
    if (time.time() - ts) > ttl_seconds:
        return None
    return payload


def save_symbol_history_cache(
    symbol: str,
    symbol_type: str,
    *,
    closes: list[tuple[int, float]],
    candles: list[tuple[int, float, float, float, float]],
) -> None:
    payload = {
        "ts": int(time.time()),
        "symbol": symbol.upper(),
        "type": symbol_type,
        "closes": closes,
        "candles": candles,
    }
    _write_json(history_cache_path(symbol, symbol_type), payload)


def load_names_cache(ttl_seconds: int) -> dict[tuple[str, str], str]:
    payload = _read_json(NAMES_FILE)
    if not payload:
        return {}
    if (time.time() - int(payload.get("ts", 0))) > ttl_seconds:
        return {}
    raw = payload.get("names")
    if not isinstance(raw, dict):
        return {}
    out: dict[tuple[str, str], str] = {}
    for key, name in raw.items():
        if not isinstance(key, str) or not isinstance(name, str):
            continue
        parts = key.split("|", 1)
        if len(parts) != 2:
            continue
        out[(parts[0], parts[1])] = name
    return out


def save_names_cache(names: dict[tuple[str, str], str]) -> None:
    payload_names: dict[str, str] = {}
    for (symbol, symbol_type), name in names.items():
        if not name:
            continue
        payload_names[f"{symbol}|{symbol_type}"] = name
    payload = {
        "ts": int(time.time()),
        "names": payload_names,
    }
    _write_json(NAMES_FILE, payload)
