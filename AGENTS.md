# Repository Guidelines

## Project Structure & Module Organization
- Entry point: `main.py` (loads settings and launches the TUI app).
- Core app code lives in `app/`:
  - `ui.py`: Textual screens, widgets, keyboard actions, charts, ticker tape.
  - `settings.py`: `config.yml` parsing and normalization.
  - `feed.py`, `stocks.py`, `news.py`: market/news data sources.
  - `cache.py`, `symbol_names.py`, `i18n.py`, `config.py`: caching, symbol metadata, localization, constants.
  - `styles.tcss`: Textual styling/theme layer.
- Runtime config: `config.yml` (source of truth for symbols, groups, timezone, language, quick actions).
- Helper script: `run_neon_quotes.sh`.

## Build, Test, and Development Commands
- Create environment and install deps:
  - `python -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt`
- Run app:
  - `python main.py`
  - or `./run_neon_quotes.sh`
- Fast sanity check (no test suite yet):
  - `.venv/bin/python -m compileall main.py app`

## Coding Style & Naming Conventions
- Language: Python 3.10+.
- Follow PEP 8 with 4-space indentation and type hints (already used broadly).
- Naming:
  - modules/functions: `snake_case`
  - classes/dataclasses: `PascalCase`
  - constants: `UPPER_SNAKE_CASE`
- Keep UI behavior in `ui.py`; keep source-specific logic in `feed.py` / `stocks.py` / `news.py`.
- Prefer small, targeted patches; avoid unrelated refactors in the same change.

## Testing Guidelines
- There is currently no formal `tests/` directory.
- Before opening a PR, run:
  - `.venv/bin/python -m compileall main.py app`
  - manual smoke test: launch app and verify key flows (`?` help modal, command mode `:`, chart modal, news/alerts updates).
- If you add non-trivial logic, add unit tests in a future `tests/` package (recommended naming: `test_<module>.py`).

## Commit & Pull Request Guidelines
- Use Conventional Commit style seen in history:
  - `feat(ui): ...`, `fix(charts): ...`, `perf(startup): ...`, `chore(repo): ...`
- PRs should include:
  - concise problem/solution summary
  - impacted files/modules
  - validation steps executed
  - terminal screenshots/GIFs for UI-visible changes.
