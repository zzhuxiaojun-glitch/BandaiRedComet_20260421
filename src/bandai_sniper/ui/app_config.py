"""GUI 配置持久化：`%APPDATA%/BandaiSniper/state.json`（Win）或
`~/.config/BandaiSniper/state.json`（Linux/Mac）。

只存 **用户上次填过的字段**，方便下次打开预填；CK 默认**不存**（敏感），
除非 `remember_ck=True`。
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any


def app_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "BandaiSniper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_file() -> Path:
    return app_dir() / "state.json"


def load_state() -> dict[str, Any]:
    p = state_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(data: dict[str, Any]) -> None:
    p = state_file()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
