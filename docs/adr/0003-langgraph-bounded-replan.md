# ADR-0003 — 역할 분리 LangGraph와 조건부 최대 1회 재검색

- 상태: Proposed
- 날짜: 2026-10-20
- 관련 요구사항: FR-06, FR-07, FR-09, FR-14

## 배경
단일 RAG 검색 결과가 질문의 상황과 다르거나 근거가 모호하면 재검색·문맥 검증이 필요하다. 동시에 무한 재계획은 시연 지연과 비용 폭증 위험이 있다.

## 결정
Router/Supervisor → Search → Context Expansion → Verification → Finalize를 LangGraph로 구성한다. Search와 Verification은 책임과 도구 접근 범위를 분리한다. 근거가 불충분한 경우에만 Query Rewrite 후 최대 1회 재검색한다. 원문/시간/ID는 결정적 코드로 확인하고 의미적 관련성은 별도 검증 단계에서 판단한다.

## 대안과 트레이드오프
- 고정 Retrieval→LLM: 단순하지만 검색 실패 시 복구 불가.
- 단일 ReAct Agent: 개발이 빠르나 역할별 품질 추적·검증 책임이 불명확할 수 있음.
- 역할 분리 Graph: 평가/관측이 명확하지만 노드·상태·지연 증가.
- 무제한 루프: 품질 개선 가능성과 맞바꿔 시간/비용 상한을 잃음 → 제외.

## 영향 및 검증
- `MAX_REPLAN_ROUNDS=1`, 실패 시 `not_found`/`unsupported`/`ambiguous`.
- 진짜 Multi-Agent라는 설명은 역할별 목표·프롬프트·입출력 계약을 별도 구현한 경우에만 사용한다.
- Tests: 초기 검색 충족 시 0회 재검색, 불충분 시 정확히 최대 1회, 검증 실패 초안 미노출.

## 재검토 조건
재검색 효과가 없거나 지연/모델 비용의 증가 폭이 커서 단일 retrieval 대비 유의미한 가치가 없을 때.
