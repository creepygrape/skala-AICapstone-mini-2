# Day 1 — 기본 검색 웹 구현 기록

- 날짜: 2026-10-20
- 브랜치: `feat/day1-web-search`
- 상태: 브라우저 → 실제 MCP 검색 → 원문 확인 → 시점 링크 동작. Final C는 미완성.
- commit/push: 수행하지 않음.

## 문제와 구현

정확한 발언이나 영상 제목 대신 장면의 상황만 기억하는 사용자를 위해 한국어 질문으로 확보한 자막을 검색한다. 영어 추출 스크립트는 데이터 처리 조건이며 사용자 문제 정의를 대체하지 않는다. 음성·영상 화면을 이해했다고 주장하지 않는다.

세 영상 SRT의 원문 cue를 보존하고 20초 창/10초 이동의 검색 청크를 만든다. 긴 cue는 단독 항목으로 보존한다. BM25Plus·다국어 bge-m3·RRF를 사용하고 같은 장면의 겹치는 후보를 억제한다. 모델은 기존 로컬 캐시에서만 로드했다. 새 모델 다운로드나 유료 API 호출은 없다.

Vue가 FastAPI JSON API를 호출한다. FastAPI lifespan에서 공식 MCP SDK 2.x의 stdio subprocess·세션을 준비하고, 세 가지 MCP 도구로 검색·원문 문맥·메타데이터를 읽는다. 인용·시각·URL은 원문 cue에서 결정적으로 구성한다. 발화자는 항상 null이다.

## 실제 데이터와 경계

| 로컬 파일 | 영상 ID | cue 수 |
|---|---|---:|
| hokkaido_1.srt | 1HJgbE66GI4 | 1,534 |
| camp_1.srt | vWjPXwKV_Y8 | 1,558 |
| oth_5.srt | zOgJILPNzbE | 658 |

총 3,750 cue, 현재 청킹 결과 869개다. cue 1220은 75.091초로 보존했다. 원본·로컬 manifest·인덱스는 Git에서 제외하고 합성 fixture와 manifest 예시만 공개 대상으로 둔다. 영상 제목은 미확인 표시를 사용하고 이용 출처·조건·영상 시각 정합성은 미확인이다. oth_5 제공 URL의 t=186은 자막 오프셋으로 적용하지 않았다.

## 실제 검증 명령과 결과

| 명령/검증 | 결과 |
|---|---|
| `.venv/bin/python -m pytest backend/tests -q` | 11 passed |
| `npm --prefix frontend run test -- --run` | 2 passed |
| `npm --prefix frontend run build` | 성공 |
| `npm --prefix frontend audit --json` | 보고된 취약점 0건 |
| `.venv/bin/python -m compileall -q backend` | 성공 |
| `git diff --check` | 성공 |
| `.venv/bin/python scripts/browser_smoke.py` | 실제 Chrome 입력·첫 결과 cue 69·189초 링크·화자 미확인·의미 검증 미완료 안내 확인 |

pytest에는 공식 SDK 2.x 실제 stdio 연결, LangGraph 노드의 동일 세션 반복 호출, JSON API의 실제 MCP 도구 3종 호출, 원문 역참조 거부, BOM·CRLF·시간 겹침·긴 cue·영상 경계가 포함된다. 합성 fixture 테스트와 로컬 실제 corpus 검사 범위를 구분했다.

Chrome 화면은 `/private/tmp/wish-finder-day1.png`에 저장했다. 영상 링크의 href를 확인했으며 YouTube 실제 재생 시각의 내용 일치까지 검증한 것은 아니다.

## 실제 관측과 측정 한계

로컬 CPU에서 bge-m3 로딩과 869개 청크 인덱스 생성에 합계 38.02초가 걸렸다(한 번 측정, 라이브러리 초기화 포함). 이전 사전 시험의 qwen3:8b JSON 응답은 4.77초였으며 제품 의미 검증 latency가 아니다.

실제 JSON API에서 워밍된 상태로 각 질문을 한 번씩 실행한 결과다. 통계적 평가나 p95로 해석하지 않는다.

| 개발 질문 | 첫 결과 | 관측 |
|---|---|---|
| 리쿠가 마니또 뽑다가 자기 자신을 뽑은 장면 | cue 69, 189.606초 | HTTP 포함 0.288초, 목표 장면 1위 |
| 료칸이 뭔지 물어본 부분 | cue 1220, 2892.165초 | 0.467초, 목표 cue 41(138.430초)은 2위 |
| 료칸이 뭔지 물어본 멤버가 누구야? | cue 1220, 2892.165초 | 0.322초, 모든 결과 speaker=null; 검색 정확도 개선 필요 |

질문은 개발·시연용이다. 고정 gold set A/B/C 실험, Scene Success@1·Hit@3·unsupported 정확도·p95·재검색 효과는 **미측정**이다. 검색 결과가 좋았던 질문만으로 품질을 일반화하지 않는다.

## ADR 및 남은 작업

- ADR-0001: 원문 cue·speaker=null 유지.
- ADR-0002: BM25Plus·NumPy 로컬 벡터·RRF·인덱스 무효화 기준 기록.
- ADR-0003: 조건부 최대 2회 재검색(최대 3라운드)은 승인됐지만 제품 Graph는 아직 미구현.
- ADR-0004: SDK 2.x MCPServer·실제 stdio·LangGraph 합성 호출과 JSON 검색 도구 호출 검증 결과 기록.
- ADR-0006: 긴 cue 단독 처리와 원문 역참조 보존.

Day 1은 원문과 시각을 검증한 검색 후보를 보여준다. 의미 검증이 없어 결과를 `partial`과 `semantic_verification_skipped`로 표시하며 Final C 성공으로 세지 않는다. 근거 없는 한국어 사실 요약을 생성하지 않는다.

Day 2 남은 P0: Router/Planner/Search/Context/Verification/Finalize 제품 Graph, 의미 검증, 조건부 최대 2회 재검색, POST SSE와 fetch 스트림 파서, timeout·취소·MCP 장애 복구·로컬 추적. Resource/Prompt 확장은 P1을 유지한다.

추가 확인: 세 영상별 수동 시간 기준점, 제목과 자막 이용 출처, 고정 gold set 작성·확정. MCP 동기 계산은 클라이언트 취소만으로 즉시 중단됨을 보장하지 않으며 장애 경로에서 추가 검증한다.
