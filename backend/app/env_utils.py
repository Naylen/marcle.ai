"""Environment helpers with optional Docker secret file support."""

from __future__ import annotations

from pathlib import Path
import os


def get_env(name: str, default: str = "") -> str:
    """Resolve environment value with optional *_FILE fallback."""
    value = os.getenv(name)
    if value is not None and value != "":
        return value

    file_path = (os.getenv(f"{name}_FILE") or "").strip()
    if file_path:
        try:
            secret = Path(file_path).read_text(encoding="utf-8").strip()
            if secret:
                return secret
        except OSError:
            return default

    return default
