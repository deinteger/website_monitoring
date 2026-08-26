"""Shared asynchronous execution controller for scheduled and manual daily runs."""
from __future__ import annotations
from datetime import datetime, timezone
import threading
from src.common.execution_lock import ExecutionLock, ExecutionLockedError
from src.daily_pipeline import DailyPipeline

class DailyRunService:
    def __init__(self, state_dir="state", output_root="output"):
        self.state_dir, self.output_root = state_dir, output_root
        self._guard=threading.RLock(); self._thread=None; self._cancel=False
        self.status={"status":"idle","stage":"idle","processed_count":0,"failure_count":0,"progress":0}

    def snapshot(self):
        with self._guard: return dict(self.status)

    def start_fixture(self, fixture, *, mode="manual", target="all", max_urls=10, force_resource=False, force_accessibility=False, force_screenshot=False):
        with self._guard:
            if self._thread and self._thread.is_alive(): raise ExecutionLockedError("daily execution is already active")
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self._cancel=False; self.status={"run_id":run_id,"mode":mode,"target":target,"max_urls":max_urls,"force_resource":force_resource,"force_accessibility":force_accessibility,"force_screenshot":force_screenshot,"status":"running","stage":"queued","started_at":datetime.now(timezone.utc).isoformat(),"processed_count":0,"failure_count":0,"progress":0,"stop_requested":False}
            self._thread=threading.Thread(target=self._run,args=(fixture,run_id,mode),daemon=True); self._thread.start()
            return self.snapshot()

    def request_stop(self):
        with self._guard:
            if self.status.get("status") != "running": return False
            self._cancel=True; self.status["stop_requested"]=True; self.status["stage"]="stop_requested"; return True

    def _run(self, fixture, run_id, mode):
        lock=ExecutionLock(self.state_dir)
        try:
            lock.acquire(run_id=run_id,mode=mode)
            with self._guard:
                if self._cancel: self.status.update(status="cancelled",stage="cancelled",progress=100); return
                self.status.update(stage="pipeline",progress=10)
            pipeline=DailyPipeline(state_dir=self.state_dir,output_root=self.output_root)
            result=pipeline.run_raw_fixture(fixture,run_id=run_id) if fixture.get("responses") else pipeline.run_offline(fixture,run_id=run_id)
            result.setdefault("exit_code", 0 if result.get("status") == "completed" else 2)
            public={k:v for k,v in result.items() if k in {"run_id","status","exit_code","report_path","execution_stages"}}
            with self._guard: self.status.update(public,status="completed" if result.get("exit_code")==0 else "partial_failed",stage="finished",progress=100,ended_at=datetime.now(timezone.utc).isoformat(),processed_count=len(fixture.get("page_results",[])))
        except ExecutionLockedError as exc:
            with self._guard: self.status.update(status="blocked",stage="lock",failure_count=1,failure_reason=str(exc),progress=100)
        finally: lock.release()
