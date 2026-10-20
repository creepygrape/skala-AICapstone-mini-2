# ADR-0005 — FastAPI POST SSE + 브라우저 fetch 스트림으로 시연한다

- 상태: Proposed
- 날짜: 2026-10-20
- 관련 요구사항: FR-11, FR-12, FR-13, FR-14

## 배경
최종 제출은 웹에서 질문을 입력하고 검색 상태와 영상 결과를 확인할 수 있어야 한다. 검색/검증은 여러 단계로 진행되지만 미검증 답변은 사용자에게 노출되면 안 된다.

## 결정
Vue 3 단일 페이지 + FastAPI `POST /api/search/stream`으로 UI를 제공한다. 서버는 `routing`, `searching`, `validating`, `replanning`, `result`, `error`, `done` SSE 이벤트를 보낸다. 클라이언트는 POST 요청에 `fetch` + `ReadableStream`을 사용한다. 최종 결과는 Validator 이후 `result` 이벤트로만 출력한다.

## 대안과 트레이드오프
- 일반 JSON 응답: 구현이 쉽지만 다단계 진행 표시가 없음.
- WebSocket: 양방향 연결에는 유리하지만 현재 요청·상태 전송에는 운영 복잡도 증가.
- GET EventSource: 내장 자동 재연결은 편하지만 POST JSON 본문과 자연스럽게 맞지 않음.
- POST SSE: 표준 HTTP 흐름 유지, 단 프레임 분할/연결 종료 파서를 직접 정확히 구현해야 함.

## 영향 및 검증
- 프런트와 백엔드 통합을 Day 1부터 시작한다.
- 연결 끊김, 이벤트 분할 전송, 빈 결과, 에러+done, 브라우저 취소를 테스트.
- 미검증 초안을 `token` 형태로 먼저 내보내지 않음.

## 재검토 조건
양방향 서버 Push 또는 채팅 협업 기능이 명확히 요구될 때 WebSocket 검토.
