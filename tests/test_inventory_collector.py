from pathlib import Path

import pytest

from src.common.config_loader import Target
from src.inventory.collector import FetchError, FetchResponse, InventoryCollector, RequestLimitError


class FakeFetcher:
    def __init__(self, responses, errors=None):
        self.responses = responses
        self.errors = errors or {}
        self.calls = []
        self.request_count = 0

    def fetch(self, url):
        self.calls.append(url)
        self.request_count += 1
        if url in self.errors:
            raise self.errors[url]
        value = self.responses[url]
        if isinstance(value, FetchResponse):
            return value
        return FetchResponse(url, 200, value)


def target(menu=None):
    return Target("test", "Test", "https://example.test", menu or {
        "main_selectors": ["nav a"],
        "all_menu_paths": ["/all-menu"],
        "all_menu_selectors": [".all-menu a"],
        "sitemap_path": "/sitemap.xml",
    })


def test_main_and_all_menu_extract_hierarchy_and_relative_urls():
    responses = {
        "https://example.test/": '<nav><ul><li>서비스<ul><li>공지<a href="/notice">공지사항</a></li></ul></li></ul></nav>',
        "https://example.test/all-menu": '<div class="all-menu"><a href="/notice">공지</a><a href="guide.html">안내</a></div>',
        "https://example.test/sitemap.xml": '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.test/map</loc></url></urlset>',
    }
    result = InventoryCollector(target(), FakeFetcher(responses)).collect()
    assert {item.url for item in result.records} == {
        "https://example.test/notice", "https://example.test/guide.html", "https://example.test/map"
    }
    notice = next(item for item in result.records if item.url.endswith("/notice"))
    assert notice.source == "main_menu"
    assert notice.menu_path == "서비스 > 공지사항"
    assert any(item.source == "all_menu" for item in result.records if item.url.endswith("/notice"))
    assert {source.source for source in result.sources} == {"main_menu", "all_menu", "sitemap"}


def test_sitemap_index_recursion_and_cycle_are_safe():
    responses = {
        "https://example.test/": "<nav></nav>",
        "https://example.test/sitemap.xml": '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>/child.xml</loc></sitemap><sitemap><loc>/child.xml</loc></sitemap></sitemapindex>',
        "https://example.test/child.xml": '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>/sitemap.xml</loc></sitemap><sitemap><loc>/leaf.xml</loc></sitemap></sitemapindex>',
        "https://example.test/leaf.xml": '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>/leaf-page</loc></url></urlset>',
    }
    fetcher = FakeFetcher(responses)
    result = InventoryCollector(target({"main_selectors": ["nav a"], "all_menu_paths": [], "all_menu_selectors": [], "sitemap_path": "/sitemap.xml"}), fetcher).collect()
    assert fetcher.calls.count("https://example.test/child.xml") == 1
    assert fetcher.calls.count("https://example.test/sitemap.xml") == 1
    assert any(item.url.endswith("/leaf-page") for item in result.records)


@pytest.mark.parametrize("status,reason", [(403, "403"), (429, "429")])
def test_blocked_source_is_recorded_and_other_sources_continue(status, reason):
    responses = {
        "https://example.test/": FetchResponse("https://example.test/", status, "blocked"),
        "https://example.test/sitemap.xml": '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>/ok</loc></url></urlset>',
    }
    result = InventoryCollector(target({"main_selectors": ["nav a"], "all_menu_paths": [], "all_menu_selectors": [], "sitemap_path": "/sitemap.xml"}), FakeFetcher(responses)).collect()
    assert reason in next(item for item in result.sources if item.source == "main_menu").failure_reason
    assert any(item.url.endswith("/ok") for item in result.records)


def test_timeout_bad_xml_and_max_requests_are_failures_without_crashing():
    responses = {"https://example.test/": "<nav></nav>", "https://example.test/sitemap.xml": "not xml"}
    fetcher = FakeFetcher(responses, {"https://example.test/all-menu": FetchError("timeout")})
    result = InventoryCollector(target(), fetcher, max_requests=3).collect()
    assert "잘못된 XML" in next(item for item in result.sources if item.source == "sitemap").failure_reason
    assert "timeout" in next(item for item in result.sources if item.source == "all_menu").failure_reason

    limited = InventoryCollector(target(), FakeFetcher(responses), max_requests=1).collect()
    assert any(source.failure_reason and "최대 요청" in source.failure_reason for source in limited.sources)


def test_external_links_are_not_followed():
    responses = {
        "https://example.test/": '<nav><a href="https://outside.test/x">outside</a><a href="relative">inside</a></nav>',
        "https://example.test/sitemap.xml": '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>',
    }
    result = InventoryCollector(target({"main_selectors": ["nav a"], "all_menu_paths": [], "all_menu_selectors": [], "sitemap_path": "/sitemap.xml"}), FakeFetcher(responses)).collect()
    assert [item.url for item in result.records] == ["https://example.test/relative"]
