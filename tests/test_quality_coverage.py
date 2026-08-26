from src.quality.coverage import build_coverage, failure_detail, screenshot_decision, coverage_state_payload

def test_coverage_counts_and_completion():
    out = build_coverage([
        {"normalized_url":"a", "classification":"internal"}, {"normalized_url":"b", "duplicate":True, "classification":"external", "excluded":True}],
        [{"source":"main_menu", "status":"성공"}, {"source":"sitemap", "status":"실패"}],
        [{"status":"정상", "required":True}, {"status":"미실행", "required":True}], True)
    assert out["coverage_summary"]["duplicates_removed"] == 1
    assert out["coverage_summary"]["required_check_completion"] == .5
    assert out["coverage_summary"]["request_limit_reached"] is True
    assert len(out["missing_scope"]) >= 2

def test_failure_payload_masks_secrets():
    x = failure_detail("t", "https://x", "HTTP 요청", "timeout", "api_key=secret stack trace", exception_class="TimeoutError")
    assert "secret" not in x["message"] and x["stage"] == "HTTP 요청"

def test_screenshot_decision_reuse_and_force_without_browser():
    issue = {"issue_key":"abc", "target_id":"t", "page_url":"https://x", "lifecycle_status":"지속", "evidence":"same"}
    policy = {"policy_version":"p", "viewport":[1,2]}
    cache = {"abc":{"content_hash":"h", "evidence":"same", "policy_version":"p"}}
    reused = screenshot_decision(issue, policy=policy, cache=cache, content_hash="h", now="2026-08-25T00:00:00+00:00")
    assert reused["reuse"] and not reused["should_capture"]
    forced = screenshot_decision(issue, force=True, policy=policy, cache=cache, content_hash="h", now="2026-08-25T00:00:00+00:00")
    assert forced["should_capture"] and forced["reuse"] is False

def test_state_payload_has_required_sections():
    c = build_coverage()
    p = coverage_state_payload(c, failures=[{"stage":"파싱"}], screenshots=[])
    assert all(k in p for k in ("coverage_summary", "source_coverage", "check_coverage", "missing_scope", "failure_details", "screenshot_evidence"))
