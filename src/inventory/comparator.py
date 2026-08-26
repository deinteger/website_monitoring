"""Compare normalized inventories without fetching any external resource."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


COMPARISON_SCHEMA_VERSION = "1.0"
CHANGE_FIELDS = (
    "titles", "link_texts", "menu_paths", "discovery_sources", "discovered_from",
    "classification", "other_target_id", "lastmod",
)


@dataclass
class ComparisonResult:
    target_id: str
    status: str
    records: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    previous_run_id: str | None = None
    current_run_id: str | None = None
    baseline_updated: bool = False
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": COMPARISON_SCHEMA_VERSION,
            "target_id": self.target_id,
            "status": self.status,
            "records": self.records,
            "counts": self.counts,
            "previous_run_id": self.previous_run_id,
            "current_run_id": self.current_run_id,
            "baseline_updated": self.baseline_updated,
            "reason": self.reason,
        }


def _normalized(payload: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not payload:
        return None
    value = payload.get("normalized", payload)
    return value if isinstance(value, Mapping) and isinstance(value.get("records", []), list) else None


def _raw(payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not payload:
        return {}
    value = payload.get("raw", payload)
    return value if isinstance(value, Mapping) else {}


def _record_map(normalized: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not normalized:
        return {}
    return {str(item.get("normalized_url")): item for item in normalized.get("records", [])
            if isinstance(item, Mapping) and item.get("normalized_url")}


def _belongs_to_target(normalized: Mapping[str, Any] | None, target_id: str) -> bool:
    if not normalized:
        return False
    return all(not item.get("target_id") or item.get("target_id") == target_id
               for item in normalized.get("records", []) if isinstance(item, Mapping))


def _sources_healthy(payload: Mapping[str, Any] | None, max_requests: int | None) -> tuple[bool, str | None]:
    raw = _raw(payload)
    sources = raw.get("sources")
    if not isinstance(sources, list) or not sources:
        return False, "수집원 상태 정보 없음"
    failed = [str(source.get("source", "unknown")) for source in sources if not source.get("success")]
    if failed:
        return False, "수집원 실패: " + ", ".join(failed)
    if max_requests is not None and isinstance(raw.get("request_count"), int) and raw["request_count"] >= max_requests:
        return False, "요청 상한 도달"
    return True, None


def _policy_compatible(previous: Mapping[str, Any] | None, current: Mapping[str, Any] | None) -> bool:
    if not previous or not current:
        return False
    previous_schema = previous.get("schema_version")
    current_schema = current.get("schema_version")
    if previous_schema != current_schema:
        return False
    previous_policy = previous.get("policy_fingerprint", previous.get("policy_version", ""))
    current_policy = current.get("policy_fingerprint", current.get("policy_version", ""))
    return previous_policy == current_policy


def _changed(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    for field in CHANGE_FIELDS:
        before = previous.get(field)
        after = current.get(field)
        if field in {"titles", "link_texts", "menu_paths", "discovery_sources", "discovered_from"}:
            before = sorted(before or [])
            after = sorted(after or [])
        if before != after:
            changes[field] = {"previous": before, "current": after}
    return changes


def compare_inventory(previous_payload: Mapping[str, Any] | None, current_payload: Mapping[str, Any], *,
                      target_id: str, max_requests: int | None = None) -> ComparisonResult:
    """Compare one target. No network or filesystem access occurs here."""
    current = _normalized(current_payload)
    current_run_id = _raw(current_payload).get("run_id") or current_payload.get("run_id")
    if current is None or not _belongs_to_target(current, target_id):
        return ComparisonResult(target_id, "비교 불가", counts={"비교 불가": 1}, current_run_id=current_run_id,
                                reason="현재 normalized inventory 없음")
    if previous_payload is None:
        records = [{"normalized_url": url, "status": "기준자료"} for url in sorted(_record_map(current))]
        return ComparisonResult(target_id, "기준자료 생성", records=records,
                                counts={"이전 전체 URL": 0, "현재 전체 URL": len(records), "신규": 0, "삭제": 0,
                                        "삭제 확인 필요": 0, "변경": 0, "메뉴 외 페이지": 0, "비교 불가": 0},
                                current_run_id=current_run_id, baseline_updated=True,
                                reason="이전 정상 인벤토리 없음")
    previous = _normalized(previous_payload)
    previous_run_id = _raw(previous_payload).get("run_id") or previous_payload.get("run_id")
    if previous is None or not _belongs_to_target(previous, target_id) or not _policy_compatible(previous, current):
        return ComparisonResult(target_id, "비교 불가", previous_run_id=previous_run_id, current_run_id=current_run_id,
                                counts={"이전 전체 URL": len(_record_map(previous)), "현재 전체 URL": len(_record_map(current)), "비교 불가": 1},
                                reason="정규화 schema 또는 정책 fingerprint 불일치")
    old = _record_map(previous)
    new = _record_map(current)
    healthy, health_reason = _sources_healthy(current_payload, max_requests)
    result_records: list[dict[str, Any]] = []
    counts = {"이전 전체 URL": len(old), "현재 전체 URL": len(new), "유지": 0, "신규": 0, "삭제": 0,
              "삭제 확인 필요": 0, "변경": 0, "메뉴 외 페이지": 0, "비교 불가": 0}
    for url in sorted(new.keys() - old.keys()):
        counts["신규"] += 1
        result_records.append({"normalized_url": url, "status": "신규", "current": new[url]})
    for url in sorted(old.keys() - new.keys()):
        status = "삭제" if healthy else "삭제 확인 필요"
        counts[status] += 1
        result_records.append({"normalized_url": url, "status": status, "previous": old[url],
                               "reason": None if healthy else health_reason})
    for url in sorted(new.keys() & old.keys()):
        changes = _changed(old[url], new[url])
        if changes:
            counts["변경"] += 1
            result_records.append({"normalized_url": url, "status": "변경", "changed_fields": changes,
                                   "previous": old[url], "current": new[url], "change_scope": "메뉴·인벤토리 구조 변경"})
        else:
            counts["유지"] += 1
    if healthy:
        for url, record in sorted(new.items()):
            if record.get("classification") == "internal" and set(record.get("discovery_sources", [])) <= {"sitemap"}:
                counts["메뉴 외 페이지"] += 1
                result_records.append({"normalized_url": url, "status": "메뉴 외 페이지", "current": record})
    elif any(record.get("classification") == "internal" and set(record.get("discovery_sources", [])) <= {"sitemap"} for record in new.values()):
        counts["비교 불가"] += 1
        result_records.append({"status": "메뉴 연결 여부 점검 불가", "reason": health_reason})
    status = "정상 비교" if healthy else "비교 불가"
    return ComparisonResult(target_id, status, result_records, counts, previous_run_id, current_run_id,
                            baseline_updated=healthy, reason=health_reason)
