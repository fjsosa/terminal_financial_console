from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path


def _clean_version(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return "0.0.0-dev"
    if value.startswith("v") and len(value) > 1 and value[1].isdigit():
        value = value[1:]
    return value


def _pep440_from_git_describe(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return "0.0.0-dev"
    dirty = value.endswith("-dirty")
    core = value[:-6] if dirty else value
    # Tag-like form: v1.2.3-4-gabcdef
    match = re.match(r"^v?(\d+\.\d+\.\d+)-(\d+)-g([0-9a-fA-F]+)$", core)
    if match:
        base, distance, sha = match.groups()
        version = f"{base}.dev{distance}+g{sha.lower()}"
        if dirty:
            version += ".dirty"
        return version
    # Hash-like fallback.
    if re.match(r"^[0-9a-fA-F]{7,}$", core):
        version = f"0.0.0+g{core.lower()}"
        if dirty:
            version += ".dirty"
        return version
    return _clean_version(value)


@lru_cache(maxsize=1)
def get_app_version() -> str:
    # 1) Preferred: setuptools-scm generated module.
    try:
        from ._version import version as generated_version  # type: ignore

        cleaned = _clean_version(generated_version)
        if cleaned:
            return cleaned
    except Exception:
        pass

    # 2) Installed package metadata.
    try:
        from importlib.metadata import version as pkg_version

        cleaned = _clean_version(pkg_version("neon-quotes-terminal"))
        if cleaned:
            return cleaned
    except Exception:
        pass

    # 3) Development fallback from git tags.
    try:
        project_root = Path(__file__).resolve().parent.parent
        raw = subprocess.check_output(
            ["git", "describe", "--tags", "--dirty", "--always"],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
        # Keep only compact semver-ish tokens when possible.
        match = re.search(r"v?\d+\.\d+\.\d+(?:[-+._a-zA-Z0-9]*)?", raw)
        if match:
            return _clean_version(match.group(0))
        if raw:
            return _pep440_from_git_describe(raw)
    except Exception:
        pass

    return "0.0.0-dev"
