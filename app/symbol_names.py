from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from .constants import SYMBOL_TYPE_CRYPTO, SYMBOL_TYPE_STOCK, SYMBOL_TYPES


YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search?q={query}"
COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"

QUOTE_SUFFIXES = (
    "USDT",
    "USDC",
    "BUSD",
    "FDUSD",
    "TUSD",
    "BTC",
    "ETH",
    "BNB",
    "EUR",
    "TRY",
    "BRL",
    "GBP",
)

KNOWN_CRYPTO = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "BNB": "BNB",
    "XRP": "XRP",
    "DOGE": "Dogecoin",
    "ADA": "Cardano",
    "AVAX": "Avalanche",
    "MATIC": "Polygon",
    "DOT": "Polkadot",
    "LINK": "Chainlink",
    "LTC": "Litecoin",
    "BCH": "Bitcoin Cash",
    "TRX": "TRON",
    "UNI": "Uniswap",
}


def _http_json(url: str) -> dict | list | None:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _crypto_base(symbol: str) -> str:
    up = symbol.upper()
    for suffix in QUOTE_SUFFIXES:
        if up.endswith(suffix) and len(up) > len(suffix):
            return up[: -len(suffix)]
    return up


def _fetch_stock_name(symbol: str) -> str:
    payload = _http_json(YAHOO_SEARCH_URL.format(query=quote(symbol)))
    if not isinstance(payload, dict):
        return ""
    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        return ""
    for item in quotes:
        if not isinstance(item, dict):
            continue
        q_symbol = str(item.get("symbol") or "").upper()
        if q_symbol != symbol.upper():
            continue
        short_name = str(item.get("shortname") or "").strip()
        long_name = str(item.get("longname") or "").strip()
        if short_name:
            return short_name
        if long_name:
            return long_name
    return ""


def _fetch_crypto_names(symbols: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    missing_base: set[str] = set()
    for symbol in symbols:
        base = _crypto_base(symbol)
        known = KNOWN_CRYPTO.get(base)
        if known:
            out[symbol] = known
        else:
            missing_base.add(base.lower())

    if not missing_base:
        return out

    payload = _http_json(COINGECKO_LIST_URL)
    if not isinstance(payload, list):
        return out

    base_to_name: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").lower()
        name = str(item.get("name") or "").strip()
        if sym in missing_base and name and sym not in base_to_name:
            base_to_name[sym] = name

    for symbol in symbols:
        if symbol in out:
            continue
        base = _crypto_base(symbol).lower()
        if base in base_to_name:
            out[symbol] = base_to_name[base]
    return out


def resolve_symbol_names(
    groups: list[dict],
    indicator_groups: list[dict] | None = None,
) -> tuple[list[dict], list[dict], dict[tuple[str, str], str], dict[str, int]]:
    indicator_groups = list(indicator_groups or [])
    stock_missing: list[str] = []
    crypto_missing: list[str] = []
    resolved_map: dict[tuple[str, str], str] = {}
    stats = {
        "stocks_total": 0,
        "crypto_total": 0,
        "stocks_missing_name": 0,
        "crypto_missing_name": 0,
        "stocks_resolved_remote": 0,
        "crypto_resolved_remote": 0,
    }

    all_groups = list(groups) + indicator_groups
    for group in all_groups:
        items = group.get("symbols")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").upper()
            symbol_type = str(item.get("type") or "").lower()
            name = str(item.get("name") or "").strip()
            if not symbol or symbol_type not in SYMBOL_TYPES:
                continue
            if symbol_type == SYMBOL_TYPE_STOCK:
                stats["stocks_total"] += 1
            else:
                stats["crypto_total"] += 1
            if name:
                resolved_map[(symbol, symbol_type)] = name
                continue
            if symbol_type == SYMBOL_TYPE_STOCK:
                stock_missing.append(symbol)
                stats["stocks_missing_name"] += 1
            else:
                crypto_missing.append(symbol)
                stats["crypto_missing_name"] += 1

    stock_names: dict[str, str] = {}
    for symbol in sorted(set(stock_missing)):
        name = _fetch_stock_name(symbol)
        if name:
            stock_names[symbol] = name
            stats["stocks_resolved_remote"] += 1

    crypto_names = _fetch_crypto_names(sorted(set(crypto_missing)))
    stats["crypto_resolved_remote"] = len(crypto_names)

    def enrich_group_list(source_groups: list[dict]) -> list[dict]:
        enriched_local: list[dict] = []
        for group in source_groups:
            new_group = {"name": group.get("name", "Group"), "symbols": []}
            items = group.get("symbols")
            if not isinstance(items, list):
                enriched_local.append(new_group)
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").upper()
                symbol_type = str(item.get("type") or "").lower()
                if not symbol or symbol_type not in SYMBOL_TYPES:
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    if symbol_type == SYMBOL_TYPE_STOCK:
                        name = stock_names.get(symbol, "")
                    else:
                        name = crypto_names.get(symbol, "")
                if not name:
                    name = _crypto_base(symbol).title() if symbol_type == SYMBOL_TYPE_CRYPTO else symbol
                resolved_map[(symbol, symbol_type)] = name
                enriched_item = {
                    "symbol": symbol,
                    "type": symbol_type,
                    "name": name,
                }
                new_group["symbols"].append(enriched_item)
            enriched_local.append(new_group)
        return enriched_local

    enriched = enrich_group_list(groups)
    enriched_indicators = enrich_group_list(indicator_groups)
    return enriched, enriched_indicators, resolved_map, stats


def update_config_group_names(
    config_path: str,
    groups: list[dict],
    indicator_groups: list[dict] | None = None,
) -> bool:
    path = Path(config_path)
    if not path.exists():
        return False
    try:
        import yaml  # type: ignore
    except Exception:
        return False

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            return False
        current_groups = data.get("groups")
        current_indicator_groups = data.get("indicator_groups")
        if not isinstance(current_groups, list):
            current_groups = []
        if not isinstance(current_indicator_groups, list):
            current_indicator_groups = []

        lookup: dict[tuple[str, str], str] = {}
        for group in groups:
            items = group.get("symbols")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").upper()
                symbol_type = str(item.get("type") or "").lower()
                symbol_name = str(item.get("name") or "").strip()
                if symbol and symbol_type in SYMBOL_TYPES and symbol_name:
                    lookup[(symbol, symbol_type)] = symbol_name
        for group in list(indicator_groups or []):
            items = group.get("symbols")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").upper()
                symbol_type = str(item.get("type") or "").lower()
                symbol_name = str(item.get("name") or "").strip()
                if symbol and symbol_type in SYMBOL_TYPES and symbol_name:
                    lookup[(symbol, symbol_type)] = symbol_name

        changed = False
        for group in list(current_groups) + list(current_indicator_groups):
            if not isinstance(group, dict):
                continue
            items = group.get("symbols")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").upper()
                symbol_type = str(item.get("type") or "").lower()
                if not symbol or symbol_type not in SYMBOL_TYPES:
                    continue
                wanted = lookup.get((symbol, symbol_type))
                if not wanted:
                    continue
                if str(item.get("name") or "").strip() == wanted:
                    continue
                item["name"] = wanted
                changed = True

        if not changed:
            return False
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
        return True
    except Exception:
        return False
