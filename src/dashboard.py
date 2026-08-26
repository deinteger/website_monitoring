"""Small localhost-only dashboard; it deliberately has no arbitrary command API."""
from __future__ import annotations
import json, socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import yaml
from src.common.execution_lock import ExecutionLock, ExecutionLockedError
from src.common.state_manager import StateManager
from src.daily_pipeline import DailyPipeline
from src.common.run_service import DailyRunService
from src.common.http_transport import build_transport
from src.ai_assistant import AIAssistant

WEB_ROOT=Path(__file__).resolve().parent.parent / "web"

def settings(config_dir="config"):
    data=yaml.safe_load((Path(config_dir)/"rules.yaml").read_text(encoding="utf-8")) or {}
    dash=data.get("dashboard", {}) or {}; port=dash.get("port", 18765)
    if not isinstance(port,int) or not 1024 <= port <= 65535: raise ValueError("dashboard.port must be 1024..65535")
    return port

def safe_report(root, name):
    path=(Path(root)/name).resolve(); base=Path(root).resolve()
    if path.suffix.lower() != ".xlsx" or base not in path.parents or not path.is_file(): return None
    return path

def safe_screenshot(root, name):
    path=(Path(root)/name).resolve(); base=Path(root).resolve()
    return path if path.suffix.lower()==".png" and base in path.parents and path.is_file() else None

def make_handler(state_dir="state", output_root="output", *, allow_fixture=False, transport_factory=None, config_dir="config"):
    service=DailyRunService(state_dir, output_root)
    if transport_factory is None:
        cfg=yaml.safe_load((Path(config_dir)/"rules.yaml").read_text(encoding="utf-8")) or {}
        crawl=cfg.get("crawl",{}); network=cfg.get("network",{})
        transport_factory=lambda: build_transport(network,user_agent=crawl.get("user_agent","NIHHS-QA-Bot/1.0"),timeout=crawl.get("timeout_seconds",15),max_retries=crawl.get("max_retries",1),interval=crawl.get("request_interval_seconds",1),max_requests=crawl.get("max_urls",10))
    cfg=yaml.safe_load((Path(config_dir)/"rules.yaml").read_text(encoding="utf-8")) or {}
    assistant=AIAssistant(state_dir,cfg.get("ai",{}))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send_json(self, value, status=200):
            raw=json.dumps(value, ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            parsed=urlparse(self.path)
            if parsed.path == "/": return self._asset("index.html", "text/html; charset=utf-8")
            if parsed.path == "/assets/style.css": return self._asset("style.css", "text/css; charset=utf-8")
            if parsed.path == "/assets/app.js": return self._asset("app.js", "application/javascript; charset=utf-8")
            state=StateManager(state_dir)
            if parsed.path == "/api/health": return self.send_json({"ok":True,"bind":"127.0.0.1"})
            if parsed.path == "/api/ai/status": return self.send_json(assistant.status())
            if parsed.path == "/api/ai/models": return self.send_json({"models":assistant.models(),"configured":bool(assistant.model)})
            if parsed.path == "/api/status":
                current=service.snapshot()
                return self.send_json(current if current.get("status") != "idle" else state.load_json("inventory.json", {}).get("run_metadata", {}))
            if parsed.path == "/api/history":
                p=Path(state_dir)/"run_history.jsonl"; rows=[json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
                return self.send_json(rows[-50:])
            if parsed.path == "/api/reports": return self.send_json([str(x.relative_to(output_root)).replace("\\","/") for x in Path(output_root).glob("**/*.xlsx")])
            if parsed.path == "/api/results":
                issues=state.load_json("issues.json", {}); inventory=state.load_json("inventory.json", {})
                pages=issues.get("page_results", []) if isinstance(issues,dict) else []
                query=parse_qs(parsed.query)
                for field in ("target_id","verdict","menu_path","issue_type","lifecycle"):
                    if query.get(field): pages=[x for x in pages if str(x.get(field,""))==query[field][0]]
                if query.get("q"):
                    needle=query["q"][0].lower(); pages=[x for x in pages if needle in str(x.get("url","")).lower()]
                sort=query.get("sort",["url"])[0]; allowed_sort={"url","target_id","verdict","menu_path","title","status_code"}
                if sort in allowed_sort: pages=sorted(pages,key=lambda x:str(x.get(sort,"")))
                page=max(1,int(query.get("page",[1])[0])); size=min(100,max(1,int(query.get("page_size",[25])[0]))); total=len(pages)
                verdicts={k:sum(x.get("verdict")==k for x in pages) for k in ("정상","검토 필요","오류","점검 불가","제외")}
                lifecycle_counts={k:sum(x.get("lifecycle")==k for x in pages) for k in ("신규","지속","변경","해결","재발")}
                return self.send_json({"verdicts":verdicts,"lifecycle":lifecycle_counts,"pages":pages[(page-1)*size:page*size],"total":total,"page":page,"page_size":size,"active_issues":len(issues.get("active_issues",[])) if isinstance(issues,dict) else 0,"inventory":inventory})
            if parsed.path == "/api/summary":
                issues=state.load_json("issues.json", {}); pages=issues.get("page_results",[]) if isinstance(issues,dict) else []
                return self.send_json({"total":len(pages),"verdicts":{k:sum(x.get("verdict")==k for x in pages) for k in ("정상","검토 필요","오류","점검 불가","제외")},"lifecycle":{k:sum(x.get("lifecycle")==k for x in pages) for k in ("신규","지속","변경","해결","재발")}})
            if parsed.path.startswith("/api/results/"):
                key=parsed.path.rsplit("/",1)[-1]; issues=state.load_json("issues.json",{}); pages=issues.get("page_results",[]) if isinstance(issues,dict) else []
                return self.send_json(next((x for x in pages if str(x.get("issue_key"))==key or str(x.get("url"))==key),{}))
            if parsed.path.startswith("/download/"):
                file=safe_report(output_root, parsed.path.removeprefix("/download/"))
                if not file: return self.send_json({"error":"not found"},404)
                raw=file.read_bytes(); self.send_response(200); self.send_header("Content-Type","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw); return
            if parsed.path.startswith("/screenshot/"):
                file=safe_screenshot("screenshots",parsed.path.removeprefix("/screenshot/"))
                if not file: return self.send_json({"error":"not found"},404)
                raw=file.read_bytes(); self.send_response(200); self.send_header("Content-Type","image/png"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw); return
            self.send_json({"error":"not found"},404)
        def do_POST(self):
            endpoint=urlparse(self.path).path
            if endpoint == "/api/stop": return self.send_json({"accepted":service.request_stop()})
            if endpoint == "/api/ai/clear": return self.send_json({"cleared":True})
            if endpoint == "/api/ai/chat":
                try: body=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}")
                except (ValueError,UnicodeDecodeError): return self.send_json({"error":"요청 형식이 올바르지 않습니다."},400)
                if set(body)-{"question","history","filters"} or not isinstance(body.get("question"),str): return self.send_json({"error":"질문 요청이 올바르지 않습니다."},400)
                try: return self.send_json(assistant.chat(body["question"],body.get("history"),body.get("filters")))
                except ValueError as exc: return self.send_json({"error":str(exc)},400)
                except Exception as exc: return self.send_json({"error":str(exc)},502)
            if endpoint != "/api/run": return self.send_json({"error":"not found"},404)
            try: body=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}")
            except (ValueError, UnicodeDecodeError): return self.send_json({"error":"invalid JSON"},400)
            allowed={"target","max_urls","force_resource","force_accessibility","force_screenshot"}
            if allow_fixture: allowed.add("fixture")
            bool_keys={"force_resource","force_accessibility","force_screenshot"}
            if set(body)-allowed or body.get("target","all") not in {"all","nihhs","fruit"} or not isinstance(body.get("max_urls",10),int) or not 1 <= body.get("max_urls",10) <= 10 or any(not isinstance(body.get(k,False),bool) for k in bool_keys): return self.send_json({"error":"invalid request"},400)
            try:
                kwargs=dict(mode="manual",target=body.get("target","all"),max_urls=body.get("max_urls",10),force_resource=body.get("force_resource",False),force_accessibility=body.get("force_accessibility",False),force_screenshot=body.get("force_screenshot",False),transport=(transport_factory() if transport_factory else build_transport({})))
                if allow_fixture and isinstance(body.get("fixture"),dict): kwargs["fixture"]=body["fixture"]
                result=service.start(**kwargs)
            except ExecutionLockedError as exc: return self.send_json({"error":str(exc)},409)
            self.send_json(result, 202)
        def _asset(self, name, content_type):
            raw=(WEB_ROOT/name).read_bytes(); self.send_response(200); self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    return Handler

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument("--port",type=int); parser.add_argument("--state-dir",default="state"); parser.add_argument("--output-root",default="output"); parser.add_argument("--config-dir",default="config"); args=parser.parse_args(argv)
    port=args.port or settings(args.config_dir)
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1",port)) == 0: print(f"Port {port} is already in use; change dashboard.port in config/rules.yaml"); return 1
    server=ThreadingHTTPServer(("127.0.0.1",port),make_handler(args.state_dir,args.output_root)); print(f"Dashboard: http://127.0.0.1:{port}")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
    return 0
if __name__ == "__main__": raise SystemExit(main())
