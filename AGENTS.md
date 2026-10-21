# WISH FINDER — Repository Instructions for Codex

> 프로젝트: AI 서비스 개발 Mini-project **과제 2 (신규 Agent)**. 이 문서는 과제 1용 AGENTS.md와 별개다.
> 승인 기준: `docs/requirements.md`와 `docs/architecture.md`의 P0, `docs/adr/`의 설계 결정. 변경 시 먼저 사용자에게 질문한다.

## 1. 제품 정의 (절대 변경하지 말 것)

- 핵심 사용자 문제: 팬이 **정확한 발언이나 영상 제목은 모르지만, 어떤 장면인지 어렴풋이 기억**하여 영상의 해당 시점을 찾기 어렵다.
- 해결 방식: 한국어 자연어 장면 설명 → 검색 → 원문 자막 맥락 검증 → 정확한 영상 URL/시점 제공.
- **대상 범위(사용자 확인 2026-10-21, 이번 한 번 수정 허용)**: 이 과제의 구현·데이터·평가는 **NCT WISH 영상 3편(첫 적용 대상)** 으로 한정한다. 이는 사용자가 위시를 좋아하고 범위를 줄이기 위한 선택이며, 제품 정의가 특정 대상에 종속되는 것은 아니다. 향후 사용자가 원하는 대상으로 확장하는 것이 계획이고, 대상별 정보(자막 언어, 번역 여부, 이름 사전)는 코드가 아니라 대상 프로필(`data/profile.*.json`)에 둔다. 이 과제 안에서는 NCT WISH 외 대상을 실제로 지원한다고 주장하지 않는다.
- 사용자 문제를 '한국어 질문 vs 영어 자막'으로 설명하지 말 것. 실제 영상 화면에는 한국어·일본어 자막이 있고 **추출 가능한 일부 스크립트가 영어**인 것은 데이터 파이프라인의 기술적 제약이다.
- **음성/영상 자체를 이해한 것처럼 주장하지 말 것.** 입력은 권한 범위에서 확보된 SRT/TXT 및 영상 메타데이터다.
- 업로드 자막에는 화자 레이블이 없다. `(RIKU chose RIKU)`는 **화면 편집 설명**이지 대사 화자 라벨이 아니다. `SAKUYA, ...`의 SAKUYA는 **호명 대상**일 수 있다. `mentioned_members != speaker`.

## 2. 우선순위 / 일정

- 마감: Day 3 13:00 이전 Git URL과 결과보고서 링크 등록; 그 전에 UI·API·Agent 연결 완료.
- P0: ADR, SRT/Cue 파싱, BM25+다국어 Dense 검색, LangGraph 라우팅/검색/맥락 확인/검증/최대 2회 재검색, 공식 MCP Python SDK 2.x의 MCPServer 도구 연동, **FastAPI+웹 UI+POST SSE**, 근거 링크, 실패 처리, 평가/테스트/추적.
- Day 1 종료 목표: 브라우저 → API → 기본 검색 결과. Day 2 종료: Agent/MCP/SSE E2E. Day 3 오전: 평가/회고 자료/제출.
- P1/P2를 P0보다 앞당기지 마라. 화자 자동 추론, 대규모 자막 크롤링, OCR, ASR, 소셜 기능, 무거운 디자인은 범위 밖.

## 3. 작업 전 필수 조사

1. `pwd`, 저장소 파일 트리, Git 상태, 프로젝트 내 다른 AGENTS.md, Python/Node 환경을 확인한다.
2. `docs/requirements.md`, `docs/architecture.md`, `docs/adr/`, `docs/implementation-plan.md`를 읽는다.
3. 검색 데이터 경로와 실제 자막·영상 메타데이터가 있는지 점검한다. 더미 영상이나 추측한 데이터가 실제로 존재하는 것처럼 서술하지 않는다.
4. 기존 코드/테스트가 있으면 재사용 가능성과 경계를 검토한다. 사용자의 승인 없이 코드를 고치지 않는다.
5. Python·임베딩·Ollama 등의 설치/다운로드와 유료 API 접근은 확인 후 실행한다.

## 4. 승인 게이트

- **Plan Mode는 읽기·실행환경 점검·설계안·실험 계획만 수행한다. 코드를 작성·수정하지 않는다.**
- 구현 계획에 작업순서, 파일 구조, MCP 도구명, Graph 노드/State, API/SSE 이벤트, 기술적 의존성, 테스트/평가, 위험·대안, 예상 비용을 제시한다.
- 실제 구현은 사용자 승인 후 시작한다. P0 변경이나 신규 의존성 도입은 근거와 트레이드오프를 설명한다.
- **Git commit / push는 사전에 변경 내용 제시 후 반드시 사용자 승인을 받는다.** 리모트 생성, 파일 삭제, reset/clean/force, 외부 배포에도 명시적 승인 필요.

## 5. 설계 원칙

- Source of truth는 원본 SRT의 cue (`video_id`, cue ID, `start`, `end`, `text`). 벡터 검색 청크만으로 인용/화자를 생성하지 않는다.
- 청킹은 영상 간 혼합 금지, cue→청크→원본 cue 역매핑 보존.
- 사용자에게 보여 주는 인용문은 실제 원문 cue에서 조회·검증. 언어가 달라도 한국어 설명은 원문의 의미를 벗어나지 말 것.
- `speaker=null`에서 발화자 단정 금지. 언급된 멤버와 발언자를 구별한다.
- 검색/시간/ID 검증은 결정적 Python 로직; 의미적 관련성 검증은 필요한 경우 LLM을 사용한다.
- Search와 Verification을 역할별 계약으로 분리하되, 진짜 독립 sub-agent가 아니라면 'Multi-Agent'라고 과장하지 않는다.
- 재검색은 조건부 **최대 2회**(최초 검색 포함 최대 3라운드, `attempt=0/1/2`, `MAX_REPLAN_ROUNDS=2`), LLM/Tool 시간 제한을 둔다. 결과가 없으면 `not_found`, 근거 없이 확정할 수 없으면 `unsupported/ambiguous`.
- 응답 스트리밍: `routing/searching/validating/replanning/result/error/done` 이벤트. **검증 전 답변/허위 결과는 스트리밍하지 않는다.** POST SSE 클라이언트는 `fetch` 스트림 파서를 사용한다.
- 백엔드 lifespan에서 Agent/인덱스/MCP 연결을 준비하고 요청별 재초기화 금지. 종료 시 리소스 정리.
- MCP는 공식 Python SDK 2.x (`mcp>=2,<3`)의 `MCPServer`를 사용한다. SDK 1.x로 다운그레이드하지 않고 별도 `fastmcp` 패키지를 도입하지 않는다. Tool/Resource/Prompt 기능과 로컬 stdio 구조를 유지하며 Resource/Prompt 확장은 기존 P1이다. LangGraph 연동은 실제 설치 버전에서 확인한다.
- API/도구 인터페이스는 Pydantic 타입 및 docstring으로 입력·출력·오류를 명시한다.

## 6. 데이터 / 저작권 / 보안

- 원본 제삼자 자막 전체를 **공개 GitHub에 커밋하거나 재배포하지 않는다**. `data/raw/`, `.env`, API 키·토큰 등은 `.gitignore` 적용.
- 자료 수집처의 이용약관·저작권을 확인한다. 시험용 최소 합성 fixture는 별도 생성 가능하며 실제 자막으로 오인시키지 않는다.
- 무단 웹 크롤링, 로그인 우회, 유료 API 호출은 사용자 승인 없이 시도하지 않는다.

## 7. 필수 테스트와 평가

- Baseline A: BM25; Baseline B: Hybrid; Final C: Hybrid+Agent. 같은 corpus/질문/정답을 사용한다.
- A/B/C 검색어 전처리가 다르면 비교의 한계를 기록하고, 동일한 초깃값 검색어로 통제 실험을 추가한다.
- 지표: Scene Success@1, Hit@3, 근거 없는 화자 단정 건수, unanswered/unsupported 정확도, latency, tool/LLM calls.
- 테스트: 원본 cue·타임스탬프/영상 경계, 괄호 속 편집 설명, speaker unknown, 무관 질문, 재검색 상한, MCP 오류, POST SSE 분할 청크 처리.
- 실제 측정값/예상값/미측정값을 구분한다. 결과를 만들거나 조작하지 않는다.
- LangSmith 설정이 없을 때도 핵심 기능이 동작하도록 로컬 로그 대안을 둔다.

## 8. 문서와 ADR

- 설계/대안 선택이나 변경을 할 때 관련 `docs/adr/000X-*.md`를 업데이트한다: 배경 → 결정 → 대안/트레이드오프 → 결과 → 재검토 조건 → 검증 근거.
- 핵심 관련 문서: `docs/requirements.md`, `docs/architecture.md`, `docs/implementation-plan.md`, `docs/adr/`.
- 완료 보고는 변경 파일, 실제 테스트 명령·결과, 측정·미측정 항목, ADR 갱신, 남은 리스크를 포함한다.
- README 및 발표/회고 문서에는 문제→설계→실험→결과→한계 흐름을 유지한다.
