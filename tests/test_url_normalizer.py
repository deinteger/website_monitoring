from types import SimpleNamespace

import pytest

from src.inventory.url_normalizer import (
    NormalizationPolicy,
    classify_url,
    merge_occurrences,
    normalize_url,
    policy_from_config,
    upgrade_inventory_state,
)


BASE = "https://Example.test/base/page.html"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../a/./b/", "https://example.test/a/b/"),
        ("HTTPS://EXAMPLE.TEST:443", "https://example.test/"),
        ("/x#section", "https://example.test/x"),
        ("/x?utm_source=x&b=2&sessionid=abc", "https://example.test/x?b=2"),
        ("/한글 문서", "https://example.test/%ED%95%9C%EA%B8%80%20%EB%AC%B8%EC%84%9C"),
    ],
)
def test_normalize_url_examples(raw, expected):
    assert normalize_url(raw, BASE, NormalizationPolicy(ignored_query_parameters=frozenset({"utm_source", "sessionid"})))[0] == expected


def test_port_fragment_empty_path_and_dot_segments():
    policy = NormalizationPolicy(trailing_slash="remove")
    value, removed = normalize_url("http://EXAMPLE.test:80/a/../b/#x", None, policy)
    assert value == "http://example.test/b"
    assert removed == ()


def test_trailing_slash_and_query_sort_are_explicit_policies():
    remove = NormalizationPolicy(trailing_slash="remove", sort_query_parameters=True)
    add = NormalizationPolicy(trailing_slash="add", sort_query_parameters=True)
    assert normalize_url("https://example.test/a/?z=2&a=1&z=3", policy=remove)[0] == "https://example.test/a?a=1&z=2&z=3"
    assert normalize_url("https://example.test/a?a=1", policy=add)[0] == "https://example.test/a/?a=1"


def test_classify_internal_external_managed_non_http_and_invalid():
    managed = {"fruit": ["fruit.example.test"]}
    assert classify_url("/x", base_url=BASE).kind == "internal"
    assert classify_url("https://outside.test/x", base_url=BASE).kind == "external"
    other = classify_url("https://fruit.example.test/x", base_url=BASE, managed_targets=managed)
    assert other.kind == "external" and other.other_target_id == "fruit"
    assert classify_url("mailto:a@example.test", base_url=BASE).kind == "non_http"
    assert classify_url("tel:123", base_url=BASE).kind == "non_http"
    assert classify_url("javascript:void(0)", base_url=BASE).kind == "non_http"
    assert classify_url("data:text/plain,x", base_url=BASE).kind == "non_http"
    assert classify_url("https:///broken", base_url=BASE).kind == "invalid"


def occurrence(raw, source="main_menu", title="Title", path="1차", discovered="https://example.test/base/page.html", at="2026-01-02T00:00:00+00:00"):
    return SimpleNamespace(original_url=raw, source=source, title=title, menu_path=path, discovered_from=discovered, discovered_at=at)


def test_merge_deduplicates_deterministically_and_preserves_all_discovery_fields():
    items = [
        occurrence("/x?utm_source=a", "main_menu", "Z title", "z", at="2026-01-02T00:00:00+00:00"),
        occurrence("https://EXAMPLE.test/x#part", "sitemap", "A title", "a", at="2026-01-03T00:00:00+00:00"),
        occurrence("/x", "all_menu", "M title", "m", at="2026-01-02T12:00:00+00:00"),
        occurrence("https://outside.test/x", "sitemap", "External", "", at="2026-01-04T00:00:00+00:00"),
    ]
    result = merge_occurrences(items, target_id="nihhs", base_url=BASE,
                               policy=NormalizationPolicy(ignored_query_parameters=frozenset({"utm_source"})))
    internal = next(record for record in result.records if record.classification == "internal")
    assert result.original_url_count == 4
    assert result.normalized_url_count == 2
    assert result.duplicate_removed_count == 2
    assert result.counts == {"internal": 1, "external": 1, "invalid": 0, "non_http": 0}
    assert internal.discovery_sources == {"main_menu", "sitemap", "all_menu"}
    assert internal.menu_paths == {"z", "a", "m"}
    assert internal.titles == {"Z title", "A title", "M title"}
    assert internal.first_discovered_at.startswith("2026-01-02T00")
    assert internal.last_discovered_at.startswith("2026-01-03")
    assert result.excluded_query_parameters == ["utm_source"]


def test_same_normalized_path_different_targets_stays_separate():
    one = merge_occurrences([occurrence("/x")], target_id="nihhs", base_url="https://one.test")
    two = merge_occurrences([occurrence("/x")], target_id="fruit", base_url="https://two.test")
    assert one.records[0].target_id != two.records[0].target_id


def test_config_policy_and_legacy_state_compatibility():
    policy = policy_from_config({"ignored_query_parameters": ["UTM"], "url_normalization": {"trailing_slash": "remove", "sort_query_parameters": True, "excluded_schemes": ["data"]}})
    assert policy.ignored_query_parameters == {"utm"}
    legacy = {"nihhs": {"target_id": "nihhs", "records": []}}
    upgraded = upgrade_inventory_state(legacy)
    assert upgraded["nihhs"]["schema_version"] == "legacy"
    assert upgraded["nihhs"]["raw"] == legacy["nihhs"]
