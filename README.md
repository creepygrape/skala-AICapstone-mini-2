# WISH FINDER — NCT WISH 장면 찾기 AI Agent

> **현재 상태:** Day 1 기본 검색 웹 구현. 실제 MCP stdio + BM25/Dense/RRF + 원문 cue 검증이 동작합니다. 의미 검증 Graph·재검색·POST SSE는 Day 2 작업입니다.

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

- Day 1 결과는 검색 후보입니다. 원문·시각의 결정적 검증은 했지만 의미 검증은 아직 없어 `partial`과 `semantic_verification_skipped`를 반환합니다. Final C 성공으로 집계하지 않습니다.
- 한국어 기본 검색은 료칸 질문에서 정답이 2위에 나오는 사례가 있습니다. [Day 1 기록](docs/reports/day1.md)에 실제 관측을 남깁니다.
- 실제 로컬 manifest의 영상 제목은 공식 YouTube 메타데이터로 확인했습니다. 자막 출처는 사용자 Wave 도구 추출이며, 영상별 3개 시점의 내용 일치를 사용자에게 확인받았습니다. 전체 자막 시각 정확도나 제삼자 재배포 권한까지 확인한 것은 아닙니다.
- 화자는 항상 미확인입니다. 모델이 화면·음성을 이해한 서비스가 아닙니다.
- 원본을 반환하는 검색 도구와 의미 검증·최대 2회 재검색·POST SSE의 통합은 Day 2에 마무리합니다.

## PR #1 리뷰 수정

manifest 상대 경로는 실행 위치와 무관하게 프로젝트 루트 기준으로 해석합니다. MCP 최초 초기화는 최대 180초, API 도구 호출은 30초, 검색 요청은 최대 60초입니다. 첫 실행에 인덱스 생성 시간이 포함되며 API는 초기화가 끝나야 요청을 받습니다.

timeout 뒤에도 서버 계산이 잠시 남을 수 있습니다. 계산이 끝날 때까지 MCP 서버가 추가 검색을 즉시 거절하고, 이후 재시도할 수 있습니다. 프로세스 강제 종료로 계산을 중단하지는 않습니다. 메타데이터는 시작 시 캐시하므로 manifest를 바꾸면 서버를 다시 시작하세요.

잘못된 원문 후보는 제외하고 경고를 표시합니다. 후보가 모두 검증에 실패하면 `unsupported`, 검색 후보 자체가 없으면 `not_found`, 도구 장애는 503으로 구별합니다.

## Day 1 데이터·평가 준비

[마무리 보고서](docs/reports/day1-completion.md)에 고정 개발 질문 5개 BM25/Hybrid 실측과 영어 재구성 실패 사례를 기록했습니다. [평가 실행 안내](eval/README.md)를 따라 같은 질문·정답·corpus로 비교할 수 있습니다. 실제 corpus·질문·정답·개별 결과는 `eval/private/`에 보관하고 공개 예시는 합성 데이터만 제공합니다.

gold 초안 24개는 아직 검색 평가에 사용하지 않았습니다. 사람의 내용 라벨 검토·부재 후보 검토를 거쳐 확정하며, 개발셋 결과를 최종 성능으로 제시하지 않습니다.
