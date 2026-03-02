from __future__ import annotations

from rich.text import Text

from .constants import AGE_NOW


class NewsPalette(dict[str, str]):
    pass


def ticker_label(
    *,
    symbol: str,
    symbol_type: str,
    symbol_names: dict[tuple[str, str], str],
    palette: dict[str, str],
    max_name_len: int = 20,
) -> Text:
    name = symbol_names.get((symbol, symbol_type), "").strip()
    label = Text(symbol, style=palette["text"])
    if not name:
        return label
    label.append(":", style=palette["muted"])
    label.append(name[:max_name_len], style=palette["accent"])
    return label


def format_volume(volume: float, width: int = 17) -> str:
    if abs(volume) >= 100_000_000:
        numeric_width = max(1, width - 1)
        return f"{(volume / 1_000_000):>{numeric_width}.2f}M"
    return f"{volume:>{width},.2f}"


def format_news_headline(
    *,
    source: str,
    age: str,
    title: str,
    line_len: int,
    news_palette: dict[str, str],
    body_color: str,
) -> Text:
    clean_source = (source.strip() or "source")[:20]
    clean_age = (age.strip() or "-")[:12]
    age_lower = clean_age.lower()
    show_fire = age_lower == AGE_NOW
    words = (title or "").split() or ["-"]
    per_line = max(12, line_len)

    body_lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= per_line:
            current = candidate
            continue
        body_lines.append(current or word[:per_line])
        current = word if len(word) <= per_line else word[:per_line]
    if current:
        body_lines.append(current)

    while len(body_lines) < 2:
        body_lines.append("")
    if len(body_lines) > 2:
        body_lines = body_lines[:2]
        body_lines[1] = (body_lines[1][: max(0, per_line - 1)] + "…").rstrip()

    age_style = news_palette["age_old"]
    if AGE_NOW in age_lower:
        age_style = news_palette["age_now"]
    elif "min" in age_lower or "hour" in age_lower:
        age_style = news_palette["age_recent"]

    text = Text()
    text.append("[", style=news_palette["bracket"])
    text.append(clean_source, style=news_palette["source"])
    text.append(": ", style=news_palette["bracket"])
    text.append(clean_age, style=age_style)
    if show_fire:
        text.append(" ", style=news_palette["bracket"])
        text.append("🔥", style=news_palette["fire"])
    text.append("]", style=news_palette["bracket"])
    text.append("\n", style=body_color)
    text.append(body_lines[0], style=body_color)
    text.append("\n", style=body_color)
    text.append(body_lines[1], style=body_color)
    return text


def headline_inline(source: str, age: str, title: str, max_title_len: int) -> str:
    clean_source = (source or "source").strip()[:16]
    clean_age = (age or "-").strip()[:10]
    if clean_age.lower() == AGE_NOW:
        clean_age = f"{clean_age} 🔥"
    clean_title = " ".join((title or "").split())
    if len(clean_title) > max_title_len:
        clean_title = clean_title[: max_title_len - 1].rstrip() + "…"
    return f"[{clean_source}: {clean_age}] {clean_title}"
