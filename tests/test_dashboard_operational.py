import json
from io import BytesIO

from src.dashboard import make_handler


def call(handler, method, path, body=b""):
    req=handler.__new__(handler); req.path=path; req.headers={"Content-Length":str(len(body))}; req.rfile=BytesIO(body); req.wfile=BytesIO()
    req.send_response=lambda *a:None; req.send_header=lambda *a:None; req.end_headers=lambda:None
    getattr(req, method)(); return req.wfile.getvalue()


def test_operational_api_rejects_fixture_and_arbitrary_input(tmp_path):
    h=make_handler(tmp_path/"state",tmp_path/"output")
    body=json.dumps({"target":"nihhs","fixture":{"page_results":[]}}).encode()
    assert json.loads(call(h,"do_POST","/api/run",body))["error"] == "invalid request"
    assert json.loads(call(h,"do_POST","/api/run",b'{"command":"dir"}'))["error"] == "invalid request"


def test_operational_html_has_no_fixture_controls(tmp_path):
    html=call(make_handler(tmp_path/"state",tmp_path/"output"),"do_GET","/").decode()
    assert "fixture JSON" not in html and "fixture 실행" not in html and "<pre" not in html
    assert "웹사이트 품질점검 대시보드" in html and "점검 시작" in html


def test_results_filters_pagination_summary_and_detail(tmp_path):
    state=tmp_path/"state"; state.mkdir()
    pages=[{"issue_key":"a","target_id":"nihhs","menu_path":"주요","title":"A","url":"https://a","verdict":"오류","issue_type":"접속","lifecycle":"신규"},{"issue_key":"b","target_id":"fruit","menu_path":"자료","title":"B","url":"https://b","verdict":"정상","lifecycle":"지속"}]
    (state/"issues.json").write_text(json.dumps({"page_results":pages},ensure_ascii=False),encoding="utf-8")
    h=make_handler(state,tmp_path/"output")
    result=json.loads(call(h,"do_GET","/api/results?verdict=%EC%98%A4%EB%A5%98&page=1&page_size=1"))
    assert result["total"]==1 and result["pages"][0]["issue_key"]=="a"
    assert json.loads(call(h,"do_GET","/api/summary"))["verdicts"]["정상"]==1
    assert json.loads(call(h,"do_GET","/api/results/a"))["title"]=="A"


def test_operational_run_accepts_only_safe_options(tmp_path):
    h=make_handler(tmp_path/"state",tmp_path/"output",transport_factory=lambda: type("T",(),{"name":"mock","build_payload":lambda self:{"page_results":[],"coverage_summary":{}}})())
    response=json.loads(call(h,"do_POST","/api/run",json.dumps({"target":"fruit","max_urls":10,"force_resource":True,"force_accessibility":False,"force_screenshot":True}).encode()))
    assert response["target"]=="fruit" and response["max_urls"]==10
