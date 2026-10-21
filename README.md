# WISH FINDER — NCT WISH 장면 찾기 AI Agent

> **현재 상태:** Day 1 검색 웹 + Day 2 Agent·POST SSE 구현. `WISH_AGENT_ENABLED=1`에서 LangGraph 의미 검증·조건부 최대 2회 재검색과 단계별 웹 진행 상태를 사용합니다.

## 문제와 목표

팬이 정확한 대사나 영상 제목은 기억하지 못하지만 장면의 상황을 어렴풋이 기억할 때, 자연어로 검색해 원본 영상의 해당 시점을 찾아 주는 서비스다.

## 문서

- [`AGENTS.md`](AGENTS.md): Codex 상시 작업 규칙 및 승인/안전 가드
- [`docs/requirements.md`](docs/requirements.md): 기능 범위·P0·인수 조건
- [`docs/architecture.md`](docs/architecture.md): 아키텍처, 데이터 모델, LangGraph/MCP/SSE
- [`docs/implementation-plan.md`](docs/implementation-plan.md): 3일 실행 계획 및 제출 게이트
- [`docs/adr/`](docs/adr/): 변경 이유와 대안·트레이드오프를 남기는 결정 기록
- [`docs/codex_plan_prompt.md`](docs/codex_plan_prompt.md): Codex Plan Mode에 붙여 넣는 프롬프트

## 개발 시작 절차

1. 프로젝트 저장소 루트에 이 문서들을 배치하고 `AGENTS.md`를 Codex가 읽을 수 있게 한다.
2. 사용이 허용된 SRT와 영상 manifest를 `data/raw/` 등에 **로컬 전용**으로 넣는다. 원본 외부 자막을 공개 Git에 커밋하지 않는다.
3. Codex Plan Mode에서 `docs/codex_plan_prompt.md`를 실행해 계획을 받는다.
4. **사용자가 계획을 검토·승인한 후에만** 실제 코드를 구현한다.

## 시연 완료 조건

웹에서 장면 질문 → SSE 진행 단계 표시 → SRT 원문/시점 검증 → 결과 카드 → YouTube 해당 구간 링크.

기술적 입력 제약: 확보 가능한 일부 스크립트는 영어 번역문이며 화자 라벨이 없다. 실제 영상에 한국어·일본어 화면 자막이 있다는 사실과 구분한다.

## 로컬 실행

Python 3.11과 Node.js가 필요합니다. 패키지·모델 다운로드는 사전에 승인된 범위에서만 실행합니다.

```sh
uv pip install --python .venv/bin/python -r backend/requirements.txt
npm --prefix frontend ci
```

실제 corpus는 `data/manifest.local.json`에 등록합니다. 공개 예시는 `data/manifest.example.json`이며, 합성 fixture는 실제 영상 자료가 아닙니다. manifest의 자막 경로는 프로젝트 기준 `data/` 아래에 있어야 합니다. 원본 자막·인덱스·로컬 manifest는 Git에서 제외합니다.

기존 로컬 bge-m3 캐시만 사용합니다. 자동 모델 다운로드는 하지 않습니다. 캐시가 다른 위치라면 `WISH_EMBEDDING_PATH`에 완전한 로컬 모델 경로를 지정하세요.

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

별도 터미널:

```sh
npm --prefix frontend run dev -- --port 5173
```

브라우저에서 `http://127.0.0.1:5173/`에 접속합니다. 백엔드 lifespan이 실제 MCP 서버를 시작하고 종료합니다. MCP 서버만 따로 실행하려면 `.venv/bin/python -m backend.app.mcp.server`를 사용합니다(stdout은 프로토콜 전용).

### Day 2 JSON Agent 실행

기존 Ollama 서버에 `qwen3:8b`가 설치되어 있어야 합니다. 시작 시 설치 여부만 확인하며 모델을 내려받지 않습니다. 기본값은 기존 A/B 검색입니다. Agent를 쓰려면 API를 다음과 같이 실행합니다(기존 API와 동시에 실행하지 마세요).

```sh
WISH_AGENT_ENABLED=1 WISH_LLM_MODEL=qwen3:8b HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Vue는 `POST /api/search/stream`에 질문을 보내고 `routing/searching/validating/replanning/result/error/done`을 표시합니다. `/ready`의 stage가 `agent_json`이면 Graph 경로입니다. 기존 `POST /api/search` JSON 응답도 평가와 회귀용으로 유지합니다. Router → MCP 검색 → MCP 문맥/원문 검증 → 의미 판정 → 필요한 경우 재검색 → 응답으로 처리합니다. 화자 질문도 장면을 찾으며 화자 확인 불가를 고지합니다. 시각·인용·화자·한국어 설명은 모델 자유 생성으로 만들지 않습니다.

전체 요청 60초, MCP 도구 30초, LLM 호출 20초이며 검색은 최대 3라운드입니다. 모델 장애·잘못된 구조화 응답·MCP 장애는 503의 안전한 `detail.code`로 반환하고 미검증 결과를 내보내지 않습니다. 의미가 불확실한 후보는 `ambiguous`, 범위 밖/일반 대화는 `unsupported`입니다. 동일 검색어를 반복 생성하면 재검색을 조기 종료합니다.

`logs/agent.jsonl`에 request ID·분류·상태·단계별 시간·호출 수·오류를 기록하며 질문·원문을 넣지 않습니다. LangSmith는 `WISH_LANGSMITH_ENABLED=1`과 키가 모두 있을 때만 같은 요약 메타데이터를 전송합니다. 자동 Graph 원문 추적은 비활성화합니다. 키가 없어도 로컬 로그로 동작합니다. 자유 한국어 장면 요약은 현재 제공하지 않고 검증 상태와 화자 한계를 고정 문구로 표시합니다.

실제 로컬 Agent 시험은 `scripts/agent_smoke.py`로 실행합니다. 다른 Dense API를 먼저 종료해야 하며 결과는 Git 제외인 `eval/private/day2-agent-smoke.json`에 저장합니다. 기존 결과가 있으면 덮어쓰지 않습니다. gold를 사용하지 않는 데모 확인이며 C 전체 정량 평가는 아닙니다.

공개 합성 fixture만 사용하는 keyword 모드는 다음과 같습니다. 이 모드는 다국어 Hybrid/Agent 품질 검증을 대체하지 않습니다.

```sh
WISH_MANIFEST=data/manifest.example.json WISH_KEYWORD_ONLY=1 .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

## 검증

```sh
.venv/bin/python -m pytest backend/tests -q
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

테스트에는 합성 자료를 이용한 실제 stdio MCP·LangGraph·JSON API 연결이 포함됩니다. 로컬 실제 corpus 검사는 파일이 없으면 skip합니다. 외부 자막은 배포하지 않으므로 제3자는 동일한 실제 corpus 평가를 즉시 재현할 수 없습니다.

브라우저 smoke 검증은 API와 Vue를 실행한 후 별도 Chrome CDP 포트 9223에서 `scripts/browser_smoke.py`를 사용합니다. 결과 화면은 `/private/tmp/wish-finder-day1.png`에 저장됩니다.

## 현재 한계

- 기본 A/B 모드의 결과는 검색 후보이며 `partial`과 `semantic_verification_skipped`를 반환합니다. Agent 모드는 별도 의미 판정을 수행하며, gold 18개 장면 질문 기준 C 정량 평가를 1회 실측했습니다([결과](docs/reports/day2-eval.md)).
- 한국어 기본 검색은 료칸 질문에서 정답이 2위에 나오는 사례가 있습니다. [Day 1 기록](docs/reports/day1.md)에 실제 관측을 남깁니다.
- 실제 로컬 manifest의 영상 제목은 공식 YouTube 메타데이터로 확인했습니다. 자막 출처는 사용자 Wave 도구 추출이며, 영상별 3개 시점의 내용 일치를 사용자에게 확인받았습니다. 전체 자막 시각 정확도나 제삼자 재배포 권한까지 확인한 것은 아닙니다.
- 화자는 항상 미확인입니다. 모델이 화면·음성을 이해한 서비스가 아닙니다.
- Agent·POST SSE·Vue 진행 상태는 구현했습니다. C 정량 평가는 완료했고 제출용 결과 보고서 정리는 Day 3 범위입니다.

## PR #1 리뷰 수정

manifest 상대 경로는 실행 위치와 무관하게 프로젝트 루트 기준으로 해석합니다. MCP 최초 초기화는 최대 180초, API 도구 호출은 30초, 검색 요청은 최대 60초입니다. 첫 실행에 인덱스 생성 시간이 포함되며 API는 초기화가 끝나야 요청을 받습니다.

timeout 뒤에도 서버 계산이 잠시 남을 수 있습니다. 계산이 끝날 때까지 MCP 서버가 추가 검색을 즉시 거절하고, 이후 재시도할 수 있습니다. 프로세스 강제 종료로 계산을 중단하지는 않습니다. 메타데이터는 시작 시 캐시하므로 manifest를 바꾸면 서버를 다시 시작하세요.

잘못된 원문 후보는 제외하고 경고를 표시합니다. 후보가 모두 검증에 실패하면 `unsupported`, 검색 후보 자체가 없으면 `not_found`, 도구 장애는 503으로 구별합니다.

## Day 1 데이터·평가 준비

[마무리 보고서](docs/reports/day1-completion.md)에 고정 개발 질문 5개 BM25/Hybrid 실측과 영어 재구성 실패 사례를 기록했습니다. [평가 실행 안내](eval/README.md)를 따라 같은 질문·정답·corpus로 비교할 수 있습니다. 실제 corpus·질문·정답·개별 결과는 `eval/private/`에 보관하고 공개 예시는 합성 데이터만 제공합니다.

gold 초안 24개는 아직 검색 평가에 사용하지 않았습니다. 사람의 내용 라벨 검토·부재 후보 검토를 거쳐 확정하며, 개발셋 결과를 최종 성능으로 제시하지 않습니다.

PR #2 수정에서는 API와 평가가 같은 검색·원문 검증 서비스를 사용합니다. 시각 상태 경고는 검증을 통과한 후보만 반영하며 `timing_verified`는 영상별 표본 확인을 뜻합니다. 오류·중단 기록과 비공개 출력 경계, 부재/화자/N/A 지표를 보완했습니다. [수정 대응 및 재측정](docs/reports/pr2-review.md)에 변경과 검증 결과를 기록합니다.

## Day 2 A/B/C 평가

사람이 승인한 gold 20문항(장면 18, 시각 요청 2)으로 A=BM25, B=Hybrid, C=Hybrid+Agent를 같은 corpus에서 1회씩 실측했습니다. Scene Success@1은 B 11/18(한국어 원문)·10/18(Router 영어 질의), C 12/18이며 차이가 1~2문항이라 Agent의 장면 정확도 이점은 입증되지 않았습니다. 대신 시각 요청 2/2 거부, 화자 미확인 3/4(의도·장면·안내 동시 충족), 근거 없는 화자 단정 0건을 확인했고 평균 지연은 B 0.2초 대 C 약 12초였습니다. not_found 정확도는 확정된 부재 질문이 없어 측정하지 못했습니다. 상세 표·검색어 전처리 통제 실험·실패 사례·한계는 [Day 2 평가 보고서](docs/reports/day2-eval.md)에 있습니다.
