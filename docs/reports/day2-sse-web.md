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

## PR #4 리뷰 7건 반영 및 재검증 (2026-10-21)

| 리뷰 | 변경 | 확인 |
|---|---|---|
| 필수 1 | 응답 __call__ finally에서 잠금 정리 | 실제 핸들러의 첫 iterator 실행 전 ASGI disconnect, 전송 실패 |
| 권장 2 | shield 안에서 최대 5초 취소 대기, 미종료 task의 종료 콜백에서 잠금 해제 | 정리 중 503, 시간 초과 후 busy 유지, 종료 후 재검색, lifespan의 MCP 종료 전 task 정리 |
| 권장 3 | unsupported의 evidence_rejected/scope/기타 안내 분리 | 실제 Vue 템플릿 렌더 테스트 |
| 개선 4 | 기본 검색 완료 후 validating 전송 | 도구 호출과 진행 이벤트 순서 회귀 |
| 개선 5 | 새 검색어 채택 후 replanning 전송 | 같은 검색어·예산 부족 종료 시 추가 이벤트 없음, 정상 0/1/2 검색 경로 |
| 개선 6 | partial/ambiguous와 화자 안내 동시 표시 | 두 상태의 실제 Vue 템플릿 렌더 테스트 |
| 개선 7 | JSON/SSE 공통 실행·오류 변환·로그 | 예외 발생 시 양 API의 안전한 오류 코드·메시지 일치 |

변경 파일: backend/app/main.py, sse.py, services/search.py, agent/graph.py; backend/tests/test_sse.py, test_agent.py; frontend/src/App.vue, App.test.js; scripts/browser_smoke.py; ADR-0003·0005, architecture.md, implementation-plan.md 및 이 보고서. 신규 의존성은 없다.

### 실제 실행 결과

- `.venv/bin/python -m pytest backend/tests -q`: **94 passed in 12.82s**.
- `npm --prefix frontend run test -- --run`: **8 passed**.
- `npm --prefix frontend run build`: **성공**.
- `git diff --check`: **통과**.
- `.venv/bin/python scripts/browser_smoke.py`: **실제 Chrome 4개 시나리오 통과**. 기존 로컬 qwen3:8b·bge-m3·공식 MCP stdio·FastAPI·Vue 연결.
- 첫 결과는 브라우저 수신 SSE에서 cue_ids=["69"], speaker=null, YouTube t=189s 확인. 화자 질문도 결과의 speaker=null 및 한계 안내 확인. 옷 색깔 질문은 unsupported 안내와 근거 카드 없음. UI에서 실행 중 취소 후 재검색하여 동일한 마니또 링크 확인.
- queue 포화 중 연결 종료도 정리가 완료되고 busy가 해제됨을 합성 ASGI 테스트로 확인했다.
- 최종 화면: Git 외부 `/private/tmp/wish-finder-day2-sse.png`.

### 검증 과정과 한계

초기 E2E는 로컬 Ollama 미실행과 sandbox의 로컬 접속 제한으로 실패했다. 기존 서비스를 시작하고 허용된 환경에서 재검증했다. 이후 추가한 네트워크 검증문이 기존 문자열 cue ID를 정수로 비교해 한 번 실패했으며, API 계약대로 검증문을 수정한 최종 실행은 통과했다. 모델 다운로드·신규 설치·유료 API 호출은 없었다.

94/8은 자동 테스트 수이며 A/B/C 정확도 측정값이 아니다. 위 Chrome 실행은 개발 smoke이며 반복 latency·p95·전체 C 정확도·실제 모델의 5초 초과 정리 빈도는 미측정이다. 정리 제한 시간 초과는 합성 task로 검증했다. 취소를 무시하는 작업은 busy 및 서버 종료를 지연시킬 수 있으며, MCP 내부 동기 계산의 즉시 중단을 보장하지 않는다. 현재 Uvicorn의 ASGI 2.3 경로를 사용하며 spec 2.4의 긴 대기 중 연결 종료 감지는 향후 재검토 대상이다.

ADR-0005에 응답 수명·보호된 정리·잠금 유지 대안과 트레이드오프를, ADR-0003에 채택된 재검색만 알리는 결정을 갱신했다. 사용자 docs/report/·원본 자막·비공개 gold는 변경·스테이징하지 않았다. commit/push는 변경 제시 후 별도 승인 대상이다.
