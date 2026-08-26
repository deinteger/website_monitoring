# 1단계 운영 가이드

실제 10페이지 운영시험 재개 명령은 `python run_all.py --mode daily --target all --max-urls 10`이다.
사이트별로는 `--target nihhs --max-urls 10` 또는 `--target fruit --max-urls 10`을 사용한다.
YAML 상한은 페이지 10, 자원 요청 10, 동시성 1, 요청 간격 1초다.

## 안전 제한과 사전진단

현재 설정은 사이트별 최대 10 URL, 동시성 1, 요청 간격 1초다. 페이지 10개라면
발견 요청(메뉴·전체메뉴·sitemap) 최대 3회와 페이지 요청 최대 10회가 기본 상한이며,
첨부·이미지 등 자원 요청은 `resources.max_requests`(10) 범위에서 추가된다. 따라서
사이트별 보수적 상한은 23회, 두 사이트는 46회이며 최소 실행시간은 요청 간격만
고려해 사이트당 약 13초, 자원 재검사까지 약 23초다. 캐시 재사용 시 자원 요청은 감소한다.

2026-08-26 사전진단에서 두 대상의 DNS A 레코드는 해석됐으나 TCP 443 연결은 실패했다.
추가 읽기 전용 진단에서 WinHTTP는 direct, 현재 사용자 프록시/PAC는 미설정, 관련 환경변수는
없었다. PowerShell Invoke-WebRequest는 연결 실패, Python 직접·시스템 프록시 모드는 모두
WinError 10013, 설치된 Playwright Chromium은 ERR_NETWORK_ACCESS_DENIED였다. SSL 검증 해제,
방화벽·보안제품·프록시 변경이나 차단 우회는 하지 않았다. 이 환경에서는 실제 10페이지 운영시험과
50페이지/전체 확대를 보류한다.

`network.transport: auto`는 `ProxyHttpTransport → HttpTransport → BrowserTransport` 순서다.
fallback은 WinError 10013, DNS/연결/SSL/프록시 연결 실패에만 적용된다. 401·403·429·WAF·캡차는
우회하지 않고 점검 불가로 반환한다. 프록시 URL은 `WEBSITE_CHECKER_PROXY` 환경변수로만 읽으며
소스·YAML·상태 파일에 저장하지 않는다.

## 자동 배치

`start_daily.bat`은 `daily_batch.py`를 실행한다. 실제 작업
스케줄러 등록은 하지 않는다. `register_daily_task.ps1`은 `-WhatIf` 기본값으로 등록 내용을
검증하며, 운영 시간을 정한 뒤에만 `-Register`로 사용한다. 종료코드는 0(완료), 2(부분실패),
1(설정·상태 저장 실패)이다.

공통 lock 파일은 `state/daily_execution.lock`이다. 자동 배치와 수동 실행이 동시에 시작되면
나중 실행은 실패하며 기존 실행을 종료하지 않는다.

생성 보고서는 `output/YYYY-MM-DD/`와 `output/latest/`에 보관한다. `retention.report_keep_days`
(기본 90일) 이전 날짜 폴더는 정리 후보로만 계산한다. 상태 JSON·실행 이력·latest는 자동 삭제하지 않는다.
