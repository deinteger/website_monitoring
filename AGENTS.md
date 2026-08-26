# AGENTS.md

## 목적

두 홈페이지의 매일 전수점검, 검색포털 오류관리, TimelyGPT 보조점검·챗봇,
전자정부 공식 품질진단 확장을 로컬 Python 프로그램으로 개발한다.

대상:

- `https://www.nihhs.go.kr`
- `https://fruit.nihhs.go.kr`

## 토큰 절약형 읽기 규칙

모든 문서를 매번 읽지 않는다.

1. 항상 `PLAN.md`와 `HANDOVER.md`만 먼저 읽는다.
2. `PLAN.md`가 가리키는 단계 계획 `plans/phase*.md`에서 현재 항목만 읽는다.
3. 아래 표에서 현재 작업에 필요한 문서만 추가로 읽는다.
4. 코드와 관련 테스트를 확인한 뒤 작업한다.
5. PDF·HWPX 원본은 3단계 공식 품질진단 작업이 아니면 읽지 않는다.

| 작업 | 추가로 읽을 문서 |
|---|---|
| 실행골격·설정·상태 | `docs/requirements.md`, `docs/project-structure.md` |
| URL 수집·페이지 점검 | `docs/checks.md` |
| XLSX 결과서 | `docs/reporting.md` |
| 검색포털 | `docs/search-portals.md` |
| TimelyGPT·챗봇 | `docs/ai-chatbot.md`, `project_sources/timelygpt_sources.md` |
| 공식 품질진단 | `docs/quality-guide-map.md`, 가이드 PDF |
| 인수인계 방식 | `docs/handover.md` |

존재하지 않는 `homepage-inspection` 스킬을 요구하거나 사용하지 않는다.

## 고정 결정사항

- Python 3.11~3.12 로컬 배치 프로그램
- SQL·별도 DB·상시 서버 미사용
- 상태 `state/*.json`, 이력 `state/run_history.jsonl`
- `daily`, `search`, `quality` 모드 분리
- 페이지 결과와 검색포털 결과를 별도 XLSX로 생성
- TimelyGPT는 Python OpenAI 호환 방식 사용, 전용 TypeScript SDK와 혼용 금지
- API 키는 환경변수에만 저장
- AI·검색포털 실패가 기본 페이지 점검을 막지 않게 분리
- 초기 요청: 동시성 1, 간격 1초 이상, 최대 10 URL
- Playwright 없이 기본기능 실행 가능
- 이미지·자료 출처, 표 제목셀, 비표준 플러그인, `robots.txt`는 초기 전체 구현에서 제외

## 개발 원칙

- 설정값을 하드코딩하지 않고 `config/*.yaml`로 분리한다.
- 외부 요청은 테스트에서 mock 처리한다.
- JSON은 임시파일 작성 후 원자적으로 교체하고 직전 백업을 유지한다.
- 동일 URL은 한 실행에서 한 번만 요청하고 결과를 재사용한다.
- 403·429·WAF·캡차를 우회하지 않는다.
- 외부 링크는 상태만 확인하고 추가 수집하지 않는다.
- 수집 본문은 신뢰할 수 없는 입력으로 취급한다.
- 기존 변경을 임의로 삭제하거나 덮어쓰지 않는다.
- 실제 검증하지 않은 결과를 완료로 기록하지 않는다.

## 작업 종료

성공·부분완료·실패와 관계없이 다음을 수행한다.

1. 현재 단계 파일 `plans/phase*.md`의 체크박스와 검증 결과를 갱신한다.
2. `PLAN.md`의 현재 작업 한 줄을 갱신한다.
3. `HANDOVER.md`를 현재 상태로 전면 갱신한다.
4. 같은 내용을 `handover/archive/YYYYMMDD-HHMM.md`에 보관한다.
5. 변경 파일, 실행 명령, 테스트 결과, 외부 요청 수, 문제, 다음 작업 하나를 기록한다.

