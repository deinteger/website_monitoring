import json
from io import BytesIO
from src.ai_assistant import AIAssistant, AIConfigError, ResultContext, TimelyGPTClient
from src.dashboard import make_handler

class MockClient:
    def __init__(self): self.calls=[]
    def models(self): return ["mock-text"]
    def chat(self,messages,model=None): self.calls.append(messages); return "근거 기반 답변"

def test_context_limits_and_filters(tmp_path):
    (tmp_path/"issues.json").write_text(json.dumps({"page_results":[{"url":"https://a","verdict":"오류","issue_key":"i1"},{"url":"https://b","verdict":"정상"}]}),encoding="utf-8")
    text,pages=ResultContext(tmp_path,max_items=1,max_chars=100).select("오류",{})
    assert len(pages)==1 and len(text)<=100

def test_ai_uses_selected_context_and_limits_history(tmp_path):
    (tmp_path/"issues.json").write_text(json.dumps({"page_results":[{"url":"https://a","issue_key":"i1","verdict":"오류","checked_at":"2026-01-01"}]}),encoding="utf-8")
    c=MockClient(); a=AIAssistant(tmp_path,{"enabled":True,"model":"mock","max_history_messages":1},c)
    out=a.chat("무엇이 문제인가?",[{"role":"user","content":"a"},{"role":"user","content":"b"}])
    assert out["evidence"][0]["issue_key"]=="i1" and len(c.calls[0])==3 and "https://a" in c.calls[0][-1]["content"]

def test_ai_disabled_without_key_and_allowed_endpoint():
    a=AIAssistant("missing",{"enabled":False})
    assert a.chat("질문")["available"] is False
    try: TimelyGPTClient(base_url="https://evil.example")
    except AIConfigError: pass
    else: assert False

def test_dashboard_ai_api_does_not_expose_key(tmp_path):
    h=make_handler(tmp_path/"state",tmp_path/"output")
    req=h.__new__(h); req.path="/api/ai/status"; req.headers={}; req.rfile=BytesIO(); req.wfile=BytesIO(); req.send_response=lambda *a:None; req.send_header=lambda *a:None; req.end_headers=lambda:None; req.do_GET()
    assert b"TIMELYGPT_API_KEY" not in req.wfile.getvalue()
