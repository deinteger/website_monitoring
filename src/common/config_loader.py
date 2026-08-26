"""Load and validate the local YAML configuration files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


class ConfigError(ValueError):
    """Raised when a configuration file is missing or unsafe."""


@dataclass(frozen=True)
class Target:
    identifier: str
    name: str
    base_url: str
    menu: dict[str, Any] = field(default_factory=dict)
    allowed_domains: tuple[str, ...] = ()
    date_selectors: dict[str, tuple[str, ...]] = field(default_factory=dict)
    list_selectors: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class CrawlSettings:
    user_agent: str
    concurrency: int
    request_interval_seconds: float
    timeout_seconds: float
    max_retries: int
    max_urls: int
    max_response_bytes: int
    browser_mode: str
    discovery_sources: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    targets: dict[str, Target]
    crawl: CrawlSettings
    rules: dict[str, Any]
    exclusions: dict[str, Any]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Configuration file is missing: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"Configuration root must be a mapping: {path}")
    return value


def _required(mapping: dict[str, Any], key: str, context: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise ConfigError(f"Missing {context}.{key}")
    return value


def _positive_number(value: Any, name: str, *, integer: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{name} must be a positive number")
    if integer and not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer")
    return value


def _validate_target(identifier: str, raw: Any) -> Target:
    if not isinstance(raw, dict):
        raise ConfigError(f"targets.{identifier} must be a mapping")
    name = _required(raw, "name", f"targets.{identifier}")
    base_url = _required(raw, "base_url", f"targets.{identifier}")
    if not isinstance(name, str) or not isinstance(base_url, str):
        raise ConfigError(f"targets.{identifier} name and base_url must be strings")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
        raise ConfigError(f"targets.{identifier}.base_url must be an HTTPS site root")
    menu = raw.get("menu", {})
    if not isinstance(menu, dict):
        raise ConfigError(f"targets.{identifier}.menu must be a mapping")
    selectors = menu.get("main_selectors", [])
    all_selectors = menu.get("all_menu_selectors", [])
    paths = menu.get("all_menu_paths", [])
    for key, value in (("main_selectors", selectors), ("all_menu_selectors", all_selectors), ("all_menu_paths", paths)):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ConfigError(f"targets.{identifier}.menu.{key} must be a string list")
    sitemap_path = menu.get("sitemap_path", "/sitemap.xml")
    if not isinstance(sitemap_path, str) or not sitemap_path:
        raise ConfigError(f"targets.{identifier}.menu.sitemap_path must be a string")
    allowed_domains = raw.get("allowed_domains", [])
    if not isinstance(allowed_domains, list) or not all(isinstance(item, str) and item for item in allowed_domains):
        raise ConfigError(f"targets.{identifier}.allowed_domains must be a string list")
    date_selectors = raw.get("date_selectors", {})
    if not isinstance(date_selectors, dict) or any(not isinstance(value, list) or not all(isinstance(item, str) for item in value) for value in date_selectors.values()):
        raise ConfigError(f"targets.{identifier}.date_selectors must be string lists")
    list_selectors = raw.get("list_selectors", {})
    if not isinstance(list_selectors, dict) or any(not isinstance(value, list) or not all(isinstance(item, str) for item in value) for value in list_selectors.values()):
        raise ConfigError(f"targets.{identifier}.list_selectors must be string lists")
    return Target(identifier=identifier, name=name, base_url=base_url.rstrip("/"), menu=menu,
                  allowed_domains=tuple(item.lower() for item in allowed_domains),
                  date_selectors={key: tuple(value) for key, value in date_selectors.items()},
                  list_selectors={key: tuple(value) for key, value in list_selectors.items()})


def load_config(config_dir: str | Path = "config") -> AppConfig:
    """Load all operational configuration and reject unsafe crawl limits."""
    directory = Path(config_dir)
    targets_doc = _read_yaml(directory / "targets.yaml")
    rules = _read_yaml(directory / "rules.yaml")
    exclusions = _read_yaml(directory / "exclusions.yaml")

    raw_targets = _required(targets_doc, "targets", "targets.yaml")
    if not isinstance(raw_targets, dict) or not raw_targets:
        raise ConfigError("targets.yaml.targets must be a non-empty mapping")
    targets = {identifier: _validate_target(identifier, raw) for identifier, raw in raw_targets.items()}

    raw_crawl = _required(rules, "crawl", "rules.yaml")
    if not isinstance(raw_crawl, dict):
        raise ConfigError("rules.yaml.crawl must be a mapping")
    concurrency = _positive_number(_required(raw_crawl, "concurrency", "crawl"), "crawl.concurrency", integer=True)
    interval = _positive_number(_required(raw_crawl, "request_interval_seconds", "crawl"), "crawl.request_interval_seconds")
    max_urls = _positive_number(_required(raw_crawl, "max_urls", "crawl"), "crawl.max_urls", integer=True)
    if concurrency != 1:
        raise ConfigError("crawl.concurrency must be 1 during the initial rollout")
    if interval < 1:
        raise ConfigError("crawl.request_interval_seconds must be at least 1")
    if max_urls > 10:
        raise ConfigError("crawl.max_urls must not exceed 10 during the initial rollout")
    crawl = CrawlSettings(
        user_agent=str(_required(raw_crawl, "user_agent", "crawl")),
        concurrency=concurrency,
        request_interval_seconds=float(interval),
        timeout_seconds=float(_positive_number(_required(raw_crawl, "timeout_seconds", "crawl"), "crawl.timeout_seconds")),
        max_retries=int(_positive_number(_required(raw_crawl, "max_retries", "crawl"), "crawl.max_retries", integer=True)),
        max_urls=max_urls,
        max_response_bytes=int(_positive_number(_required(raw_crawl, "max_response_bytes", "crawl"), "crawl.max_response_bytes", integer=True)),
        browser_mode=str(_required(raw_crawl, "browser_mode", "crawl")),
        discovery_sources=tuple(_required(raw_crawl, "discovery_sources", "crawl")),
    )
    if not all(isinstance(source, str) for source in crawl.discovery_sources):
        raise ConfigError("crawl.discovery_sources must contain strings")
    return AppConfig(targets=targets, crawl=crawl, rules=rules, exclusions=exclusions)
