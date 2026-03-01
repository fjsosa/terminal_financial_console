from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.request import Request, urlopen

FOREX_FACTORY_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]

COUNTRY_MAP = {
    "USA": {"US", "USD", "USA", "UNITED STATES"},
    "ARGENTINA": {"AR", "ARS", "ARG", "ARGENTINA"},
    "INTERNACIONAL": set(),
    "GLOBAL": set(),
    "INTL": set(),
}

_DIGITS_RE = re.compile(r"(\d{10,13})")


@dataclass(slots=True)
class CalendarEvent:
    calendar_name: str
    title: str
    start_utc: datetime
    end_utc: datetime
    source: str
    region: str
    country: str
    impact: str


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=UTC)
        except Exception:
            return None

    raw = str(value).strip()
    if not raw:
        return None
    match = _DIGITS_RE.search(raw)
    if match:
        try:
            ts = float(match.group(1))
            if ts > 1_000_000_000_000:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=UTC)
        except Exception:
            pass

    iso = raw.replace("Z", "+00:00")
    for fmt in (
        None,
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            if fmt is None:
                dt = datetime.fromisoformat(iso)
            else:
                dt = datetime.strptime(raw, fmt)
            return _as_utc(dt)
        except Exception:
            continue
    return None


def _load_json_url(url: str) -> list[dict]:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _ff_country(raw: str) -> str:
    return raw.strip().upper()


def _region_matches(country: str, region: str) -> bool:
    region_key = (region or "").strip().upper()
    if not region_key:
        return True
    allowed = COUNTRY_MAP.get(region_key)
    if allowed is None:
        return True
    if not allowed:
        return True
    return country.upper() in allowed


def _fetch_forexfactory_events(
    calendar_name: str,
    region: str,
    horizon_days: int,
    default_duration_min: int,
) -> list[CalendarEvent]:
    now = datetime.now(tz=UTC)
    end_limit = now + timedelta(days=max(1, horizon_days))
    out: list[CalendarEvent] = []
    dedup: set[tuple[str, int, str]] = set()
    for url in FOREX_FACTORY_URLS:
        try:
            rows = _load_json_url(url)
        except Exception:
            continue
        for row in rows:
            title = str(row.get("title") or row.get("event") or row.get("name") or "").strip()
            if not title:
                continue
            start = (
                _parse_datetime(row.get("date"))
                or _parse_datetime(row.get("datetime"))
                or _parse_datetime(row.get("timestamp"))
            )
            if start is None:
                date_part = str(row.get("date") or "").strip()
                time_part = str(row.get("time") or "").strip()
                if date_part and time_part:
                    start = _parse_datetime(f"{date_part} {time_part}")
            if start is None:
                continue
            if start > end_limit:
                continue
            country = _ff_country(str(row.get("country") or row.get("currency") or "INTL"))
            if not _region_matches(country, region):
                continue
            impact = str(row.get("impact") or row.get("volatility") or "").strip().lower()
            duration_min = int(row.get("duration_minutes") or default_duration_min or 60)
            if duration_min <= 0:
                duration_min = 60
            end = start + timedelta(minutes=duration_min)
            key = (title.casefold(), int(start.timestamp()), country)
            if key in dedup:
                continue
            dedup.add(key)
            out.append(
                CalendarEvent(
                    calendar_name=calendar_name,
                    title=title,
                    start_utc=start,
                    end_utc=end,
                    source="forexfactory",
                    region=region.upper() if region else "GLOBAL",
                    country=country,
                    impact=impact,
                )
            )
    out.sort(key=lambda e: e.start_utc)
    return out


def fetch_calendar_events(
    calendars: list[dict],
    horizon_days: int = 15,
) -> list[CalendarEvent]:
    all_events: list[CalendarEvent] = []
    for item in calendars:
        if not isinstance(item, dict):
            continue
        enabled = item.get("enabled", True)
        if enabled is False:
            continue
        name = str(item.get("name") or "Calendar").strip()
        source = str(item.get("source") or "forexfactory").strip().lower()
        region = str(item.get("region") or "GLOBAL").strip()
        duration_min = int(item.get("default_duration_min") or 60)
        if source == "forexfactory":
            events = _fetch_forexfactory_events(name, region, horizon_days, duration_min)
        else:
            events = []
        all_events.extend(events)
    all_events.sort(key=lambda e: e.start_utc)
    return all_events
