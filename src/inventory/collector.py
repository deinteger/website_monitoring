"""Collect menu and sitemap URL occurrences without crawling page bodies."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import requests

from src.common.config_loader import Target


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status_code: int
    text: str
    elapsed_seconds: float = 0.0
    headers: dict[str, str] = field(default_factory=dict)
    requested_transport: str = ""
    actual_transport: str = ""
    proxy_used: bool = False
    fallback_used: bool = False
    fallback_reason: str = ""
    connection_result: str = ""


class Fetcher(Protocol):
    def fetch(self, url: str) -> FetchResponse: ...


class RequestFetcher:
    """Small sequential fetcher; it never bypasses server-side blocking."""

    def __init__(self, *, user_agent: str, timeout: float, max_retries: int, interval: float, max_requests: int, transport: Fetcher | None = None) -> None:
        self.transport = transport
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "text/html,application/xml,text/xml"})
        self.timeout = timeout
        self.max_retries = max_retries
        self.interval = interval
        self.max_requests = max_requests
        self.request_count = 0
        self._last_request_at: float | None = None

    def fetch(self, url: str) -> FetchResponse:
        if self.transport is not None:
            response = self.transport.fetch(url)
            self.request_count = getattr(self.transport, "request_count", self.request_count + 1)
            return response
        if self.request_count >= self.max_requests:
            raise RequestLimitError(f"최대 요청 URL {self.max_requests}개에 도달")
        if self._last_request_at is not None:
            time.sleep(max(0.0, self.interval - (time.monotonic() - self._last_request_at)))
        self._last_request_at = time.monotonic()
        self.request_count += 1
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                started = time.monotonic()
                response = self.session.get(url, timeout=self.timeout, allow_redirects=False)
                return FetchResponse(url, response.status_code, response.text, time.monotonic() - started, dict(response.headers))
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    continue
        raise FetchError(f"요청 실패: {last_error}") from last_error


class FetchError(RuntimeError):
    pass


class RequestLimitError(FetchError):
    pass


@dataclass
class DiscoveryOccurrence:
    target_id: str
    url: str
    original_url: str
    title: str
    menu_path: str
    source: str
    discovered_from: str
    discovered_at: str


@dataclass
class SourceResult:
    source: str
    success: bool = False
    discovered_url_count: int = 0
    requested_urls: list[str] = field(default_factory=list)
    failure_reason: str | None = None


@dataclass
class InventoryResult:
    target_id: str
    records: list[DiscoveryOccurrence] = field(default_factory=list)
    sources: list[SourceResult] = field(default_factory=list)
    request_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"target_id": self.target_id, "records": [asdict(record) for record in self.records],
                "sources": [asdict(source) for source in self.sources], "request_count": self.request_count}


def _local_url(target: Target, href: str, page_url: str) -> str | None:
    absolute = urljoin(page_url, href.strip())
    parsed = urlparse(absolute)
    base = urlparse(target.base_url)
    if parsed.scheme != "https" or parsed.hostname != base.hostname:
        return None
    return absolute


def _blocked(response: FetchResponse) -> str | None:
    if response.status_code in (403, 429):
        return f"HTTP {response.status_code} 차단(우회하지 않음)"
    body = response.text[:4000].lower()
    if any(term in body for term in ("captcha", "access denied", "web application firewall", "waf")):
        return "WAF/캡차 의심 응답(우회하지 않음)"
    return None


class InventoryCollector:
    def __init__(self, target: Target, fetcher: Fetcher, *, max_requests: int = 10, include_root: bool = False, crawl_internal: bool = False) -> None:
        self.target = target
        self.fetcher = fetcher
        self.max_requests = max_requests
        self.include_root = include_root
        self.crawl_internal = crawl_internal
        self._responses: dict[str, FetchResponse] = {}
        self._errors: dict[str, FetchError] = {}
        self._visited_sitemaps: set[str] = set()
        self._records: dict[str, DiscoveryOccurrence] = {}
        self._extra_occurrences: list[DiscoveryOccurrence] = []
        self._now = datetime.now(timezone.utc).isoformat()

    def _get(self, url: str) -> FetchResponse:
        if url in self._responses:
            return self._responses[url]
        if url in self._errors:
            raise self._errors[url]
        if len(self._responses) >= self.max_requests:
            raise RequestLimitError(f"최대 요청 URL {self.max_requests}개에 도달")
        try:
            response = self.fetcher.fetch(url)
        except FetchError as exc:
            self._errors[url] = exc
            raise
        self._responses[url] = response
        return response

    def _add(self, source: str, original: str, page_url: str, title: str = "", menu_path: str = "") -> None:
        url = _local_url(self.target, original, page_url)
        if not url:
            return
        occurrence = DiscoveryOccurrence(self.target.identifier, url, original, title.strip(), menu_path, source, page_url, self._now)
        prior = self._records.get(url)
        if prior is None:
            self._records[url] = occurrence
        else:
            self._extra_occurrences.append(occurrence)

    def _parse_menu(self, source: str, page_url: str, html: str, selectors: list[str], source_result: SourceResult) -> None:
        soup = BeautifulSoup(html, "html.parser")
        seen: set[int] = set()
        for selector in selectors:
            for anchor in soup.select(selector):
                if id(anchor) in seen:
                    continue
                seen.add(id(anchor))
                href = anchor.get("href")
                if not href:
                    continue
                before = len(self._records) + len(self._extra_occurrences)
                labels = []
                for item in anchor.find_parents("li"):
                    own_anchor = item.find("a", recursive=False)
                    if own_anchor and own_anchor.get_text(" ", strip=True):
                        label = own_anchor.get_text(" ", strip=True)
                    else:
                        label = " ".join(str(node).strip() for node in item.find_all(string=True, recursive=False) if str(node).strip())
                    if label:
                        labels.append(label)
                labels.reverse()
                menu_path = " > ".join(labels)
                self._add(source, href, page_url, anchor.get_text(" ", strip=True), menu_path)
                if len(self._records) + len(self._extra_occurrences) > before:
                    source_result.discovered_url_count += 1

    def _run_page_source(self, source: str, page_url: str, selectors: list[str]) -> SourceResult:
        result = SourceResult(source)
        try:
            response = self._get(page_url)
            result.requested_urls.append(page_url)
            blocked = _blocked(response)
            if blocked:
                result.failure_reason = blocked
            elif response.status_code >= 400:
                result.failure_reason = f"HTTP {response.status_code}"
            else:
                self._parse_menu(source, page_url, response.text, selectors, result)
                result.success = True
        except FetchError as exc:
            result.failure_reason = str(exc)
        return result

    def _run_sitemap(self, sitemap_url: str, result: SourceResult) -> None:
        if sitemap_url in self._visited_sitemaps:
            return
        self._visited_sitemaps.add(sitemap_url)
        try:
            response = self._get(sitemap_url)
            result.requested_urls.append(sitemap_url)
            blocked = _blocked(response)
            if blocked:
                raise FetchError(blocked)
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code}")
            try:
                root = ET.fromstring(response.text)
            except ET.ParseError as exc:
                raise FetchError(f"잘못된 XML: {exc}") from exc
            tag = root.tag.rsplit("}", 1)[-1]
            if tag not in ("urlset", "sitemapindex"):
                raise FetchError(f"지원하지 않는 sitemap 루트: {tag}")
            for child in root:
                child_tag = child.tag.rsplit("}", 1)[-1]
                loc = next((node.text.strip() for node in child if node.tag.rsplit("}", 1)[-1] == "loc" and node.text), None)
                if not loc:
                    continue
                if child_tag == "url":
                    before = len(self._records) + len(self._extra_occurrences)
                    self._add("sitemap", loc, sitemap_url)
                    if len(self._records) + len(self._extra_occurrences) > before:
                        result.discovered_url_count += 1
                elif child_tag == "sitemap" and _local_url(self.target, loc, sitemap_url):
                    self._run_sitemap(urljoin(sitemap_url, loc), result)
        except FetchError as exc:
            if result.failure_reason is None:
                result.failure_reason = str(exc)

    def collect(self) -> InventoryResult:
        menu = self.target.menu
        main_url = self.target.base_url + "/"
        main = self._run_page_source("main_menu", main_url, list(menu.get("main_selectors", [])))
        if self.include_root:
            self._add("root", main_url, main_url, self.target.name, "")
            if self.crawl_internal and main_url in self._responses:
                self._parse_menu("crawl", main_url, self._responses[main_url].text, ["a"], main)
                queue=list(self._records)
                seen={main_url}
                while queue and len(self._responses) < self.max_requests:
                    url=queue.pop(0)
                    if url in seen: continue
                    seen.add(url)
                    try: page=self._get(url)
                    except FetchError: continue
                    before=set(self._records)
                    self._parse_menu("crawl", url, page.text, ["a"], main)
                    queue.extend(x for x in self._records if x not in before and x not in seen)
        self._parse_all_menu(main_url, menu, main)
        sitemap = SourceResult("sitemap")
        sitemap_path = str(menu.get("sitemap_path", "/sitemap.xml"))
        sitemap_url = urljoin(main_url, sitemap_path)
        self._run_sitemap(sitemap_url, sitemap)
        result = InventoryResult(self.target.identifier, list(self._records.values()) + self._extra_occurrences,
                                 [main, self._all_result, sitemap], getattr(self.fetcher, "request_count", len(self._responses)))
        return result

    def _parse_all_menu(self, main_url: str, menu: dict[str, Any], main_result: SourceResult) -> None:
        result = SourceResult("all_menu")
        self._all_result = result
        paths = list(menu.get("all_menu_paths", []))
        if not paths:
            paths = [url for url in self._responses if url == main_url]
        for path in paths:
            page_url = urljoin(main_url, path)
            page = self._run_page_source("all_menu", page_url, list(menu.get("all_menu_selectors", [])))
            result.discovered_url_count += page.discovered_url_count
            result.requested_urls.extend(page.requested_urls)
            if not page.success and page.failure_reason:
                result.failure_reason = page.failure_reason
            elif page.success:
                result.success = True
        if not paths:
            # A configured all-menu selector may be embedded in the main page.
            response = self._responses.get(main_url)
            if response:
                self._parse_menu("all_menu", main_url, response.text, list(menu.get("all_menu_selectors", [])), result)
                result.success = True
            else:
                result.failure_reason = "메인 페이지를 가져오지 못해 전체 메뉴 영역을 확인하지 못함"
