"""Coverage, failure and screenshot evidence records; no network/browser calls."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib, re

def _count(items, key, values):
    return {v: sum(1 for x in items if x.get(key) == v) for v in values}

def build_coverage(url_records=(), source_records=(), check_records=(), request_limit_reached=False):
    urls = list(url_records); sources = list(source_records); checks = list(check_records)
    types = ("정상", "부분점검", "실패", "점검 불가", "제외")
    summary = {"discovered_urls": len(urls), "normalized_urls": sum(1 for x in urls if x.get("normalized_url")),
               "duplicates_removed": sum(1 for x in urls if x.get("duplicate")),
               "internal_urls": sum(1 for x in urls if x.get("classification") == "internal"),
               "external_urls": sum(1 for x in urls if x.get("classification") == "external"),
               "invalid_urls": sum(1 for x in urls if x.get("classification") == "invalid"),
               "non_http_urls": sum(1 for x in urls if x.get("classification") == "non_http"),
               "excluded_urls": sum(1 for x in urls if x.get("excluded")),
               "check_targets": len(checks), "request_limit_reached": bool(request_limit_reached)}
    summary["check_status_counts"] = _count(checks, "status", types)
    required = [x for x in checks if x.get("required", True)]
    done = [x for x in required if x.get("status") not in (None, "미실행", "제외")]
    summary["required_check_completion"] = round(len(done) / len(required), 3) if required else 1.0
    return {"coverage_summary": summary,
            "source_coverage": {"records": sources, "counts": _count(sources, "status", ("성공", "부분성공", "실패"))},
            "check_coverage": {"records": checks},
            "missing_scope": missing_scope(urls, sources, checks, request_limit_reached)}

def missing_scope(urls=(), sources=(), checks=(), request_limit_reached=False):
    out = []
    for x in urls:
        if x.get("status") in ("미실행", "점검 불가") or x.get("uninspected"):
            out.append({"type": "페이지 미점검", "url": x.get("url"), "reason": x.get("reason", "점검이 수행되지 않음")})
    if request_limit_reached: out.append({"type": "요청 상한", "reason": "요청 상한으로 범위가 축소됨"})
    for x in sources:
        if x.get("status") in ("부분성공", "실패"):
            out.append({"type": "수집원 실패", "source": x.get("source"), "reason": x.get("reason", "수집 실패")})
    return out

def failure_detail(target_id, page_url, stage, failure_type, message, **kwargs):
    # Deliberately omit raw exception/HTML/API keys from user payload.
    safe = re.sub(r"(?i)(api[_ -]?key|token|authorization)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", str(message))
    return {"target_id": target_id, "page_url": page_url, "menu_path": kwargs.get("menu_path", ""),
            "source": kwargs.get("source", ""), "stage": stage, "failure_type": failure_type,
            "http_status": kwargs.get("http_status"), "exception_class": kwargs.get("exception_class", ""),
            "message": safe[:500], "retry_count": kwargs.get("retry_count", 0),
            "last_attempt_at": kwargs.get("last_attempt_at", ""), "retryable": bool(kwargs.get("retryable", False)),
            "request_limit_reached": bool(kwargs.get("request_limit_reached", False)),
            "run_id": kwargs.get("run_id", ""), "screenshot_path": kwargs.get("screenshot_path", ""),
            "checked_at": kwargs.get("checked_at", datetime.now(timezone.utc).isoformat())}

def screenshot_decision(issue, force=False, policy=None, cache=None, content_hash="", now=None):
    policy = policy or {}; cache = cache or {}; now = now or datetime.now(timezone.utc).isoformat()
    status = issue.get("lifecycle_status", "")
    capture_states = set(policy.get("capture_states", ["신규", "재발", "변경", "수동확인 필요"]))
    key = issue.get("issue_key", hashlib.sha256(issue.get("page_url", "").encode()).hexdigest())
    old = cache.get(key)
    reuse = bool(old and not force and status == "지속" and old.get("content_hash") == content_hash and old.get("evidence") == issue.get("evidence") and old.get("policy_version") == policy.get("policy_version"))
    should = force or status in capture_states or (status == "지속" and not reuse)
    return {"should_capture": should, "reuse": reuse, "reason": "강제 캡처" if force else ("기존 증거 재사용" if reuse else status),
            "path": str(Path("screenshots") / datetime.fromisoformat(now.replace("Z", "+00:00")).strftime("%Y-%m-%d") / str(issue.get("target_id", "target")) / f"{key}.png"),
            "metadata": {"page_url": issue.get("page_url", ""), "issue_key": key, "capture_reason": status,
                         "captured_at": now, "viewport": policy.get("viewport", [1280, 900]), "full_page": bool(policy.get("full_page", True)),
                         "content_hash": content_hash, "related_issues": issue.get("related_issues", []), "reused": reuse, "failure_reason": ""}}

def coverage_state_payload(coverage, failures=(), screenshots=(), run_metadata=None):
    return {**coverage, "failure_details": list(failures), "screenshot_evidence": list(screenshots), "run_metadata": run_metadata or {}}
