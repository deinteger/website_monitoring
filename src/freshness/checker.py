"""Pure HTML date extraction and conservative content freshness assessment."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup


DATE_KINDS = ("published", "modified")
DATE_METHODS = ("time_datetime", "article_meta", "json_ld", "label", "configured_selector", "body_pattern")
DATE_PATTERN = re.compile(r"(?P<year>\d{4})\s*(?:[-./년]\s*)\s*(?P<month>\d{1,2})\s*(?:[-./월]\s*)\s*(?P<day>\d{1,2})\s*(?:일)?")


@dataclass
class DateExtraction:
    date_kind: str
    original_text: str = ""
    normalized_date: str | None = None
    extraction_method: str = ""
    evidence_location: str = ""
    evidence_text: str = ""
    confidence: float = 0.0
    parse_success: bool = False
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContentFreshnessResult:
    target_id: str
    url: str
    page_type: str
    applicability: str
    published: DateExtraction
    modified: DateExtraction
    reference_date: str
    review_days: int
    elapsed_days: int | None
    verdict: str
    reason: str
    extraction_evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    manual_review_required: bool = False
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["published"] = self.published.to_dict()
        value["modified"] = self.modified.to_dict()
        return value


def _parse_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    iso = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        pass
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    try:
        return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None


def _parsed(kind: str, original: str, method: str, location: str, evidence: str, confidence: float) -> DateExtraction:
    parsed = _parse_date(original)
    if parsed is None:
        return DateExtraction(kind, original, None, method, location, evidence, confidence, False, "지원하지 않는 날짜 형식 또는 잘못된 날짜")
    return DateExtraction(kind, original, parsed.isoformat(), method, location, evidence, confidence, True)


def _kind_from_text(text: str, labels: Mapping[str, Iterable[str]]) -> str | None:
    lowered = text.lower()
    for kind in ("modified", "published"):
        if any(str(label).lower() in lowered for label in labels.get(kind, ())):
            return kind
    return None


def _empty(kind: str, reason: str = "해당 날짜를 찾지 못함") -> DateExtraction:
    return DateExtraction(date_kind=kind, failure_reason=reason)


def _choose(found: dict[str, DateExtraction], candidate: DateExtraction) -> None:
    if candidate.date_kind not in found or not found[candidate.date_kind].parse_success:
        found[candidate.date_kind] = candidate


def extract_dates(html: str, *, selectors: Mapping[str, Iterable[str]] | None = None,
                 labels: Mapping[str, Iterable[str]] | None = None, page_type: str = "detail") -> dict[str, DateExtraction]:
    """Extract one publication and modification date; list pages are not page-date sources."""
    found: dict[str, DateExtraction] = {}
    if page_type.lower() in {"list", "listing", "search"}:
        return {kind: _empty(kind, "목록형 페이지의 행별 날짜는 이번 점검 대상이 아님") for kind in DATE_KINDS}
    labels = labels or {"published": ("게시일", "등록일", "작성일", "발행일"), "modified": ("수정일", "최종수정일", "변경일", "갱신일")}
    selectors = selectors or {}
    soup = BeautifulSoup(html or "", "html.parser")

    # 1. Explicit time elements, using a nearby label when available.
    for index, element in enumerate(soup.find_all("time")):
        raw = element.get("datetime") or element.get_text(" ", strip=True)
        nearby = []
        sibling = element.previous_sibling
        for _ in range(3):
            if sibling is None:
                break
            text = sibling.get_text(" ", strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
            if text:
                nearby.append(text)
            sibling = sibling.previous_sibling
        context = " ".join(reversed(nearby)) + " " + (element.get("class", [""])[0] if element.get("class") else "")
        kind = _kind_from_text(context, labels) or ("published" if "published" not in found else "modified")
        _choose(found, _parsed(kind, raw, "time_datetime" if element.get("datetime") else "label", f"time[{index}]", context, 0.98 if element.get("datetime") else 0.88))

    # 2. Open Graph article metadata.
    for kind, property_name in (("published", "article:published_time"), ("modified", "article:modified_time")):
        if kind in found and found[kind].parse_success:
            continue
        meta = soup.find("meta", attrs={"property": property_name}) or soup.find("meta", attrs={"name": property_name})
        if meta and meta.get("content"):
            _choose(found, _parsed(kind, meta["content"], "article_meta", f"meta[{property_name}]", meta["content"], 0.96))

    # 3. JSON-LD objects, including @graph arrays.
    def walk_json(value: Any):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk_json(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk_json(child)

    for script_index, script in enumerate(soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)})):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        for obj in walk_json(data):
            for kind, key in (("published", "datePublished"), ("modified", "dateModified")):
                if kind not in found or not found[kind].parse_success:
                    raw = obj.get(key) if isinstance(obj, dict) else None
                    if raw:
                        _choose(found, _parsed(kind, str(raw), "json_ld", f"script[{script_index}].{key}", str(raw), 0.94))

    # 4/5. Explicit labels and configured selectors.
    for element in soup.find_all(string=True):
        text = str(element).strip()
        kind = _kind_from_text(text, labels)
        if not kind or (kind in found and found[kind].parse_success):
            continue
        surrounding = element.parent.get_text(" ", strip=True) if element.parent else text
        match = DATE_PATTERN.search(surrounding)
        if match:
            _choose(found, _parsed(kind, match.group(0), "label", "label", surrounding, 0.90))
    for kind in DATE_KINDS:
        if kind in found and found[kind].parse_success:
            continue
        for selector in selectors.get(kind, ()):
            element = soup.select_one(selector)
            if element:
                raw = element.get("datetime") or element.get_text(" ", strip=True)
                _choose(found, _parsed(kind, raw, "configured_selector", selector, element.get_text(" ", strip=True), 0.86))
                break

    return {kind: found.get(kind, _empty(kind)) for kind in DATE_KINDS}


def determine_applicability(url: str, page_type: str, rules: Mapping[str, Any] | None = None) -> str:
    normalized_type = (page_type or "").lower()
    if normalized_type in {"list", "listing", "search", "static", "guide", "institution", "facility"}:
        return "not_required"
    if normalized_type in {"detail", "notice", "post", "press", "article", "news"}:
        return "required"
    patterns = (rules or {}).get("content_type_patterns", {})
    path = urlparse(url).path.lower()
    if any(str(pattern).lower() in path for pattern in patterns.get("required", ())):
        return "required"
    if any(str(pattern).lower() in path for pattern in patterns.get("not_required", ())):
        return "not_required"
    return "uncertain"


def check_content_freshness(html: str, *, target_id: str, url: str, page_type: str = "unknown",
                            reference_date: date, rules: Mapping[str, Any] | None = None,
                            selectors: Mapping[str, Iterable[str]] | None = None,
                            checked_at: str = "") -> ContentFreshnessResult:
    rules = rules or {}
    applicability = determine_applicability(url, page_type, rules)
    freshness = rules.get("freshness", rules)
    labels = freshness.get("date_labels")
    extra_selectors = selectors or freshness.get("date_selectors", {})
    dates = extract_dates(html, selectors=extra_selectors, labels=labels, page_type=page_type)
    published, modified = dates["published"], dates["modified"]
    review_days = int(freshness.get("default_review_days", 730))
    evidence = [item.to_dict() for item in (published, modified) if item.parse_success]
    if applicability == "not_required":
        return ContentFreshnessResult(target_id, url, page_type, applicability, published, modified, reference_date.isoformat(), review_days, None, "해당 없음", "날짜 비적용 페이지", evidence, 0.0, False, checked_at)
    if applicability == "uncertain":
        return ContentFreshnessResult(target_id, url, page_type, applicability, published, modified, reference_date.isoformat(), review_days, None, "수동확인 필요", "페이지 유형이 불확실함", evidence, min((item.confidence for item in dates.values() if item.parse_success), default=0.0), True, checked_at)
    effective = modified if modified.parse_success else published
    if not effective.parse_success or not effective.normalized_date:
        return ContentFreshnessResult(target_id, url, page_type, applicability, published, modified, reference_date.isoformat(), review_days, None, "점검 불가", effective.failure_reason or "게시일·수정일을 추출하지 못함", evidence, 0.0, False, checked_at)
    effective_date = date.fromisoformat(effective.normalized_date)
    elapsed = (reference_date - effective_date).days
    future_tolerance = int(freshness.get("future_tolerance_days", 1))
    page_text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True).lower()
    archive_keywords = [str(value).lower() for value in freshness.get("archive_keywords", ("연혁", "지난자료", "아카이브"))]
    archived = any(keyword in (url.lower() + " " + page_text) for keyword in archive_keywords)
    if archived:
        verdict, reason = "정상", "아카이브·연혁·지난자료 보존 예외"
    elif elapsed < -future_tolerance:
        verdict, reason = "검토 필요", "기준일보다 허용범위를 초과한 미래 날짜"
    elif elapsed >= review_days:
        verdict, reason = "검토 필요", f"기준일로부터 {elapsed}일 경과(검토 기준 {review_days}일)"
    else:
        verdict, reason = "정상", f"기준일로부터 {max(elapsed, 0)}일 경과"
    return ContentFreshnessResult(target_id, url, page_type, applicability, published, modified, reference_date.isoformat(), review_days, elapsed, verdict, reason, evidence, effective.confidence, False, checked_at)


def freshness_state_payload(results: Iterable[ContentFreshnessResult]) -> dict[str, Any]:
    """Build the JSON-compatible issues payload without touching inventory state."""
    values = list(results)
    return {"schema_version": "1.0", "issue_type": "content_freshness", "results": [item.to_dict() for item in values],
            "counts": {verdict: sum(1 for item in values if item.verdict == verdict)
                       for verdict in sorted({item.verdict for item in values})}}
