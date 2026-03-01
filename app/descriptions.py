from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import quote
from urllib.request import Request, urlopen

import yfinance as yf

YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search?q={query}"
COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"
COINGECKO_COIN_URL = (
    "https://api.coingecko.com/api/v3/coins/{coin_id}"
    "?localization=false&tickers=false&market_data=false&community_data=false"
    "&developer_data=false&sparkline=false"
)

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

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


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


def _clean_text(value: str) -> str:
    text = unescape(value or "")
    text = TAG_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text).strip()
    return text


def fetch_stock_profile(symbol: str) -> tuple[str, str]:
    try:
        ticker = yf.Ticker(symbol.upper())
        info = ticker.info or {}
    except Exception:
        info = {}
    category = str(info.get("sector") or info.get("industry") or "").strip()
    for key in ("longBusinessSummary", "shortBusinessSummary", "longName"):
        value = str(info.get(key) or "").strip()
        if value:
            return _clean_text(value), category
    return "", category


def _find_coingecko_id_for_symbol(symbol: str) -> str:
    base = _crypto_base(symbol).lower()
    payload = _http_json(COINGECKO_LIST_URL)
    if not isinstance(payload, list):
        return ""
    for item in payload:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").lower()
        if sym != base:
            continue
        coin_id = str(item.get("id") or "").strip()
        if coin_id:
            return coin_id
    return ""


def fetch_crypto_profile(symbol: str) -> tuple[str, str]:
    coin_id = _find_coingecko_id_for_symbol(symbol)
    if not coin_id:
        return "", ""
    payload = _http_json(COINGECKO_COIN_URL.format(coin_id=quote(coin_id)))
    if not isinstance(payload, dict):
        return "", ""
    categories_raw = payload.get("categories")
    category = ""
    if isinstance(categories_raw, list) and categories_raw:
        category = str(categories_raw[0] or "").strip()
    description = payload.get("description")
    if not isinstance(description, dict):
        return "", category
    for key in ("en", "es"):
        value = str(description.get(key) or "").strip()
        if value:
            return _clean_text(value), category
    return "", category


def fetch_symbol_description(symbol: str, symbol_type: str) -> str:
    st = (symbol_type or "").strip().lower()
    if st == "stock":
        return fetch_stock_profile(symbol)[0]
    if st == "crypto":
        return fetch_crypto_profile(symbol)[0]
    return ""


def fetch_symbol_profile(symbol: str, symbol_type: str) -> tuple[str, str]:
    st = (symbol_type or "").strip().lower()
    if st == "stock":
        return fetch_stock_profile(symbol)
    if st == "crypto":
        return fetch_crypto_profile(symbol)
    return "", ""
