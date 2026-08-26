"""Safe, bounded resource extraction and checking with shared execution caching."""

from __future__ import annotations

import hashlib
import ipaddress
import mimetypes
import os
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.inventory.url_normalizer import NormalizationPolicy, classify_url, normalize_url
from .cache import AttachmentCache


@dataclass(frozen=True)
class ResourceReference:
    page_url: str
    kind: str
    original_url: str
    normalized_url: str | None
    text: str = ""
    alt: str | None = None
    location: str = ""
    relation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceResponse:
    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    final_url: str = ""
    history: tuple[Any, ...] = ()
    error: str | None = None


class ResourceClient(Protocol):
    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None) -> ResourceResponse: ...


class RequestBudgetError(RuntimeError):
    pass


class ExecutionResourceClient:
    """Adapt a requests-like session while enforcing one shared request budget."""
    def __init__(self, session: Any, *, timeout: float, max_requests: int, interval: float = 1.0, max_retries: int = 1, max_response_bytes: int = 20971520) -> None:
        self.session, self.timeout, self.max_requests, self.interval, self.max_retries, self.max_response_bytes = session, timeout, max_requests, interval, max_retries, max_response_bytes
        self.request_count = 0
        self._cache: dict[tuple[str, str, tuple[tuple[str, str], ...]], ResourceResponse] = {}
        self._last_request = 0.0

    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None) -> ResourceResponse:
        key = (method, url, tuple(sorted((headers or {}).items())))
        if key in self._cache:
            return self._cache[key]
        if self.request_count >= self.max_requests:
            raise RequestBudgetError(f"실행 전체 요청 상한 {self.max_requests}개 초과")
        import time
        if self._last_request:
            time.sleep(max(0.0, self.interval - (time.monotonic() - self._last_request)))
        self._last_request = time.monotonic()
        self.request_count += 1
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(method, url, headers=dict(headers or {}), timeout=self.timeout, allow_redirects=True, stream=True)
                body = b""
                if method != "HEAD":
                    body = response.raw.read(self.max_response_bytes, decode_content=True)
                result = ResourceResponse(response.status_code, dict(response.headers), body, response.url,
                                          tuple(response.history), None)
                self._cache[key] = result
                return result
            except Exception as exc:  # requests exceptions are intentionally isolated per resource
                last_error = str(exc)
        result = ResourceResponse(0, {}, b"", url, (), last_error or "요청 실패")
        self._cache[key] = result
        return result


def _safe_destination(url: str) -> tuple[bool, str | None]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, "HTTP/HTTPS가 아닌 scheme"
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False, "로컬 호스트 차단"
    try:
        address = ipaddress.ip_address(host)
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            return False, "사설·loopback·link-local 주소 차단"
    except ValueError:
        pass
    return True, None


def _srcset(value: str) -> list[str]:
    return [part.strip().split()[0] for part in value.split(",") if part.strip()]


def extract_resources(html: str, *, page_url: str, target_base_url: str, policy: NormalizationPolicy | None = None,
                      menu_path: str = "") -> list[ResourceReference]:
    soup = BeautifulSoup(html or "", "html.parser")
    output: list[ResourceReference] = []
    def add(kind: str, raw: str, node: Any, index: int, text: str = "", alt: str | None = None, relation: str = ""):
        normalized, _ = normalize_url(raw, page_url, policy or NormalizationPolicy())
        output.append(ResourceReference(page_url, kind, raw, normalized, text, alt, f"{kind}[{index}]", relation))
    for index, node in enumerate(soup.find_all("a", href=True)):
        href = node["href"]
        kind = "attachment" if (PurePosixPath(urlparse(href).path).suffix.lower() in {".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".hwp", ".hwpx"} or node.has_attr("download")) else "link"
        if not href.startswith("#"):
            add(kind, href, node, index, node.get_text(" ", strip=True), relation=menu_path)
        if "#" in href:
            anchor_ref = ResourceReference(page_url, "anchor", href, urljoin(page_url, href), node.get_text(" ", strip=True), None, f"anchor[{index}]", menu_path)
            output.append(anchor_ref)
    for index, node in enumerate(soup.find_all("img")):
        raw = node.get("src")
        if raw:
            add("image", raw, node, index, alt=node.get("alt"), relation=("decorative " if node.get("role") == "presentation" else "") + menu_path)
        for src in _srcset(node.get("srcset", "")):
            add("image", src, node, index, alt=node.get("alt"), relation=("decorative " if node.get("role") == "presentation" else "") + menu_path)
    for kind, tag, attr in (("script", "script", "src"), ("stylesheet", "link", "href")):
        for index, node in enumerate(soup.find_all(tag, **{"src" if attr == "src" else "href": True})):
            add(kind, node[attr], node, index, relation=menu_path)
    return output


@dataclass
class ResourceResult:
    reference: ResourceReference
    status_code: int | None
    final_url: str
    redirect_count: int
    verdict: str
    severity: str
    reason: str
    content_type: str = ""
    content_length: int | None = None
    request_method: str = ""
    checked: bool = False
    rechecked: bool = False
    cache_used: bool = False
    detailed_check: bool = False
    cache_reason: str | None = None
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "reference": self.reference.to_dict()}


class ResourceChecker:
    def __init__(self, client: ResourceClient, *, target_base_url: str, policy: NormalizationPolicy | None = None,
                 attachment_cache: AttachmentCache | None = None, max_redirect_hops: int = 3,
                 attachment_extensions: Iterable[str] = (".pdf", ".zip", ".docx", ".xlsx", ".pptx", ".hwp", ".hwpx"),
                 policy_version: str = "resources-1") -> None:
        self.client, self.target_base_url, self.policy = client, target_base_url, policy or NormalizationPolicy()
        self.attachment_cache, self.max_redirect_hops = attachment_cache, max_redirect_hops
        self.attachment_extensions, self.policy_version = {ext.lower() for ext in attachment_extensions}, policy_version
        self.results_by_url: dict[str, ResourceResult] = {}
        self.html_by_url: dict[str, str] = {}

    def _result(self, reference: ResourceReference, response: ResourceResponse | None, verdict: str, reason: str,
                *, severity: str = "검토", method: str = "", **kwargs: Any) -> ResourceResult:
        return ResourceResult(reference, response.status_code if response else None, response.final_url if response else "", len(response.history) if response else 0,
                              verdict, severity, reason, dict(response.headers).get("Content-Type", "") if response else "",
                              int(response.headers.get("Content-Length")) if response and str(response.headers.get("Content-Length", "")).isdigit() else (len(response.body) if response and response.body else None),
                              method, bool(response), checked_at=datetime.now(timezone.utc).isoformat(), **kwargs)

    def _request(self, reference: ResourceReference, *, headers: Mapping[str, str] | None = None) -> ResourceResponse:
        if not reference.normalized_url:
            raise ValueError("정규화할 수 없는 URL")
        return self.client.request("HEAD", reference.normalized_url, headers=headers)

    def check_reference(self, reference: ResourceReference, *, force_attachment: bool = False, content_hash: str = "", today: date | None = None) -> ResourceResult:
        if reference.normalized_url in self.results_by_url:
            cached_result = self.results_by_url[reference.normalized_url]
            if reference.kind == "attachment" and self.attachment_cache and today:
                filename = os.path.basename(urlparse(reference.normalized_url or "").path)
                self.attachment_cache.relations(reference.normalized_url, reference.page_url, original_url=reference.original_url, filename=filename, link_text=reference.text)
                return replace(cached_result, reference=reference, cache_used=True, cache_reason="실행 중 동일 첨부파일 결과 재사용")
            return replace(cached_result, reference=reference)
        if reference.kind == "anchor":
            parsed = urlparse(reference.original_url)
            target_document_url = urljoin(reference.page_url, reference.original_url.split("#", 1)[0])
            document = self.html_by_url.get(target_document_url)
            if not parsed.fragment or document is None:
                result = self._result(reference, None, "점검 불가", "앵커 대상 페이지를 가져오지 않음", method="none")
            else:
                soup = BeautifulSoup(document, "html.parser")
                exists = soup.find(id=parsed.fragment) or soup.find(attrs={"name": parsed.fragment})
                result = self._result(reference, None, "정상" if exists else "오류", "앵커 존재" if exists else "앵커 대상 없음", severity="하" if not exists else "검토", method="none")
            self.results_by_url[reference.normalized_url or reference.original_url] = result
            return result
        safe, safety_reason = _safe_destination(reference.normalized_url or "")
        if not safe:
            result = self._result(reference, None, "점검 불가", safety_reason or "위험한 대상", method="none")
            self.results_by_url[reference.normalized_url or reference.original_url] = result
            return result
        if reference.kind == "attachment" and self.attachment_cache and today:
            filename = os.path.basename(urlparse(reference.normalized_url or "").path)
            reusable, cache_reason = self.attachment_cache.reusable(reference.normalized_url, content_hash=content_hash, original_url=reference.original_url,
                                                                     filename=filename, link_text=reference.text, today=today, policy_version=self.policy_version, force=force_attachment)
            if reusable:
                cached = self.attachment_cache.get(reference.normalized_url)
                result = self._result(reference, None, cached.get("verdict", "정상"), "정상 첨부파일 캐시 재사용", method="cache", cache_used=True, cache_reason=None)
                self.results_by_url[reference.normalized_url] = result
                return result
            cache_reason_value = cache_reason
        else:
            cache_reason_value = None
        try:
            conditional_headers = {}
            if reference.kind == "attachment" and self.attachment_cache:
                cached_entry = self.attachment_cache.get(reference.normalized_url or "")
                if cached_entry:
                    if cached_entry.get("etag"):
                        conditional_headers["If-None-Match"] = cached_entry["etag"]
                    if cached_entry.get("last_modified"):
                        conditional_headers["If-Modified-Since"] = cached_entry["last_modified"]
            response = self.client.request("HEAD", reference.normalized_url, headers=conditional_headers)
            if response.status_code == 304 and reference.kind == "attachment" and self.attachment_cache:
                cached_entry = self.attachment_cache.get(reference.normalized_url or "") or {}
                if today:
                    cached_entry["last_revalidation"] = today.isoformat()
                    from datetime import timedelta
                    cached_entry["next_recheck_date"] = (today + timedelta(days=self.attachment_cache.recheck_days)).isoformat()
                result = self._result(reference, response, cached_entry.get("verdict", "정상"), "304 Not Modified; 첨부파일 캐시 유지", method="HEAD", cache_used=True, rechecked=True, detailed_check=True, cache_reason=cache_reason_value)
                self.results_by_url[reference.normalized_url] = result
                return result
            if response.status_code in (405, 0) or (response.status_code == 403 and reference.kind == "attachment"):
                response = self.client.request("GET", reference.normalized_url, headers={"Range": "bytes=0-65535"})
            elif reference.kind == "attachment" and response.status_code == 200:
                cached_entry = self.attachment_cache.get(reference.normalized_url or "") if self.attachment_cache else None
                metadata_changed = bool(cached_entry and any(cached_entry.get(key) and cached_entry.get(key) != response.headers.get(header)
                                      for key, header in (("etag", "ETag"), ("last_modified", "Last-Modified"), ("content_length", "Content-Length"))))
                if not response.body or metadata_changed:
                    response = self.client.request("GET", reference.normalized_url, headers={"Range": "bytes=0-65535"})
            if response.final_url and response.final_url != reference.normalized_url:
                safe_final, final_reason = _safe_destination(response.final_url)
                if not safe_final:
                    result = self._result(reference, response, "점검 불가", final_reason or "위험한 리다이렉트 목적지", method="HEAD")
                    self.results_by_url[reference.normalized_url] = result
                    return result
                if len(response.history) > self.max_redirect_hops:
                    result = self._result(reference, response, "점검 불가", "리다이렉트 횟수 상한 초과", method="HEAD")
                    self.results_by_url[reference.normalized_url] = result
                    return result
            if response.error:
                verdict, reason = "점검 불가", response.error
            elif response.status_code in (401, 403, 429) or "captcha" in response.body[:1000].lower().decode("latin1", "ignore"):
                verdict, reason = "점검 불가", f"HTTP {response.status_code} 또는 차단 응답"
            elif response.status_code in (404, 410):
                verdict, reason = "오류", f"HTTP {response.status_code}"
            elif 500 <= response.status_code < 600:
                verdict, reason = "검토 필요", f"HTTP {response.status_code}"
            elif 200 <= response.status_code < 300:
                verdict, reason = "정상", f"HTTP {response.status_code}"
            else:
                verdict, reason = "검토 필요", f"HTTP {response.status_code}"
            result = self._result(reference, response, verdict, reason, severity="상" if verdict == "오류" else "검토", method="GET" if response.body else "HEAD", cache_reason=cache_reason_value)
            if reference.kind == "image":
                result = self._check_image(reference, response, result)
            if reference.kind == "attachment":
                result = self._check_attachment(reference, response, result, content_hash=content_hash, today=today, cache_reason=cache_reason_value)
        except Exception as exc:
            result = self._result(reference, None, "점검 불가", str(exc), method="none", cache_reason=cache_reason_value)
        self.results_by_url[reference.normalized_url or reference.original_url] = result
        return result

    def _check_image(self, reference: ResourceReference, response: ResourceResponse, result: ResourceResult) -> ResourceResult:
        content_type = result.content_type.lower()
        if result.verdict == "정상" and reference.alt is None and "decorative" not in reference.relation:
            return replace(result, verdict="오류", severity="하", reason="이미지 alt 속성 누락")
        if result.verdict == "정상" and (not content_type.startswith("image/") or result.content_length == 0):
            return replace(result, verdict="오류", severity="중", reason="이미지 Content-Type 또는 크기 오류")
        return result

    def _check_attachment(self, reference: ResourceReference, response: ResourceResponse, result: ResourceResult, *, content_hash: str, today: date | None, cache_reason: str | None) -> ResourceResult:
        body = response.body
        suffix = PurePosixPath(urlparse(reference.normalized_url or "").path).suffix.lower()
        signature_ok = True
        if body and suffix == ".pdf": signature_ok = body.startswith(b"%PDF-")
        if body and suffix in {".zip", ".docx", ".xlsx", ".pptx", ".hwpx"}: signature_ok = body.startswith(b"PK")
        if body and suffix == ".hwp": signature_ok = body.startswith(bytes.fromhex("d0cf11e0"))
        expected_type_mismatch = (suffix == ".pdf" and result.content_type and "pdf" not in result.content_type.lower()) or (suffix in {".zip", ".docx", ".xlsx", ".pptx", ".hwpx"} and result.content_type and not any(token in result.content_type.lower() for token in ("zip", "office", "octet-stream")))
        if result.verdict == "정상" and (result.content_length == 0 or not signature_ok or expected_type_mismatch):
            result = replace(result, verdict="오류", severity="중", reason="첨부파일 크기 또는 시그니처 불일치")
        if self.attachment_cache and today:
            filename = os.path.basename(urlparse(reference.normalized_url or "").path)
            self.attachment_cache.update(reference.normalized_url, content_hash=content_hash, original_url=reference.original_url, page_url=reference.page_url,
                                         filename=filename, link_text=reference.text, result={"verdict": result.verdict, "content_type": result.content_type,
                                         "content_length": result.content_length, "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified"),
                                         "signature": body[:16].hex(), "policy_version": self.policy_version}, checked_date=today, policy_version=self.policy_version)
        return replace(result, detailed_check=True, rechecked=True)

    def check_html(self, html: str, *, page_url: str, menu_path: str = "", force_attachment: bool = False,
                   content_hash: str = "", today: date | None = None) -> list[ResourceResult]:
        self.html_by_url[page_url] = html
        references = extract_resources(html, page_url=page_url, target_base_url=self.target_base_url, policy=self.policy, menu_path=menu_path)
        return [self.check_reference(reference, force_attachment=force_attachment, content_hash=content_hash, today=today) for reference in references]


def resource_state_payload(results: Iterable[ResourceResult]) -> dict[str, Any]:
    values = list(results)
    return {"schema_version": "1.0", "issue_type": "resources", "results": [item.to_dict() for item in values],
            "counts": {verdict: sum(1 for item in values if item.verdict == verdict)
                       for verdict in sorted({item.verdict for item in values})}}
