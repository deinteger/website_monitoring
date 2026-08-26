from pathlib import Path

import pytest

from src.common.config_loader import ConfigError, load_config


def write_config(root: Path, targets: str, rules: str, exclusions: str = "excluded_paths: []\n") -> None:
    (root / "targets.yaml").write_text(targets, encoding="utf-8")
    (root / "rules.yaml").write_text(rules, encoding="utf-8")
    (root / "exclusions.yaml").write_text(exclusions, encoding="utf-8")


def valid_rules(**overrides: object) -> str:
    values = {"concurrency": 1, "request_interval_seconds": 1, "max_urls": 10}
    values.update(overrides)
    return """crawl:
  user_agent: test
  concurrency: {concurrency}
  request_interval_seconds: {request_interval_seconds}
  timeout_seconds: 5
  max_retries: 1
  max_urls: {max_urls}
  max_response_bytes: 100
  browser_mode: off
  discovery_sources: [main_menu]
""".format(**values)


def test_loads_operational_config() -> None:
    config = load_config()
    assert set(config.targets) == {"nihhs", "fruit"}
    assert config.crawl.concurrency == 1
    assert config.crawl.request_interval_seconds == 1


@pytest.mark.parametrize("override", [{"concurrency": 2}, {"request_interval_seconds": 0.5}, {"max_urls": 11}])
def test_rejects_unsafe_initial_crawl_limits(tmp_path: Path, override: dict[str, object]) -> None:
    write_config(tmp_path, "targets:\n  sample:\n    name: Sample\n    base_url: https://example.test\n", valid_rules(**override))
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_rejects_non_https_target(tmp_path: Path) -> None:
    write_config(tmp_path, "targets:\n  sample:\n    name: Sample\n    base_url: http://example.test\n", valid_rules())
    with pytest.raises(ConfigError, match="HTTPS"):
        load_config(tmp_path)
