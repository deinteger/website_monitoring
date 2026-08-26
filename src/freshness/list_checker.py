"""First-page list freshness checks using calendar-month arithmetic."""

from __future__ import annotations

import calendar
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .checker import DATE_PATTERN, _parse_date


POSTED_LABELS = ("게시일", "등록일", "작성일", "발행일")
EXCLUDED_DATE_CONTEXT = ("수정일", "최종수정", "행사기간", "접수기간", "조회수", "첨부")
DEFAULT_EMPTY_PHRASES = ("게시물이 없습니다", "등록된 게시물이 없습니다", "검색 결과가 없습니다", "조회된 결과가 없습니다")


@dataclass
class ListItemDate:
    original_text: str
    normalized_date: str | None
    title: str
    url: str
    location: str
    extraction_method: str
    confidence: float
    parse_success: bool
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ListFreshnessResult:
    target_id: str
    list_title: str
    list_url: str
    menu_path: str
    list_type: str
    list_applicability: str
    valid_date_count: int
    parse_failure_count: int
    latest_title: str
    latest_url: str
    latest_published_date: str | None
    reference_date: str
    calendar_months: int
    boundary_date: str
    verdict: str
    issue_type: str | None
    reason: str
    extraction_method: str
    confidence: float
    scope: str
    manual_review_required: bool
    items: list[ListItemDate] = field(default_factory=list)
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["items"] = [item.to_dict() for item in self.items]
        return value


def subtract_calendar_months(value: date, months: int) -> date:
    """Subtract calendar months, clamping the day to the target month's end."""
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _date_from_text(text: str) -> tuple[str, date | None]:
    match = DATE_PATTERN.search(text)
    if not match:
        return "", None
    raw = match.group(0)
    return raw, _parse_date(raw)


def _item_from_node(node, *, base_url: str, location: str, title_selector: str | None = None,
                   link_selector: str | None = None, date_selector: str | None = None) -> ListItemDate:
    text = node.get_text(" ", strip=True)
    date_node = node.select_one(date_selector) if date_selector else node.find("time")
    candidate = date_node.get("datetime") if date_node and date_node.get("datetime") else (date_node.get_text(" ", strip=True) if date_node else text)
    if any(term in text for term in EXCLUDED_DATE_CONTEXT) and not any(label in text for label in POSTED_LABELS):
        candidate = ""
    original, parsed = _date_from_text(candidate)
    if date_node and date_node.get("datetime"):
        original = date_node.get("datetime")
        parsed = _parse_date(original)
    title_node = node.select_one(title_selector) if title_selector else node.find(["h1", "h2", "h3", "h4", "a"])
    link_node = node.select_one(link_selector) if link_selector else node.find("a", href=True)
    title = title_node.get_text(" ", strip=True) if title_node else ""
    url = urljoin(base_url, link_node.get("href")) if link_node and link_node.get("href") else ""
    if parsed is None:
        return ListItemDate(original or candidate, None, title, url, location, "list_date", 0.0, False, "게시일을 파싱하지 못함")
    return ListItemDate(original, parsed.isoformat(), title, url, location, "list_time" if date_node else "list_label", 0.90 if date_node else 0.82, True)


def _selectors(value: Mapping[str, Iterable[str]] | None, key: str) -> list[str]:
    return [str(item) for item in (value or {}).get(key, ())]


def _automatic_rows(soup: BeautifulSoup):
    rows = []
    for selector in ("table tbody tr", "article", ".item", ".card", "li"):
        candidates = soup.select(selector)
        if len(candidates) >= 2:
            rows = candidates
            break
    return rows


def check_list_freshness(html: str, *, target_id: str, list_url: str, reference_date: date,
                         list_title: str = "", menu_path: str = "", list_type: str = "unknown",
                         selectors: Mapping[str, Iterable[str]] | None = None,
                         rules: Mapping[str, Any] | None = None, checked_at: str = "") -> ListFreshnessResult:
    rules = rules or {}
    freshness = rules.get("freshness", rules)
    months = int(freshness.get("list_calendar_months", freshness.get("list_latest_calendar_months", 3)))
    boundary = subtract_calendar_months(reference_date, months)
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text(" ", strip=True)
    phrases = tuple(freshness.get("list_empty_phrases", DEFAULT_EMPTY_PHRASES))
    selector_map = selectors or {}
    container = soup.select_one(_selectors(selector_map, "container")[0]) if _selectors(selector_map, "container") else soup
    if any(phrase in text for phrase in phrases):
        return ListFreshnessResult(target_id, list_title, list_url, menu_path, list_type, "required", 0, 0, "", "", None,
                                   reference_date.isoformat(), months, boundary.isoformat(), "검토 필요", None,
                                   "빈 목록 문구 확인", "", 0.88, "첫 화면만 점검(다음 페이지 미탐색)", False, [], checked_at)
    row_selectors = _selectors(selector_map, "row")
    rows = container.select(row_selectors[0]) if row_selectors else []
    if not rows and not selector_map:
        rows = _automatic_rows(soup)
    if list_type.lower() in {"calendar", "history", "table_stat", "menu", "gallery"} or any(term in text.lower() for term in ("연혁", "달력", "관련 사이트")):
        rows = []
        applicability = "not_required"
    elif len(rows) >= 2:
        applicability = "required"
    else:
        applicability = "uncertain"
    if applicability == "not_required":
        return ListFreshnessResult(target_id, list_title, list_url, menu_path, list_type, applicability, 0, 0, "", "", None,
                                   reference_date.isoformat(), months, boundary.isoformat(), "해당 없음", None,
                                   "목록형 점검 제외 영역", "", 0.90, "첫 화면만 점검(다음 페이지 미탐색)", False, [], checked_at)
    if not rows:
        return ListFreshnessResult(target_id, list_title, list_url, menu_path, list_type, applicability, 0, 0, "", "", None,
                                   reference_date.isoformat(), months, boundary.isoformat(), "수동확인 필요", None,
                                   "목록 구조를 확정하지 못함", "", 0.0, "첫 화면만 점검(다음 페이지 미탐색)", True, [], checked_at)
    title_selector = _selectors(selector_map, "title")
    link_selector = _selectors(selector_map, "link")
    date_selector = _selectors(selector_map, "date")
    if not date_selector and rows and rows[0].find_parent("table"):
        table = rows[0].find_parent("table")
        headers = [header.get_text(" ", strip=True).lower() for header in table.select("thead th")]
        date_index = next((index for index, header in enumerate(headers) if any(label in header for label in POSTED_LABELS)), None)
        if date_index is not None:
            date_selector = [f"td:nth-of-type({date_index + 1})"]
    items = [_item_from_node(row, base_url=list_url, location=f"row[{index}]", title_selector=title_selector[0] if title_selector else None,
                             link_selector=link_selector[0] if link_selector else None, date_selector=date_selector[0] if date_selector else None)
             for index, row in enumerate(rows)]
    valid = [item for item in items if item.parse_success]
    failures = len(items) - len(valid)
    future = [item for item in valid if date.fromisoformat(item.normalized_date) > reference_date]
    usable = [item for item in valid if item not in future]
    if future:
        verdict, issue, reason, manual = "수동확인 필요", None, "미래 게시일이 포함됨", True
    elif not valid:
        verdict, issue, reason, manual = "점검 불가", None, "유효한 게시일을 추출하지 못함", False
    elif not usable:
        verdict, issue, reason, manual = "수동확인 필요", None, "미래 게시일만 존재함", True
    else:
        latest = max(usable, key=lambda item: item.normalized_date)
        if date.fromisoformat(latest.normalized_date) <= boundary:
            verdict, issue, reason, manual = "검토 필요", str(freshness.get("list_latest_issue_type", "게시 최신성 지연")), f"최신 게시일이 {boundary.isoformat()} 이하", False
        else:
            verdict, issue, reason, manual = "정상", None, f"최신 게시일이 {boundary.isoformat()} 이후", False
    latest = max(usable, key=lambda item: item.normalized_date) if usable else None
    return ListFreshnessResult(target_id, list_title, list_url, menu_path, list_type, applicability, len(valid), failures,
                               latest.title if latest else "", latest.url if latest else "", latest.normalized_date if latest else None,
                               reference_date.isoformat(), months, boundary.isoformat(), verdict, issue, reason,
                               latest.extraction_method if latest else "", latest.confidence if latest else 0.0,
                               "첫 화면만 점검(다음 페이지 미탐색)", manual, items, checked_at)


def list_freshness_state_payload(results: Iterable[ListFreshnessResult]) -> dict[str, Any]:
    values = list(results)
    return {"schema_version": "1.0", "issue_type": "list_freshness", "results": [item.to_dict() for item in values],
            "counts": {verdict: sum(1 for item in values if item.verdict == verdict)
                       for verdict in sorted({item.verdict for item in values})}}
