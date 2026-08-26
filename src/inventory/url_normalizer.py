"""Pure URL normalization, classification, and deterministic inventory merging."""

from __future__ import annotations

import posixpath
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlsplit, urlunsplit


@dataclass(frozen=True)
class NormalizationPolicy:
    ignored_query_parameters: frozenset[str] = frozenset()
    trailing_slash: str = "preserve"
    sort_query_parameters: bool = False
    excluded_schemes: frozenset[str] = frozenset({"mailto", "tel", "javascript", "data"})

    def __post_init__(self) -> None:
        if self.trailing_slash not in {"preserve", "remove", "add"}:
            raise ValueError("trailing_slash must be preserve, remove, or add")


@dataclass(frozen=True)
class URLClassification:
    original_url: str
    normalized_url: str | None
    kind: str
    other_target_id: str | None = None
    excluded_query_parameters: tuple[str, ...] = ()
    reason: str | None = None


@dataclass
class MergedURL:
    target_id: str
    normalized_url: str
    classification: str
    original_urls: set[str] = field(default_factory=set)
    discovery_sources: set[str] = field(default_factory=set)
    menu_paths: set[str] = field(default_factory=set)
    discovered_from: set[str] = field(default_factory=set)
    titles: set[str] = field(default_factory=set)
    link_texts: set[str] = field(default_factory=set)
    first_discovered_at: str = ""
    last_discovered_at: str = ""
    other_target_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("original_urls", "discovery_sources", "menu_paths", "discovered_from", "titles", "link_texts"):
            value[key] = sorted(value[key])
        return value


@dataclass
class NormalizedInventory:
    schema_version: str
    records: list[MergedURL]
    original_url_count: int
    normalized_url_count: int
    duplicate_removed_count: int
    counts: dict[str, int]
    excluded_query_parameters: list[str]
    policy_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "records": [record.to_dict() for record in self.records],
            "stats": {
                "original_url_count": self.original_url_count,
                "normalized_url_count": self.normalized_url_count,
                "duplicate_removed_count": self.duplicate_removed_count,
                "counts": self.counts,
                "excluded_query_parameters": self.excluded_query_parameters,
            },
            "policy_fingerprint": self.policy_fingerprint,
        }


def policy_from_config(exclusions: Mapping[str, Any]) -> NormalizationPolicy:
    raw = exclusions.get("url_normalization", {})
    if not isinstance(raw, Mapping):
        raise ValueError("url_normalization must be a mapping")
    return NormalizationPolicy(
        ignored_query_parameters=frozenset(str(value).lower() for value in exclusions.get("ignored_query_parameters", [])),
        trailing_slash=str(raw.get("trailing_slash", "preserve")),
        sort_query_parameters=bool(raw.get("sort_query_parameters", False)),
        excluded_schemes=frozenset(str(value).lower() for value in raw.get("excluded_schemes", [])),
    )


def policy_fingerprint(policy: NormalizationPolicy) -> str:
    payload = {
        "ignored_query_parameters": sorted(policy.ignored_query_parameters),
        "trailing_slash": policy.trailing_slash,
        "sort_query_parameters": policy.sort_query_parameters,
        "excluded_schemes": sorted(policy.excluded_schemes),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def normalize_url(raw_url: str, base_url: str | None = None, policy: NormalizationPolicy | None = None) -> tuple[str | None, tuple[str, ...]]:
    """Return a comparison URL and removed query names without making a request."""
    policy = policy or NormalizationPolicy()
    if not isinstance(raw_url, str) or not raw_url.strip():
        return None, ()
    value = raw_url.strip()
    if base_url and not urlsplit(value).scheme:
        value = urljoin(base_url, value)
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname:
            return None, ()
        host = parsed.hostname.lower()
        try:
            port = parsed.port
        except ValueError:
            return None, ()
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            port = None
        netloc = host if port is None else f"{host}:{port}"
        if parsed.username is not None:
            user = quote(unquote(parsed.username), safe="")
            netloc = user + (":" + quote(unquote(parsed.password), safe="") if parsed.password else "") + "@" + netloc
        raw_path = unquote(parsed.path or "/")
        path = posixpath.normpath(raw_path)
        if not path.startswith("/"):
            path = "/" + path
        had_trailing = raw_path.endswith("/")
        if policy.trailing_slash == "remove" and path != "/":
            path = path.rstrip("/")
        elif policy.trailing_slash == "add" and path != "/":
            path = path.rstrip("/") + "/"
        elif policy.trailing_slash == "preserve" and had_trailing and path != "/":
            path = path.rstrip("/") + "/"
        path = quote(path, safe="/%:@!$&'()*+,;=-._~")
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        removed = tuple(name for name, _ in query_pairs if name.lower() in policy.ignored_query_parameters)
        query_pairs = [(name, value) for name, value in query_pairs if name.lower() not in policy.ignored_query_parameters]
        if policy.sort_query_parameters:
            query_pairs.sort()
        query = "&".join(f"{quote(name, safe='-._~')}={quote(value, safe='-._~')}" for name, value in query_pairs)
        return urlunsplit((scheme, netloc, path, query, "")), removed
    except (ValueError, UnicodeError):
        return None, ()


def classify_url(raw_url: str, *, base_url: str, allowed_domains: Iterable[str] = (), managed_targets: Mapping[str, Iterable[str]] | None = None,
                policy: NormalizationPolicy | None = None) -> URLClassification:
    policy = policy or NormalizationPolicy()
    value = raw_url.strip() if isinstance(raw_url, str) else ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return URLClassification(raw_url, None, "invalid", reason="파싱할 수 없는 URL")
    if parsed.scheme.lower() in policy.excluded_schemes:
        return URLClassification(raw_url, None, "non_http", reason="점검 제외 scheme")
    normalized, removed = normalize_url(raw_url, base_url, policy)
    if normalized is None:
        if parsed.scheme.lower() not in {"", "http", "https"}:
            return URLClassification(raw_url, None, "non_http", reason="점검 제외 scheme")
        return URLClassification(raw_url, None, "invalid", reason="HTTP URL로 해석할 수 없음")
    host = urlsplit(normalized).hostname or ""
    base_host = (urlsplit(base_url).hostname or "").lower()
    allowed = {base_host, *(domain.lower() for domain in allowed_domains)}
    if host in allowed:
        return URLClassification(raw_url, normalized, "internal", excluded_query_parameters=removed)
    other = None
    for target_id, domains in (managed_targets or {}).items():
        if host in {domain.lower() for domain in domains}:
            other = target_id
            break
    return URLClassification(raw_url, normalized, "external", other, removed)


def merge_occurrences(occurrences: Iterable[Any], *, target_id: str, base_url: str, allowed_domains: Iterable[str] = (),
                      managed_targets: Mapping[str, Iterable[str]] | None = None, policy: NormalizationPolicy | None = None) -> NormalizedInventory:
    policy = policy or NormalizationPolicy()
    merged: dict[tuple[str, str], MergedURL] = {}
    original_count = 0
    removed_parameters: set[str] = set()
    counts = {kind: 0 for kind in ("internal", "external", "invalid", "non_http")}
    for occurrence in occurrences:
        original_count += 1
        raw = getattr(occurrence, "original_url", getattr(occurrence, "url", ""))
        occurrence_base = getattr(occurrence, "discovered_from", "") or base_url
        classification = classify_url(raw, base_url=occurrence_base, allowed_domains=allowed_domains, managed_targets=managed_targets, policy=policy)
        removed_parameters.update(classification.excluded_query_parameters)
        counts[classification.kind] += 1
        normalized = classification.normalized_url or f"{classification.kind}:{raw}"
        key = (target_id, normalized)
        current = merged.get(key)
        timestamp = getattr(occurrence, "discovered_at", "") or datetime.now(timezone.utc).isoformat()
        if current is None:
            current = MergedURL(target_id, normalized, classification.kind, other_target_id=classification.other_target_id)
            merged[key] = current
        current.original_urls.add(raw)
        current.discovery_sources.add(getattr(occurrence, "source", ""))
        current.menu_paths.add(getattr(occurrence, "menu_path", ""))
        current.discovered_from.add(getattr(occurrence, "discovered_from", ""))
        title = getattr(occurrence, "title", "")
        current.titles.add(title)
        current.link_texts.add(title)
        current.first_discovered_at = min(filter(None, (current.first_discovered_at, timestamp)))
        current.last_discovered_at = max(current.last_discovered_at, timestamp)
    records = sorted(merged.values(), key=lambda item: (item.target_id, item.normalized_url))
    counts = {kind: sum(1 for record in records if record.classification == kind) for kind in counts}
    return NormalizedInventory("1.0", records, original_count, len(records), max(0, original_count - len(records)), counts,
                               sorted(removed_parameters), policy_fingerprint(policy))


def upgrade_inventory_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the pre-normalization target map readable without discarding any fields."""
    if any(isinstance(value, Mapping) and ("raw" in value or "normalized" in value) for value in payload.values()):
        return dict(payload)
    return {target_id: {"raw": value, "normalized": None, "schema_version": "legacy"}
            for target_id, value in payload.items()}
