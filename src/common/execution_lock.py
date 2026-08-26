"""A process-wide, crash-recoverable lock for daily runs."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class ExecutionLockedError(RuntimeError):
    pass


class ExecutionLock:
    def __init__(self, state_dir: str | Path = "state"):
        self.path = Path(state_dir) / "daily_execution.lock"
        self.acquired = False

    def acquire(self, *, run_id: str, mode: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({"run_id": run_id, "mode": mode, "pid": os.getpid(),
                           "started_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ExecutionLockedError(f"daily execution is already active: {self.path}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
        self.acquired = True

    def release(self) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False

    def __enter__(self): return self
    def __exit__(self, *_): self.release()
