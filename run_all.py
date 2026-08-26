"""Command-line entry point for the local homepage quality checker."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.common.config_loader import ConfigError, load_config
from src.common.state_manager import StateManager
from src.inventory.collector import InventoryCollector, RequestFetcher
from src.inventory.url_normalizer import merge_occurrences, policy_from_config
from src.inventory.comparator import compare_inventory
from src.daily_pipeline import run_offline_fixture
from src.common.http_transport import build_transport
from src.common.env_loader import load_project_env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NIHHS 홈페이지 품질점검 로컬 배치")
    parser.add_argument("--mode", choices=("daily", "search", "quality"), default="daily")
    parser.add_argument("--target", choices=("all", "nihhs", "fruit"), default="all")
    parser.add_argument("--check", choices=("all", "inventory"), default="all")
    parser.add_argument("--max-urls", type=int, help="설정값 이하의 이번 실행 URL 상한")
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--state-dir", type=Path, default=Path("state"))
    parser.add_argument("--dry-run", action="store_true", help="설정만 검증하고 실행 이력을 남기지 않음")
    parser.add_argument("--force-resource-check", action="store_true", help="첨부파일 캐시를 무시하고 이번 실행에서 재점검")
    parser.add_argument("--force-accessibility-check", action="store_true", help="페이지 HTML·접근성 캐시를 무시하고 이번 실행에서 재점검")
    parser.add_argument("--offline-fixture", type=Path, help="Run daily from a local JSON fixture without network access")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    args = build_parser().parse_args(argv)
    if args.offline_fixture:
        if args.mode != "daily":
            return 2
        try:
            result = run_offline_fixture(args.offline_fixture, state_dir=args.state_dir, output_root="output")
        except (OSError, ValueError):
            return 1
        if result.get("report_path"):
            print(f"daily offline {result.get('status', 'failed')}: {result['report_path']}")
        else:
            print(f"daily offline failed: {result.get('failure_reason', 'unknown error')}")
        return int(result.get("exit_code", 1))
    try:
        config = load_config(args.config_dir)
    except ConfigError as exc:
        print(f"설정 오류: {exc}")
        return 1
    if args.max_urls is not None and not 1 <= args.max_urls <= config.crawl.max_urls:
        print(f"설정 오류: --max-urls는 1에서 {config.crawl.max_urls} 사이여야 합니다.")
        return 2
    selected = list(config.targets) if args.target == "all" else [args.target]
    state = StateManager(args.state_dir)
    inventory_results = []
    if args.check == "inventory" and not args.dry_run:
        run_id = datetime.now(timezone.utc).isoformat()
        baseline_state = state.load_json("inventory_baseline.json", {})
        if not isinstance(baseline_state, dict):
            baseline_state = {}
        if not baseline_state:
            legacy_current = state.load_json("inventory.json", {})
            if isinstance(legacy_current, dict):
                baseline_state = legacy_current
        baseline_changed = False
        for target_id in selected:
            target = config.targets[target_id]
            transport = build_transport(config.rules.get("network", {}), user_agent=config.crawl.user_agent,
                timeout=config.crawl.timeout_seconds, max_retries=config.crawl.max_retries,
                interval=config.crawl.request_interval_seconds, max_requests=args.max_urls or config.crawl.max_urls)
            fetcher = RequestFetcher(
                user_agent=config.crawl.user_agent,
                timeout=config.crawl.timeout_seconds,
                max_retries=config.crawl.max_retries,
                interval=config.crawl.request_interval_seconds,
                max_requests=args.max_urls or config.crawl.max_urls,
                transport=transport,
            )
        inventory_results.append(InventoryCollector(target, fetcher, max_requests=args.max_urls or config.crawl.max_urls).collect())
        policy = policy_from_config(config.exclusions)
        state_payload = {}
        managed = {identifier: [target.base_url.split("//", 1)[1]] for identifier, target in config.targets.items()}
        for item in inventory_results:
            target = config.targets[item.target_id]
            normalized = merge_occurrences(item.records, target_id=item.target_id, base_url=target.base_url,
                                           allowed_domains=target.allowed_domains, managed_targets=managed, policy=policy)
            raw_payload = item.to_dict()
            raw_payload["run_id"] = run_id
            current_payload = {"raw": raw_payload, "normalized": normalized.to_dict()}
            comparison = compare_inventory(baseline_state.get(item.target_id), current_payload,
                                           target_id=item.target_id, max_requests=args.max_urls or config.crawl.max_urls)
            current_payload["comparison"] = comparison.to_dict()
            state_payload[item.target_id] = current_payload
            if comparison.baseline_updated:
                baseline_state[item.target_id] = current_payload
                baseline_changed = True
        state.save_json("inventory.json", state_payload)
        if baseline_changed:
            state.save_json("inventory_baseline.json", baseline_state)
    if not args.dry_run:
        state.append_run_history({
            "started_at": datetime.now(timezone.utc).isoformat(),
            "mode": args.mode,
            "check": args.check,
            "targets": selected,
            "max_urls": args.max_urls or config.crawl.max_urls,
            "status": "completed" if args.check == "inventory" else "not_implemented",
            "inventory_targets": len(inventory_results),
        })
    print(f"검증 완료: mode={args.mode}, targets={','.join(selected)}, max_urls={args.max_urls or config.crawl.max_urls}")
    print("현재는 실행 기반 단계입니다. 실제 점검 모듈은 다음 작업에서 연결됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
