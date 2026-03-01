from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


CACHE_DIR = Path.home() / ".cache" / "neon_quotes"
HISTORY_DIR = CACHE_DIR / "history"
NAMES_FILE = CACHE_DIR / "names.json"
APP_LOG_FILE = CACHE_DIR / "app.log"
APP_LOG_MAX_BYTES = 2 * 1024 * 1024
APP_LOG_BACKUPS = 3
_RICH_TAG_RE = re.compile(r"\[/?[^\]]+\]")
_LOCAL_FALLBACK_LOG = Path.cwd() / ".neon_quotes" / "app.log"


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


def _rotate_log_files(path: Path, max_bytes: int = APP_LOG_MAX_BYTES, backups: int = APP_LOG_BACKUPS) -> None:
    try:
        if not path.exists():
            return
        if path.stat().st_size < max_bytes:
            return
    except Exception:
        return

    for index in range(backups, 0, -1):
        src = path.with_name(f"{path.name}.{index}")
        dst = path.with_name(f"{path.name}.{index + 1}")
        if src.exists():
            try:
                if index == backups:
                    src.unlink(missing_ok=True)
                else:
                    src.replace(dst)
            except Exception:
                pass
    try:
        path.replace(path.with_name(f"{path.name}.1"))
    except Exception:
        pass


def append_app_log_line(line: str) -> None:
    clean = _RICH_TAG_RE.sub("", line or "")
    targets = [APP_LOG_FILE, _LOCAL_FALLBACK_LOG]
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _rotate_log_files(target)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(clean.rstrip() + "\n")
            return
        except Exception:
            continue
