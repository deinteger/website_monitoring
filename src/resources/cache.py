"""Execution-independent attachment cache backed by plain JSON-compatible data."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


class AttachmentCache:
    @classmethod
    def from_state(cls, state_manager: Any, *, policy_version: str = "resources-1", recheck_days: int = 30) -> "AttachmentCache":
        payload = state_manager.load_json("attachment_cache.json", {})
        return cls(payload if isinstance(payload, dict) else {}, policy_version=policy_version, recheck_days=recheck_days)

    def save_state(self, state_manager: Any) -> Any:
        return state_manager.save_json("attachment_cache.json", self.to_dict())

    def __init__(self, data: dict[str, Any] | None = None, *, policy_version: str = "resources-1", recheck_days: int = 30) -> None:
        self.entries: dict[str, dict[str, Any]] = dict((data or {}).get("entries", data or {}))
        self.policy_version = policy_version
        self.recheck_days = recheck_days

    def get(self, url: str) -> dict[str, Any] | None:
        return self.entries.get(url)

    def relations(self, url: str, page_url: str, *, original_url: str, filename: str, link_text: str) -> None:
        entry = self.entries.setdefault(url, {"normalized_url": url, "original_pages": []})
        pages = set(entry.setdefault("original_pages", []))
        pages.add(page_url)
        entry["original_pages"] = sorted(pages)
        entry["original_url"] = original_url
        entry["filename"] = filename
        entry["link_text"] = link_text

    def reusable(self, url: str, *, content_hash: str, original_url: str, filename: str, link_text: str,
                 today: date, policy_version: str, force: bool = False) -> tuple[bool, str | None]:
        entry = self.entries.get(url)
        if force or not entry:
            return False, "강제 재점검" if force else "캐시 없음"
        if entry.get("policy_version") != policy_version:
            return False, "검사 정책 버전 변경"
        if entry.get("content_hash") != content_hash:
            return False, "원본 게시글 콘텐츠 해시 변경"
        if entry.get("original_url") != original_url or entry.get("filename", "") != filename or entry.get("link_text", "") != link_text:
            return False, "첨부파일 URL·파일명·링크 문구 변경"
        if entry.get("verdict") != "정상":
            return False, "이전 결과가 정상 아님"
        next_date = entry.get("next_recheck_date")
        if not next_date or today >= date.fromisoformat(next_date):
            return False, "재검사 주기 만료"
        return True, None

    def update(self, url: str, *, content_hash: str, original_url: str, page_url: str, filename: str,
               link_text: str, result: dict[str, Any], checked_date: date, policy_version: str) -> dict[str, Any]:
        self.relations(url, page_url, original_url=original_url, filename=filename, link_text=link_text)
        entry = self.entries[url]
        entry.update(result)
        entry.update({"normalized_url": url, "content_hash": content_hash, "original_url": original_url,
                      "filename": filename, "link_text": link_text, "last_detailed_check": checked_date.isoformat(),
                      "last_revalidation": checked_date.isoformat(), "next_recheck_date": (checked_date + timedelta(days=self.recheck_days)).isoformat(),
                      "policy_version": policy_version, "cache_created_at": entry.get("cache_created_at", checked_date.isoformat())})
        return entry

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "policy_version": self.policy_version, "entries": self.entries}
