# 2단계 — 검색포털·TimelyGPT·자동실행

1단계 통합시험이 완료된 후 시작한다. 검색포털과 AI는 서로 독립된 하위기능으로
구현하며, 실패해도 기본 페이지 점검과 결과서 생성을 계속한다.

## A. 검색포털

작업 시 `docs/search-portals.md`, 결과서 작업 시 `docs/reporting.md`만 추가로 읽는다.

- [ ] 기존 검색 노출 오류 URL seed 형식
- [ ] seed URL 매일 접속상태 재검증
- [ ] Google provider 또는 수동입력 대체
- [ ] Naver provider 또는 수동입력 대체
- [ ] Daum provider 또는 수동입력 대체
- [ ] 캡차·쿼터·차단·수집실패 처리
- [ ] `검색포털_오류결과.xlsx` 생성
- [ ] 포털별 수집범위·마지막 확인일 검증

## B. TimelyGPT AI 보조점검·챗봇

작업 시 `docs/ai-chatbot.md`, `project_sources/timelygpt_sources.md`만 추가로 읽는다.

- [ ] OpenAI 호환 클라이언트와 모델목록 확인
- [ ] 입력선별·마스킹·콘텐츠 해시 캐시
- [ ] 구조화 결과 검증과 페이지 결과서 반영
- [ ] 최신 JSON 기반 질의응답 서비스
- [ ] 허용된 점검 실행 함수
- [ ] 터미널 챗봇
- [ ] 선택적 `127.0.0.1` 웹 챗봇
- [ ] 401·402·404·429·5xx·비용 처리
- [ ] AI 장애 시 기본 점검 계속 여부 검증

## C. 자동실행·안정화

- [ ] 전체 배치 오케스트레이터와 부분실패 처리
- [ ] Windows 작업 스케줄러 가이드
- [ ] 연속 2회 실행으로 전일 비교·latest 갱신 검증
# H. TimelyGPT 점검결과 분석 챗봇

- [x] 로컬 AI API·컨텍스트 제한·mock 테스트 기반 구현
- [ ] 실제 TimelyGPT 연결시험(사용자 PowerShell에서 API 키 설정 후 수행)
