# ADR-0004 — 공식 MCP Python SDK 2.x의 MCPServer와 로컬 stdio 경계

- 상태: Accepted (사용자 확정, 실제 stdio·Graph 통합 검증 전)
- 날짜: 2026-10-20
- 관련 요구사항: FR-08, FR-15, FR-19

## 배경 및 변경 이력
Agent 조율과 검색·데이터 접근을 분리하고 표준 MCP Tool 인터페이스를 사용한다. 초기 Proposed 설계와 Day 1 메모는 FastMCP를 기준으로 했으며, 설치된 공식 `mcp 2.3.0`에서는 서버 클래스가 `MCPServer`로 바뀌었다.

2026-10-20 사용자는 **공식 SDK 2.x 유지와 MCPServer 사용**을 확정했다. 이전 FastMCP 유지 및 SDK 1.x 다운그레이드 제안은 폐기한다. 기존 설치 환경을 활용하면서 Tool/Resource/Prompt와 stdio 서비스 경계를 유지하는 것이 선택 이유다.

## 결정
- 의존성은 공식 `mcp>=2,<3`이다. 별도 `fastmcp` 패키지는 도입하지 않고 SDK 1.x로 다운그레이드하지 않는다.
- 서버는 `from mcp.server.mcpserver import MCPServer`로 가져온다. `MCPServer(...)`를 구성하고 `run(transport="stdio")`로 실행한다.
- `tool()`, `resource(uri)`, `prompt()` 등록 API를 사용한다. 읽기 전용 `search_transcripts`, `get_scene_context`, `get_video_metadata`의 입력·출력 계약은 유지한다.
- Tool의 기존 P0 기준과 Resource(영상 카탈로그)/Prompt(검색 절차) 확장의 기존 P1을 유지한다. 서버 클래스 변경을 이유로 기능을 삭제하거나 우선순위를 바꾸지 않는다.
- 로컬 subprocess + stdio를 사용한다. 표준 출력은 MCP 프로토콜 전용, 로그는 표준 오류로 보낸다. 사용자 입력으로 임의 자막 파일 경로를 받지 않는다.
- 인덱스·모델은 서버에서 한 번만 준비한다. FastAPI lifespan에서 transport·클라이언트 세션을 열고 재사용하며 종료 시 정리한다.

## LangGraph와 클라이언트 연동 기준
설치된 `mcp 2.3.0`, `langgraph 1.2.16`의 실제 API를 확인했다.

- `mcp.client.stdio`: `StdioServerParameters`, `stdio_client`.
- `mcp.client.session`: `ClientSession`. `initialize`, `list_tools`, `call_tool`, `list_resources`, `read_resource`, `list_prompts`, `get_prompt`는 비동기 메서드다.
- FastAPI lifespan의 동일한 task에서 `AsyncExitStack`으로 stdio transport와 세션을 열고 `await session.initialize()`한다. 같은 경계에서 종료한다.
- LangGraph 비동기 노드는 준비된 세션을 받아 `await session.call_tool(...)`을 수행한다. `StateGraph.add_node`와 `add_conditional_edges`로 연결하며 요청마다 subprocess를 생성하지 않는다.
- `langchain-mcp-adapters`는 현재 미설치이며 필수로 가정하지 않는다. 추가 도입 시 SDK 2.x 호환성과 세션 재사용 방식을 확인하고 승인받는다.

## 대안 비교 및 트레이드오프
- **공식 SDK 2.x MCPServer + stdio(채택)**: 설치 환경과 사용자 결정에 부합하고 MCP 기능을 유지한다. 구버전 FastMCP 예제를 그대로 쓸 수 없어 실제 API 검증이 필요하다.
- 공식 SDK 1.x FastMCP: 기존 예제 활용에는 유리하지만 확정된 2.x 유지 방침과 충돌하므로 채택하지 않는다.
- 별도 fastmcp 패키지: 다른 수명 관리·기능을 선택할 수 있으나 의존성과 버전 호환성 확인 범위가 증가하므로 채택하지 않는다.
- Python 함수 직접 호출: 가장 단순하지만 실제 MCP 연동 P0를 충족하지 못한다. 단위 테스트의 대역으로만 사용할 수 있다.
- HTTP MCP 서버: 독립 배포에 유리하지만 현재 로컬 프로젝트에 운영·인증 복잡도를 추가하므로 stdio를 유지한다.

## 영향
서버 클래스·import·버전 명세를 변경한다. 검색 기능, 원문 데이터 모델, 화자 정책, SSE 이벤트, 웹 UI, Tool/Resource/Prompt 기능과 transport 구조는 유지한다. subprocess 수명·초기화·취소·오류 전파 검증이 필요하다.

## 검증 방법 및 현재 근거
**실제 확인:** 기존 `.venv`의 버전 조회와 API import·시그니처 점검에 성공했다. `MCPServer.run`이 stdio transport를 지원하고 Tool/Resource/Prompt 등록 메서드가 있음을 확인했다. 패키지를 변경하거나 다운그레이드하지 않았다.

**미검증/예정:** import 성공을 실제 MCP 통신 성공으로 간주하지 않는다.

1. 로컬 stdio subprocess 연결 → initialize → list_tools → 읽기 전용 Tool 호출·반환 스키마 확인.
2. 같은 세션을 비동기 LangGraph 노드에 전달해 Tool 호출이 실제 MCP를 통과함을 trace로 확인.
3. Resource/Prompt 확장 시 `list_resources`/`read_resource`와 `list_prompts`/`get_prompt`의 실제 통신·내용 검증(P1).
4. 연속 요청에서 subprocess·인덱스·임베딩 모델 재초기화 방지 확인.
5. stdout 오염, 잘못된 입력, Tool 오류, timeout, 프로세스 중단 시 명확한 오류 전달 및 미검증 결과 차단.
6. lifespan 종료·요청 취소·초기화 실패 시 세션과 subprocess 정리 확인. 단순 클라이언트 timeout이 서버 계산 중단까지 보장하지 않는 한계도 기록한다.

## 재검토 조건
설치된 SDK 2.x에서 필요한 기능이나 세션 유지가 불안정한 경우 실패 재현과 대안을 기록해 사용자와 재검토한다. 1.x로 자동 다운그레이드하거나 transport를 조용히 변경하지 않는다.

## Day 1 검증 결과

`backend/tests/test_mcp_transport.py`에서 공식 SDK 2.x의 실제 stdio subprocess·initialize·도구 목록·구조화 Tool 반환을 검증했다. LangGraph 비동기 노드가 같은 세션을 두 번 사용한 뒤 정상 종료했다. SDK 2.x의 Tool 구조화 출력을 위해 Pydantic 반환 타입과 `structured_output=True`를 명시한다.

`backend/tests/test_api.py`는 합성 fixture로 JSON API → 실제 MCP 도구 3종 → 원문 검증 경로를 통과했다. 실제 corpus에서는 Chrome 입력부터 MCP Hybrid 검색 및 cue 69의 189초 링크 렌더링까지 확인했다. 전체 의미 검증 Graph·취소 전파·장애 복구 검증은 여전히 미완료다.
