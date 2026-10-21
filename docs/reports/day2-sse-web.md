# Day 2 — POST SSE·Vue E2E

- 날짜: 2026-10-21
- 브랜치: `feat/day2-sse-web`
- 상태: 구현·자동 테스트·실제 브라우저 E2E 완료

## 구현

FastAPI `POST /api/search/stream`이 Router/Search/Context·Verification/Replan 진행 단계를 공개 SSE 계약으로 전송한다. 진행 이벤트에는 request ID, 단계, 검색 attempt와 고정 안내만 포함한다. 최종 `SearchResponse`가 만들어진 뒤에만 `result`를 보내며, 모든 정상·오류 경로는 `done`으로 끝난다.

Vue는 POST `fetch`와 `ReadableStream`으로 SSE를 읽는다. UTF-8 스트리밍 디코딩, LF/CRLF 프레임 경계, 멀티라인 data, 분할 프레임과 한 청크의 복수 프레임을 처리한다. HTTP 오류와 스트림 내부 오류를 구분하고 `done` 전 연결 종료를 성공으로 처리하지 않는다.

기존 JSON API와 검색·원문·화자·재검색 계약은 유지한다. `result`의 partial/ambiguous는 화면에서도 확정 결과와 구분한다.

## 검증 대상

- 성공: `routing → searching → validating → result → done`.
- 재검색: `replanning` 최대 2회, searching attempt 0/1/2.
- 실행 오류: 안전한 `error → done(status=error)`이며 내부 예외 비노출.
- 스트림 전 입력 오류와 busy: HTTP 422/503.
- 브라우저: 마니또 189초 링크, 화자 미확인 고지, 결과 없음/범위 밖.

## 실제 검증 결과

- 백엔드 85 passed, 프런트엔드 5 passed, Vite 프로덕션 빌드 성공.
- 실제 로컬 qwen3:8b, Hybrid 검색, 공식 MCP stdio, FastAPI SSE, Vue를 함께 실행했다.
- 마니또 질문은 `routing → searching(1차) → validating → result → done`을 거쳐 cue 69의 189초 링크와 `(RIKU chose RIKU) Got myself`, `speaker=null`을 표시했다.
- 료칸 화자 질문은 관련 장면 카드와 “자막에는 화자 정보가 없어 발화자는 확인할 수 없습니다” 안내를 함께 표시했다.
- 옷 색깔 질문은 `unsupported`로 종료하고 근거 카드를 만들지 않았다.
- Chrome E2E 3개 시나리오가 통과했으며 최종 화면은 Git 밖 `/private/tmp/wish-finder-day2-sse.png`에 저장했다.

이는 개발 smoke 1회 결과이며 C 전체 정확도나 반복 latency 측정이 아니다. 해당 평가는 Day 3 고정 gold A/B/C 실행에서 별도로 수행한다.
