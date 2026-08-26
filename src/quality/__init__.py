"""HTML and accessibility baseline checks."""

from .accessibility import AccessibilityCache, AccessibilityReport, check_page, accessibility_state_payload
from .performance import PageHTTPObservation, PerformanceResult, check_page_performance, performance_state_payload, sitemap_status_payload
from .aggregation import PageCompositeResult, aggregate_page, issue_key, reconcile_issues, site_stats, composite_state_payload
from .coverage import build_coverage, missing_scope, failure_detail, screenshot_decision, coverage_state_payload

__all__ = ["AccessibilityCache", "AccessibilityReport", "check_page", "accessibility_state_payload", "PageHTTPObservation", "PerformanceResult", "check_page_performance", "performance_state_payload", "sitemap_status_payload", "PageCompositeResult", "aggregate_page", "issue_key", "reconcile_issues", "site_stats", "composite_state_payload", "build_coverage", "missing_scope", "failure_detail", "screenshot_decision", "coverage_state_payload"]
