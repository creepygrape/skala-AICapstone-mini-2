# Day 2 첫 리뷰 — LangGraph·MCP·JSON API

- 날짜: 2026-10-21
- 브랜치: `feat/day2-agent-json`
- 범위: 첫 리뷰용 Agent JSON 경로. SSE·Vue 진행 상태·최종 C 평가는 아직 완료하지 않았다.

## 문제와 구현

Day 1 검색 후보가 질문의 상황과 실제로 관련 있는지 판정하고 근거가 부족하면 제한된 검색어 변경으로 다시 탐색한다. 팬의 희미한 장면 기억을 찾는 문제를 유지하며 음성·영상 자체를 분석하지 않는다.

`backend/app/agent/graph.py`의 Router → Search → Context → Verification → Replan/Finalize를 LangGraph 1.2.16으로 구현했다. 공식 MCP 2.3.0의 같은 stdio 세션으로 검색·문맥 도구를 호출하고 메타데이터는 lifespan 캐시를 재사용한다. SDK 다운그레이드·추가 adapter는 없다.

원문 검증은 A/B와 같은 `ground_candidates`/`verify_candidate`를 사용한다. 모델은 질의 분류·검색어·근거 ID별 relevant/uncertain/irrelevant만 반환한다. 잘못된 ID·중복/누락 판정은 오류다. 인용·URL·시각·화자는 모델로 생성하지 않으며 설명문도 검증 상태/화자 한계 고정 문구로 만든다.

검색은 최초 포함 최대 3라운드이며 관련 근거가 충분하면 즉시 종료한다. 근거 없음·의미 불일치·불확실만 재검색하고 같은 검색어가 나오면 조기 종료한다. 원문이 유효하지만 의미가 불확실한 후보는 ambiguous로 구별한다. MCP/모델 실패는 재검색하거나 빈 결과로 숨기지 않고 503으로 반환한다. 전체 60초·도구 30초·LLM 20초 상한을 둔다.

## 실행과 API 계약

기존 Ollama에 설치된 qwen3:8b를 사용한다. 모델/인덱스/HTTP client/Graph/MCP는 요청마다 초기화하지 않는다.

```sh
WISH_AGENT_ENABLED=1 WISH_LLM_MODEL=qwen3:8b HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

- POST `/api/search`: 기존 SearchRequest/SearchResponse 필드 유지. `/ready` stage는 `agent_json`.
- 기본 `WISH_AGENT_ENABLED=0`: 기존 A/B 경로 유지. 두 경로를 실행 중 자동 전환하지 않으며 서버를 재시작한다.
- 화자 질문: speaker_query로 분류해 관련 장면을 검색하고 자막만으로 확인 불가를 명시한다. 모든 speaker는 null이다.
- 범위 밖/일반 대화: 검색 없이 unsupported와 subtitle_only_scope 경고. 일반 대화 생성은 하지 않는다.
- 오류: 503의 request_id·안전한 code·한국어 메시지. 모델 내부 응답/예외 경로는 노출하지 않는다.
- 로그: Git 제외 `logs/agent.jsonl`에 의도·상태·단계·시간·호출 수·오류를 기록한다. 질문·자막 원문은 저장하지 않는다.
- LangSmith: 자동 원문 추적은 비활성화. 별도 `WISH_LANGSMITH_ENABLED=1`과 키가 있어야 메타데이터 요약만 전송한다. 실제 계정 전송은 미검증이며 대역 테스트와 로컬 로그를 검증했다.

## 실제 로컬 모델·MCP 실측

`scripts/agent_smoke.py`로 기존 개발/데모 질문만 사용했다. 원본 결과는 Git 제외 `eval/private/day2-agent-smoke.json`에 보관한다. gold 초안은 검색·평가하지 않았다. 아래는 문항별 1회 실행이며 최종 성능 비교가 아니다.

| 질문 유형 | Router | 결과 | 첫 링크 시각 | 검색 라운드 | Tool / LLM | 총 시간 |
|---|---|---|---|---|---|---|
| 마니또 자기 자신 뽑기 | scene_search | found | 189초 | 1 | 4 / 2 | 16.4721초 |
| 료칸 질문 화자 | speaker_query | found + 화자 확인 불가 | 140초 | 1 | 4 / 2 | 11.8008초 |
| 옷 색깔 | unsupported | unsupported | 없음 | 0 | 0 / 1 | 1.7436초 |

추가 실제 HTTP 시험: `/ready` → POST `/api/search` → 실제 Graph/로컬 LLM/MCP → 마니또 189초 링크·speaker=null을 확인했다. 이 요청은 1라운드, Tool 4회/LLM 2회, Graph 시간 11.1448초였다. 초기화 시간은 위 요청 시간 밖이며 캐시/모델 준비 상태 차이가 있어 반복 성능이나 p95로 해석하지 않는다.

첫 장면 요청은 15초 목표를 초과했다. 8b 의미 판정과 검색의 누적 지연이 있으며 timeout 상한 내에서는 동작했다. SSE 미연결 상태이므로 첫 진행 이벤트 2초 목표는 아직 측정하지 않았다. 지연 목표가 달성됐다고 주장하지 않는다.

## 테스트

```sh
.venv/bin/python -m pytest backend/tests -q
npm --prefix frontend run test -- --run
npm --prefix frontend run build
git diff --check
```

- 백엔드 70 passed, 프런트엔드 2 passed, 빌드 성공.
- 0/1/2회 재검색·최대 3라운드·성공 후 종료·동일 검색어 종료·장면 유지 화자 안내·범위 밖·0건·원문 전부 탈락을 확인했다.
- 모델 JSON 오류/HTTP/timeout·잘못된 근거 ID·MCP 오류·전체 timeout·요청 취소를 검사했다. 실패는 미검증 응답/추가 재검색으로 이어지지 않는다.
- 실제 stdio API 테스트는 모델만 대역으로 두고 MCP 도구/원문/연속 요청·초기화/종료를 확인했다. 실제 모델 시험은 위 실측과 구별한다.
- 모델 준비 실패 시 HTTP client 정리·API 오류 뒤 busy 해제·LangSmith opt-in 경계를 검증했다.

## 변경 파일과 리뷰 포인트

- `backend/app/agent/{graph,model,telemetry}.py`: State/노드/구조화 모델/추적.
- `backend/app/main.py`: lifespan 초기화·종료와 opt-in JSON 연결.
- `backend/app/services/search.py`: 공통 원문 검증 경계 추출, A/B 동작 보존.
- `backend/tests/test_agent.py`, `scripts/agent_smoke.py`: 회귀 및 실제 로컬 시험.
- `.env.example`, README, architecture, implementation-plan, ADR 0003·0004: 실행·설계·검증 상태 정합성.

리뷰에서는 재검색 종료/오류 분리, 원문과 의미 검증 경계, 화자 설명 안전성, A/B 회귀, 수명 관리와 로그 개인정보 범위를 우선 확인한다. 독립 Multi-Agent 구현이라고 주장하지 않는다.

## 남은 작업과 한계

- 다음 PR: POST SSE·Vue 진행 상태/오류/연결 중단·전체 웹 E2E. 기존 Vue 안내는 기본 A/B 기준이며 이번 API 리뷰에서 Agent 웹 완료를 주장하지 않는다.
- Day 3: 확정 gold와 동일 조건 A/B/C 비교, C 화자 정답 3조건 및 설명문 단정 검토. 아직 미측정이다.
- A/B의 화자 정확도는 N/A이며 화자 단정 0건도 구조상 값이다. C도 고정 설명으로 위험을 줄였지만 Router/의미 판정의 정확도를 보장하지 않는다.
- 모델의 번역/의미 판정 오류, 자막 내 지시문을 통한 오판 가능성이 남는다. 원문 검증은 의미 판정의 정답을 보장하지 않는다.
- context는 기존 20초 창을 유지한다. 선택 cue가 밖이면 제외하므로 긴 청크의 recall 손실 가능성이 남는다.
- 한국어 설명은 안전한 상태 안내이며 자유 장면 요약은 제공하지 않는다. 상세 맥락 요약은 인용·화자 안전성을 유지하는 방식으로 후속 검토한다.
- 모델 다운로드·신규 의존성·유료 API·자막 재수집·원본 공개는 하지 않았다. commit/push는 변경 제시 후 별도 승인한다.

## PR #3 리뷰 반영

필수 2건·권장 3건·개선 2건을 모두 반영했다. 재검색 전후 시간 예산 확인과 timeout 근거 보존, 라운드별 원문 탈락 상태, 비동기 lifespan LangSmith 큐, 모델/MCP 오류 메시지 분리와 의미 모델 fallback, 태그 없는 Ollama 이름의 `:latest` 처리, 공통 근거 ID·시각 경고 함수, 단일 telemetry 레코드를 적용했다.

의미 모델 fallback의 `partial`은 C 성공이 아니다. 이전 uncertain 근거가 있으면 `ambiguous`이며, 근거가 없거나 Router가 실패하면 안전한 503이다. 마지막 라운드가 정상 0건이면 과거 `evidence_rejected`와 관계없이 `not_found`다. 모든 후보가 원문 검증에서 탈락한 마지막 라운드만 `unsupported`다.

수정 후 백엔드 76 passed, 프런트엔드 2 passed, 빌드와 `git diff --check`가 통과했다. 리뷰 재현 테스트에는 시간 예산 종료/전체 timeout 근거 보존, 이전 라운드 탈락 경고 비누출, 모델 오류 fallback·구분 메시지, 태그 없는 모델 이름, 느린 추적 전송의 응답 비차단·Client 재사용, 반환/로컬 로그 telemetry 동일성을 포함한다.

수정 코드로 실제 로컬 API를 재시작한 뒤 마니또 질문이 1라운드 `found`, 189초 링크, `speaker=null`, `video_timing_sampled`·`speaker_unknown` 경고를 반환하는 것도 다시 확인했다.
