from src.quality.accessibility import AccessibilityCache, accessibility_state_payload, build_content_hash, check_page


BASE = '<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>공지</title><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><a href="#main">본문 바로가기</a><main id="main">내용</main></body></html>'


def issue_codes(report):
    return {issue.code for issue in report.issues}


def test_valid_doctype_encoding_title_lang_and_viewport():
    report = check_page(BASE, target_id="nihhs", url="https://example.test/p")
    assert "doctype" not in issue_codes(report)
    assert "encoding" not in issue_codes(report)
    assert "title" not in issue_codes(report)
    assert "lang" not in issue_codes(report)
    assert "viewport" not in issue_codes(report)


def test_doctype_encoding_title_lang_and_viewport_candidates():
    html = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN"><html lang=""><head><meta charset="euc-kr"><meta name="viewport" content="initial-scale=1,user-scalable=no"><title>홈</title><title> </title></head><body></body></html>'
    report = check_page(html, target_id="nihhs", url="https://example.test/p")
    assert {"doctype", "encoding", "title", "lang", "viewport-width", "viewport-zoom"} <= issue_codes(report)


def test_http_charset_meta_conflict_is_error():
    report = check_page(BASE, target_id="nihhs", url="https://example.test/p", http_charset="euc-kr")
    assert "encoding" in issue_codes(report)
    assert next(issue for issue in report.issues if issue.code == "encoding").result == "오류"


def test_duplicate_and_empty_ids():
    report = check_page(BASE.replace('id="main"', 'id="dup"') + '<div id="dup"></div><div id=" "></div>', target_id="nihhs", url="https://example.test/p")
    assert "duplicate-id" in issue_codes(report)
    assert "empty-id" in issue_codes(report)


def test_form_labels_all_supported_and_missing_cases():
    html = BASE.replace('</main>', '<label for="a">A</label><input id="a"><label><input id="b"></label><input aria-label="C"><input aria-labelledby="label"><span id="label">D</span><input placeholder="only"><input type="hidden"><input type="submit"></main>')
    report = check_page(html, target_id="nihhs", url="https://example.test/p")
    labels = [issue for issue in report.issues if issue.code == "input-label"]
    assert len(labels) == 1 and labels[0].result == "검토 필요"


def test_invalid_aria_labelledby_is_error():
    html = BASE.replace('</main>', '<input aria-labelledby="missing"></main>')
    report = check_page(html, target_id="nihhs", url="https://example.test/p")
    assert next(issue for issue in report.issues if issue.code == "input-label-ref").result == "오류"


def test_empty_controls_and_image_name():
    html = BASE.replace('</main>', '<a href="/x"> </a><button aria-label="ok"></button><button><img alt="아이콘"></button><button><img></button></main>')
    report = check_page(html, target_id="nihhs", url="https://example.test/p")
    assert "empty-control" in issue_codes(report)
    assert sum(issue.code == "empty-control" for issue in report.issues) == 1


def test_skip_link_missing_target_and_missing_skip_link():
    bad = check_page(BASE.replace('id="main"', 'id="other"'), target_id="nihhs", url="https://example.test/p")
    assert "skip-link-target" in issue_codes(bad)
    missing = check_page(BASE.replace('<a href="#main">본문 바로가기</a>', ''), target_id="nihhs", url="https://example.test/p")
    assert "skip-link" in issue_codes(missing)


def test_image_alt_reuses_resource_issue_without_duplicate_dom_issue():
    html = BASE.replace('</main>', '<img src="/x.png"></main>')
    resources = [{"reference": {"kind": "image"}, "reason": "이미지 alt 속성 누락", "verdict": "오류", "severity": "하", "issue_id": "resource-1"}]
    report = check_page(html, target_id="nihhs", url="https://example.test/p", resource_results=resources)
    image_issues = [issue for issue in report.issues if issue.code == "image-alt"]
    assert len(image_issues) == 1 and image_issues[0].related_issue_id == "resource-1"


def test_decorative_image_exemption_and_dynamic_unknown_manual():
    html = BASE.replace('</main>', '<img src="/decor.png" alt=""><img src="/decor2.png" role="presentation"></main>')
    report = check_page(html, target_id="nihhs", url="https://example.test/p")
    assert "image-alt" not in issue_codes(report)
    manual = check_page(None, target_id="nihhs", url="https://example.test/p")
    assert next(issue for issue in manual.issues if issue.code == "parse").result == "점검 불가"


def test_html_syntax_candidate_and_excluded_items_absent():
    report = check_page('<html lang="ko"><head><meta charset="utf-8"><title>x</title><meta name="viewport" content="width=device-width"></head><body><main>', target_id="nihhs", url="https://example.test/p")
    assert "html-syntax" in issue_codes(report)
    assert "table-header" not in issue_codes(report)
    assert "plugin" not in issue_codes(report)


def test_cache_reuse_and_recheck_conditions(tmp_path):
    from src.common.state_manager import StateManager
    cache = AccessibilityCache(policy_version="p")
    first = check_page(BASE, target_id="nihhs", url="https://example.test/p", cache=cache, policy_version="p", menu_path="A", checked_at="first")
    second = check_page(BASE, target_id="nihhs", url="https://example.test/p", cache=cache, policy_version="p", menu_path="B", checked_at="second")
    assert second.cache_used and second.menu_path == "B" and second.checked_at == "second"
    changed = check_page(BASE.replace("공지", "변경"), target_id="nihhs", url="https://example.test/p", cache=cache, policy_version="p")
    assert changed.cache_used is False
    policy = check_page(BASE, target_id="nihhs", url="https://example.test/p", cache=cache, policy_version="other")
    assert policy.cache_used is False
    manager = StateManager(tmp_path)
    cache.save_state(manager)
    assert AccessibilityCache.from_state(manager, policy_version="p").entries


def test_accessibility_state_payload_has_deterministic_issue_keys():
    report = check_page(BASE.replace('<title>공지</title>', ''), target_id="nihhs", url="https://example.test/p")
    payload = accessibility_state_payload([report])
    assert payload["issue_type"] == "accessibility"
    assert payload["issues"][0]["issue_key"]
    assert payload["counts"]["오류"] >= 1


def test_content_hash_ignores_configured_volatile_regions_and_records_scope():
    first = '<html><body><main><h1>공지</h1><span class="view-count">조회수 1</span><div nonce="abc">본문</div></main></body></html>'
    second = first.replace("조회수 1", "조회수 999").replace('nonce="abc"', 'nonce="xyz"')
    hash1, scope1, removed1 = build_content_hash(first, content_selector="main", volatile_selectors=[".view-count"], volatile_attributes=["nonce"])
    hash2, scope2, removed2 = build_content_hash(second, content_selector="main", volatile_selectors=[".view-count"], volatile_attributes=["nonce"])
    assert hash1 == hash2
    assert scope1 == scope2 == "main"
    assert ".view-count" in removed1 and "@nonce" in removed1


def test_content_hash_fallback_is_explicit_and_body_change_rechecks():
    hash1, scope, _ = build_content_hash("<div>A</div>", content_selector="main")
    hash2, _, _ = build_content_hash("<div>B</div>", content_selector="main")
    assert scope == "full_html_fallback" and hash1 != hash2
