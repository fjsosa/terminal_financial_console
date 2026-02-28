from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import FINVIZ_CRYPTO_NEWS_URL

TIME_TOKEN = re.compile(r"^(?:\d+\s+(?:min|mins|minute|minutes|hour|hours|day|days)|[A-Z][a-z]{2}-\d{2})$")


@dataclass(slots=True)
class NewsItem:
    title: str
    url: str
    source: str
    age: str


class _FinvizNewsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[NewsItem] = []
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
        self._in_anchor = False
        self._href = ""
        self._anchor_text_parts = []

        if not href.startswith("http"):
            return
        if not title or len(title.split()) < 5:
            return

        host = urlparse(href).netloc.lower()
        if "finviz.com" in host:
            return

        source = host.replace("www.", "") or "unknown"
        self.items.append(
            NewsItem(
                title=title,
                url=href,
                source=source,
                age=self._pending_age or "now",
            )
        )
        self._pending_age = ""


def fetch_crypto_news(limit: int = 12) -> list[NewsItem]:
    req = Request(
        FINVIZ_CRYPTO_NEWS_URL,
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
    for item in parser.items:
        if item.url not in dedup:
            dedup[item.url] = item
    return list(dedup.values())[:limit]
