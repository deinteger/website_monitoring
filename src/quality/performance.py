"""Connection, timing, size, mixed-content, and soft-404 checks over existing results."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class PageHTTPObservation:
    request_url: str
    status_code: int | None = None
    final_url: str = ""
    redirect_chain: tuple[str, ...] = ()
    started_at: str = ""
    ended_at: str = ""
    total_seconds: float | None = None
    ttfb_seconds: float | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    html: str = ""
    retries: int = 0
    timed_out: bool = False
    failure_type: str | None = None
    failure_reason: str | None = None
    request_limit_exceeded: bool = False


@dataclass
class PerformanceResult:
    target_id: str
    url: str
    final_url: str
    status_code: int | None
    redirect_count: int
    redirect_chain: list[str]
    total_seconds: float | None
    ttfb_seconds: float | None
    retries: int
    content_length_header: int | None
    received_bytes: int
    decompressed_html_bytes: int | None
    content_encoding: str
    console_error_count: int | None
    console_status: str
    ssl_result: str
    mixed_content: list[dict[str, Any]]
    soft_404_candidate: bool
    verdict: str
    severity: str
    reason: str
    measurement_limit: str
    issue_key: str
    checked_at: str
    started_at: str = ""
    ended_at: str = ""
    ttfb_reason: str = ""
    failure_type: str | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _key(target_id: str, url: str, code: str) -> str:
    return hashlib.sha256(f"{target_id}|{url}|{code}".encode()).hexdigest()[:20]


def _status_verdict(status: int | None) -> tuple[str, str, str]:
    if status is None:
        return "점검 불가", "검토", "HTTP 응답 없음"
    if 200 <= status < 300:
        return "정상", "", f"HTTP {status}"
    if status in {301, 302, 307, 308}:
        return "검토 필요", "검토", f"HTTP {status} 리다이렉트"
    if status in {401, 403, 429}:
        return "점검 불가", "검토", f"HTTP {status} 자동 오류 확정 안 함"
    if status in {404, 410}:
        return "오류", "상", f"HTTP {status}"
    if 500 <= status < 600:
        return "오류", "상", f"HTTP {status}"
    return "검토 필요", "검토", f"HTTP {status}"


def _worse(current: tuple[str, str, str], candidate: tuple[str, str, str]) -> tuple[str, str, str]:
    rank = {"정상": 0, "검토 필요": 1, "점검 불가": 2, "오류": 3}
    return candidate if rank.get(candidate[0], 1) > rank.get(current[0], 1) else current


def check_page_performance(observation: PageHTTPObservation, *, target_id: str, html: str | None = None,
                          resources: Iterable[Any] = (), performance_rules: Mapping[str, Any] | None = None,
                          console_errors: int | None = None, console_status: str = "미실행",
                          max_redirect_hops: int = 3, checked_at: str | None = None) -> PerformanceResult:
    rules = performance_rules or {}
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    body_html = html if html is not None else observation.html
    headers = {str(key).lower(): str(value) for key, value in observation.headers.items()}
    content_length = int(headers["content-length"]) if headers.get("content-length", "").isdigit() else None
    received = len(observation.body)
    decompressed = len(body_html.encode("utf-8")) if body_html else None
    verdict = _status_verdict(observation.status_code)
    if observation.request_limit_exceeded:
        verdict = _worse(verdict, ("점검 불가", "검토", "실행 전체 요청 상한 초과"))
    elif observation.timed_out or observation.failure_type in {"timeout", "dns", "connection", "ssl"}:
        verdict = _worse(verdict, ("점검 불가", "검토", observation.failure_reason or observation.failure_type or "요청 실패"))
    if observation.failure_type == "ssl":
        ssl_result = "SSL 점검 불가"
    elif observation.failure_type:
        ssl_result = "SSL 오류 아님/확인 불가"
    else:
        ssl_result = "확인되지 않음"
    if len(observation.redirect_chain) > max_redirect_hops:
        verdict = _worse(verdict, ("점검 불가", "검토", "리다이렉트 횟수 상한 초과"))
    warning = float(rules.get("response_warning_seconds", 3.0))
    error = float(rules.get("response_error_seconds", 5.0))
    if observation.timed_out:
        pass
    elif observation.total_seconds is not None and observation.total_seconds >= error:
        verdict = _worse(verdict, ("검토 필요", "검토", f"응답시간 {observation.total_seconds:.3f}초"))
    elif observation.total_seconds is not None and observation.total_seconds >= warning:
        verdict = _worse(verdict, ("검토 필요", "검토", f"응답시간 {observation.total_seconds:.3f}초"))
    size_warning = float(rules.get("page_size_warning_mb", 3.0)) * 1024 * 1024
    size_error = float(rules.get("page_size_error_mb", 5.0)) * 1024 * 1024
    if received >= size_error:
        verdict = _worse(verdict, ("검토 필요", "검토", f"실제 수신 바이트 {received}"))
    elif received >= size_warning:
        verdict = _worse(verdict, ("검토 필요", "검토", f"실제 수신 바이트 {received}"))
    text = body_html or ""
    soft_keywords = tuple(str(value) for value in rules.get("soft_404_keywords", ("페이지를 찾을 수 없습니다", "존재하지 않습니다", "오류가 발생했습니다")))
    soft = bool(observation.status_code == 200 and any(keyword in text for keyword in soft_keywords) and (len(text.encode("utf-8")) < int(rules.get("soft_404_min_body_bytes", 512)) or any(keyword in text for keyword in soft_keywords)))
    if soft:
        verdict = _worse(verdict, ("검토 필요", "검토", "HTTP 200 Soft 404 후보"))
    mixed: list[dict[str, Any]] = []
    if rules.get("mixed_content", True) and urlparse(observation.request_url).scheme.lower() == "https":
        for resource in resources:
            if isinstance(resource, Mapping):
                kind = resource.get("reference", {}).get("kind", "")
                resource_url = resource.get("reference", {}).get("normalized_url")
            else:
                kind = getattr(resource, "kind", "")
                resource_url = getattr(resource, "normalized_url", None)
            if resource_url and urlparse(resource_url).scheme.lower() == "http" and kind not in {"link", "anchor"}:
                mixed.append({"kind": kind, "url": resource_url, "page_url": observation.request_url})
        if mixed:
            verdict = _worse(verdict, ("검토 필요", "검토", "혼합 콘텐츠 후보"))
    final_url = observation.final_url or observation.request_url
    return PerformanceResult(target_id, observation.request_url, final_url, observation.status_code, len(observation.redirect_chain), list(observation.redirect_chain), observation.total_seconds, observation.ttfb_seconds, observation.retries, content_length, received, decompressed, headers.get("content-encoding", ""), console_errors, console_status, ssl_result, mixed, soft, verdict[0], verdict[1] or "", verdict[2], "단일 로컬 측정; 공식 성능점수 아님; HTML 응답 용량 기준", _key(target_id, observation.request_url, "performance"), checked_at,
                             observation.started_at, observation.ended_at, "측정 불가" if observation.ttfb_seconds is None else "", observation.failure_type, observation.failure_reason)


def performance_state_payload(results: Iterable[PerformanceResult]) -> dict[str, Any]:
    values = list(results)
    return {"schema_version": "1.0", "issue_type": "performance", "results": [result.to_dict() for result in values],
            "counts": {verdict: sum(1 for result in values if result.verdict == verdict) for verdict in sorted({result.verdict for result in values})}}


def sitemap_status_payload(sources: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Reuse existing inventory sitemap source results; never performs a sitemap request."""
    sitemap = next((dict(source) for source in sources if source.get("source") == "sitemap"), None)
    if sitemap is None:
        return {"status": "점검 불가", "reason": "기존 sitemap 수집 결과 없음"}
    return {"status": "정상" if sitemap.get("success") else "점검 불가", "requested_urls": sitemap.get("requested_urls", []),
            "discovered_url_count": sitemap.get("discovered_url_count", 0), "failure_reason": sitemap.get("failure_reason")}
