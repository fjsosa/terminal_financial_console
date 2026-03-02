from __future__ import annotations

from rich.text import Text

from .i18n import tr


def build_header_markup(
    *,
    palette: dict[str, str],
    app_version: str,
    config_name: str,
    now_text: str,
    status_text: str,
    age_ms: int,
    heartbeat: bool,
) -> str:
    conn_color = "green" if age_ms < 3000 else "yellow" if age_ms < 10000 else "red"
    pulse = "●" if heartbeat else "○"
    effective_name = config_name or "default"
    return (
        f"[bold {palette['ok']}]NEON MARKET TERM v{app_version}[/] "
        f"[{palette['muted']}]|[/] "
        f"[{palette['brand']}]{effective_name}[/] "
        f"[{palette['muted']}]|[/] "
        f"[{palette['accent']}]{now_text}[/]  "
        f"[{conn_color}]LINK {pulse} {status_text}[/]  "
        f"[{palette['warn']}]latency~{age_ms}ms[/]"
    )


def build_status_line_text(
    *,
    palette: dict[str, str],
    command_mode: bool,
    command_buffer: str,
    width: int,
) -> Text:
    if command_mode:
        left = (
            f":{command_buffer}█ | [Enter] {tr('run')} | [Esc] {tr('normal')} | "
            f"q {tr('quit')} | r {tr('reset')} | n {tr('news')} | ? {tr('help')} | "
            "c calendar | add/del/mv/edit"
        )
        right = tr("status: enter command")
        right_style = palette["warn"]
    else:
        left = (
            f":|f2 {tr('Cmd')} | q {tr('quit')} | [enter] {tr('chart')} | "
            f"? {tr('help')} | ⌃P palette | < {tr('previous group')} | > {tr('next group')}"
        )
        right = tr("status: normal")
        right_style = palette["ok"]

    total_width = max(40, width - 2)
    max_left = max(1, total_width - len(right) - 1)
    if len(left) > max_left:
        left = left[:max_left] if max_left <= 1 else (left[: max_left - 1] + "…")
    spaces = max(1, total_width - len(left) - len(right))
    txt = Text()
    txt.append(left, style=palette["text"])
    txt.append(" " * spaces, style=palette["muted"])
    txt.append(right, style=f"bold {right_style}")
    return txt
