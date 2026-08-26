# 인수인계

실제 운영시험 재개 명령: `python run_all.py --mode daily --target all --max-urls 10`
사이트별 명령: `python run_all.py --mode daily --target nihhs --max-urls 10`,
`python run_all.py --mode daily --target fruit --max-urls 10`.

## 상태

### 사이트맵 없는 실제 점검 보완 (2026-08-26)

- 운영 수동 점검이 `DailyPipeline` 앞단에서 대표 페이지를 먼저 요청하고, 사이트맵이 없거나 비어 있어도 동일 도메인 내부 `<a href>` 링크를 순차적으로 따라가 인벤토리를 만든다.
- 최대 URL 수는 기존 안전 제한(10)을 그대로 공유하며, 발견된 URL별 응답을 공통 raw fixture 경로로 전달해 JSON·XLSX·이슈 상태를 생성한다.
- fixture 검증 `tests/test_dashboard_operational.py` 7개, 전체 회귀 `223 passed`.
- 이 환경의 실제 HTTPS 요청은 프록시·직접 HTTP·브라우저 transport 모두 차단되어 운영 결과 생성까지 도달하지 못했다. 일반 PowerShell에서 다음 명령으로 재개한다: `python run_all.py --mode daily --target fruit --max-urls 10`.

- E: 접속 방식 진단과 다중 transport mock 테스트 완료. 실제 10페이지 운영시험은 Codex 환경 차단으로 미완료이며 50페이지·전체 확대도 미완료다.
- F: 자동 배치 fixture 통합 검증 완료.
- G: 운영용 HTML 대시보드·구조화 API·fixture 주입 통합 및 실제 localhost 서버 검증 완료. 운영 화면에는 fixture 입력과 원시 JSON 출력이 없다.
- 외부 사이트에는 이번 작업에서 추가 요청하지 않았다.

## F/G 완료 증거

- 배치: `daily_batch.py`, `start_daily.bat`
- 스케줄러: `register_daily_task.ps1`, `unregister_daily_task.ps1` (기본 dry-run은 등록 API 미호출)
- 실행 잠금: `src/common/execution_lock.py`
- 웹서버: `src/dashboard.py`; HTML/CSS/JS: `web/index.html`, `web/style.css`, `web/app.js`
- 대시보드 문서: `docs/web-dashboard.md`; 시작 도구: `start_dashboard.bat`
- 테스트: `tests/test_daily_batch.py`, `tests/test_dashboard.py`, `tests/test_dashboard_server.py`, `tests/test_execution_lock.py`, `tests/test_run_service.py`
- 배치와 수동 실행은 raw fixture에서 동일 `DailyPipeline` inventory 정규화 결과를 생성하는지 검증했다.

## 최신 검증

- F/G 전용: 15 passed
- 전체 수집: 195 collected
- 전체 회귀: 195 passed
- `python run_all.py --help`, `python daily_batch.py --help`, `python -m src.dashboard --help`: 성공
- 실제 localhost server: `127.0.0.1:18765/api/health` → HTTP 200 / bind `127.0.0.1`
- 포트 충돌: 자동 테스트에서 명확한 오류와 exit 1 확인
- scheduler dry-run: 성공, 등록 없음

## G 운영 화면 보완 검증

- 운영 화면: `web/index.html`, `web/style.css`, `web/app.js`
- API: health, status, summary, results(필터·정렬·페이지네이션), 상세, history, reports, run, stop
- 수동 실행: 허용된 대상·최대 10페이지·강제점검 옵션만 받고 공통 `DailyPipeline`·실행 잠금을 사용한다.
- fixture: `make_handler(..., allow_fixture=True)` 의존성 주입 테스트에서만 허용한다.
- 전용 대시보드 테스트: 13 passed
- 전체 회귀: 199 passed
- 시각 검증: localhost에서 Playwright 1366×768 및 390×844 캡처·확인
- 외부 사이트 요청: 0회

## H TimelyGPT AI 점검 도우미

- `src/ai_assistant.py`와 `/api/ai/status`, `/api/ai/models`, `/api/ai/chat`, `/api/ai/clear` 구현
- `TIMELYGPT_API_KEY`는 서버 환경변수에서만 읽고 기본 AI 기능은 비활성화
- 질문 관련 결과만 최대 건수·문자 수로 선택하며 URL·issue key·점검일 근거를 반환
- TimelyGPT 외부 호출: 0회(mock client만 사용)
- H 전용 테스트: 4개

H 보완 검토: 환경변수 우선순위(`TIMELYGPT_*`), 모델 허용목록·선택, 대화 이력 제한·초기화, 근거 표시, XSS 방어를 반영했다. AI 전용 테스트는 16개, 전체 회귀는 215개 통과했다. 실제 TimelyGPT·외부 사이트 요청은 0회다.

실운영 비밀설정: 루트 `.env`는 공통 로더가 읽고 Git에서 제외하며, `.env.example`만 추적한다. PowerShell 환경변수가 `.env`보다 우선한다. 최종 보완 검증은 전체 220 passed, 외부 요청 0회다.

## 실제 운영시험 재개 명령

TCP 443이 가능한 일반 PowerShell 환경에서 아래처럼 **명시적으로 최대 10페이지**만 실행한다.

`python run_all.py --mode daily --target all --max-urls 10`

성공한 뒤에만 50페이지 및 전체 범위를 검토한다. SSL·방화벽·프록시 설정을 변경하거나 403/429/WAF/캡차를 우회하지 않는다.
