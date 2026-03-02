from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CompletionResult:
    value: str | None
    tab_cycle_key: tuple[Any, ...] | None
    tab_cycle_index: int
    no_candidates: bool = False
    suggestions_preview: str = ""


def quote_token(value: str) -> str:
    if not value:
        return value
    if any(ch.isspace() for ch in value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def token_starts_with(candidate: str, partial: str) -> bool:
    raw = candidate.strip()
    normalized = raw.strip('"').strip("'")
    probe = (partial or "").strip()
    if not probe:
        return True
    cf = probe.casefold()
    return raw.casefold().startswith(cf) or normalized.casefold().startswith(cf)


def token_equals(candidate: str, partial: str) -> bool:
    raw = candidate.strip()
    normalized = raw.strip('"').strip("'")
    probe = (partial or "").strip()
    if not probe:
        return False
    cf = probe.casefold()
    return raw.casefold() == cf or normalized.casefold() == cf


def all_configured_symbols(main_group_items: list[tuple[str, list[tuple[str, str]]]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for _, items in main_group_items:
        for symbol, _ in items:
            if symbol not in seen:
                seen.add(symbol)
                out.append(symbol)
    return out


def command_slot_candidates(
    committed: list[str],
    market_groups: list[dict[str, Any]],
    main_group_items: list[tuple[str, list[tuple[str, str]]]],
) -> list[str]:
    commands = ["q", "r", "n", "c", "calendar", "?", "add", "del", "mv", "edit"]
    if not committed:
        return commands
    cmd = committed[0].lower()
    target_index = len(committed)
    if cmd == "c" and target_index == 1:
        return ["calendar"]
    if cmd in {"del", "mv", "edit"} and target_index == 1:
        return all_configured_symbols(main_group_items)
    if cmd == "add" and target_index == 2:
        return ["crypto", "stock"]
    if cmd in {"add", "mv"} and target_index == 2 + (1 if cmd == "add" else 0):
        groups = [quote_token(str(g.get("name") or "").strip()) for g in market_groups]
        return [g for g in groups if g]
    if cmd == "edit" and target_index >= 2:
        return ["group=", "type=", "name="]
    return []


def autocomplete(
    *,
    raw_value: str,
    market_groups: list[dict[str, Any]],
    main_group_items: list[tuple[str, list[tuple[str, str]]]],
    tab_cycle_key: tuple[Any, ...] | None,
    tab_cycle_index: int,
) -> CompletionResult:
    value = raw_value or ""
    if value.startswith(":"):
        value = value[1:]
    ends_space = bool(value) and value[-1].isspace()
    try:
        tokens = shlex.split(value)
    except ValueError:
        tokens = value.split()

    current_partial = ""
    committed = list(tokens)
    if not ends_space and tokens:
        current_partial = tokens[-1]
        committed = tokens[:-1]

    slot_candidates = command_slot_candidates(committed, market_groups, main_group_items)
    filtered_candidates = [c for c in slot_candidates if token_starts_with(c, current_partial)]
    if (
        len(slot_candidates) > 1
        and current_partial
        and any(token_equals(c, current_partial) for c in slot_candidates)
    ):
        candidates = slot_candidates
    else:
        candidates = filtered_candidates

    if not candidates:
        return CompletionResult(
            value=None,
            tab_cycle_key=None,
            tab_cycle_index=-1,
            no_candidates=True,
        )

    next_token = ""
    add_trailing_space = False
    new_cycle_key: tuple[Any, ...] | None = tab_cycle_key
    new_cycle_index = tab_cycle_index
    preview = ""

    if len(candidates) == 1:
        next_token = candidates[0]
        add_trailing_space = True
        new_cycle_key = None
        new_cycle_index = -1
    else:
        cycle_key = (tuple(committed), tuple(candidates))
        if tab_cycle_key == cycle_key:
            idx = (tab_cycle_index + 1) % len(candidates)
        else:
            idx = 0
            for i, cand in enumerate(candidates):
                if token_equals(cand, current_partial):
                    idx = (i + 1) % len(candidates)
                    break
        new_cycle_key = cycle_key
        new_cycle_index = idx
        next_token = candidates[idx]
        preview = ", ".join(candidates[:8])
        if len(candidates) > 8:
            preview += ", …"

    rebuilt = list(committed)
    rebuilt.append(next_token)
    suffix = " " if add_trailing_space else ""
    completed = ":" + " ".join(rebuilt) + suffix
    return CompletionResult(
        value=completed,
        tab_cycle_key=new_cycle_key,
        tab_cycle_index=new_cycle_index,
        no_candidates=False,
        suggestions_preview=preview,
    )
