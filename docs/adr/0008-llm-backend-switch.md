# ADR-0008 — 환경변수 하나로 LLM 백엔드 교체 (개발 Ollama, 시연·제출 OpenAI)

- 상태: Accepted (사용자 승인 2026-10-21)
- 날짜: 2026-10-21
- 관련: ADR-0003(LangGraph Agent), FR 비용·보안 요구사항

## 배경
개발은 로컬 Ollama(`qwen3:8b`, 무료)로 하고, 시연과 결과 제출은 OpenAI로 하기로 했다. 기존 구현은 `OllamaModel`을 세 곳(`main.py`, `eval/run_eval.py`, `scripts/agent_smoke.py`)에서 직접 생성했고, ADR-0003은 "유료 API·adapter 미추가"였다. 그래프는 이미 생성자 주입된 `model`의 `route / verify / rewrite`만 호출한다.

## 결정
- **공통 계약 `JsonLLM`**([agent/model.py](../../backend/app/agent/model.py))이 프롬프트(`INSTRUCTIONS`, route/verify/rewrite 지시문)와 Pydantic 스키마를 소유한다. 백엔드 클래스는 전송(`ask / ready / close`)만 구현한다. 그래서 두 백엔드가 **같은 프롬프트와 스키마**를 쓰고, 결과를 공정하게 비교할 수 있다.
- **팩토리 `build_model()`**: `WISH_LLM_BACKEND=ollama`(기본) | `openai`로 클래스를 고른다. 그래프·MCP·SSE·평가 코드는 바꾸지 않는다.
- **fast / quality 분리**: `route`·`rewrite`는 fast 모델, `verify`는 quality 모델을 쓴다.
  - OpenAI 기본값은 `gpt-4o-mini` / `gpt-4o`다(`OPENAI_FAST_MODEL` / `OPENAI_QUALITY_MODEL`로 바꿀 수 있다).
  - Ollama 기본값은 둘 다 `qwen3:8b`다. Router 번역 품질 때문에 작은 모델로 낮추지 않는다.
- **OpenAI 구현**([agent/openai_model.py](../../backend/app/agent/openai_model.py))
  - 기존 `httpx`로 Chat Completions를 호출한다. 신규 의존성은 없다.
  - **Structured Outputs(strict json_schema)**로 응답 형태를 강제한다. strict가 거부할 수 있는 키워드(`maxItems`, `minLength` 등)는 전송용 스키마에서만 빼고, 응답은 기존처럼 Pydantic으로 다시 검증한다.
  - `ready()`는 과금되지 않는 `/models/{id}` 조회로 키와 모델 접근 권한을 확인한다.
  - 오류는 기존 코드(`model_timeout / model_unavailable / model_invalid_response`)로 매핑하므로 기존 폴백 경로가 그대로 동작한다.
- **실행**: `scripts/run_backend.sh [ollama|openai]`
  - `.env`를 읽고 Agent·오프라인 임베딩 플래그를 고정한다.
  - openai 모드에서는 키를 검사하고, 과금 고지와 y/N 확인을 받는다.
  - `/ready`의 `llm_backend`로 현재 백엔드를 확인할 수 있다.
- **비용 대리 지표**: 백엔드별 입·출력 토큰을 집계해 `logs/agent.jsonl`에 `llm_tokens_in/out`, `llm_backend`로 숫자만 기록한다.

## 외부 전송 범위 (사용자 승인)
OpenAI 모드에서는 다음만 OpenAI API로 전송한다.
- 사용자 질문
- 검색 후보 최대 3개의 원문 대사와 각 20초 문맥 cue

전체 자막 파일·인덱스·원본 경로는 전송하지 않는다. API 키는 `.env`(Git 제외)에만 두고, 키·요청·응답 본문은 로그에 남기지 않는다. 기본 백엔드는 Ollama라서, 명시적으로 openai를 고를 때만 전송이 일어난다.

## LangSmith 추적 (사용자 승인, 2026-10-21)
`WISH_LANGSMITH_ENABLED=1`과 `LANGSMITH_API_KEY`가 모두 있을 때만 켠다(opt-in, 기본 꺼짐). 켜면 그래프 노드(Router/Search/Context/Verification/Replan/Finalize)와 **LLM 호출마다 `run_type="llm"` 기록**(모델명·`ls_provider`·입출력 토큰 `usage_metadata`·지연·입력 메시지·출력)이 한 트레이스 트리로 올라간다. 비용 계산은 LangSmith가 모델명·토큰으로 하며 실제 표시는 사용자가 화면에서 확인한다.
- **외부 전송 범위 확대**: OpenAI 외에 **LangSmith**에도 사용자 질문과 후보 자막 원문·20초 문맥이 저장된다(요청당 최대 3구간, 전체 자막 아님). 사용자가 명시적으로 승인했다. 개인 워크스페이스의 비공개 프로젝트에서만 쓰고, 공용·공개 워크스페이스에는 올리지 않는다. API 키는 전송하지 않는다.
- 기존의 "원문 미전송·자동 추적 차단" 방침은 **기본값(꺼짐)**으로 유지한다. 환경의 `LANGCHAIN_TRACING_V2` 같은 변수만으로는 켜지지 않는다.
- 전송은 배치 클라이언트의 백그라운드 스레드로 하며 종료 시 flush한다. LangSmith 장애·키 오류는 검색을 막지 않는다.
- 검증: `test_llm_backends.py`가 실제 LangSmith 클라이언트의 전송을 가짜 세션으로 가로채, 꺼짐=전송 0건, 켜짐=LLM 호출별 run(모델·토큰·입력)과 노드 트리를 확인한다. **실제 LangSmith 계정으로의 전송은 미검증**이다(사용자가 화면에서 확인).

## 발견된 결함과 수정 — 검색하지 않는 의도의 빈 검색어 (2026-10-21)
- **증상**: OpenAI 평가(gold 20문항, 1회)에서 시각·청각 전용 질문 2건이 C와 C-ko 모두 `model_invalid_response`로 오류가 났고, unsupported 정확도가 0/2로 집계됐다. 올바른 분류(`unsupported`)가 오류로 바뀐 것이다. 원인은 오류 코드와 토큰 수(출력 10토큰)로 한 **추정**이며 응답 원문은 확인하지 않았다.
- **원인(추정)**: Router가 `unsupported`에서 `search_query`를 빈 문자열로 돌려줬고, strict 스키마 전송에서 `minLength`를 뺐기 때문에 API가 막지 못한 채 우리 Pydantic(`min_length=1`)이 거부했다. Ollama는 서버가 `format` 스키마를 강제해 이 문제가 없었다.
- **결정(A안)**: `Route`에서 `search_query`의 최소 길이를 없애고, `scene_search`/`speaker_query`일 때만 비어 있으면 거부하는 검증을 추가한다. `unsupported`/`chat`은 검색하지 않으므로 비어 있어도 허용하고, 로그·trace를 위해 사용자의 원래 질문을 자리표시자로 둔다.
- **대안과 트레이드오프**: (B) 전송 스키마에 `minLength` 유지 — strict가 거부할 수 있어 호출 전체가 실패할 위험. (C) 프롬프트로 "항상 비우지 마라" — 모델 준수 보장이 없고 프롬프트가 바뀌어 백엔드 간 비교 조건이 달라짐. (D) 의도별 `anyOf` 스키마 — 가장 엄격하지만 변경이 큼. (E) 모든 의도에서 원래 질문으로 대체 — 검색하는 의도의 Router 실패가 점수에서 사라져 평가가 부정직해짐. A는 의미가 맞는 곳만 완화하고 실패 집계를 보존한다.
- **부작용**: Ollama에서도 `minLength`가 스키마에 없어져, 검색하는 의도에서 빈 값이 나오면 서버가 막는 대신 검증 오류(`model_invalid_response`)로 드러난다. 기존 평가에서 이런 경우는 관찰되지 않았다.
- **측정 기록**: 결함이 있던 실행은 비공개 결과로 보관하고, 수정 후 같은 gold를 새 경로로 다시 측정한다. 수정 전 수치는 제출 수치로 쓰지 않는다.
- **검증**: `test_llm_backends.py`가 빈 검색어 허용/거부 규칙, `unsupported` 응답이 오류가 아닌 `unsupported`로 끝나는지, 검색하는 의도의 빈 검색어는 여전히 `model_invalid_response`인지, 자리표시자 동작을 확인한다.

## 실측 검증 (2026-10-21)
OpenAI 백엔드로 gold 20문항(A,B,C,C-ko)을 실제 측정했다. 수정 후 실행(v2)은 완료·오류 0건이며 C 장면 Success@1 16/18, unsupported 2/2, 근거 없는 화자 단정 0건, LLM 98회·입력 56,941 / 출력 4,125 토큰이다. 같은 설정의 v1과 장면 결과가 1문항 달라 비결정성이 확인됐다. 상세와 한계는 [reports/day2-eval-openai.md](../reports/day2-eval-openai.md). LangSmith 전송은 켜서 실행했으나 화면 확인은 사용자 몫이다.

## 대안과 트레이드오프
- **openai SDK**: 편하지만 신규 의존성이 생긴다. httpx로 충분하고 Ollama와 같은 오류 처리 방식을 유지할 수 있다.
- **JSON 모드**(`json_object`, 참고 프로젝트 방식): 유효한 JSON만 보장하고 스키마는 강제하지 않는다. 우리는 `extra='forbid'` 계약이 핵심이라 strict json_schema를 택했다.
- **단일 모델**: 구현은 더 단순하다. 하지만 판정(verify)에만 상위 모델을 쓰면 비용 대비 품질이 낫다. 다만 두 모델 결과가 섞이므로 평가 기록에 백엔드와 모델명(`agent_model`)을 남긴다.
- **백엔드별 프롬프트 튜닝**: 비교 공정성이 깨지므로 하지 않는다. 프롬프트 개선은 공통 계약에서 한다.

## 결과와 한계
- 기존 Day 2 평가 수치는 **Ollama qwen3:8b 기준**이다. OpenAI 수치는 **미측정**이다. 제출용 수치는 OpenAI로 다시 측정해야 하며, 과금 실행이므로 별도 승인을 받는다.
- strict 스키마의 실제 호환성과 OpenAI 실제 응답은 모의 HTTP 테스트로만 검증했다. 실제 확인은 사용자가 웹에서 진행한다.
- OpenAI 장애나 네트워크 지연은 기존 20초 LLM timeout과 60초 전체 상한 안에서 폴백 또는 안전한 오류로 처리된다.

## 재검토 조건
- strict 스키마 거부, 지연 15초 초과가 반복되는 경우
- OpenAI 결과가 Ollama보다 나쁜 경우
- 데이터 이용 조건상 외부 전송이 문제가 되는 경우

## 검증 근거
`backend/tests/test_llm_backends.py`(httpx MockTransport, 과금 없음)에서 다음을 확인한다.
- 팩토리 선택과 잘못된 값 거부
- fast/quality 모델 라우팅
- strict `response_format`과 Authorization 헤더
- 토큰 집계
- timeout / 401 / 비JSON / 스키마 불일치 / refusal 오류 매핑과 비공개 텍스트 미노출
- 키·모델 확인

기존 그래프·SSE 테스트는 `build_model`을 주입해 그대로 통과한다.
