"""Shared asynchronous execution controller for scheduled and manual daily runs."""
from __future__ import annotations
from datetime import datetime, timezone
import threading
from src.common.execution_lock import ExecutionLock, ExecutionLockedError
from src.daily_pipeline import DailyPipeline
from src.common.config_loader import load_config
from src.inventory.collector import InventoryCollector, RequestFetcher

class OperationalPayload:
    """Small production adapter feeding the shared pipeline finalization path."""
    def __init__(self, transport, target="all", max_urls=10): self.transport=transport; self.target=target; self.max_urls=max_urls
    def build_payload(self):
        config=load_config("config"); targets=list(config.targets) if self.target=="all" else [self.target]
        pages=[]
        for identifier in targets:
            target=config.targets[identifier]; response=self.transport.fetch(target.base_url)
            pages.append({"target_id":identifier,"url":target.base_url,"title":target.name,
                          "verdict":"정상" if response.status_code < 400 else "점검 불가",
                          "status_code":response.status_code,"response_time":response.elapsed_seconds,
                          "checked_at":datetime.now(timezone.utc).isoformat(),
                          "transport":response.actual_transport,"connection_result":response.connection_result})
        return {"page_results":pages,"coverage_summary":{},"run_metadata":{"target":self.target,"max_urls":self.max_urls}}
    def run_full(self, pipeline, run_id):
        config=load_config("config"); targets=list(config.targets) if self.target=="all" else [self.target]; responses={}
        for identifier in targets:
            target=config.targets[identifier]
            fetcher=RequestFetcher(user_agent=config.crawl.user_agent,timeout=config.crawl.timeout_seconds,max_retries=config.crawl.max_retries,interval=config.crawl.request_interval_seconds,max_requests=self.max_urls,transport=self.transport)
            inventory=InventoryCollector(target,fetcher,max_requests=self.max_urls,include_root=True,crawl_internal=True).collect()
            for record in inventory.records[:self.max_urls]:
                # InventoryCollector returns DiscoveryOccurrence objects.  Keep
                # the discovered URL (including links found while crawling),
                # rather than silently falling back to the homepage.
                url=getattr(record,"url",None) or target.base_url
                response=self.transport.fetch(url); responses[url]={"status_code":response.status_code,"html":response.text,"elapsed_seconds":response.elapsed_seconds,"headers":response.headers}
        return pipeline.run_raw_fixture({"responses":responses,"max_requests":self.max_urls,"include_root":True,"crawl_internal":True},target_id=targets[0],base_url=config.targets[targets[0]].base_url,run_id=run_id)

class DailyRunService:
    def __init__(self, state_dir="state", output_root="output"):
        self.state_dir, self.output_root = state_dir, output_root
        self._guard=threading.RLock(); self._thread=None; self._cancel=False
        self.status={"status":"idle","stage":"idle","processed_count":0,"failure_count":0,"progress":0}

    def snapshot(self):
        with self._guard: return dict(self.status)

    def start(self, *, mode="manual", target="all", max_urls=10, force_resource=False, force_accessibility=False, force_screenshot=False, transport=None, fixture=None):
        with self._guard:
            if self._thread and self._thread.is_alive(): raise ExecutionLockedError("daily execution is already active")
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self._cancel=False; self.status={"run_id":run_id,"mode":mode,"target":target,"max_urls":max_urls,"force_resource":force_resource,"force_accessibility":force_accessibility,"force_screenshot":force_screenshot,"status":"running","stage":"queued","started_at":datetime.now(timezone.utc).isoformat(),"processed_count":0,"failure_count":0,"progress":0,"stop_requested":False}
            self._thread=threading.Thread(target=self._run,args=(fixture,transport,run_id,mode),daemon=True); self._thread.start()
            return self.snapshot()

    def start_fixture(self, fixture, **options):
        return self.start(fixture=fixture, **options)

    def request_stop(self):
        with self._guard:
            if self.status.get("status") != "running": return False
            self._cancel=True; self.status["stop_requested"]=True; self.status["stage"]="stop_requested"; self.status["status"]="stop_requested"; self.status["ended_at"]=datetime.now(timezone.utc).isoformat(); return True

    def _run(self, fixture, transport, run_id, mode):
        lock=ExecutionLock(self.state_dir)
        try:
            lock.acquire(run_id=run_id,mode=mode)
            with self._guard:
                if self._cancel: self.status.update(status="cancelled",stage="cancelled",progress=100); return
                self.status.update(stage="pipeline",progress=10)
            pipeline=DailyPipeline(state_dir=self.state_dir,output_root=self.output_root)
            if self._cancel:
                with self._guard: self.status.update(status="cancelled",stage="cancelled",progress=100,ended_at=datetime.now(timezone.utc).isoformat())
                return
            if fixture is not None:
                result=pipeline.run_raw_fixture(fixture,run_id=run_id) if fixture.get("responses") else pipeline.run_offline(fixture,run_id=run_id)
            else:
                adapter=OperationalPayload(transport,self.status.get("target","all"),self.status.get("max_urls",10))
                result=adapter.run_full(pipeline,run_id) if fixture is None else pipeline.run_with_transport(adapter,run_id=run_id,transport_name=getattr(transport,"name","auto"))
            result.setdefault("exit_code", 0 if result.get("status") == "completed" else 2)
            public={k:v for k,v in result.items() if k in {"run_id","status","exit_code","report_path","execution_stages"}}
            with self._guard:
                if self._cancel:
                    self.status.update(status="cancelled",stage="cancelled",progress=100,ended_at=datetime.now(timezone.utc).isoformat())
                else:
                    self.status.update(public,status="completed" if result.get("exit_code")==0 else "partial_failed",stage="finished",progress=100,ended_at=datetime.now(timezone.utc).isoformat(),processed_count=len((fixture or {}).get("page_results",[])))
        except ExecutionLockedError as exc:
            with self._guard: self.status.update(status="blocked",stage="lock",failure_count=1,failure_reason=str(exc),progress=100)
        except Exception:
            # Never leave the dashboard in an indefinite 10%/pipeline state.
            with self._guard:
                self.status.update(status="failed",stage="failed",failure_count=1,
                                   failure_reason="점검 실행 중 내부 오류가 발생했습니다.",progress=100,
                                   ended_at=datetime.now(timezone.utc).isoformat())
        finally: lock.release()
