import pytest

from src.common.execution_lock import ExecutionLock, ExecutionLockedError


def test_second_execution_is_blocked_and_release_allows_restart(tmp_path):
    first = ExecutionLock(tmp_path); first.acquire(run_id="one", mode="daily")
    with pytest.raises(ExecutionLockedError):
        ExecutionLock(tmp_path).acquire(run_id="two", mode="manual")
    first.release()
    second = ExecutionLock(tmp_path); second.acquire(run_id="two", mode="manual")
    assert (tmp_path / "daily_execution.lock").exists()
    second.release()
