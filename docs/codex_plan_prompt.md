# Codex Plan Mode용 프롬프트 — WISH FINDER

아래부터 Codex에 그대로 붙여 넣으세요.

---

너는 Python/FastAPI/LangGraph/MCP/Vue를 다루는 시니어 AI 서비스 아키텍트이자 개발 리드다.

이번 작업은 **AI 서비스 개발 Mini-project 과제 2: WISH FINDER 신규 AI Agent 구축**을 위한 **Plan Mode**다. 사용자 승인 전에는 코드·설정·문서 파일을 새로 만들거나 수정하지 말고, 현황 조사·검증·구현 계획만 보고하라. Git commit/push/원격 저장소 작업도 하지 마라.

## 1. 최우선 문서

프로젝트 루트에서 `AGENTS.md`, `docs/requirements.md`, `docs/architecture.md`, `docs/implementation-plan.md`, `docs/adr/README.md`, `docs/adr/0001~0006-*.md`를 모두 읽고 요약하라. 파일이 없다면 없는 그대로 보고하라. 이 문서의 P0를 임의로 P1로 내리지 마라.

## 2. 프로젝트 배경

사용자는 NCT WISH 영상의 정확한 대사나 제목을 잊고, '마니또 뽑다가 리쿠가 자기 자신을 뽑은 장면'처럼 상황만 희미하게 기억한다. 목표는 자연어 질문을 통해 실제 SRT를 검색·검증하고 원본 영상의 정확한 시점 링크를 제공하는 웹 서비스다.

추출 가능한 일부 스크립트가 영어인 것은 기술적 데이터 조건이며 **한국어 자막이 없는 문제가 아니다**. 실제 영상은 한국어·일본어 화면 자막을 포함한다. 자막에는 화자 정보가 없으므로 `mentioned_members`와 `speaker`를 절대 혼동하지 마라. 괄호 속 `(RIKU chose RIKU)`는 편집 설명이므로 장면 검색에 유용하지만 리쿠의 대사라고 주장해서는 안 된다.

현재 제공된 첫 번째 영상: `1HJgbE66GI4`의 SRT/TXT. 사용자는 두 편의 추가 영상 자막을 확보할 수 있다고 했으나 현재 프로젝트에 실제 파일이 있는지 직접 확인하라. **아직 없는 파일을 존재한다고 가정하지 마라.**

## 3. 필수 P0

- SRT 파싱/시간정보/원문 cue 보존/청킹
- BM25 키워드와 다국어 Dense 검색을 결합한 Hybrid Retrieval
- 공식 MCP Python SDK 2.x (`mcp>=2,<3`)의 `MCPServer` 서버와 LangGraph 도구 호출
- Router, Search, Evidence Verification, 조건부 최대 2회 Dynamic Replanning(최초 검색 포함 최대 3라운드, `attempt=0/1/2`)
- FastAPI JSON API 및 `POST /api/search/stream`의 SSE 이벤트
- Vue 웹: 질문 입력, 진행 상태, 근거 결과 카드, 타임스탬프 링크, 오류 표시
- 원문 인용 검증 / 근거 없는 화자 추정 차단
- LangSmith/로컬 로그, Baseline A/B/Final C 고정 질문 기반 정량 평가
- ADR 작성과 실험 결과 연결, README, 자동화 테스트

주의: **백엔드만 만들어서는 미완성**. Day 2까지 실제 웹에서 끝까지 시연이 가능해야 한다.

## 4. 환경·데이터 조사 요청

1. pwd/Git 상태/추가 AGENTS, 실제 폴더 구조, 존재 파일 경로를 명시한다.
2. Python/Node 버전, 패키지, 검색 임베딩/Ollama 환경, API 키 유무는 **값을 출력하지 말고 사용 가능 여부만** 조사한다.
3. 첫 SRT에서 cue 수, 시간 포맷, UTF-8/BOM, 괄호 속 화면 설명, 시간 겹침, 중복 자막 등 실제 데이터를 조사한다.
4. 기존 코드의 재사용 가능성이 있으면 원본 보존·복사 정책을 제시한다.
5. 외부 자막의 공개 재배포를 피할 수 있는 `.gitignore` 및 sample fixture 전략을 제안한다.
6. 유료 API/대형 모델 다운로드/크롤링을 허가 없이 실행하지 않는다.

## 5. 구체적 설계안 제출 요청

- 데이터/청킹: cue 구조, 보존 정책, 20초/10초 윈도우 가설과 트레이드오프
- 검색: BM25, 다국어 임베딩, RRF, 한국어→영어 검색 재구성 사용 여부의 **측정 가능한 비교안**
- LangGraph: State 타입, 노드 입출력, 조건부 edge, 재검색 카운터(`MAX_REPLAN_ROUNDS=2`, `attempt=0/1/2`)/조기 종료·최대 3라운드 종료조건, Search/Verification 책임 경계
- MCP: 공식 SDK 2.x의 `MCPServer`, 로컬 stdio, Tool 3종 입력/반환/오류, Tool/Resource/Prompt 기능 유지(Resource/Prompt 확장은 P1), lifespan 초기화·종료, 설치 버전의 LangGraph/클라이언트 API 확인과 실제 호출 데모 방법. SDK 1.x로 다운그레이드하지 말 것
- API/SSE: 구체적 JSON·이벤트 계약, `fetch` 스트림 파서, HTTP 오류와 SSE 오류 구분, 검증된 결과만 전송
- UI: 페이지 최소 와이어프레임/컴포넌트, 데모 사용자 시나리오 3개
- 품질: 근거 없는 인용 방지, 화자 질문, 영상에 없는 장면, MCP 에러, no-result/fallback
- 평가: A=BM25, B=Hybrid, C=Agent, gold set 최소 20문항 계획, latency/Scene Success@1/Hit@3/허위 화자 단정 비교
- 문서: ADR을 기능 변경 전에 갱신하는 흐름, 최종 회고 자료 활용 방식

## 6. 3일 구현 계획

반드시 Day 1 웹 검색 결과 동작, Day 2 MCP+Agent+SSE E2E, Day 3 오전 평가/제출 마감으로 계획하라. 단계별 파일 경로·선행조건·산출물·테스트 명령·완료 기준을 제시한다. P0 완료가 불가능해 보이면 근거 있는 리스크와 선택지를 보고하되 사용자 승인 없이 제외하지 마라.

## 7. 답변 형식

1. 현재 확인된 사실 / 미확인 사항 / 주요 블로커
2. 권장 시스템 아키텍처와 LangGraph 순서
3. 인터페이스 계약(데이터, MCP, API, SSE)
4. ADR 0001~0006의 잠정 결정 및 검증할 가설
5. Day 1/2/3 작업 계획과 파일 변경 예정 목록
6. 테스트·평가(Before/After) 방법
7. 예상 리스크·안전한 대안 및 사용자 결정이 필요한 사항
8. **최종 질문: "이 계획대로 구현을 시작해도 될까요?"**

절대 지금 코드를 구현하지 마라.
