# ADR-0004 — 자막 검색·문맥 조회를 별도 로컬 FastMCP 서비스로 제공한다

- 상태: Proposed
- 날짜: 2026-10-20
- 관련 요구사항: FR-08, FR-15

## 배경
Agent의 작업 조율과 검색·데이터 접근 로직을 분리하여 표준 Tool 인터페이스를 실습하고, 추후 새로운 영상 검색 도구를 추가하기 쉽게 한다.

## 결정
FastMCP 서버를 로컬 subprocess + stdio로 실행하는 방안을 우선 사용한다. `search_transcripts`, `get_scene_context`, `get_video_metadata`를 읽기 전용 Tool로 제공하고, LangGraph가 실제 MCP 클라이언트로 호출했는지 확인한다. 긴 생명주기의 MCP 세션은 FastAPI lifespan에서 관리한다.

## 대안과 트레이드오프
- Python 함수 직접 호출: 가장 간단하나 MCP 실습과 서비스 경계 재사용을 보여주기 어려움.
- 별도 HTTP MCP 서버: 독립 배포에 좋지만 3일 프로젝트에서는 인프라와 인증이 과함.
- stdio MCP: 격리·재사용 장점; 서브프로세스 수명/초기화/실패 처리를 신경 써야 함.

## 영향 및 검증
인덱스 초기화와 MCP 서버 생성의 중복 방지, Tool 입력 제한 및 명시적 docstring 작성. MCP 연결 실패와 복구·부분 결과 시나리오를 테스트한다.

## 재검토 조건
실제 로컬 OS/SDK 조합에서 안정적인 stdio 세션 유지가 어려운 경우. 변경 시 사용자 승인 및 ADR 갱신.
