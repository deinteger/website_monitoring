from datetime import date, timedelta

from src.inventory.url_normalizer import NormalizationPolicy
from src.resources.cache import AttachmentCache
from src.resources.checker import ResourceChecker, ResourceResponse, extract_resources, resource_state_payload


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, url, *, headers=None):
        self.calls.append((method, url, dict(headers or {})))
        value = self.responses.get((method, url)) or self.responses.get(url)
        if isinstance(value, list):
            value = value.pop(0)
        return value or ResourceResponse(404, {"Content-Type": "text/html"}, b"", url)


def response(status=200, content_type="text/html", body=b"ok", headers=None, final_url=""):
    return ResourceResponse(status, {"Content-Type": content_type, "Content-Length": str(len(body)), **(headers or {})}, body, final_url)


def test_extracts_links_images_srcset_css_js_and_attachments():
    html = '''<a href="/notice">공지</a><a href="file.pdf">파일</a><a href="mailto:a@x">메일</a>
    <img src="/a.png" srcset="/a-2.png 2x" alt="그림"><script src="/app.js"></script><link href="/a.css" rel="stylesheet">'''
    refs = extract_resources(html, page_url="https://example.test/page", target_base_url="https://example.test")
    assert {ref.kind for ref in refs} == {"link", "attachment", "image", "script", "stylesheet"}
    assert any(ref.normalized_url == "https://example.test/a-2.png" for ref in refs)
    mail = next(ref for ref in refs if ref.original_url.startswith("mailto"))
    assert mail.normalized_url is None


def test_duplicate_resource_is_requested_once_and_external_not_crawled():
    html = '<a href="/a">A</a><img src="/a"><a href="https://outside.test/x">X</a>'
    client = FakeClient({"https://example.test/a": response(), "https://outside.test/x": response(404)})
    checker = ResourceChecker(client, target_base_url="https://example.test")
    results = checker.check_html(html, page_url="https://example.test/page")
    assert len([call for call in client.calls if call[1] == "https://example.test/a"]) == 1
    assert any(result.reference.normalized_url == "https://outside.test/x" for result in results)


def test_statuses_head_fallback_and_request_budget_failure():
    client = FakeClient({("HEAD", "https://example.test/no"): response(404), "https://example.test/no": response(404),
                         ("HEAD", "https://example.test/fallback"): response(405), ("GET", "https://example.test/fallback"): response(200)})
    checker = ResourceChecker(client, target_base_url="https://example.test")
    results = checker.check_html('<a href="/no">no</a><a href="/fallback">fallback</a>', page_url="https://example.test/p")
    assert next(item for item in results if item.reference.normalized_url.endswith("/no")).verdict == "오류"
    assert any(call[0] == "GET" for call in client.calls)


def test_unsafe_destination_and_non_http_are_not_requested():
    client = FakeClient({})
    checker = ResourceChecker(client, target_base_url="https://example.test")
    results = checker.check_html('<a href="http://127.0.0.1/x">local</a><a href="javascript:void(0)">js</a>', page_url="https://example.test/p")
    assert all(result.verdict == "점검 불가" for result in results)
    assert client.calls == []


def test_anchor_same_page_success_failure_and_cross_page_unknown():
    client = FakeClient({})
    checker = ResourceChecker(client, target_base_url="https://example.test")
    results = checker.check_html('<a href="#ok">ok</a><a href="#missing">bad</a><a href="/other#id">other</a><div id="ok">x</div>', page_url="https://example.test/p")
    assert [result.verdict for result in results if result.reference.kind == "anchor"] == ["정상", "오류", "점검 불가"]


def test_image_alt_content_type_and_zero_bytes():
    client = FakeClient({"https://example.test/missing.png": response(200, "image/png", b"x"),
                         "https://example.test/bad.png": response(200, "text/html", b"x"),
                         "https://example.test/zero.png": response(200, "image/png", b"")})
    checker = ResourceChecker(client, target_base_url="https://example.test")
    results = checker.check_html('<img src="/missing.png"><img src="/bad.png" alt="bad"><img src="/zero.png" alt="zero"><img src="/decor.png" alt="">', page_url="https://example.test/p")
    assert next(item for item in results if item.reference.normalized_url.endswith("missing.png")).verdict == "오류"
    assert next(item for item in results if item.reference.normalized_url.endswith("bad.png")).verdict == "오류"
    assert next(item for item in results if item.reference.normalized_url.endswith("zero.png")).verdict == "오류"


def test_decorative_role_allows_missing_alt():
    client = FakeClient({"https://example.test/decor.png": response(200, "image/png", b"x")})
    checker = ResourceChecker(client, target_base_url="https://example.test")
    result = checker.check_html('<img src="/decor.png" role="presentation">', page_url="https://example.test/p")[0]
    assert result.verdict == "정상"


def test_attachment_first_check_signature_and_cache_reuse():
    cache = AttachmentCache(policy_version="p", recheck_days=30)
    client = FakeClient({"https://example.test/file.pdf": response(200, "application/pdf", b"%PDF-1.7 data", {"ETag": "abc"})})
    checker = ResourceChecker(client, target_base_url="https://example.test", attachment_cache=cache, policy_version="p")
    first = checker.check_html('<a href="/file.pdf">file</a>', page_url="https://example.test/a", content_hash="h", today=date(2026, 1, 1))[0]
    second = checker.check_html('<a href="/file.pdf">file</a>', page_url="https://example.test/b", content_hash="h", today=date(2026, 1, 2))[0]
    assert first.detailed_check and first.cache_used is False
    assert second.cache_used is True
    assert len(client.calls) == 1
    assert set(cache.get("https://example.test/file.pdf")["original_pages"]) == {"https://example.test/a", "https://example.test/b"}


def test_attachment_cache_recheck_reasons_force_expiry_and_failure():
    cache = AttachmentCache(policy_version="p", recheck_days=30)
    cache.update("https://example.test/f.pdf", content_hash="old", original_url="/f.pdf", page_url="/a", filename="f.pdf", link_text="f", result={"verdict": "정상"}, checked_date=date(2026, 1, 1), policy_version="p")
    assert cache.reusable("https://example.test/f.pdf", content_hash="old", original_url="/f.pdf", filename="f.pdf", link_text="f", today=date(2026, 1, 2), policy_version="p")[0]
    assert cache.reusable("https://example.test/f.pdf", content_hash="new", original_url="/f.pdf", filename="f.pdf", link_text="f", today=date(2026, 1, 2), policy_version="p")[1]
    assert cache.reusable("https://example.test/f.pdf", content_hash="old", original_url="/f.pdf", filename="f.pdf", link_text="f", today=date(2026, 2, 1), policy_version="p")[1] == "재검사 주기 만료"
    assert cache.reusable("https://example.test/f.pdf", content_hash="old", original_url="/f.pdf", filename="f.pdf", link_text="f", today=date(2026, 1, 2), policy_version="p", force=True)[1] == "강제 재점검"


def test_attachment_304_uses_conditional_headers():
    cache = AttachmentCache(policy_version="p", recheck_days=1)
    cache.update("https://example.test/f.pdf", content_hash="h", original_url="/f.pdf", page_url="/a", filename="f.pdf", link_text="f", result={"verdict": "정상", "etag": "etag-1"}, checked_date=date(2026, 1, 1), policy_version="p")
    client = FakeClient({"https://example.test/f.pdf": ResourceResponse(304, {"ETag": "etag-1"}, b"", "https://example.test/f.pdf")})
    checker = ResourceChecker(client, target_base_url="https://example.test", attachment_cache=cache, policy_version="p")
    result = checker.check_html('<a href="/f.pdf">f</a>', page_url="https://example.test/a", content_hash="h", today=date(2026, 1, 2))[0]
    assert result.cache_used and result.rechecked and "If-None-Match" in client.calls[0][2]


def test_cache_can_round_trip_through_state_manager(tmp_path):
    from src.common.state_manager import StateManager
    cache = AttachmentCache(policy_version="p")
    cache.update("https://example.test/f.pdf", content_hash="h", original_url="/f.pdf", page_url="/a", filename="f.pdf", link_text="f", result={"verdict": "정상"}, checked_date=date(2026, 1, 1), policy_version="p")
    manager = StateManager(tmp_path)
    cache.save_state(manager)
    loaded = AttachmentCache.from_state(manager, policy_version="p")
    assert loaded.get("https://example.test/f.pdf")["verdict"] == "정상"


def test_attachment_signature_mismatch_and_state_shape():
    cache = AttachmentCache(policy_version="p")
    client = FakeClient({"https://example.test/f.pdf": response(200, "application/pdf", b"not pdf")})
    checker = ResourceChecker(client, target_base_url="https://example.test", attachment_cache=cache, policy_version="p")
    result = checker.check_html('<a href="/f.pdf">f</a>', page_url="https://example.test/a", content_hash="h", today=date(2026, 1, 1))[0]
    assert result.verdict == "오류"
    assert cache.to_dict()["schema_version"] == "1.0"
    assert resource_state_payload([result])["issue_type"] == "resources"
