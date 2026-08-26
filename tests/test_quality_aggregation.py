from src.quality.aggregation import aggregate_page, issue_key, reconcile_issues, site_stats


def test_verdicts_and_excluded():
    base = {"required": True}
    assert aggregate_page("t", "u", {"a": {**base, "result": "정상"}}).verdict == "정상"
    assert aggregate_page("t", "u", {"a": {**base, "result": "검토 필요"}}).verdict == "검토 필요"
    assert aggregate_page("t", "u", {"a": {**base, "result": "오류"}}).verdict == "오류"
    assert aggregate_page("t", "u", {"a": {**base, "result": "점검 불가"}}).verdict == "점검 불가"
    assert aggregate_page("t", "u", {}, excluded=True).verdict == "제외"


def test_required_optional_and_completeness():
    r = aggregate_page("t", "u", {"a": {"result": "정상", "required": True}, "b": {"result": "미실행", "required": True}, "c": {"result": "점검 불가", "required": False}})
    assert r.required_count == 2 and r.performed_required_count == 1
    assert r.completeness_ratio == .5 and r.verdict == "정상"


def test_deterministic_issue_key():
    assert issue_key("t", "u", "c", "x", "p") == issue_key("t", "u", "c", "x", "p")
    assert issue_key("t", "u", "c") != issue_key("other", "u", "c")


def test_issue_lifecycle_new_continued_changed_resolved_recurred():
    k = issue_key("t", "u", "c")
    first = reconcile_issues({}, [{"issue_key": k, "result": "오류", "evidence": "a"}], now="1")
    assert first["active_issues"][0]["lifecycle_status"] == "신규"
    same = reconcile_issues(first, [{"issue_key": k, "result": "오류", "evidence": "a"}], now="2")
    assert same["active_issues"][0]["lifecycle_status"] == "지속"
    changed = reconcile_issues(same, [{"issue_key": k, "result": "오류", "evidence": "b"}], now="3")
    assert changed["active_issues"][0]["lifecycle_status"] == "변경"
    resolved = reconcile_issues(changed, [], now="4")
    assert resolved["resolved_issues"][-1]["lifecycle_status"] == "해결"
    recurred = reconcile_issues(resolved, [{"issue_key": k, "result": "오류"}], now="5")
    assert recurred["active_issues"][0]["lifecycle_status"] == "재발"


def test_partial_failure_blocks_resolution():
    k = issue_key("t", "u", "c")
    old = reconcile_issues({}, [{"issue_key": k, "result": "오류"}])
    out = reconcile_issues(old, [], execution_healthy=False)
    assert out["active_issues"][0]["lifecycle_status"] != "해결"


def test_manual_exception_and_false_positive_preserved():
    k = issue_key("t", "u", "c")
    old = {"active_issues": [{"issue_key": k, "manual_status": "예외"}], "manual_issues": []}
    out = reconcile_issues(old, [{"issue_key": k, "result": "오류"}])
    assert out["manual_issues"][0]["manual_status"] == "예외"


def test_site_stats_sum():
    s = site_stats([{"verdict": "정상"}, {"verdict": "오류"}, {"verdict": "검토 필요"}])
    assert s["pages_total"] == sum(s["verdict_counts"].values()) == 3


def test_legacy_issues_compatibility():
    k = issue_key("t", "u", "c")
    out = reconcile_issues({"issues": [{"issue_key": k, "lifecycle_status": "지속"}]}, [], execution_healthy=False)
    assert out["active_issues"][0]["issue_key"] == k
