from __future__ import annotations

import json
from pathlib import Path

SESSION_NAME = "micromeasure_session.json"


def session_path(folder: Path) -> Path:
    return folder / SESSION_NAME


def read_session(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_session(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
