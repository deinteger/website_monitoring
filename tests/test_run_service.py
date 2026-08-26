import time
from src.common.run_service import DailyRunService

def test_service_runs_fixture_and_exposes_progress(tmp_path):
    service=DailyRunService(tmp_path/"s",tmp_path/"o"); started=service.start_fixture({"page_results":[]})
    assert started["status"] == "running"
    for _ in range(20):
        if service.snapshot()["status"] != "running": break
        time.sleep(.02)
    assert service.snapshot()["status"] == "completed"
