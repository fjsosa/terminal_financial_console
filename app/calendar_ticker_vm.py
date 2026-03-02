from __future__ import annotations

import re
from datetime import UTC, date, datetime

from rich.text import Text

from .calendar import CalendarEvent
from .constants import SYMBOL_TYPE_CRYPTO
from .formatters import headline_inline
from .i18n import tr
from .news import NewsItem


def alerts_items_for_ticker(alerts_row_item_by_index: dict[int, tuple[str, str]]) -> list[tuple[str, str]]:
    if not alerts_row_item_by_index:
        return []
    return [alerts_row_item_by_index[i] for i in sorted(alerts_row_item_by_index)]


def format_hhmmss(delta_seconds: int) -> str:
    total = max(0, int(delta_seconds))
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def calendar_status_label(
    event: CalendarEvent,
    *,
    now_utc: datetime,
    soon_hours: int,
) -> tuple[str, str]:
    if event.start_utc <= now_utc <= event.end_utc:
        return tr("LIVE ALERT"), "live"
    if now_utc > event.end_utc:
        return tr("FINISHED"), "done"
    delta = event.start_utc - now_utc
    if delta.total_seconds() <= soon_hours * 3600:
        return tr("event starts in {time}").format(time=format_hhmmss(int(delta.total_seconds()))), "soon"
    return tr("SCHEDULED"), "scheduled"


def calendar_events_for_ticker(
    events: list[CalendarEvent],
    *,
    local_now: datetime,
    local_today: date,
    local_tz: object,
) -> list[CalendarEvent]:
    del local_now
    if not events:
        return []
    out: list[CalendarEvent] = []
    for event in events:
        start_local = event.start_utc.astimezone(local_tz)  # type: ignore[arg-type]
        if start_local.date() != local_today:
            continue
        impact = (event.impact or "").strip().lower()
        if impact not in {"high", "alto", "3", "3.0"}:
            continue
        out.append(event)
    out.sort(key=lambda e: e.start_utc)
    return out


def build_calendar_text(
    *,
    palette: dict[str, str],
    calendars: list[dict[str, str]],
    calendar_events: list[CalendarEvent],
    calendar_last_update: str,
    horizon_days: int,
    now_local: datetime,
    soon_hours: int,
) -> Text:
    txt = Text()
    txt.append(f"{tr('ECONOMIC CALENDAR')}\n", style=f"bold {palette['brand']}")
    txt.append(
        (
            f"{tr('updated')} {calendar_last_update} | "
            f"{tr('horizon')} {horizon_days}d | "
            f"{tr('now')} {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        ),
        style=palette["muted"],
    )
    if not calendars:
        txt.append(f"{tr('No calendars configured in config.yml.')}\n", style=palette["warn"])
        txt.append(
            tr("Add a 'calendars' section with one or more entries.") + "\n",
            style=palette["muted"],
        )
        return txt
    if not calendar_events:
        txt.append(
            f"{tr('Calendars configured: {count}. No events available from source.').format(count=len(calendars))}\n",
            style=palette["warn"],
        )
        txt.append(
            f"{tr('Check internet connectivity, source availability, and region filters.')}\n",
            style=palette["muted"],
        )
        return txt

    now_utc = datetime.now(tz=UTC)
    for event in calendar_events:
        start_local = event.start_utc.astimezone(now_local.tzinfo)
        end_local = event.end_utc.astimezone(now_local.tzinfo)
        status, kind = calendar_status_label(event, now_utc=now_utc, soon_hours=soon_hours)
        status_color = palette["muted"]
        if kind == "live":
            status_color = palette["err"]
        elif kind == "soon":
            status_color = palette["warn"]
        txt.append(
            f"[{event.calendar_name}] {start_local.strftime('%Y-%m-%d %H:%M')} - {end_local.strftime('%H:%M')} ",
            style=palette["accent"],
        )
        txt.append(f"{event.title}\n", style=palette["text"])
        txt.append(
            f"  {event.country}/{event.region}  impact={event.impact or '-'}  ",
            style=palette["muted"],
        )
        txt.append(f"{status}\n\n", style=f"bold {status_color}")
    return txt


def headline_inline_text(item: NewsItem, *, max_title_len: int) -> str:
    return headline_inline(
        source=item.source,
        age=item.age,
        title=item.title,
        max_title_len=max_title_len,
    )


def ticker_chunks_quotes(
    *,
    alerts_items: list[tuple[str, str]],
    symbol_data: dict[str, object],
    stock_data: dict[str, object],
) -> list[str]:
    chunks: list[str] = []
    for symbol, symbol_type in alerts_items:
        state = symbol_data.get(symbol) if symbol_type == SYMBOL_TYPE_CRYPTO else stock_data.get(symbol)
        if state is None or getattr(state, "price", 0.0) <= 0:
            continue
        change = float(getattr(state, "change_percent", 0.0))
        arrow = "▲" if change >= 0 else "▼"
        prefix = "C" if symbol_type == SYMBOL_TYPE_CRYPTO else "S"
        price = float(getattr(state, "price", 0.0))
        chunks.append(f"{prefix}:{symbol} {arrow} {price:,.2f} ({change:+.2f}%)")
    return chunks


def ticker_chunks_news(
    *,
    latest_items: list[NewsItem],
    limit: int,
) -> list[str]:
    chunks: list[str] = []
    for idx, item in enumerate(latest_items[:limit]):
        chunks.append(headline_inline_text(item, max_title_len=110))
        if idx < min(len(latest_items), limit) - 1:
            chunks.append("BREAKING NEWS")
    return chunks


def ticker_chunks_calendar(
    *,
    events: list[CalendarEvent],
    max_events: int,
    soon_hours: int,
) -> list[str]:
    chunks: list[str] = []
    now_utc = datetime.now(tz=UTC)
    for idx, event in enumerate(events[:max_events]):
        status, _kind = calendar_status_label(event, now_utc=now_utc, soon_hours=soon_hours)
        title = " ".join(event.title.split())
        if len(title) > 60:
            title = title[:59].rstrip() + "…"
        chunks.append(f"[{event.calendar_name}] {title} ({status})")
        if (idx + 1) % 2 == 0 and idx < len(events) - 1:
            chunks.append(tr("TODAY EVENTS"))
    return chunks


def render_ticker_visible_text(
    *,
    mode: str,
    visible: str,
    palette: dict[str, str],
    heartbeat: bool,
) -> Text:
    ticker_text = Text(visible, style=palette["text"])
    if mode == "quotes":
        for idx, ch in enumerate(visible):
            if ch == "▲":
                ticker_text.stylize(palette["ok"], idx, idx + 1)
            elif ch == "▼":
                ticker_text.stylize(palette["err"], idx, idx + 1)
        return ticker_text

    if mode == "news":
        alert_style = palette["warn"] if heartbeat else palette["err"]
        token = "BREAKING NEWS"
        start = 0
        while True:
            pos = visible.find(token, start)
            if pos < 0:
                break
            ticker_text.stylize(f"bold {alert_style}", pos, pos + len(token))
            start = pos + len(token)
        return ticker_text

    token = tr("LIVE ALERT")
    start = 0
    while True:
        pos = visible.find(token, start)
        if pos < 0:
            break
        ticker_text.stylize(f"bold {palette['err']}", pos, pos + len(token))
        start = pos + len(token)

    alert_token = tr("TODAY EVENTS")
    start = 0
    blink_style = palette["warn"] if heartbeat else palette["err"]
    while True:
        pos = visible.find(alert_token, start)
        if pos < 0:
            break
        ticker_text.stylize(f"bold {blink_style}", pos, pos + len(alert_token))
        start = pos + len(alert_token)

    for match in re.finditer(r"\[[^\]]+\]", visible):
        ticker_text.stylize(f"bold {palette['accent']}", match.start(), match.end())
    return ticker_text
