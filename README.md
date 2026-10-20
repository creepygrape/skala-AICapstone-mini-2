# WISH FINDER — NCT WISH 장면 찾기 AI Agent

> **현재 상태:** 개발 전 기획·설계 초안(실행 가능한 애플리케이션은 아직 없음)

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
