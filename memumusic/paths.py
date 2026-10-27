from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("MEMUMUSIC_DATA_DIR")
    if override:
        path = Path(override).expanduser().resolve()
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MemuMusic"
    elif sys.platform == "darwin":
        path = Path.home() / "Library/Application Support/MemuMusic"
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "memumusic"
    path.mkdir(parents=True, exist_ok=True)
    return path


def web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"
