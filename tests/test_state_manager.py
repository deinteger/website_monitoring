import json
from pathlib import Path

from src.common.state_manager import StateManager


def test_json_save_is_atomic_and_keeps_previous_backup(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    manager.save_json("inventory.json", {"version": 1})
    manager.save_json("inventory.json", {"version": 2})
    assert manager.load_json("inventory.json") == {"version": 2}
    assert json.loads((tmp_path / "inventory.json.bak").read_text(encoding="utf-8")) == {"version": 1}
    assert not (tmp_path / "inventory.json.tmp").exists()


def test_missing_json_returns_default_and_history_is_replayable(tmp_path: Path) -> None:
    manager = StateManager(tmp_path)
    assert manager.load_json("missing.json", []) == []
    manager.append_run_history({"mode": "daily", "status": "started"})
    manager.append_run_history({"mode": "daily", "status": "completed"})
    records = [json.loads(line) for line in (tmp_path / "run_history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [record["status"] for record in records] == ["started", "completed"]
    assert all("recorded_at" in record for record in records)
