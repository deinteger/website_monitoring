# PLAN.md

이 파일은 전체 계획, 현재 단계와 현재 작업을 관리한다. 단계별 체크리스트는 `plans/phase*.md`에서 관리한다.

## 현재 위치

- 현재 단계: `1단계`
- 현재 작업: `E 실제 사이트 운영검증 대기` (사이트맵 없는 경우 내부 링크 자동 수집 구현 완료)
- 단계 계획: `plans/phase1-daily.md`
- 상태: `부분완료`

## 현재 상태

- F 자동 배치: 완료
- G 웹 대시보드: 완료
- E 접속 방식 진단 및 다중 transport mock 테스트: 완료
- E 실제 10페이지 운영시험: Codex 실행 환경 네트워크 차단으로 미완료
- E 50페이지·전체 확대: 미완료
- 다음 작업: 접속 가능한 일반 PowerShell에서 실제 사이트별 10페이지 시험
- 사이트맵이 없는 사이트는 대표 페이지에서 동일 도메인 내부 링크를 순차 수집하며 `crawl.max_urls: 10` 상한을 적용한다.
- H TimelyGPT 분석 챗봇: mock 기반 구현·보안 보완 완료, 실제 연결시험 대기

## 단계별 계획

| 단계 | 상태 | 계획 파일 |
|---|---|---|
| 1. 매일 페이지 전수점검·결과서 | 진행 중(운영시험 대기) | `plans/phase1-daily.md` |
| 2. 검색포털·TimelyGPT·자동 실행 | 대기 | `plans/phase2-search-ai.md` |
| 3. 전자정부 공식 품질진단 | 대기 | `plans/phase3-quality.md` |

## 운영 명령

전체 사이트:

```text
python run_all.py --mode daily --target all --max-urls 10
```

사이트별:

```text
python run_all.py --mode daily --target nihhs --max-urls 10
python run_all.py --mode daily --target fruit --max-urls 10
```

설정 상한은 `crawl.max_urls: 10`, `resources.max_requests: 10`, 동시성 1, 요청 간격 1초 이상이다.
