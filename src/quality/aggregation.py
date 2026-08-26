"""Page verdict aggregation and issue lifecycle management."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib, json

VERDICTS = ("정상", "검토 필요", "오류", "점검 불가", "제외")

def issue_key(target_id, page_url, check_code, subject="", problem_type=""):
    raw = "|".join(map(str, (target_id, page_url, check_code, subject, problem_type)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

@dataclass
class PageCompositeResult:
    target_id: str; url: str; verdict: str; menu_path: str = ""; checked_at: str = ""
    inventory_change_status: str = ""; required_count: int = 0; performed_required_count: int = 0
    completeness_ratio: float = 0.0; issue_count: int = 0; manual_review_required: bool = False
    representative_issue: dict | None = None; checks: list | None = None
    def to_dict(self): return asdict(self)

def aggregate_page(target_id, url, checks=None, menu_path="", inventory_change_status="", excluded=False, checked_at=None):
    items = list(checks or [])
    if isinstance(checks, dict):
        items = [dict(v, code=k) if isinstance(v, dict) else {"code": k, "result": str(v)} for k,v in checks.items()]
    if excluded:
        return PageCompositeResult(target_id, url, "제외", menu_path, checked_at or "", inventory_change_status, checks=items)
    required = [x for x in items if x.get("required", True)]
    done = [x for x in required if x.get("result") not in (None, "미실행", "제외")]
    errors = [x for x in items if x.get("result") == "오류" or x.get("severity") == "상"]
    unavailable = [x for x in required if x.get("result") == "점검 불가"]
    reviews = [x for x in items if x.get("result") in ("검토 필요", "수동확인 필요") or x.get("manual_review_required")]
    if errors: verdict = "오류"
    elif unavailable: verdict = "점검 불가"
    elif reviews: verdict = "검토 필요"
    else: verdict = "정상"
    rank = {"오류":0, "점검 불가":1, "검토 필요":2, "정상":3}
    rep = sorted((x for x in items if x.get("result") not in ("정상", "미실행", "제외")), key=lambda x:(rank.get(x.get("result"), 9), x.get("code", ""), x.get("location", "")))
    return PageCompositeResult(target_id, url, verdict, menu_path, checked_at or "", inventory_change_status,
        len(required), len(done), round(len(done)/len(required), 3) if required else 1.0,
        len(rep), bool(reviews), rep[0] if rep else None, items)

def reconcile_issues(previous, current_issues, run_id="", now=None, execution_healthy=True, history_max_entries=50):
    now = now or datetime.now(timezone.utc).isoformat()
    previous = previous or {}
    old = {}
    for bucket in ("active_issues", "resolved_issues", "manual_issues", "issues"):
        for item in previous.get(bucket, []) or []:
            if item.get("issue_key"): old[item["issue_key"]] = item
    current = {x["issue_key"]: dict(x) for x in (current_issues or []) if x.get("issue_key")}
    active, resolved, manual = [], list(previous.get("resolved_issues", []) or []), []
    for key, item in current.items():
        prior = old.get(key); out = dict(prior or {}); out.update(item)
        if prior and prior.get("lifecycle_status") == "해결":
            out["lifecycle_status"] = "재발"
            out["discovery_count"] = prior.get("discovery_count", 1) + 1
        elif prior:
            changed = any(prior.get(k) != item.get(k) for k in ("severity", "evidence", "result", "reason"))
            out["lifecycle_status"] = prior.get("manual_status") or ("변경" if changed else "지속")
            out["discovery_count"] = prior.get("discovery_count", 1) + 1
        else:
            out["lifecycle_status"] = "재발" if any(x.get("issue_key") == key for x in resolved) else "신규"
            out["discovery_count"] = 1
        out["first_seen"] = out.get("first_seen", now); out["last_seen"] = now; out["run_id"] = run_id
        out["first_discovered_at"] = out.get("first_discovered_at", out["first_seen"])
        out["last_discovered_at"] = now
        out["previous_fingerprint"] = prior.get("fingerprint") if prior else None
        out["fingerprint"] = item.get("fingerprint") or hashlib.sha256(json.dumps({k:item.get(k) for k in ("result","reason","evidence","severity")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        out["changed_fields"] = sorted(set((prior or {}).get("changed_fields", [])) | {k for k in ("result", "reason", "evidence", "severity") if prior and prior.get(k) != item.get(k)})
        out["recurred_count"] = prior.get("recurred_count", 0) + (1 if out["lifecycle_status"] == "재발" else 0) if prior else 0
        out["lifecycle_history"] = list((prior or {}).get("lifecycle_history", [])) + [{"status": out["lifecycle_status"], "at": now}]
        if out.get("manual_status") in ("예외", "오탐"): manual.append(out)
        else: active.append(out)
    seen = set(current)
    for key, prior in old.items():
        if key in seen or prior.get("manual_status") in ("예외", "오탐"): continue
        if execution_healthy and prior.get("lifecycle_status") not in ("해결",):
            item = dict(prior); item["lifecycle_status"] = "해결"; item["resolved_at"] = now; item["last_resolved_at"] = now; item["lifecycle_history"] = list(item.get("lifecycle_history", [])) + [{"status":"해결", "at":now}]; resolved.append(item)
        else:
            item = dict(prior); item["resolution_blocked_reason"] = "부분실패 또는 필수 점검 미실행"; active.append(item)
    active_keys = {x.get("issue_key") for x in active}
    resolved = [x for x in resolved if x.get("issue_key") not in active_keys]
    for item in active + resolved + manual:
        hist = list(item.get("history", [])); hist.append({"status": item.get("lifecycle_status"), "at": now}); item["history"] = hist[-history_max_entries:]
    return {"schema_version":"1.0", "active_issues":active, "resolved_issues":resolved[-history_max_entries:], "manual_issues":manual, "run_metadata":{"run_id":run_id, "checked_at":now}}

def site_stats(page_results):
    counts = {v: 0 for v in VERDICTS}
    for p in page_results: counts[p.get("verdict", "점검 불가")] = counts.get(p.get("verdict"), 0) + 1
    return {"pages_total": len(page_results), "verdict_counts": counts}

def composite_state_payload(page_results, lifecycle_state=None, run_metadata=None):
    return {"schema_version":"1.0", "page_results":page_results, "site_stats":site_stats(page_results), **(lifecycle_state or {}), "run_metadata":run_metadata or {}}
