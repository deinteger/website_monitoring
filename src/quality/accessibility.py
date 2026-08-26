"""Browserless HTML/accessibility baseline checks with content-hash caching."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from bs4 import BeautifulSoup


@dataclass
class AccessibilityIssue:
    issue_key: str
    target_id: str
    url: str
    code: str
    name: str
    result: str
    severity: str
    element: str = ""
    location: str = ""
    evidence: str = ""
    recommendation: str = ""
    manual_review_required: bool = False
    related_issue_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AccessibilityReport:
    target_id: str
    url: str
    menu_path: str
    checked_at: str
    content_hash: str
    policy_version: str
    cache_used: bool
    hash_scope: str = ""
    removed_regions: list[str] = field(default_factory=list)
    issues: list[AccessibilityIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["issues"] = [issue.to_dict() for issue in self.issues]
        return value


class AccessibilityCache:
    def __init__(self, data: Mapping[str, Any] | None = None, *, policy_version: str = "accessibility-1") -> None:
        self.entries = dict((data or {}).get("entries", data or {}))
        self.policy_version = policy_version

    @classmethod
    def from_state(cls, state_manager: Any, *, policy_version: str = "accessibility-1") -> "AccessibilityCache":
        return cls(state_manager.load_json("content_hashes.json", {}), policy_version=policy_version)

    def save_state(self, state_manager: Any) -> Any:
        return state_manager.save_json("content_hashes.json", self.to_dict())

    def get_reusable(self, url: str, content_hash: str, *, policy_version: str, force: bool = False) -> AccessibilityReport | None:
        entry = self.entries.get(url)
        if force or not entry or entry.get("content_hash") != content_hash or entry.get("policy_version") != policy_version or entry.get("last_result") == "점검 불가":
            return None
        issues = [AccessibilityIssue(**issue) for issue in entry.get("issues", [])]
        return AccessibilityReport(entry.get("target_id", ""), url, entry.get("menu_path", ""), entry.get("checked_at", ""), content_hash, policy_version, True,
                                   entry.get("hash_scope", ""), list(entry.get("removed_regions", [])), issues)

    def update(self, report: AccessibilityReport) -> None:
        self.entries[report.url] = {"target_id": report.target_id, "menu_path": report.menu_path, "content_hash": report.content_hash,
                                    "policy_version": report.policy_version, "checked_at": report.checked_at,
                                    "hash_scope": report.hash_scope, "removed_regions": report.removed_regions,
                                    "last_result": "점검 불가" if any(issue.result == "점검 불가" for issue in report.issues) else "완료",
                                    "issues": [issue.to_dict() for issue in report.issues]}

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "policy_version": self.policy_version, "entries": self.entries}


def build_content_hash(html: str, *, content_selector: str = "", volatile_selectors: Iterable[str] = (),
                       volatile_attributes: Iterable[str] = (), volatile_patterns: Iterable[str] = ()) -> tuple[str, str, list[str]]:
    """Normalize volatile markup before hashing; return hash, scope, and removal evidence."""
    soup = BeautifulSoup(html, "html.parser")
    selected = soup.select_one(content_selector) if content_selector else None
    scope = content_selector if selected else "full_html_fallback"
    root = selected or soup
    removed: list[str] = []
    for selector in volatile_selectors:
        for node in root.select(selector):
            removed.append(selector)
            node.decompose()
    for node in root.find_all(True):
        for attribute in volatile_attributes:
            if node.has_attr(attribute):
                removed.append("@" + attribute)
                del node[attribute]
        for attribute in ("nonce", "data-nonce"):
            if node.has_attr(attribute):
                removed.append("@" + attribute)
                del node[attribute]
    normalized = " ".join(root.decode(formatter="minimal").split())
    for pattern in volatile_patterns:
        try:
            normalized, count = re.subn(pattern, "", normalized)
            if count:
                removed.append("pattern:" + pattern)
        except re.error:
            removed.append("invalid-pattern:" + pattern)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest(), scope, sorted(set(removed))


def _key(target_id: str, url: str, code: str, location: str) -> str:
    return hashlib.sha256(f"{target_id}|{url}|{code}|{location}".encode()).hexdigest()[:20]


def _issue(target_id: str, url: str, code: str, name: str, result: str, severity: str, *, element: str = "", location: str = "", evidence: str = "", recommendation: str = "", manual: bool = False, related: str | None = None) -> AccessibilityIssue:
    return AccessibilityIssue(_key(target_id, url, code, location), target_id, url, code, name, result, severity, element, location, evidence[:500], recommendation, manual, related)


def _valid_id_target(soup: BeautifulSoup, value: str) -> bool:
    return bool(soup.find(id=value) or soup.find(attrs={"name": value}))


def _accessible_name(element: Any, soup: BeautifulSoup) -> tuple[str, str | None]:
    text = element.get_text(" ", strip=True)
    if text:
        return text, None
    if element.get("aria-label", "").strip():
        return element["aria-label"].strip(), None
    labelled = element.get("aria-labelledby", "").split()
    if labelled:
        missing = [value for value in labelled if not soup.find(id=value)]
        if missing:
            return "", "aria-labelledby 대상 없음: " + ",".join(missing)
        return " ".join(soup.find(id=value).get_text(" ", strip=True) for value in labelled), None
    image = element.find("img")
    if image and image.get("alt", "").strip():
        return image["alt"].strip(), None
    return "", None


def _syntax_candidates(html: str, soup: BeautifulSoup, target_id: str, url: str) -> list[AccessibilityIssue]:
    issues: list[AccessibilityIssue] = []
    prefix = html[:500].lower()
    doctype = re.match(r"\s*<!doctype\s+html([^>]*)>", prefix, re.I)
    if not doctype:
        issues.append(_issue(target_id, url, "doctype", "HTML5 문서 선언", "검토 필요", "검토", evidence=html[:120], recommendation="문서 시작에 <!DOCTYPE html>을 선언하세요."))
    elif doctype.group(1).strip():
        issues.append(_issue(target_id, url, "doctype", "HTML5 문서 선언", "검토 필요", "검토", evidence=html[:120]))
    # BeautifulSoup repairs malformed markup; only report clear source candidates.
    for tag in ("html", "head", "body", "title", "main", "form"):
        if html.lower().count(f"<{tag}") > html.lower().count(f"</{tag}"):
            issues.append(_issue(target_id, url, "html-syntax", "HTML 문법 오류 후보", "검토 필요", "검토", element=tag, evidence=f"<{tag}> 닫힘 후보 부족", recommendation="원본 HTML의 태그 중첩과 닫힘을 확인하세요."))
    return issues


def check_page(html: str | None, *, target_id: str, url: str, menu_path: str = "", http_charset: str | None = None,
               resource_results: Iterable[Mapping[str, Any]] | None = None, cache: AccessibilityCache | None = None,
               policy_version: str = "accessibility-1", force: bool = False, config: Mapping[str, Any] | None = None,
               checked_at: str | None = None) -> AccessibilityReport:
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    if not isinstance(html, str):
        return AccessibilityReport(target_id, url, menu_path, checked_at, "", policy_version, False, "no_html", [],
                                    [_issue(target_id, url, "parse", "HTML 파싱", "점검 불가", "검토", evidence="HTML 본문 없음", recommendation="페이지 HTML 수집 결과를 확인하세요.")])
    config = config or {}
    access_config = config.get("accessibility", config)
    content_hash, hash_scope, removed_regions = build_content_hash(
        html,
        content_selector=str(access_config.get("content_selector", "")),
        volatile_selectors=access_config.get("volatile_selectors", ()),
        volatile_attributes=access_config.get("volatile_attributes", ()),
        volatile_patterns=access_config.get("volatile_patterns", ()),
    )
    if cache:
        reusable = cache.get_reusable(url, content_hash, policy_version=policy_version, force=force)
        if reusable:
            reusable.menu_path = menu_path
            reusable.checked_at = checked_at
            cache.update(reusable)
            return reusable
    allowed_langs = set(access_config.get("allowed_langs", ("ko", "ko-KR", "en", "en-US")))
    generic_titles = tuple(str(value).lower() for value in access_config.get("generic_title_keywords", ("홈", "페이지", "home", "untitled")))
    skip_keywords = tuple(str(value).lower() for value in access_config.get("skip_link_keywords", ("본문 바로가기", "skip to content")))
    soup = BeautifulSoup(html, "html.parser")
    issues = _syntax_candidates(html, soup, target_id, url)
    # Encoding: HTTP metadata is reused, never fetched here.
    meta_charsets = []
    for meta in soup.find_all("meta"):
        if meta.get("charset"):
            meta_charsets.append(meta["charset"].lower())
        if meta.get("http-equiv", "").lower() == "content-type":
            match = re.search(r"charset\s*=\s*([\w-]+)", meta.get("content", ""), re.I)
            if match:
                meta_charsets.append(match.group(1).lower())
    declared = ([http_charset.lower()] if http_charset else []) + meta_charsets
    if not declared:
        issues.append(_issue(target_id, url, "encoding", "문자 인코딩", "점검 불가", "검토", recommendation="HTTP charset 또는 UTF-8 meta 선언을 확인하세요."))
    elif any(value not in {"utf-8", "utf8"} for value in declared) or len(set(declared)) > 1:
        issues.append(_issue(target_id, url, "encoding", "문자 인코딩", "오류" if len(set(declared)) > 1 else "검토 필요", "중" if len(set(declared)) > 1 else "검토", evidence=", ".join(declared)))
    # Title and language.
    titles = soup.find_all("title")
    if len(titles) != 1 or not titles[0].get_text(strip=True):
        issues.append(_issue(target_id, url, "title", "페이지 제목", "오류", "중", element="title", evidence=f"title count={len(titles)}", recommendation="의미 있는 단일 title을 제공하세요."))
    elif titles[0].get_text(" ", strip=True).lower() in generic_titles:
        issues.append(_issue(target_id, url, "title-generic", "일반적인 페이지 제목", "검토 필요", "하", element="title", evidence=titles[0].get_text(strip=True)))
    root = soup.find("html")
    lang = root.get("lang", "").strip() if root else ""
    if not lang or not re.match(r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?$", lang):
        issues.append(_issue(target_id, url, "lang", "문서 기본 언어", "검토 필요", "검토", element="html", evidence=lang or "lang 없음"))
    elif lang not in allowed_langs:
        issues.append(_issue(target_id, url, "lang", "문서 기본 언어", "수동확인 필요", "검토", element="html", evidence=lang, manual=True))
    # Duplicate and empty IDs.
    ids: dict[str, list[str]] = {}
    for index, element in enumerate(soup.find_all(attrs={"id": True})):
        value = element.get("id", "")
        if not value.strip():
            issues.append(_issue(target_id, url, "empty-id", "빈 id", "검토 필요", "하", element=element.name, location=f"id[{index}]"))
        ids.setdefault(value, []).append(f"{element.name}[{index}]")
    for value, locations in ids.items():
        if value and len(locations) > 1:
            issues.append(_issue(target_id, url, "duplicate-id", "중복 id", "오류", "중", element=value, location="|".join(locations), evidence=str(locations)))
    # Form labels.
    for index, control in enumerate(soup.find_all(["input", "select", "textarea"])):
        typ = control.get("type", "").lower()
        if typ in {"hidden", "submit", "button", "reset", "image"}:
            continue
        label_ok = bool(control.get("aria-label", "").strip())
        labelled = control.get("aria-labelledby", "").split()
        if labelled and any(not _valid_id_target(soup, value) for value in labelled):
            issues.append(_issue(target_id, url, "input-label-ref", "입력서식 레이블", "오류", "중", element=control.name, location=f"{control.name}[{index}]", evidence=control.get("aria-labelledby", "")))
            continue
        label_ok = label_ok or bool(labelled) or bool(control.find_parent("label"))
        if control.get("id") and soup.find("label", attrs={"for": control["id"]}):
            label_ok = True
        if not label_ok:
            result = "검토 필요" if control.get("placeholder") else "오류"
            issues.append(_issue(target_id, url, "input-label", "입력서식 레이블", result, "검토" if result == "검토 필요" else "중", element=control.name, location=f"{control.name}[{index}]", recommendation="label, aria-label 또는 aria-labelledby를 제공하세요."))
    # Empty links/buttons.
    for index, element in enumerate(soup.find_all(["a", "button"])):
        name, error = _accessible_name(element, soup)
        if error:
            issues.append(_issue(target_id, url, "accessible-name-ref", "링크·버튼 이름", "오류", "중", element=element.name, location=f"{element.name}[{index}]", evidence=error))
        elif not name and element.find("img") is not None and not element.find("img").get("alt", "").strip():
            issues.append(_issue(target_id, url, "icon-control", "아이콘 링크·버튼", "수동확인 필요", "검토", element=element.name, location=f"{element.name}[{index}]", manual=True, recommendation="아이콘의 접근 가능한 이름을 확인하세요."))
        elif not name:
            issues.append(_issue(target_id, url, "empty-control", "빈 링크·버튼", "검토 필요", "검토", element=element.name, location=f"{element.name}[{index}]", recommendation="보이는 텍스트 또는 접근 가능한 이름을 제공하세요."))
    # Skip link and target.
    skip_links = [link for link in soup.find_all("a", href=True) if link["href"].startswith("#") and (any(word in link.get_text(" ", strip=True).lower() for word in skip_keywords) or link.sourceline is not None)]
    if not skip_links:
        issues.append(_issue(target_id, url, "skip-link", "반복영역 건너뛰기 링크", "검토 필요", "검토", recommendation="본문 바로가기 링크 제공을 검토하세요."))
    else:
        for link in skip_links:
            if not _valid_id_target(soup, link["href"][1:]):
                issues.append(_issue(target_id, url, "skip-link-target", "건너뛰기 링크 대상", "오류", "중", element="a", evidence=link["href"]))
    # Viewport.
    viewport = next((meta for meta in soup.find_all("meta") if meta.get("name", "").lower() == "viewport"), None)
    if not viewport or not viewport.get("content", "").strip():
        issues.append(_issue(target_id, url, "viewport", "모바일 viewport", "검토 필요", "검토", evidence="viewport 없음"))
    else:
        content = viewport["content"].lower()
        if "width=device-width" not in content:
            issues.append(_issue(target_id, url, "viewport-width", "모바일 viewport", "검토 필요", "검토", evidence=content))
        if "user-scalable=no" in content or "maximum-scale=1" in content:
            issues.append(_issue(target_id, url, "viewport-zoom", "모바일 확대 제한", "검토 필요", "검토", evidence=content, manual=True))
    # Reuse resource alt issues instead of duplicating them.
    if resource_results is None:
        for index, image in enumerate(soup.find_all("img")):
            if image.get("alt") is None and image.get("role") != "presentation":
                issues.append(_issue(target_id, url, "image-alt", "이미지 대체텍스트", "오류", "중", element="img", location=f"img[{index}]", related="resource:image-alt"))
    else:
        for resource in resource_results:
            if resource.get("reference", {}).get("kind") == "image" and "alt" in resource.get("reason", ""):
                issues.append(_issue(target_id, url, "image-alt", "이미지 대체텍스트", resource.get("verdict", "오류"), resource.get("severity", "중"), related=resource.get("issue_id", "resource:image-alt")))
    report = AccessibilityReport(target_id, url, menu_path, checked_at, content_hash, policy_version, False, hash_scope, removed_regions, issues)
    if cache:
        cache.update(report)
    return report


def accessibility_state_payload(reports: Iterable[AccessibilityReport]) -> dict[str, Any]:
    values = list(reports)
    issues = [issue.to_dict() for report in values for issue in report.issues]
    return {"schema_version": "1.0", "issue_type": "accessibility", "results": [report.to_dict() for report in values], "issues": issues,
            "counts": {result: sum(1 for issue in issues if issue["result"] == result) for result in sorted({issue["result"] for issue in issues})}}
