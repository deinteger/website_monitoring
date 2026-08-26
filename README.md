# 홈페이지 현행화·품질점검 자동화

두 홈페이지를 매일 점검해 페이지별 결과와 검색포털 오류 결과를 각각 XLSX로 만들고,
TimelyGPT 기반 AI 보조점검·결과 질의응답을 제공하는 로컬 Python 프로젝트다.

## 새 작업자 시작 순서

```text
1. AGENTS.md
2. PLAN.md
3. HANDOVER.md
4. PLAN.md가 가리키는 plans/phase*.md의 현재 항목
5. AGENTS.md 표에 지정된 작업별 docs 1~2개
```

전체 `docs/`와 원본 PDF·HWPX를 매번 읽지 않는다.

## 대상

- `https://www.nihhs.go.kr`
- `https://fruit.nihhs.go.kr`

## 핵심 결과물

- `페이지별_점검결과_YYYY-MM-DD.xlsx`
- `검색포털_오류결과_YYYY-MM-DD.xlsx`

## 개발단계

1. 매일 페이지 전수점검과 페이지별 결과서
2. 검색포털·TimelyGPT 챗봇·매일 자동실행
3. 전자정부 공식 품질진단 확장

현재 작업은 `PLAN.md`와 `HANDOVER.md`를 확인한다.
# 10페이지 실제 운영시험 재개 명령

전체 사이트:

```powershell
python run_all.py --mode daily --target all --max-urls 10
```

사이트별:

```powershell
python run_all.py --mode daily --target nihhs --max-urls 10
python run_all.py --mode daily --target fruit --max-urls 10
```

`config/rules.yaml` 안전 상한은 `crawl.max_urls: 10`, `resources.max_requests: 10`,
동시성 1, 요청 간격 1초다. E 실제 운영시험은 Codex 환경 네트워크 차단으로 미완료이며,
F 자동 배치와 G 대시보드는 fixture 검증 완료다.

