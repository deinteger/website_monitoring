"""Offline-capable daily orchestration boundary.

Network collection remains injectable; the offline runner consumes fixture payloads
and exercises state, aggregation/coverage, report and history integration.
"""
from __future__ import annotations
from datetime import datetime, timezone, date as date_type
from pathlib import Path
import json
from src.common.state_manager import StateManager
from src.reports.page_report import PageReportGenerator
from src.inventory.collector import InventoryCollector, FetchResponse
from src.inventory.url_normalizer import merge_occurrences, policy_from_config
from src.inventory.comparator import compare_inventory
from src.inventory.collector import RequestLimitError
from src.freshness.checker import check_content_freshness, freshness_state_payload
from src.freshness.list_checker import check_list_freshness, list_freshness_state_payload
from src.resources.checker import extract_resources, resource_state_payload, ResourceChecker, ResourceResponse
from src.resources.cache import AttachmentCache
from src.quality.accessibility import check_page as check_accessibility, accessibility_state_payload, build_content_hash
from src.quality.performance import PageHTTPObservation, check_page_performance
from src.quality.aggregation import aggregate_page, reconcile_issues, site_stats
from src.quality.coverage import build_coverage, failure_detail
from src.quality.aggregation import issue_key
from src.common.config_loader import Target

class DailyPipeline:
    def __init__(self, *, state_dir="state", output_root="output", report_generator=None):
        self.state = StateManager(state_dir); self.report = report_generator or PageReportGenerator(output_root); self.last_metrics = {}

    def _stage(self, name, *, input_count=0, processed_count=0, failure=None):
        """Create a JSON-safe execution record; errors never include raw payloads."""
        started = datetime.now(timezone.utc).isoformat()
        code, reason = (failure or (None, ""))
        return {"stage": name, "status": "failed" if failure else "completed",
                "started_at": started, "ended_at": datetime.now(timezone.utc).isoformat(),
                "input_count": input_count, "processed_count": processed_count,
                "failure_count": 1 if failure else 0, "failure_code": code,
                "failure_reason": str(reason or "")[:500]}

    def _run_payload(self, payload, *, run_id=None, date=None, transport_name="fixture"):
        """Common finalization used by fixture and operational transports.

        A failed check stage is a partial result: it must not advance the inventory
        baseline or resolve an issue that was absent only because that stage failed.
        """
        self.last_execution_trace = getattr(self, "last_execution_trace", []) + ["validate_payload"]
        if not isinstance(payload, dict):
            return {"run_id": run_id, "status": "failed", "exit_code": 1,
                    "failure_reason": "configuration payload must be a mapping"}
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        started = datetime.now(timezone.utc).isoformat()
        payload = dict(payload)
        failures = payload.get("stage_failures", {}) or {}
        if not isinstance(failures, dict):
            return {"run_id": run_id, "status": "failed", "exit_code": 1,
                    "failure_reason": "stage_failures must be a mapping"}
        pages = list(payload.get("page_results") or [])
        stages = []
        for name, count in (("inventory", len((payload.get("inventory") or {}))),
                            ("checks", len(pages)), ("aggregation", len(pages))):
            value = failures.get(name)
            failure = (str(value.get("code", name + "_failed")), value.get("reason", "stage failed")) if isinstance(value, dict) else ((name + "_failed", str(value)) if value else None)
            stages.append(self._stage(name, input_count=count, processed_count=0 if failure else count, failure=failure))
        partial = any(x["status"] == "failed" for x in stages)
        metadata = {**(payload.get("run_metadata") or {}), "run_id": run_id, "started_at": started,
                    "mode": "daily", "transport": transport_name, "offline": transport_name == "fixture",
                    "execution_stages": stages}
        payload["run_metadata"] = metadata
        try:
            self.last_execution_trace.append("report.save")
            report_path = self.report.save(payload, date=date, run_metadata=metadata)
        except (OSError, ValueError) as exc:
            return {"run_id": run_id, "status": "failed", "exit_code": 1,
                    "failure_reason": f"report save failed: {exc}"}
        try:
            self.last_execution_trace.append("state.save")
            self.state.save_json("inventory.json", {**(payload.get("inventory") or {}), "run_metadata": metadata})
            if not partial:
                self.state.save_json("issues.json", {"run_id": run_id, "page_results": pages,
                    "coverage_summary": payload.get("coverage_summary", {}), "run_metadata": metadata})
                if payload.get("inventory_baseline") is not None:
                    self.state.save_json("inventory_baseline.json", payload["inventory_baseline"])
            else:
                # Keep the last lifecycle decision intact; annotate it without resolving anything.
                prior = self.state.load_json("issues.json", {})
                prior = dict(prior) if isinstance(prior, dict) else {}
                prior["last_partial_run"] = {"run_id": run_id, "execution_stages": stages}
                prior["run_metadata"] = metadata
                self.state.save_json("issues.json", prior)
        except (OSError, ValueError) as exc:
            return {"run_id": run_id, "status": "failed", "exit_code": 1,
                    "report_path": str(report_path), "failure_reason": f"state save failed: {exc}"}
        finished = datetime.now(timezone.utc).isoformat(); exit_code = 2 if partial else 0
        history = {"run_id": run_id, "mode": "daily", "transport": transport_name,
                   "offline": transport_name == "fixture", "started_at": started, "ended_at": finished,
                   "total_discovered_urls": len(pages), "report_path": str(report_path),
                   "external_requests": 0, "browser_runs": 0,
                   "status": "partial_failed" if partial else "completed", "exit_code": exit_code,
                   "execution_stages": stages}
        try:
            self.last_execution_trace.append("history.append")
            self.state.append_run_history(history)
        except OSError as exc:
            return {"run_id": run_id, "status": "failed", "exit_code": 1,
                    "report_path": str(report_path), "failure_reason": f"history save failed: {exc}"}
        return {"run_id": run_id, "status": history["status"], "exit_code": exit_code,
                "report_path": str(report_path), "history": history, "execution_stages": stages}

    def run_with_transport(self, transport, *, run_id=None, date=None, transport_name="operational"):
        """Run a transport adapter through the same payload finalization sequence.

        Adapters only need ``build_payload()``.  Production adapters may perform
        requests themselves; tests use in-memory adapters exclusively.
        """
        try:
            self.last_execution_trace = ["transport.build_payload"]
            payload = transport.build_payload()
        except (OSError, ValueError) as exc:
            return {"run_id": run_id, "status": "failed", "exit_code": 1,
                    "failure_reason": f"transport failed: {exc}"}
        return self._run_payload(payload, run_id=run_id, date=date, transport_name=transport_name)

    def run_offline(self, fixture, *, run_id=None, date=None):
        class FixtureTransport:
            def build_payload(self_nonlocal): return fixture
        return self.run_with_transport(FixtureTransport(), run_id=run_id, date=date, transport_name="fixture")

    def run_raw_fixture(self, fixture, *, target_id="fixture", base_url="https://fixture.test", run_id=None, date=None):
        """Run the same discovery/check modules using fixture transport responses."""
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        responses = fixture.get("responses", {})
        class FixtureFetcher:
            request_count = 0
            def fetch(self, url):
                self.request_count += 1; value = responses.get(url, responses.get(url.rstrip("/"), {}))
                return FetchResponse(url, int(value.get("status_code", 200)), value.get("html", value.get("text", "")), float(value.get("elapsed_seconds", 0)), value.get("headers", {}))
        fetcher = FixtureFetcher(); raw_target = Target(target_id, target_id, base_url, fixture.get("menu", {"main_selectors":["a"], "all_menu_selectors":["a"], "all_menu_paths":[], "sitemap_path":"/sitemap.xml"}), tuple(), {}, {})
        attachment_cache = AttachmentCache.from_state(self.state, recheck_days=30)
        class ResourceFixtureClient:
            def __init__(self): self.calls=[]; self.signature_checks=0; self.download_bytes=0
            def request(self, method, url, *, headers=None):
                self.calls.append((method,url,dict(headers or {}))); v=responses.get(url,{}); body=v.get("body", b"")
                if isinstance(body,str): body=body.encode()
                if method == "HEAD": body = b""
                if method != "HEAD":
                    self.download_bytes += len(body)
                    if body.startswith(b"%PDF-"): self.signature_checks += 1
                return ResourceResponse(int(v.get("status_code",200)), v.get("headers",{}), body, url, (), None)
        resource_client=ResourceFixtureClient(); resource_checker=ResourceChecker(resource_client,target_base_url=base_url,attachment_cache=attachment_cache)
        inventory = InventoryCollector(raw_target, fetcher, max_requests=int(fixture.get("max_requests", 10))).collect()
        normalized = merge_occurrences(inventory.records, target_id=target_id, base_url=base_url, policy=policy_from_config({}))
        current = {"raw":inventory.to_dict(), "normalized":normalized.to_dict()}; previous = self.state.load_json("inventory_baseline.json", {}).get(target_id)
        comparison = compare_inventory(previous, current, target_id=target_id, max_requests=int(fixture.get("max_requests", 10)))
        html_results=[]; accessibility=[]; performance=[]; resources=[]; freshness=[]; lists=[]; issues=[]; checks=[]
        old_hashes = self.state.load_json("content_hashes.json", {}) or {}; hash_cache = {}; accessibility_runs = 0; attachment_reuses = 0; attachment_downloads = 0
        reference_date = date_type.fromisoformat(date) if date else date_type.today()
        for rec in normalized.records:
            original = next(iter(rec.original_urls), rec.normalized_url)
            response = responses.get(rec.normalized_url, responses.get(original, {})); html=response.get("html", response.get("text", "")); url=rec.normalized_url
            fresh=check_content_freshness(html, target_id=target_id, url=url, reference_date=reference_date); freshness.append(fresh.to_dict())
            references=extract_resources(html, page_url=url, target_base_url=base_url)
            for ref in references:
                if ref.kind == "attachment" and ref.normalized_url:
                    import os
                    attachment_cache.relations(ref.normalized_url, url, original_url=ref.original_url, filename=os.path.basename(ref.normalized_url), link_text=ref.text)
            cached_attachment_refs = [r for r in references if r.kind == "attachment" and (attachment_cache.get(r.normalized_url or "") or {}).get("next_recheck_date", "") > reference_date.isoformat()]
            if cached_attachment_refs and len(cached_attachment_refs) == len([r for r in references if r.kind == "attachment"]):
                res = []
                attachment_reuses += len(cached_attachment_refs)
            else:
                res=resource_checker.check_html(html,page_url=url,content_hash=build_content_hash(html),today=reference_date)
            resources.extend(x.to_dict() for x in res)
            menu_path = next(iter(rec.menu_paths), "")
            content_hash = build_content_hash(html); cached_hash = old_hashes.get(url, {}).get("content_hash") if isinstance(old_hashes.get(url), dict) else None
            if cached_hash == content_hash:
                acc = check_accessibility(html, target_id=target_id, url=url, menu_path=menu_path, cache=None)
                acc.cache_used = True
                accessibility_runs += 0
            else:
                acc=check_accessibility(html, target_id=target_id, url=url, menu_path=menu_path); accessibility_runs += 1
            accessibility.extend(x.to_dict() for x in acc.issues)
            for resource in res:
                rdict = resource.to_dict(); rurl = rdict.get("reference", {}).get("url", rdict.get("url", ""))
                if rdict.get("reference", {}).get("kind") == "attachment" or str(rurl).lower().endswith((".pdf", ".zip", ".hwpx", ".hwp")):
                    if attachment_cache.get(rurl) and attachment_cache.get(rurl).get("next_recheck_date", "") > reference_date.isoformat(): attachment_reuses += 1; rdict["cache_used"] = True; rdict["cache_reason"] = "정상 캐시 30일 이내 재사용"
                    else: attachment_downloads += 1
            obs=PageHTTPObservation(request_url=url, status_code=int(response.get("status_code",200)), final_url=response.get("final_url",url), html=html, body=html.encode(), total_seconds=float(response.get("elapsed_seconds",0)), headers=response.get("headers",{}))
            perf=check_page_performance(obs, target_id=target_id, html=html); performance.append(perf.to_dict())
            if int(response.get("status_code", 200)) in (404, 410):
                code="connectivity"; reason=f"HTTP {response.get('status_code')}"; subject=url
                issues.append({"issue_key":issue_key(target_id,url,code,subject,"http_status"),"target_id":target_id,"page_url":url,"target_url":url,"check_code":code,"problem_type":"http_status","result":"오류","severity":"상","reason":reason,"evidence":reason,"fingerprint":f"{response.get('status_code')}"})
            for ref in res:
                rd=ref.to_dict(); reference=rd.get("reference", {}); rurl=reference.get("normalized_url") or reference.get("original_url", "")
                if reference.get("kind") == "image" and reference.get("alt") in (None, ""):
                    code="image-alt"; issues.append({"issue_key":issue_key(target_id,url,code,rurl,"alt_missing"),"target_id":target_id,"page_url":url,"target_url":rurl,"check_code":code,"problem_type":"alt_missing","result":"오류","severity":"중","reason":"이미지 대체텍스트 누락","evidence":rurl,"fingerprint":"alt-missing"})
            checks.append({"code":"content_basic","result":fresh.verdict,"required":True}); checks.append({"code":"accessibility","result":"오류" if acc.issues else "정상","required":True}); checks.append({"code":"connectivity","result":perf.verdict,"required":True})
            page=aggregate_page(target_id,url,checks[-3:],menu_path=menu_path,inventory_change_status="")
            html_results.append(page.to_dict())
            for item in acc.issues: issues.append({"issue_key":item.issue_key,"target_id":target_id,"page_url":url,"check_code":item.code,"result":item.result,"evidence":item.evidence})
        lifecycle=reconcile_issues(self.state.load_json("issues.json",{}), issues, run_id=run_id, execution_healthy=not any(x.failure_reason for x in inventory.sources))
        coverage=build_coverage([{"normalized_url":x.normalized_url,"classification":"internal"} for x in normalized.records], [x.__dict__ for x in inventory.sources], [{"status":"정상","required":True} for _ in checks])
        lifecycle_rows = [dict(x) for bucket in ("active_issues", "resolved_issues") for x in lifecycle.get(bucket, [])]
        payload={"page_results":html_results,"freshness_results":freshness,"resource_results":resources,"accessibility_issues":accessibility,"performance_results":performance,"coverage_records":coverage.get("missing_scope",[]) + lifecycle_rows,"site_stats":site_stats(html_results),"missing_scope":coverage.get("missing_scope",[]),"run_metadata":{"run_id":run_id}}
        result=self.report.save(payload,date=date); self.state.save_json("inventory.json",{target_id:current});
        if comparison.baseline_updated: self.state.save_json("inventory_baseline.json",{target_id:current})
        for x in html_results:
            u=x.get("url", ""); hash_cache[u] = {"content_hash":build_content_hash(responses.get(u,{}).get("html", "")), "last_checked_at":datetime.now(timezone.utc).isoformat(), "cache_used": bool(old_hashes.get(u))}
        attachment_cache.save_state(self.state); self.state.save_json("issues.json",lifecycle); self.state.save_json("content_hashes.json",hash_cache)
        self.last_metrics = {"accessibility_runs": accessibility_runs, "attachment_reuses": attachment_reuses, "attachment_downloads": attachment_downloads, "cache_hash_reuses": sum(1 for x in hash_cache.values() if x.get("cache_used")), "resource_calls":resource_client.calls, "signature_checks":resource_client.signature_checks, "download_bytes":resource_client.download_bytes}
        self.state.append_run_history({"run_id":run_id,"mode":"daily","status":"completed","external_requests":0,"request_count":fetcher.request_count})
        return {"run_id":run_id,"status":"completed","report_path":str(result),"inventory":inventory,"comparison":comparison,"lifecycle":lifecycle}

def run_offline_fixture(fixture_path, *, state_dir="state", output_root="output", run_id=None, date=None):
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    return DailyPipeline(state_dir=state_dir, output_root=output_root).run_offline(fixture, run_id=run_id, date=date)
