# PR #1 리뷰 수정 기록

- 날짜: 2026-10-20
- 대상: Day 1 검색 웹, 리뷰 10건(필수 6건·개선 4건)
- Final C 의미 검증·재검색·SSE는 기존 Day 2 범위를 유지한다.

## 반영 내용과 회귀 검증

| 번호 | 수정 | 검증 |
|---|---|---|
| 1 | MCP 세션 초기화 기본 180초, API 도구 호출 30초 분리 | 도구 timeout보다 긴 시작 지연이 있는 실제 stdio 서버 연결, 실제 corpus API 재시작 성공 |
| 2 | 검증 실패 후보만 제외, evidence_rejected 경고 | 일부 실패 시 정상 후보 유지, 전부 실패 시 unsupported, 도구 장애는 503 |
| 3 | 반복 접두어는 완전 반복·공백 경계에서만 제거 | Go/Good, I/It's, we/we're 보존 및 실제 반복 설명 중복 제거 |
| 4 | 연속 빈 줄·구조 행 공백 허용 | cue ID·시간 행 정리, 자막 본문 앞뒤 공백 보존 |
| 5 | 공통 manifest resolver로 루트 기준 상대 경로 해석 | 실행 디렉터리 변경 후 같은 manifest·원문 읽기 |
| 6 | MCP 검색 worker의 비차단 잠금, 중복 검색 즉시 거절 | 실제 stdio: 느린 호출 timeout → search_busy 즉시 반환 → 기존 계산 완료 후 정상 검색 |
| 7 | 라운드당 질의 벡터 1회·cue 맵 초기화 시 재사용 | 합성 encoder에서 hybrid 질의 encode 1회, keyword encode 0회 |
| 8 | 시작 시 영상별 메타데이터 캐시 | 영상 목록 반복 조회·검색 후에도 영상당 메타데이터 Tool 호출 1회 |
| 9 | 검증된 ID·시간으로 공통 URL 생성 | 영상 ID·음수·NaN 거부, 189.606초 → t=189s |
| 10 | 미사용 startup_error 제거, 종료 시 상태 정리 | 실제 API lifespan 통합 테스트 및 문서에 fail-fast 정책 명시 |

## 실제 실행 결과

- `.venv/bin/python -m pytest backend/tests -q`: **23 passed**.
- `npm --prefix frontend run test -- --run`: **2 passed**.
- `npm --prefix frontend run build`: **성공**.
- `.venv/bin/python -m compileall -q backend`: **성공**.
- `git diff --check`: **성공**.
- `.venv/bin/python scripts/browser_smoke.py`: **성공**. 수정 서버에서 한국어 마니또 질문의 첫 원문 cue와 189초 링크·화자 미확인·의미 검증 미완료 안내 확인.

## 결정과 한계

관련 ADR 0001/0002/0004/0006 및 README를 갱신했다. 원문 데이터·화자 null·SDK 2.x·stdio·조건부 재검색 최대 2회·SSE 계약은 유지한다.

클라이언트 timeout은 계산 강제 중단을 보장하지 않는다. 실제 계산이 끝날 때까지 서버 잠금을 유지하고 추가 계산을 큐에 쌓지 않는 것으로 메모리·공용 캐시를 보호한다. 초기화 180초·도구 30초·전체 요청 60초는 각기 다른 상한이다. 시작 실패는 fail-fast이며 실행 중 시작 오류를 `/ready`에서 제공한다고 주장하지 않는다.

원문 검증에 실패한 후보는 노출하지 않는다. 일부 성공은 Day 1 partial, 전부 실패는 unsupported, 실제 검색 0건은 not_found로 구분한다. 메타데이터는 서버 재시작 시 갱신한다.

실제 영상과 자막의 시각 정합성·출처/이용 조건·gold set 정량 평가·Day 2 전체 Graph/취소/장애 복구는 미완료다. 이번 회귀 시험을 전체 P0 완료로 해석하지 않는다.
