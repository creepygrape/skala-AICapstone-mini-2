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
