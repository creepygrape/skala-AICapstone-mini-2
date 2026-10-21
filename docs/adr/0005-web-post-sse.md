# ADR-0005 — FastAPI POST SSE + 브라우저 fetch 스트림으로 시연한다

- 상태: Accepted (구현·브라우저 검증 완료)
- 날짜: 2026-10-20
- 관련 요구사항: FR-11, FR-12, FR-13, FR-14

## 배경
최종 제출은 웹에서 질문을 입력하고 검색 상태와 영상 결과를 확인할 수 있어야 한다. 검색/검증은 여러 단계로 진행되지만 미검증 답변은 사용자에게 노출되면 안 된다.

## 결정
Vue 3 단일 페이지 + FastAPI `POST /api/search/stream`으로 UI를 제공한다. 서버는 `routing`, `searching`, `validating`, `replanning`, `result`, `error`, `done` SSE 이벤트를 보낸다. 클라이언트는 POST 요청에 `fetch` + `ReadableStream`을 사용한다. 최종 결과는 Validator 이후 `result` 이벤트로만 출력한다.

- Graph는 공개 진행 콜백으로 노드명과 0 기반 `attempt`만 전달한다. 질문·후보·모델 추론 내용은 진행 이벤트에 넣지 않는다.
- 요청 검증, readiness, 동시 검색 거절은 스트림 시작 전 HTTP 422/503으로 처리한다. 응답 헤더가 시작된 뒤의 모델·Agent·MCP 오류는 안전한 `error` 다음 `done(status=error)`로 처리한다.
- `result`는 기존 `SearchResponse` 전체 계약을 사용하며 Graph가 최종 상태를 만든 뒤 한 번만 보낸다. `partial`과 `ambiguous`는 상태 그대로 표시하고 C 성공으로 간주하지 않는다.
- 연결 종료 시 실행 task를 취소하고 API busy 상태를 해제한다. MCP의 동기 계산이 즉시 중단되지 않을 수 있는 기존 한계는 유지한다.
- 브라우저 파서는 UTF-8 스트리밍 디코더, CRLF/LF 빈 줄 경계, 여러 `data:` 줄, 한 청크의 복수 프레임과 여러 청크로 나뉜 프레임을 처리한다. `done` 전 연결 종료는 성공으로 처리하지 않는다.

## 대안과 트레이드오프
- 일반 JSON 응답: 구현이 쉽지만 다단계 진행 표시가 없음.
- WebSocket: 양방향 연결에는 유리하지만 현재 요청·상태 전송에는 운영 복잡도 증가.
- GET EventSource: 내장 자동 재연결은 편하지만 POST JSON 본문과 자연스럽게 맞지 않음.
- POST SSE: 표준 HTTP 흐름 유지, 단 프레임 분할/연결 종료 파서를 직접 정확히 구현해야 함.
- LangGraph `astream_events` 직접 노출: 구현량은 줄 수 있지만 내부 노드·모델 이벤트와 데이터가 API 계약으로 새어 나갈 수 있어 채택하지 않는다. 명시적인 공개 진행 콜백만 사용한다.

## 영향 및 검증
- Day 1 JSON UI를 유지한 상태에서 Day 2 Agent 완료 후 스트림 경계를 통합한다.
- 이벤트 분할 전송, CRLF·멀티라인 data, 빈 결과, HTTP 오류, error+done, done 전 연결 종료와 브라우저 취소를 테스트한다.
- 미검증 초안을 `token` 형태로 먼저 내보내지 않음.

## 재검토 조건
양방향 서버 Push 또는 채팅 협업 기능이 명확히 요구될 때 WebSocket 검토.

## PR #4 리뷰 반영 — 응답 수명과 취소 정리 (2026-10-21)

배경: 스트림 제너레이터가 시작되기 전에 연결이 끊기면 제너레이터의 finally가 실행되지 않아 busy가 남는다. 실행 중 연결 종료의 AnyIO 취소 범위는 정리 대기까지 반복 취소할 수 있다.

결정: 응답 __call__의 finally에서도 동일한 StreamOwner 정리를 호출한다. 실행 task를 한 번 취소하고 shield 안에서 최대 5초 기다린다. 종료 콜백은 대기 전에 등록한다. 제한 시간 내 종료하지 않으면 경고를 기록하고 task 종료까지 busy를 유지한다. task는 lifespan이 보유하며 MCP·모델을 닫기 전에 종료를 기다린다. 종료용 queue sentinel은 제거하고 done 프레임으로 소비를 끝내어 가득 찬 queue가 취소 정리를 막지 않게 한다.

대안/트레이드오프: 제너레이터 finally만으로 관리하면 미시작 경로를 놓친다. 5초 뒤 무조건 잠금을 풀면 같은 MCP 세션에 작업이 겹칠 수 있다. 채택안은 안전하게 겹침을 막지만 정리가 끝나지 않는 작업은 검색·서버 종료를 지연시킬 수 있다. MCP 서버 내부의 동기 계산이 즉시 취소됨을 보장하지 않는다.

JSON/SSE는 공통 실행 함수로 검색 분기·오류 변환·로그를 공유한다. 기본 검색은 search_transcripts 완료 후 validating을 보낸다. unsupported는 원문 검증 실패와 범위 밖 안내를 구분하며 partial/ambiguous에도 화자 안내를 함께 표시한다.

검증 근거: 실제 ASGI 즉시 disconnect·실행 중 disconnect·전송 실패, 지연 정리·제한 시간 초과 후 busy 유지·종료 후 재검색, 기본 검색 도구/단계 순서와 JSON/SSE 오류 일치 회귀 테스트를 추가했다. 실행 명령과 실제 결과는 reports/day2-sse-web.md에 기록한다.

재검토 조건: 정리 시간 초과가 반복되거나 ASGI spec 2.4 서버로 바꾸는 경우. 후자는 긴 모델 대기 중 disconnect 감지가 다음 send까지 늦어질 수 있어 별도 감지 또는 heartbeat를 검토한다.

## 진행 이벤트에 elapsed_ms 추가 (2026-10-21, 시연 피드백)

배경: 진행 문구가 덮어써져 단계 이력과 소요 시간을 볼 수 없었다. 결정: routing/searching/validating/replanning/done payload에 가산 필드 `elapsed_ms`(서버 monotonic 기준 요청 시작 후 경과)를 추가한다. 프론트는 이벤트를 누적하고 다음 이벤트와의 차이로 단계 시간을 계산한다. 대안: 브라우저 수신 시각 차이(네트워크·버퍼링 영향으로 부정확) — 서버 값이 없을 때만 폴백. 기존 필드·이벤트 이름·순서는 불변이고 `result`에는 추가하지 않는다(검증 전 결과 미노출 원칙 유지). 검증: test_sse.py의 elapsed_ms 단조 증가 단언, App.test.js 누적 렌더 테스트. 재검토: 단계 내부 세부(LLM/Tool 호출별) 시간이 필요해질 때.

### 보강 — 노드별 실제 시간 `stage_ms` (PR #6 리뷰 반영)

`elapsed_ms`의 이벤트 간 차이는 노드별 시간이 아니다. `replanning`은 rewrite 완료 후 발행(PR #4 계약)되므로 rewrite 시간이 직전 validating에 합산되고, 마지막 구간에는 finalize가 섞인다. 이벤트 이름·발행 시점은 유지하고, 진행 이벤트와 `done`에 가산 필드 `stage_ms`(마지막 공개 이벤트 이후 완료된 노드별 ms: `router/search/context/verification/replan/finalize`)를 추가한다. 프론트(`api/steps.js`)는 routing←router, searching←search, validating←context+verification, replanning←replan으로 매핑하고 `finalize`는 총 시간에만 반영한다. 비-Agent 폴백 경로처럼 `stage_ms`가 없으면 `elapsed_ms` 이벤트 간 경과로 대체하며 이 경우 값은 노드별 시간이 아니라 공개 이벤트 사이 경과 시간이다. `error` 이벤트 또는 `done.status=error`는 실행 중 단계를 완료가 아닌 실패로 표시한다. 검증: `test_agent.py`(rewrite 지연 시 `stage_ms.replan` 귀속), `steps.test.js`(실제 이벤트 순서).

## 갱신 (ADR-0010)
SSE 이벤트 종류·순서는 불변이다. 요청 본문에 선택 필드 `history`(최대 3턴)와 `exclude`(최대 20)가 추가됐고, 없으면 기존과 같다. 프론트는 한 화면의 단일 응답 대신 대화 목록에 턴별로 이벤트를 누적한다.
