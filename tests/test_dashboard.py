import json, time
from io import BytesIO
from src.dashboard import make_handler, safe_report

def call(h, method, path, body=b""):
    req=h.__new__(h); req.path=path; req.headers={"Content-Length":str(len(body))}; req.rfile=BytesIO(body); req.wfile=BytesIO(); req.send_response=lambda *a:None; req.send_header=lambda *a:None; req.end_headers=lambda:None
    getattr(req,method)(); return req.wfile.getvalue()

def test_dashboard_health_and_path_traversal_are_safe(tmp_path):
    h=make_handler(tmp_path/"state",tmp_path/"output",allow_fixture=True)
    assert b"fixture JSON" not in call(h,"do_GET","/")
    assert b"font-family" in call(h,"do_GET","/assets/style.css")
    assert b"/api/run" in call(h,"do_GET","/assets/app.js")
    assert json.loads(call(h,"do_GET","/api/health"))["ok"] is True
    assert b"not found" in call(h,"do_GET","/download/../state/issues.json")

def test_dashboard_manual_fixture_uses_pipeline_and_writes_history(tmp_path):
    h=make_handler(tmp_path/"state",tmp_path/"output",allow_fixture=True)
    fixture={"page_results":[],"coverage_summary":{}}
    raw=call(h,"do_POST","/api/run",json.dumps({"target":"nihhs","max_urls":10,"fixture":fixture}).encode())
    assert json.loads(raw)["status"] == "running"
    for _ in range(20):
        status=json.loads(call(h,"do_GET","/api/status"))
        if status.get("status") != "running": break
        time.sleep(.02)
    assert status["status"] == "completed"
    assert (tmp_path/"state"/"run_history.jsonl").exists()

def test_dashboard_records_safe_manual_options(tmp_path):
    h=make_handler(tmp_path/"state",tmp_path/"output",allow_fixture=True)
    response=json.loads(call(h,"do_POST","/api/run",json.dumps({"target":"fruit","max_urls":7,"force_resource":True,"force_accessibility":True,"force_screenshot":True,"fixture":{"page_results":[]}}).encode()))
    assert response["target"] == "fruit" and response["max_urls"] == 7 and response["force_screenshot"] is True

def test_dashboard_rejects_arbitrary_inputs(tmp_path):
    assert b"invalid request" in call(make_handler(tmp_path/"state",tmp_path/"output"),"do_POST","/api/run",b'{"command":"whoami"}')

def test_safe_report_allows_only_xlsx_within_output(tmp_path):
    p=tmp_path/"output"/"a.xlsx"; p.parent.mkdir(); p.write_bytes(b"x")
    assert safe_report(tmp_path/"output","a.xlsx") == p.resolve()

def test_dashboard_result_filters_are_local_state_only(tmp_path):
    h=make_handler(tmp_path/"state",tmp_path/"output",allow_fixture=True)
    (tmp_path/"state").mkdir(); (tmp_path/"state"/"issues.json").write_text(json.dumps({"page_results":[{"target_id":"nihhs","url":"https://x/a","verdict":"오류"},{"target_id":"fruit","url":"https://x/b","verdict":"정상"}]}),encoding="utf-8")
    result=json.loads(call(h,"do_GET","/api/results?target_id=nihhs"))
    assert len(result["pages"]) == 1 and result["pages"][0]["url"].endswith("/a")

def test_dashboard_raw_fixture_runs_full_pipeline_and_writes_xlsx(tmp_path):
    h=make_handler(tmp_path/"state",tmp_path/"output",allow_fixture=True)
    base="https://fixture.test"; fixture={"responses":{base+"/":{"html":"<a href='/a'>A</a>"},base+"/sitemap.xml":{"text":"<urlset/>"},base+"/a":{"html":"<html><body>A</body></html>"}}}
    assert json.loads(call(h,"do_POST","/api/run",json.dumps({"target":"nihhs","max_urls":10,"fixture":fixture}).encode()))["status"] == "running"
    for _ in range(50):
        if json.loads(call(h,"do_GET","/api/status")).get("status") != "running": break
        time.sleep(.02)
    assert list((tmp_path/"output").glob("**/*.xlsx")) and (tmp_path/"state"/"inventory.json").exists()
