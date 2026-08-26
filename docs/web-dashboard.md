# 운영용 웹 대시보드

`python -m src.dashboard`는 `127.0.0.1:18765`에만 바인딩되는 운영용 HTML 화면을 제공한다. 포트는 `config/rules.yaml`의 `dashboard.port`에서 설정하며, 사용 중인 포트를 종료하지 않고 시작을 거부한다.

## 수동 점검

화면에서 대상 사이트, 최대 1~10페이지, 자원·접근성·스크린샷 강제점검을 선택한다. `점검 시작`은 배치와 같은 `DailyPipeline`과 공통 실행 잠금을 사용한다. 화면과 운영 API는 fixture, URL, 파일 경로, 명령어를 입력받지 않는다. fixture는 자동 테스트에서 `make_handler(..., allow_fixture=True)`로 의존성 주입할 때만 사용할 수 있다.

## API

- `GET /api/health`, `/api/status`, `/api/summary`
- `GET /api/results` — `target_id`, `menu_path`, `verdict`, `issue_type`, `lifecycle`, `q`, `page`, `page_size`, `sort` 허용
- `GET /api/results/<issue_key>`
- `GET /api/history`, `/api/reports`
- `POST /api/run` — `target`, `max_urls`, 세 가지 강제점검 옵션만 허용
- `POST /api/stop`
- `GET /download/<상대 XLSX 경로>`, `GET /screenshot/<상대 PNG 경로>`

다운로드와 스크린샷은 허용된 루트 안의 파일만 제공하며 경로 순회를 차단한다. API 오류와 실행 상태는 민감한 traceback이나 절대경로를 노출하지 않는다.

## 실행

```text
python -m src.dashboard
```

브라우저를 열려면 `start_dashboard.bat`을 사용한다. 외부 사이트 요청 없는 화면·API 검증은 fixture transport를 주입한 테스트로 수행한다.
