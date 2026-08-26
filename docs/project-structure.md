# 목표 프로젝트 구조

개발단계는 3단계로 단순하게 유지하되, 코드는 기능별 책임이 섞이지 않도록 분리한다.

```text
homepage-quality-checker/
├─ AGENTS.md
├─ README.md
├─ PLAN.md
├─ HANDOVER.md
├─ plans/
│  ├─ phase1-daily.md
│  ├─ phase2-search-ai.md
│  └─ phase3-quality.md
├─ run_all.py
├─ requirements.txt 또는 pyproject.toml
├─ config/
│  ├─ targets.yaml
│  ├─ rules.yaml
│  ├─ exclusions.yaml
│  └─ domain_terms.txt
├─ docs/
├─ project_sources/
├─ src/
│  ├─ inventory/
│  │  ├─ collector.py
│  │  ├─ menu_parser.py
│  │  ├─ sitemap_parser.py
│  │  └─ url_normalizer.py
│  ├─ freshness/
│  │  ├─ date_parser.py
│  │  └─ checker.py
│  ├─ resources/
│  │  ├─ link_checker.py
│  │  ├─ image_checker.py
│  │  └─ attachment_checker.py
│  ├─ quality/
│  │  ├─ html_checker.py
│  │  ├─ accessibility_checker.py
│  │  └─ performance_checker.py
│  ├─ search_portals/
│  │  ├─ base.py
│  │  ├─ google.py
│  │  ├─ naver.py
│  │  └─ daum.py
│  ├─ ai/
│  │  ├─ timely_client.py
│  │  ├─ input_selector.py
│  │  ├─ reviewer.py
│  │  └─ schemas.py
│  ├─ chatbot/
│  │  ├─ service.py
│  │  ├─ retrieval.py
│  │  ├─ commands.py
│  │  └─ web/
│  ├─ reports/
│  │  ├─ page_report.py
│  │  └─ search_report.py
│  └─ common/
│     ├─ config_loader.py
│     ├─ http_client.py
│     ├─ models.py
│     ├─ state_manager.py
│     └─ logger.py
├─ state/
│  ├─ inventory.json
│  ├─ issues.json
│  ├─ content_hashes.json
│  ├─ search_urls.json
│  ├─ ai_findings.json
│  ├─ ai_cache.json
│  ├─ chat_sessions.json
│  └─ run_history.jsonl
├─ output/
├─ screenshots/
├─ logs/
├─ handover/archive/
└─ tests/
```

## 구조 원칙

- 루트에는 실행 진입점과 프로젝트 문서만 둔다.
- `PLAN.md`는 현재 작업과 단계 색인만 유지하고 세부 체크리스트는 `plans/`로 분리한다.
- 기능별 구현 규칙은 `docs/`에 두며 기능별 `SKILL.md`를 만들지 않는다.
- `src/common`은 공통 통신·설정·데이터 모델만 담당한다.
- 점검 모듈이 XLSX 형식을 직접 다루지 않고 표준 결과 모델을 반환한다.
- 보고서 모듈은 수집이나 판정을 수행하지 않는다.
- 검색포털 provider 실패가 페이지 전수점검 실패로 이어지지 않게 분리한다.
- AI API 실패가 규칙 기반 점검과 결과서 생성을 막지 않게 분리한다.
- 챗봇은 보고서 파일을 매번 역파싱하지 않고 정규화된 최신 JSON을 읽는다.
- 웹 UI는 API 키를 알 수 없으며 모든 TimelyGPT 요청은 Python 백엔드를 거친다.
- `state/`, `output/`, `screenshots/`, `logs/`의 실행 산출물은 소스와 구분한다.
