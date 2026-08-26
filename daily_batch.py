"""Lock-protected daily batch entry point; suitable for Task Scheduler."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from src.common.execution_lock import ExecutionLock, ExecutionLockedError
from src.daily_pipeline import DailyPipeline
from src.common.env_loader import load_project_env

def main(argv=None):
    load_project_env()
    parser = argparse.ArgumentParser(description="Run the NIHHS daily pipeline")
    parser.add_argument("--offline-fixture", type=Path, help="local fixture used for offline validation")
    parser.add_argument("--state-dir", type=Path, default=Path("state"))
    parser.add_argument("--output-root", type=Path, default=Path("output"))
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    args = parser.parse_args(argv)
    if not args.offline_fixture:
        print("Operational transport is unavailable in this environment; use the dashboard or a normal PowerShell after TCP 443 is available.")
        return 1
    lock = ExecutionLock(args.state_dir)
    try:
        lock.acquire(run_id="batch", mode="scheduled")
        fixture=json.loads(args.offline_fixture.read_text(encoding="utf-8"))
        pipeline=DailyPipeline(state_dir=args.state_dir, output_root=args.output_root)
        result=pipeline.run_raw_fixture(fixture) if fixture.get("responses") else pipeline.run_offline(fixture)
        result.setdefault("exit_code", 0 if result.get("status") == "completed" else 2)
        args.log_dir.mkdir(parents=True, exist_ok=True)
        with (args.log_dir / "daily_batch.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"recorded_at":datetime.now(timezone.utc).isoformat(),"mode":"scheduled",**result},ensure_ascii=False,default=str)+"\n")
        print(result.get("report_path", result.get("failure_reason", "failed")))
        return int(result.get("exit_code", 1))
    except ExecutionLockedError as exc:
        print(exc); return 1
    finally:
        lock.release()

if __name__ == "__main__": raise SystemExit(main())
