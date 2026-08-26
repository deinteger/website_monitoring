# 확정 요구사항

## 시스템 형태

- 로컬에서 실행하는 Python 배치 프로그램
- 별도 서버·포트·SQL DB 없음
- Windows 작업 스케줄러로 매일 실행
- 상태는 JSON, 이력은 JSONL
- TimelyGPT API를 사용한 AI 보조점검과 점검결과 챗봇
- 웹 챗봇 사용 시에만 로컬 백엔드 실행

## 대상 사이트

| ID | 사이트명 | 기본 URL |
|---|---|---|
| `nihhs` | 국립원예특작과학원 | `https://www.nihhs.go.kr` |
| `fruit` | 과수생육·품질관리시스템 | `https://fruit.nihhs.go.kr` |

## 매일 점검영역

1. 페이지·메뉴 변동
2. 콘텐츠 최신성·신뢰성
3. 링크·이미지·첨부파일
4. 웹표준·접근성 기초
5. 접속상태·성능
6. 검색포털 오류

AI는 별도 점검영역을 늘리는 것이 아니라 2번 콘텐츠 최신성·신뢰성의 후보 재검토와
전체 결과 질의응답에 사용한다. AI 결과는 자동확정 오류가 아니라 `AI 검토 후보`로
표시한다.

URL은 메인 메뉴, 전체 메뉴, sitemap.xml을 각각 확인해 수집하고 각 URL의 발견
출처를 보존한다. 점검 범위 내 URL은 정규화·중복제거 후 순차 탐색한다.

게시일이 표시되는 모든 목록형 콘텐츠는 최신 게시일을 추출한다. 최신 게시일이
실행 기준일보다 달력 기준 3개월 이상 오래되면 `게시 최신성 지연`으로 분류한다.
날짜가 없거나 파싱할 수 없으면 지연으로 단정하지 않고 `점검 불가`로 기록한다.

## 결과 파일

페이지 관련 1~5번은 `페이지별_점검결과_YYYY-MM-DD.xlsx`, 검색포털 6번은
`검색포털_오류결과_YYYY-MM-DD.xlsx`로 분리한다.

결과 파일은 `output/YYYY-MM-DD/`, 오류 증거화면은 `screenshots/YYYY-MM-DD/`에
저장한다. 누락 범위와 점검 실패 사유는 페이지 결과서의 별도 시트에 기록한다.

## 실행 인터페이스 목표

```bash
python run_all.py --mode daily --target all
python run_all.py --mode daily --target nihhs
python run_all.py --mode daily --target fruit
python run_all.py --mode search --target all
python run_all.py --mode quality --target all
python run_all.py --check inventory --max-urls 10
python chatbot.py
python chatbot_server.py --host 127.0.0.1
```

실제 CLI 옵션은 최초 골격 단계에서 확정하되 위 사용성을 유지한다.
