from src.quality.performance import PageHTTPObservation, check_page_performance, performance_state_payload
from src.resources.checker import ResourceReference


def obs(status=200, *, total=1.0, body=b"<html>ok</html>", html="<html>ok</html>", headers=None, **kwargs):
    return PageHTTPObservation("https://example.test/page", status, "https://example.test/page", (), "s", "e", total, 0.2, headers or {}, body, html, **kwargs)


def test_status_and_redirect_results():
    assert check_page_performance(obs(200), target_id="nihhs").verdict == "정상"
    assert check_page_performance(obs(404), target_id="nihhs").verdict == "오류"
    assert check_page_performance(obs(403), target_id="nihhs").verdict == "점검 불가"
    assert check_page_performance(obs(503), target_id="nihhs").verdict == "오류"
    redirected = check_page_performance(PageHTTPObservation("https://example.test/p", 200, "https://example.test/f", ("https://example.test/a",), total_seconds=1, body=b"x", html="x"), target_id="nihhs")
    assert redirected.redirect_count == 1 and redirected.final_url.endswith("/f")


def test_timeout_dns_connection_ssl_and_request_limit():
    for kwargs in ({"timed_out": True, "failure_type": "timeout"}, {"failure_type": "dns"}, {"failure_type": "connection"}, {"failure_type": "ssl"}, {"request_limit_exceeded": True}):
        result = check_page_performance(obs(None, **kwargs), target_id="nihhs")
        assert result.verdict == "점검 불가"
    assert check_page_performance(obs(None, failure_type="ssl"), target_id="nihhs").ssl_result == "SSL 점검 불가"


def test_response_time_boundaries():
    rules = {"response_warning_seconds": 3.0, "response_error_seconds": 5.0}
    assert check_page_performance(obs(200, total=2.99), target_id="nihhs", performance_rules=rules).verdict == "정상"
    assert check_page_performance(obs(200, total=3.0), target_id="nihhs", performance_rules=rules).verdict == "검토 필요"
    assert check_page_performance(obs(200, total=5.0), target_id="nihhs", performance_rules=rules).verdict == "검토 필요"


def test_size_header_actual_and_decompressed_bytes():
    body = b"x" * (3 * 1024 * 1024)
    result = check_page_performance(obs(200, body=body, html="x", headers={"Content-Length": str(len(body)), "Content-Encoding": "gzip"}), target_id="nihhs", performance_rules={"page_size_warning_mb": 3, "page_size_error_mb": 5})
    assert result.content_length_header == len(body)
    assert result.received_bytes == len(body)
    assert result.decompressed_html_bytes == 1
    assert result.content_encoding == "gzip"
    assert result.verdict == "검토 필요"


def test_content_length_missing_and_mismatch_not_error_by_itself():
    result = check_page_performance(obs(200, body=b"123", html="123", headers={"Content-Length": "99"}), target_id="nihhs")
    assert result.received_bytes == 3 and result.content_length_header == 99 and result.verdict == "정상"


def test_soft_404_candidate_and_short_body_false_positive():
    rules = {"soft_404_keywords": ["페이지를 찾을 수 없습니다"], "soft_404_min_body_bytes": 512}
    candidate = check_page_performance(obs(200, body=b"x", html="페이지를 찾을 수 없습니다"), target_id="nihhs", performance_rules=rules)
    assert candidate.soft_404_candidate and candidate.verdict == "검토 필요"
    normal_text = "페이지를 찾을 수 없습니다" + "x" * 1000
    normal = check_page_performance(obs(200, body=normal_text.encode(), html=normal_text), target_id="nihhs", performance_rules=rules)
    assert normal.soft_404_candidate is True  # keyword is still a candidate; it is not promoted to 오류


def test_mixed_content_only_for_active_resources_not_plain_links():
    resources = [ResourceReference("https://example.test/page", "image", "http://cdn.test/a.png", "http://cdn.test/a.png"),
                 ResourceReference("https://example.test/page", "link", "http://outside.test", "http://outside.test")]
    result = check_page_performance(obs(200), target_id="nihhs", resources=resources)
    assert len(result.mixed_content) == 1 and result.mixed_content[0]["kind"] == "image"


def test_console_is_not_run_without_browser():
    result = check_page_performance(obs(), target_id="nihhs")
    assert result.console_error_count is None and result.console_status == "미실행"


def test_redirect_limit_and_sitemap_payload():
    result = check_page_performance(PageHTTPObservation("https://example.test/p", 200, redirect_chain=("a", "b", "c", "d"), total_seconds=1, body=b"x", html="x"), target_id="nihhs", max_redirect_hops=3)
    assert result.verdict == "점검 불가"
    payload = performance_state_payload([result])
    assert payload["issue_type"] == "performance" and payload["results"][0]["issue_key"]
