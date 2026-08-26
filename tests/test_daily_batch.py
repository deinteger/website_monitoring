import json
import time
from daily_batch import main
from src.common.run_service import DailyRunService

def test_batch_fixture_runs_pipeline(tmp_path):
    fixture=tmp_path/"fixture.json"; fixture.write_text(json.dumps({"page_results":[]}),encoding="utf-8")
    assert main(["--offline-fixture",str(fixture),"--state-dir",str(tmp_path/"state"),"--output-root",str(tmp_path/"out"),"--log-dir",str(tmp_path/"logs")]) == 0
    assert (tmp_path/"logs"/"daily_batch.jsonl").exists()

def test_batch_preserves_partial_result_exit_code(tmp_path):
    fixture=tmp_path/"fixture.json"; fixture.write_text(json.dumps({"page_results":[],"stage_failures":{"checks":"fixture failure"}}),encoding="utf-8")
    assert main(["--offline-fixture",str(fixture),"--state-dir",str(tmp_path/"state"),"--output-root",str(tmp_path/"out")]) == 2

def test_batch_without_transport_returns_one():
    assert main([]) == 1

def test_batch_and_manual_share_raw_fixture_pipeline_result(tmp_path):
    base="https://fixture.test"; payload={"responses":{base+"/":{"html":"<a href='/a'>A</a>"},base+"/sitemap.xml":{"text":"<urlset/>"},base+"/a":{"html":"<html>A</html>"}}}
    fixture=tmp_path/"fixture.json"; fixture.write_text(json.dumps(payload),encoding="utf-8")
    assert main(["--offline-fixture",str(fixture),"--state-dir",str(tmp_path/"batch-state"),"--output-root",str(tmp_path/"batch-out")]) == 0
    service=DailyRunService(tmp_path/"manual-state",tmp_path/"manual-out"); service.start_fixture(payload)
    for _ in range(50):
        if service.snapshot()["status"] != "running": break
        time.sleep(.02)
    assert service.snapshot()["status"] == "completed"
    batch=json.loads((tmp_path/"batch-state"/"inventory.json").read_text(encoding="utf-8")); manual=json.loads((tmp_path/"manual-state"/"inventory.json").read_text(encoding="utf-8"))
    def stable(value):
        rows=[]
        for row in value["records"]:
            rows.append({k:v for k,v in row.items() if k not in {"first_discovered_at","last_discovered_at"}})
        return rows
    assert stable(batch["fixture"]["normalized"]) == stable(manual["fixture"]["normalized"])
