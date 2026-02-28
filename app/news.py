from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import (
    FINVIZ_CRYPTO_NEWS_URL,
    FINVIZ_ECONOMY_NEWS_URL,
    FINVIZ_GENERAL_NEWS_URL,
    FINVIZ_STOCKS_NEWS_URL,
    FINVIZ_TECH_NEWS_URL,
)

TIME_TOKEN = re.compile(
    r"^(?:\d+\s+(?:min|mins|minute|minutes|hour|hours|day|days)|[A-Z][a-z]{2}-\d{2})$"
)


@dataclass(slots=True)
class NewsItem:
    category: str
    title: str
    url: str
    source: str
    age: str


@dataclass(slots=True)
class NewsSource:
    key: str
    label: str
    url: str


NEWS_SOURCES = [
    NewsSource(key="crypto", label="CRYPTO NEWS", url=FINVIZ_CRYPTO_NEWS_URL),
    NewsSource(key="stocks", label="STOCKS NEWS", url=FINVIZ_STOCKS_NEWS_URL),
    NewsSource(key="economy", label="ECONOMY NEWS", url=FINVIZ_ECONOMY_NEWS_URL),
    NewsSource(key="tech", label="TECH NEWS", url=FINVIZ_TECH_NEWS_URL),
    NewsSource(key="news", label="NEWS", url=FINVIZ_GENERAL_NEWS_URL),
]


class _FinvizNewsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, str, str]] = []
        self._in_anchor = False
        self._href = ""
        self._anchor_text_parts: list[str] = []
        self._pending_age = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        self._in_anchor = True
        self._href = href
        self._anchor_text_parts = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_anchor:
            self._anchor_text_parts.append(text)
            return
        if TIME_TOKEN.match(text):
            self._pending_age = text

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._in_anchor:
            return

        title = unescape(" ".join(self._anchor_text_parts)).strip()
        href = self._href.strip()
        age = self._pending_age or "now"

        self._in_anchor = False
        self._href = ""
        self._anchor_text_parts = []
        self._pending_age = ""

        if not href.startswith("http"):
            return
        if not title or len(title.split()) < 5:
            return

        host = urlparse(href).netloc.lower()
        if "finviz.com" in host:
            return

        source = host.replace("www.", "") or "unknown"
        self.rows.append((title, href, source + "|" + age))


def _fetch_source_news(source: NewsSource, limit: int) -> list[NewsItem]:
    req = Request(
        source.url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        },
    )
    with urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    parser = _FinvizNewsParser()
    parser.feed(html)

    dedup: dict[str, NewsItem] = {}
    for title, url, payload in parser.rows:
        if url in dedup:
            continue
        source_host, age = payload.split("|", 1)
        dedup[url] = NewsItem(
            category=source.label,
            title=title,
            url=url,
            source=source_host,
            age=age,
        )

    return list(dedup.values())[:limit]


def fetch_all_news(limit_per_source: int = 15) -> dict[str, list[NewsItem]]:
    out: dict[str, list[NewsItem]] = {}
    for source in NEWS_SOURCES:
        try:
            out[source.label] = _fetch_source_news(source, limit_per_source)
        except Exception:
            out[source.label] = []
    return out

