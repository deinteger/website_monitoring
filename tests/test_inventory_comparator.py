from copy import deepcopy

from src.inventory.comparator import compare_inventory


FP = "policy-a"


def record(url, *, title="Title", sources=None, menu=None, classification="internal", other=None, discovered="page"):
    return {
        "target_id": "nihhs", "normalized_url": url, "classification": classification,
        "other_target_id": other, "original_urls": [url], "discovery_sources": sources or ["main_menu"],
        "menu_paths": menu or ["Home"], "discovered_from": [discovered], "titles": [title],
        "link_texts": [title], "first_discovered_at": "2026-01-01T00:00:00+00:00",
        "last_discovered_at": "2026-01-01T00:00:00+00:00",
    }


def payload(records, *, source_ok=True, request_count=3, fingerprint=FP, run_id="run"):
    return {
        "raw": {
            "run_id": run_id, "request_count": request_count,
            "sources": [
                {"source": "main_menu", "success": source_ok},
                {"source": "all_menu", "success": source_ok},
                {"source": "sitemap", "success": source_ok},
            ],
        },
        "normalized": {"schema_version": "1.0", "policy_fingerprint": fingerprint, "records": records},
    }


def test_first_run_creates_baseline_without_new_or_deleted_counts():
    result = compare_inventory(None, payload([record("/a"), record("/b")]), target_id="nihhs", max_requests=10)
    assert result.status == "기준자료 생성"
    assert result.baseline_updated is True
    assert result.counts["신규"] == result.counts["삭제"] == 0


def test_identical_runs_have_no_changes_and_ignore_discovery_time():
    old = payload([record("/a")], run_id="old")
    current = deepcopy(old)
    current["raw"]["run_id"] = "new"
    current["normalized"]["records"][0]["last_discovered_at"] = "2026-02-02T00:00:00+00:00"
    result = compare_inventory(old, current, target_id="nihhs", max_requests=10)
    assert result.counts["유지"] == 1 and result.counts["변경"] == 0


def test_new_and_confirmed_delete_when_all_sources_are_healthy():
    result = compare_inventory(payload([record("/old")]), payload([record("/new")]), target_id="nihhs", max_requests=10)
    statuses = {item["status"] for item in result.records}
    assert {"신규", "삭제"} <= statuses
    assert result.counts["삭제 확인 필요"] == 0


def test_source_failure_or_request_limit_prevents_delete_confirmation():
    old = payload([record("/old")])
    failed = payload([record("/new")], source_ok=False)
    limited = payload([record("/new")], request_count=10)
    for current in (failed, limited):
        result = compare_inventory(old, current, target_id="nihhs", max_requests=10)
        assert result.counts["삭제 확인 필요"] == 1
        assert result.baseline_updated is False


def test_title_menu_source_and_classification_changes_are_reported():
    old_record = record("/a", title="Old", sources=["main_menu"], menu=["One"])
    new_record = record("/a", title="New", sources=["sitemap"], menu=["Two"], classification="external", other="fruit")
    result = compare_inventory(payload([old_record]), payload([new_record]), target_id="nihhs", max_requests=10)
    changed = next(item for item in result.records if item["status"] == "변경")
    assert {"titles", "menu_paths", "discovery_sources", "classification", "other_target_id"} <= set(changed["changed_fields"])
    assert changed["change_scope"] == "메뉴·인벤토리 구조 변경"


def test_original_expression_and_source_order_do_not_create_change():
    old_record = record("/a", sources=["main_menu", "sitemap"], menu=["One", "Two"])
    new_record = deepcopy(old_record)
    new_record["original_urls"] = ["HTTPS://EXAMPLE.test:443/a#x"]
    new_record["discovery_sources"] = ["sitemap", "main_menu"]
    new_record["menu_paths"] = ["Two", "One"]
    result = compare_inventory(payload([old_record]), payload([new_record]), target_id="nihhs", max_requests=10)
    assert result.counts["변경"] == 0


def test_sitemap_only_internal_page_is_menu_outside_and_failures_make_it_unknown():
    sitemap_only = record("/sitemap-only", sources=["sitemap"])
    healthy = compare_inventory(payload([sitemap_only]), payload([sitemap_only]), target_id="nihhs", max_requests=10)
    assert healthy.counts["메뉴 외 페이지"] == 1
    failed = compare_inventory(payload([sitemap_only]), payload([sitemap_only], source_ok=False), target_id="nihhs", max_requests=10)
    assert failed.counts["메뉴 외 페이지"] == 0
    assert any(item["status"] == "메뉴 연결 여부 점검 불가" for item in failed.records)


def test_external_invalid_non_http_are_not_menu_outside():
    records = [record("https://outside/a", classification="external", sources=["sitemap"]),
               record("invalid:x", classification="invalid", sources=["sitemap"]),
               record("mailto:a", classification="non_http", sources=["sitemap"])]
    result = compare_inventory(payload(records), payload(records), target_id="nihhs", max_requests=10)
    assert result.counts["메뉴 외 페이지"] == 0


def test_policy_mismatch_and_target_mismatch_are_not_compared():
    mismatch = compare_inventory(payload([record("/a")], fingerprint="old"), payload([record("/a")]), target_id="nihhs", max_requests=10)
    assert mismatch.status == "비교 불가" and mismatch.baseline_updated is False
    other_target = compare_inventory(payload([record("/a")]), payload([record("/a")]), target_id="fruit", max_requests=10)
    assert other_target.status == "비교 불가"
