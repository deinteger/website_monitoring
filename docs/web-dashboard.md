# 로컬 웹 대시보드

`python -m src.dashboard`는 기본적으로 `127.0.0.1:18765`에서만 수신한다. 포트는
`config/rules.yaml`의 `dashboard.port`로 바꿀 수 있다. 시작 전 포트 점유를 확인하며 기존
프로세스를 종료하지 않는다.

API는 상태 조회(`GET /api/health`, `/api/status`, `/api/history`), 최신 XLSX 목록
(`GET /api/reports`), 결과 다운로드(`GET /download/<상대경로>`)와 fixture 기반 수동 실행
(`POST /api/run`)을 제공한다. 다운로드는 output root 내부의 `.xlsx`만 허용하며 URL·명령·임의
파일 경로를 입력받지 않는다. 실행 요청은 설정된 target과 1~10 URL만 허용하고 공통 lock을 쓴다.

`POST /api/run`은 fixture payload만 받아 백그라운드에서 동일 `DailyPipeline`을 실행한다.
`POST /api/stop`은 아직 시작하지 않은 실행에 중지 요청을 기록한다. `/api/results`는 target,
verdict, menu_path, q(URL 부분문자열)로 필터할 수 있다. 스크린샷은 `/screenshot/<상대경로>`에서
`screenshots/` 내부 PNG만 제공한다.
