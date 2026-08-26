from datetime import date

from src.freshness.checker import check_content_freshness, extract_dates, freshness_state_payload


def test_time_datetime_extracts_published_and_modified_with_provenance():
    html = '<article><span>게시일</span><time datetime="2026-08-25T09:30:00+09:00">2026. 8. 25.</time><span>최종수정일</span><time datetime="2026-08-26">2026-08-26</time></article>'
    result = extract_dates(html)
    assert result["published"].normalized_date == "2026-08-25"
    assert result["published"].extraction_method == "time_datetime"
    assert result["modified"].normalized_date == "2026-08-26"
    assert result["modified"].evidence_location == "time[1]"


def test_meta_has_priority_over_json_ld_and_labels():
    html = '''<meta property="article:published_time" content="2026-01-02T00:00:00Z"><script type="application/ld+json">{"datePublished":"2025-01-01"}</script><div>게시일 2024. 1. 1.</div>'''
    result = extract_dates(html)
    assert result["published"].normalized_date == "2026-01-02"
    assert result["published"].extraction_method == "article_meta"


def test_json_ld_date_modified_and_korean_label_formats():
    html = '<script type="application/ld+json">{"@type":"Article","datePublished":"2026년 8월 25일","dateModified":"2026/08/26"}</script>'
    result = extract_dates(html)
    assert result["published"].normalized_date == "2026-08-25"
    assert result["modified"].normalized_date == "2026-08-26"
    assert result["modified"].extraction_method == "json_ld"


def test_configured_selector_and_bad_date_failure():
    result = extract_dates('<div class="date">2026-02-30</div>', selectors={"published": [".date"]})
    assert result["published"].parse_success is False
    assert result["published"].extraction_method == "configured_selector"
    assert result["published"].failure_reason


def test_list_dates_are_not_used_as_page_date():
    result = extract_dates('<ul><li>게시일 2026-08-25</li><li>게시일 2026-08-24</li></ul>', page_type="list")
    assert all(not item.parse_success for item in result.values())
    assert "목록형" in result["published"].failure_reason


def test_applicability_static_missing_date_is_not_an_issue():
    result = check_content_freshness("<h1>기관소개</h1><footer>2026</footer>", target_id="nihhs", url="https://example.test/about", page_type="static", reference_date=date(2026, 8, 25))
    assert result.verdict == "해당 없음"
    assert result.applicability == "not_required"


def test_required_missing_date_is_uncheckable():
    result = check_content_freshness("<article><h1>공지</h1></article>", target_id="nihhs", url="https://example.test/notice/1", page_type="notice", reference_date=date(2026, 8, 25))
    assert result.verdict == "점검 불가"
    assert result.published.parse_success is False


def test_reference_date_boundary_and_old_content_review():
    html = '<time datetime="2024-08-25">2024-08-25</time>'
    result = check_content_freshness(html, target_id="nihhs", url="https://example.test/notice/1", page_type="notice", reference_date=date(2026, 8, 25), rules={"freshness": {"default_review_days": 730}})
    assert result.elapsed_days == 730
    assert result.verdict == "검토 필요"


def test_modified_date_is_used_for_freshness():
    html = '<span>게시일</span><time datetime="2020-01-01">2020-01-01</time><span>수정일</span><time datetime="2026-08-24">2026-08-24</time>'
    result = check_content_freshness(html, target_id="nihhs", url="https://example.test/notice/1", page_type="notice", reference_date=date(2026, 8, 25))
    assert result.modified.parse_success
    assert result.elapsed_days == 1
    assert result.verdict == "정상"


def test_future_date_and_archive_exception():
    future = check_content_freshness('<time datetime="2026-08-30">2026-08-30</time>', target_id="nihhs", url="https://example.test/notice/1", page_type="notice", reference_date=date(2026, 8, 25))
    assert future.verdict == "검토 필요"
    archive = check_content_freshness('<h1>연혁</h1><time datetime="2000-01-01">2000-01-01</time>', target_id="nihhs", url="https://example.test/history", page_type="detail", reference_date=date(2026, 8, 25))
    assert archive.verdict == "정상"
    assert "보존" in archive.reason


def test_uncertain_page_type_requires_manual_review():
    result = check_content_freshness('<h1>자료</h1><time datetime="2026-08-24">2026-08-24</time>', target_id="nihhs", url="https://example.test/resource", page_type="unknown", reference_date=date(2026, 8, 25))
    assert result.verdict == "수동확인 필요"
    assert result.manual_review_required is True


def test_false_positive_values_are_not_dates():
    html = '<footer>Copyright 2026</footer><div>조회수 20260825</div><div>전화 02-1234-5678</div><a href="file_2026_08_25.pdf">자료</a>'
    result = extract_dates(html)
    assert all(not item.parse_success for item in result.values())


def test_invalid_leap_day_and_iso_timezone():
    bad = extract_dates('<div>게시일 2025-02-29</div>')
    assert bad["published"].parse_success is False
    good = extract_dates('<time datetime="2024-02-29T23:00:00-05:00">date</time>')
    assert good["published"].normalized_date == "2024-02-29"


def test_deterministic_reference_date_and_serialized_result():
    result = check_content_freshness('<time datetime="2026-08-25">2026-08-25</time>', target_id="nihhs", url="https://example.test/notice/1", page_type="notice", reference_date=date(2026, 8, 25), checked_at="run-1")
    value = result.to_dict()
    assert value["reference_date"] == "2026-08-25"
    assert value["checked_at"] == "run-1"
    assert value["published"]["parse_success"] is True


def test_freshness_state_payload_is_issues_compatible():
    result = check_content_freshness('<time datetime="2026-08-25">2026-08-25</time>', target_id="nihhs", url="https://example.test/notice/1", page_type="notice", reference_date=date(2026, 8, 25))
    payload = freshness_state_payload([result])
    assert payload["schema_version"] == "1.0"
    assert payload["issue_type"] == "content_freshness"
    assert payload["counts"]["정상"] == 1
