# TimelyGPT AI 보조점검·챗봇

## 1. 목적

TimelyGPT API를 이용해 다음 기능을 제공한다.

1. 변경되거나 규칙검사에서 후보가 된 페이지의 오탈자·최신성·개선안 재검토
2. 최신 페이지 점검결과와 검색포털 오류결과에 대한 자연어 질의응답
3. 사용자의 명시적 요청에 따른 허용된 사이트 점검 실행

AI는 크롤러와 규칙검사를 대체하지 않는다. 사실 데이터는 로컬 JSON에서 가져오고,
AI는 선별·설명·요약·후보판정만 수행한다.

## 2. 연결방식

기본 구현은 Python과 OpenAI 호환 Chat Completions를 사용한다.

```text
base URL: https://hello.timelygpt.co.kr/api/v2/chat/bridge/openai
model list: https://hello.timelygpt.co.kr/api/v2/chat/bridge/info/models
```

TimelyGPT 전용 TypeScript SDK는 별도 방식이다.

| 구분 | OpenAI 호환 방식 | TimelyGPT 전용 SDK |
|---|---|---|
| 언어 | Python·TypeScript 등 OpenAI SDK | TypeScript/JavaScript |
| base URL | `/api/v2/chat/bridge/openai` | `/api/v2/chat` |
| 모델명 | `공급사/모델` | 전용 SDK 모델명 |
| 키 예시 | `tgpt_sk_...` | `sdk_live_...` |

두 방식을 혼용하지 않는다. 현재 Python 프로젝트에는 OpenAI 호환 방식을 적용한다.
사용자가 보유한 키 종류가 맞지 않으면 키를 노출시키지 않은 상태에서 연결방식만
재선택한다.

## 3. 환경변수

```text
TIMELYGPT_API_KEY=
TIMELYGPT_BASE_URL=https://hello.timelygpt.co.kr/api/v2/chat/bridge/openai
TIMELYGPT_MODELS_URL=https://hello.timelygpt.co.kr/api/v2/chat/bridge/info/models
TIMELYGPT_MODEL=
```

- 키는 소스, HTML, JSON, XLSX, 로그, 인수인계서에 저장하지 않는다.
- `base_url`을 누락해 키가 OpenAI 공식 서버로 전송되지 않게 테스트한다.
- 허용 호스트를 `hello.timelygpt.co.kr`로 제한한다.
- 모델명은 하드코딩하지 않고 실행 시 모델목록을 확인하거나 설정에서 선택한다.

## 4. 연결시험

1. 모델목록 URL을 호출한다.
2. HTTP 200뿐 아니라 응답이 JSON 배열인지 확인한다.
3. 설정된 모델이 목록에 존재하는지 확인한다.
4. 최소 토큰의 인증 요청 1회를 실행한다.

오류 분류:

- OpenAI의 `Incorrect API key`: TimelyGPT base URL 누락 가능성
- TimelyGPT 401: 키 오류·폐기된 키
- 402: 크레딧 부족, 재시도 금지
- 404: 허용되지 않는 모델, 모델목록 갱신
- 429: rate limit, 지수 백오프 후 제한 재시도
- 5xx: 일시 오류로 기록하고 규칙 기반 점검은 계속

## 5. AI 보조점검 흐름

```text
페이지 수집
→ 규칙검사 및 콘텐츠 해시 비교
→ 변경 페이지·검토 후보 선별
→ 개인정보 마스킹·본문 길이 제한
→ TimelyGPT 요청
→ JSON 결과 구조검증
→ ai_findings.json 저장
→ 페이지 결과서에 AI 보조 항목 표시
```

입력 제한:

- 공개된 페이지 콘텐츠만 사용
- 메뉴, 제목, URL, 게시일자, 필요한 근거 문단만 전송
- 동일 콘텐츠 해시는 다시 호출하지 않음
- 실행별 AI 최대 페이지 수와 토큰 한도 설정
- 전체 첨부파일 원문은 기본적으로 전송하지 않음

결과 필드:

- `issue_type`
- `confidence`
- `evidence`
- `reason`
- `recommendation`
- `needs_human_review`

응답 구조검증이 실패하면 자유문을 억지로 파싱하지 않고 `AI 판정 불가`로 기록한다.

## 6. 챗봇 데이터 이용

챗봇은 다음 로컬 데이터만 근거로 사용한다.

- `state/inventory.json`
- `state/issues.json`
- `state/search_urls.json`
- `state/ai_findings.json`
- `state/run_history.jsonl`

질문과 관련된 레코드를 먼저 로컬에서 필터링하고 필요한 일부만 AI에 전달한다. 전체
JSON을 매 질문마다 보내지 않는다.

답변 필수사항:

- 대상 사이트와 메뉴 경로
- 근거 URL
- 점검일시
- 신규·지속·해결 상태
- 데이터가 없거나 오래된 경우 명시
- 사실과 AI 제안을 구분

## 7. 허용된 점검 실행

챗봇이 실행할 수 있는 명령은 코드에 등록된 다음 함수로 제한한다.

- `run_check(target: nihhs|fruit|all, max_urls: configured_limit)`
- `get_run_status(run_id)`
- `get_latest_summary(target)`
- `get_page_issues(url)`
- `compare_runs(date_a, date_b)`

임의 URL, 임의 파일경로, 임의 셸 명령은 입력받지 않는다. 전체 점검 실행은 사용자가
대상과 범위를 확인한 뒤 수행한다.

## 8. 사용자 인터페이스

### 필수: 터미널 챗봇

```bash
python chatbot.py
```

- 새 대화
- 점검결과 질문
- 허용된 점검 실행
- 현재 실행상태
- 종료

### 선택: 로컬 웹 챗봇

```bash
python chatbot_server.py --host 127.0.0.1 --port 8766
```

- `127.0.0.1`에만 바인딩
- API 키는 Python 백엔드에만 존재
- HTML·JavaScript가 TimelyGPT를 직접 호출하지 않음
- 대화기록은 메모리 또는 로컬 JSON이며 DB 사용 안 함
- CSRF·입력크기·동시실행 제한 적용

## 9. 테스트

- 실제 API 대신 mock을 사용하는 단위·통합 테스트
- 모델목록이 JSON이 아닌 HTML인 경우 실패 처리
- base URL 누락 방지 테스트
- 키·프롬프트 내 비밀정보 로그 미노출 테스트
- 401·402·404·429·5xx 처리 테스트
- 보고서 데이터가 프롬프트 명령으로 동작하지 않는 prompt injection 테스트
- 근거 URL 없는 답변 차단 테스트
- AI 장애 시 규칙검사·XLSX 생성 계속 여부 테스트

## 10. 참고 문서

- TimelyGPT SDK: https://github.com/timely-hub/timely-gpt-sdk
- TimelyGPT OpenAI 호환 가이드:
  https://github.com/timely-hub/timely-gpt-sdk/blob/master/OPENAI_SDK_GUIDE.md
- TimelyGPT REST API 문서: https://hello.timelygpt.co.kr/api/v2/chat/sdk

