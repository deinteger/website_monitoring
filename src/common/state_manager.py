"""Atomic JSON state and append-only JSONL run history."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StateError(ValueError):
    """Raised for malformed stored JSON data."""


class StateManager:
    def __init__(self, state_dir: str | Path = "state") -> None:
        self.state_dir = Path(state_dir)

    def load_json(self, name: str, default: Any | None = None) -> Any:
        path = self.state_dir / name
        if not path.exists():
            return {} if default is None else default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StateError(f"Malformed JSON state: {path}") from exc

    def save_json(self, name: str, value: Any) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_dir / name
        backup = path.with_suffix(path.suffix + ".bak")
        temporary = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary.write_text(payload, encoding="utf-8")
        if path.exists():
            backup.write_bytes(path.read_bytes())
        os.replace(temporary, path)
        return path

    def append_run_history(self, event: dict[str, Any]) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        record = dict(event)
        record.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        path = self.state_dir / "run_history.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return path
