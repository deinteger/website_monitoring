from datetime import date

from src.freshness.list_checker import check_list_freshness, list_freshness_state_payload, subtract_calendar_months


RULES = {"freshness": {"list_calendar_months": 3, "list_latest_issue_type": "게시 최신성 지연"}}


def test_table_uses_date_column_and_latest_value_not_html_order():
    html = '''<table><thead><tr><th>번호</th><th>제목</th><th>등록일</th><th>조회수</th></tr></thead><tbody>
    <tr><td>1</td><td><a href="/old">오래된 공지</a></td><td>2026-05-25</td><td>20260825</td></tr>
    <tr><td>2</td><td><a href="/new">새 공지</a></td><td>2026-05-26</td><td>3</td></tr></tbody></table>'''
    result = check_list_freshness(html, target_id="nihhs", list_url="https://example.test/notice", reference_date=date(2026, 8, 25), list_type="table", rules=RULES)
    assert result.latest_published_date == "2026-05-26"
    assert result.latest_title == "새 공지"
    assert result.verdict == "정상"
    assert result.valid_date_count == 2


def test_card_list_time_and_css_selectors():
    html = '''<div class="board"><div class="card"><a class="title" href="/a">A</a><time class="published">2026. 5. 25.</time></div>
    <div class="card"><a class="title" href="/b">B</a><time class="published">2026. 6. 1.</time></div></div>'''
    selectors = {"container": [".board"], "row": [".card"], "title": [".title"], "date": [".published"]}
    result = check_list_freshness(html, target_id="nihhs", list_url="https://example.test/list", reference_date=date(2026, 8, 25), list_type="card", selectors=selectors, rules=RULES)
    assert result.latest_title == "B"
    assert result.items[0].extraction_method == "list_time"


def test_boundary_date_is_delayed_and_next_day_is_normal():
    html = '<ul><li><a href="/a">A</a><span>게시일 2026-05-25</span></li><li><a href="/b">B</a><span>게시일 2026-05-20</span></li></ul>'
    boundary = check_list_freshness(html, target_id="nihhs", list_url="https://example.test/list", reference_date=date(2026, 8, 25), list_type="list", rules=RULES)
    assert boundary.boundary_date == "2026-05-25"
    assert boundary.verdict == "검토 필요"
    html_next = html.replace("2026-05-25", "2026-05-26")
    assert check_list_freshness(html_next, target_id="nihhs", list_url="https://example.test/list", reference_date=date(2026, 8, 25), list_type="list", rules=RULES).verdict == "정상"


def test_month_end_and_leap_year_calendar_math():
    assert subtract_calendar_months(date(2026, 5, 31), 3) == date(2026, 2, 28)
    assert subtract_calendar_months(date(2024, 5, 31), 3) == date(2024, 2, 29)
    assert subtract_calendar_months(date(2026, 3, 30), 3) == date(2025, 12, 30)


def test_invalid_dates_are_counted_and_valid_date_still_selected():
    html = '<div class="item"><a href="/bad">Bad</a><span>게시일 2026-02-30</span></div><div class="item"><a href="/ok">OK</a><span>게시일 2026-05-26</span></div>'
    result = check_list_freshness(html, target_id="nihhs", list_url="https://example.test/list", reference_date=date(2026, 8, 25), list_type="card", rules=RULES)
    assert result.valid_date_count == 1
    assert result.parse_failure_count == 1
    assert result.latest_title == "OK"


def test_future_date_requires_manual_review_and_is_not_latest():
    html = '<ul><li><a href="/future">Future</a><span>게시일 2026-09-01</span></li><li><a href="/old">Old</a><span>게시일 2026-05-26</span></li></ul>'
    result = check_list_freshness(html, target_id="nihhs", list_url="https://example.test/list", reference_date=date(2026, 8, 25), list_type="list", rules=RULES)
    assert result.verdict == "수동확인 필요"
    assert result.manual_review_required is True
    assert result.latest_title == "Old"


def test_empty_list_and_unknown_list_are_not_false_delays():
    empty = check_list_freshness('<p>등록된 게시물이 없습니다.</p>', target_id="nihhs", list_url="https://example.test/list", reference_date=date(2026, 8, 25), list_type="list", rules=RULES)
    assert empty.verdict == "검토 필요" and empty.latest_published_date is None
    unknown = check_list_freshness('<div><a href="/x">일반 링크</a></div>', target_id="nihhs", list_url="https://example.test/links", reference_date=date(2026, 8, 25), rules=RULES)
    assert unknown.verdict == "수동확인 필요"


def test_excluded_areas_and_non_post_dates_are_not_lists():
    for list_type, html in [("history", '<ul><li>2020년 연혁</li><li>2021년 연혁</li></ul>'), ("calendar", '<div>2026-08-25 달력</div>'), ("menu", '<nav><li>2026 안내</li><li>2025 안내</li></nav>')]:
        result = check_list_freshness(html, target_id="nihhs", list_url="https://example.test/x", reference_date=date(2026, 8, 25), list_type=list_type, rules=RULES)
        assert result.verdict == "해당 없음"


def test_event_period_views_and_footer_year_do_not_become_post_dates():
    html = '<div class="item"><a href="/event">행사</a><span>행사기간 2026-08-01 ~ 2026-08-31</span><span>조회수 12</span></div><div class="item"><a href="/event2">행사2</a><footer>Copyright 2026</footer></div>'
    result = check_list_freshness(html, target_id="nihhs", list_url="https://example.test/events", reference_date=date(2026, 8, 25), list_type="card", rules=RULES)
    assert result.valid_date_count == 0
    assert result.verdict == "점검 불가"


def test_state_payload_keeps_list_results_separate():
    result = check_list_freshness('<ul><li><a href="/a">A</a><time>2026-08-24</time></li><li><a href="/b">B</a><time>2026-08-23</time></li></ul>', target_id="nihhs", list_url="https://example.test/list", reference_date=date(2026, 8, 25), list_type="list", rules=RULES)
    payload = list_freshness_state_payload([result])
    assert payload["issue_type"] == "list_freshness"
    assert payload["results"][0]["latest_published_date"] == "2026-08-24"
