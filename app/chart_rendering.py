from __future__ import annotations

import textwrap
from collections import deque
from typing import Any, Callable, Protocol

from rich.text import Text

from .i18n import tr

try:
    import plotext as _plotext
except Exception:  # pragma: no cover - optional backend
    _plotext = None


class ChartRenderHost(Protocol):
    candles: dict[str, deque[Any]]
    stock_candles: dict[str, deque[Any]]
    symbol_names: dict[tuple[str, str], str]
    symbol_descriptions: dict[tuple[str, str], str]
    symbol_categories: dict[tuple[str, str], str]
    description_fetching: set[tuple[str, str]]

    def _get_crypto_series(self, symbol: str, timeframe: str) -> deque[Any] | None: ...
    def _get_stock_series(self, symbol: str, timeframe: str) -> deque[Any] | None: ...
    def _resample_candles(self, candles: list[Any], timeframe: str) -> list[Any]: ...
    def _ui_palette(self) -> dict[str, str]: ...
    def _trend_color(self, is_up: bool, symbol_type: str | None = None) -> str: ...


def build_chart_text(
    host: ChartRenderHost,
    state: Any,
    timeframe: str = "15m",
    target_candles: int = 96,
) -> Text:
    candles = list(host._get_crypto_series(state.symbol, timeframe) or deque())
    if timeframe != "15m" and not candles:
        candles = host._resample_candles(list(host.candles.get(state.symbol, deque())), timeframe)
    return build_chart_from_series(
        host,
        symbol=state.symbol,
        display_name=host.symbol_names.get((state.symbol, "crypto"), ""),
        market_label="CRYPTO",
        price=state.price,
        change_percent=state.change_percent,
        volume=state.volume,
        values=list(state.points or []),
        candles=candles,
        timeframe=timeframe,
        target_candles=target_candles,
    )


def build_stock_chart_text(
    host: ChartRenderHost,
    state: Any,
    timeframe: str = "15m",
    target_candles: int = 96,
) -> Text:
    candles = list(host._get_stock_series(state.symbol, timeframe) or deque())
    if timeframe != "15m" and not candles:
        candles = host._resample_candles(list(host.stock_candles.get(state.symbol, deque())), timeframe)
    return build_chart_from_series(
        host,
        symbol=state.symbol,
        display_name=host.symbol_names.get((state.symbol, "stock"), ""),
        market_label="STOCK",
        price=state.price,
        change_percent=state.change_percent,
        volume=state.volume,
        values=list(state.points or []),
        candles=candles,
        timeframe=timeframe,
        target_candles=target_candles,
    )


def build_chart_from_series(
    host: ChartRenderHost,
    *,
    symbol: str,
    display_name: str,
    market_label: str,
    price: float,
    change_percent: float,
    volume: float,
    values: list[float],
    candles: list[Any],
    timeframe: str,
    target_candles: int,
) -> Text:
    symbol_type = "stock" if market_label == "STOCK" else "crypto"
    color = host._trend_color(change_percent >= 0, symbol_type=symbol_type)
    palette = host._ui_palette()
    visible_candles = max(24, target_candles)
    description = host.symbol_descriptions.get((symbol, symbol_type), "").strip()
    category = host.symbol_categories.get((symbol, symbol_type), "").strip()
    loading_description = (symbol, symbol_type) in host.description_fetching

    chart = Text()
    if display_name:
        chart.append(f"{symbol} ({display_name}) // {market_label} SNAPSHOT\n", style=f"bold {palette['brand']}")
    else:
        chart.append(f"{symbol} // {market_label} SNAPSHOT\n", style=f"bold {palette['brand']}")
    chart.append(
        f"price: {price:,.4f}   change: {change_percent:+.2f}%   volume: {volume:,.2f}\n",
        style=f"bold {color}",
    )
    chart.append(
        f"timeframe: {timeframe.upper()}   toggle: [t] 15m/1h/1d/1w/1mo   close: [Esc]/[Enter]/[q]\n\n",
        style=palette["muted"],
    )
    chart.append(f"{tr('Category')}: ", style=f"bold {palette['brand']}")
    chart.append((category or "-") + "\n", style=palette["accent"])
    chart.append(f"{tr('Description')}: ", style=f"bold {palette['brand']}")
    if description:
        lines = textwrap.wrap(description, width=112)
        if not lines:
            lines = [description]
        chart.append(lines[0] + "\n", style=palette["text"])
        for line in lines[1:]:
            chart.append(line + "\n", style=palette["text"])
    elif loading_description:
        chart.append(f"{tr('loading description...')}\n", style=palette["muted"])
    else:
        chart.append(f"{tr('description unavailable')}\n", style=palette["muted"])
    chart.append("\n")

    if len(candles) >= 2:
        chart.append("Chart 1: Candlestick view\n", style=f"bold {palette['ok']}")
        chart.append(
            f"{timeframe.upper()} OHLC candles  |  showing latest {min(len(candles), visible_candles)}\n",
            style=palette["accent"],
        )
        chart.append_text(
            render_candlestick_chart(
                candles,
                width=visible_candles,
                height=16,
                palette=palette,
                trend_color=lambda up: host._trend_color(up, symbol_type=None),
            )
        )
        chart.append("\n")

    if len(values) >= 2:
        lo = min(values)
        hi = max(values)
        chart.append("Chart 2: Live updates\n", style=f"bold {palette['brand']}")
        chart.append(
            f"tick trend min: {lo:,.4f}   max: {hi:,.4f}   points: {len(values)}\n",
            style=palette["accent"],
        )
        plotext_text = render_plotext_xy(values, symbol)
        if plotext_text and plotext_text.count("\n") >= 8:
            chart.append(plotext_text, style=palette["text"])
        else:
            chart.append_text(render_xy_ascii(values, width=108, height=22, color=color, palette=palette))
        chart.append("\n")
    else:
        chart.append("Waiting for more ticks to draw chart...\n", style=palette["accent"])
    return chart


def render_plotext_xy(values: list[float], symbol: str, plotext_module: Any | None = None) -> str:
    plt = plotext_module if plotext_module is not None else _plotext
    if plt is None:
        return ""
    try:
        series = values[-240:]
        x = list(range(len(series)))
        clear_fn = getattr(plt, "clear_figure", None) or getattr(plt, "clf", None)
        if clear_fn:
            clear_fn()

        plot_size_fn = getattr(plt, "plot_size", None) or getattr(plt, "plotsize", None)
        if plot_size_fn:
            plot_size_fn(120, 28)

        title_fn = getattr(plt, "title", None)
        if title_fn:
            title_fn(f"{symbol} XY trend")

        xlabel_fn = getattr(plt, "xlabel", None)
        if xlabel_fn:
            xlabel_fn("ticks")

        ylabel_fn = getattr(plt, "ylabel", None)
        if ylabel_fn:
            ylabel_fn("price")

        grid_fn = getattr(plt, "grid", None)
        if grid_fn:
            try:
                grid_fn(True, True)
            except Exception:
                pass

        plot_fn = getattr(plt, "plot", None)
        if plot_fn:
            try:
                plot_fn(x, series, color="cyan", marker="braille")
            except Exception:
                plot_fn(x, series)

        build_fn = getattr(plt, "build", None)
        if not build_fn:
            return ""
        out = build_fn()
        if clear_fn:
            clear_fn()
        return out if isinstance(out, str) else str(out)
    except Exception:
        return ""


def render_xy_ascii(values: list[float], width: int, height: int, color: str, palette: dict[str, str]) -> Text:
    series = values[-max(width * 2, width):]
    if len(series) > width:
        step = len(series) / width
        sampled = [series[int(i * step)] for i in range(width)]
    else:
        sampled = series[:]
        if len(sampled) < width:
            sampled = [sampled[0]] * (width - len(sampled)) + sampled

    lo = min(sampled)
    hi = max(sampled)
    span = hi - lo or 1.0

    def y(value: float) -> int:
        return int((value - lo) / span * (height - 1))

    grid = [[" " for _ in range(width)] for _ in range(height)]

    prev_y = y(sampled[0])
    grid[height - 1 - prev_y][0] = "●"
    for x in range(1, width):
        cur_y = y(sampled[x])
        y0 = min(prev_y, cur_y)
        y1 = max(prev_y, cur_y)
        for yy in range(y0, y1 + 1):
            ch = "●" if yy == cur_y else "│"
            grid[height - 1 - yy][x] = ch
        prev_y = cur_y

    text = Text()
    text.append(f"{hi:,.4f} ┤", style=palette["accent"])
    text.append("\n")
    for row in grid:
        text.append("      │", style=palette["muted"])
        text.append("".join(row), style=color)
        text.append("\n")
    text.append(f"{lo:,.4f} ┼", style=palette["accent"])
    text.append("─" * width, style=palette["muted"])
    text.append("\n")
    text.append("       oldest", style=palette["muted"])
    text.append(" " * (max(1, width - 13)))
    text.append("latest", style=palette["muted"])
    text.append("\n")
    return text


def compress_series(values: list[float], target: int) -> list[float]:
    if len(values) <= target:
        return values
    step = len(values) / target
    out: list[float] = []
    for i in range(target):
        idx = int(i * step)
        out.append(values[idx])
    return out


def render_candlestick_chart(
    candles: list[Any],
    *,
    width: int,
    height: int,
    palette: dict[str, str],
    trend_color: Callable[[bool], str],
) -> Text:
    sampled = candles[-width:] if len(candles) > width else candles

    lo = min(c.low for c in sampled)
    hi = max(c.high for c in sampled)
    span = hi - lo or 1.0

    def scale(price: float) -> int:
        return int((price - lo) / span * (height - 1))

    text = Text()
    for row in range(height - 1, -1, -1):
        for candle in sampled:
            y_low = scale(candle.low)
            y_high = scale(candle.high)
            y_open = scale(candle.open)
            y_close = scale(candle.close)
            body_min = min(y_open, y_close)
            body_max = max(y_open, y_close)
            up = candle.close >= candle.open
            c_color = trend_color(up)

            if body_min <= row <= body_max:
                text.append("█", style=c_color)
            elif y_low <= row <= y_high:
                text.append("│", style=c_color)
            else:
                text.append(" ")
        text.append("\n")

    text.append(f"high {hi:,.4f}\n", style=palette["accent"])
    text.append(f"low  {lo:,.4f}\n", style=palette["accent"])
    return text
