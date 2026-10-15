"""Settings loaded from the repo-root .env (re-read on change so new API keys apply without a restart)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"

_env_cache: dict[str, str] = {}
_env_mtime: float = -1.0


def env() -> dict[str, str]:
    """Process env overlaid with .env; .env is re-read whenever its mtime changes."""
    global _env_cache, _env_mtime
    try:
        mtime = ENV_FILE.stat().st_mtime
    except OSError:
        mtime = 0.0
    if mtime != _env_mtime:
        values = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
        _env_cache = {k: v for k, v in values.items() if v is not None}
        _env_mtime = mtime
    merged = dict(_env_cache)
    for k, v in os.environ.items():
        if v:
            merged[k] = v
    return merged


def get(name: str, default: str = "") -> str:
    return env().get(name, default) or default


def data_dir() -> Path:
    p = Path(get("DATA_DIR", "./data"))
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


PYPI_URL = "https://pypi.org/pypi"
OSV_URL = "https://api.osv.dev/v1/query"
TOOL_VERSION = "0.1.0"
GEMMA_TERMS_URL = "https://ai.google.dev/gemma/terms"
