# 평가 준비와 실행

A=BM25Plus/B=Hybrid/C=Hybrid+Agent(실제 `FinderAgent`)를 같은 corpus·질문·정답으로 비교한다. Day 2 gold 실측은 [결과 보고서](../docs/reports/day2-eval.md)를 따른다. 데이터·질문·정답을 동일하게 두며, 한국어 원문과 고정한 모델 영어 재구성 조건을 따로 보고한다.

## 파일

- `dataset.py`: 질문·정답 타입과 원문 cue 연결 검증.
- `metrics.py`: 실제 클릭 링크 시각 한 점과 부재·화자 미확인 지표를 분리 계산.
- `paths.py`: 프로젝트 루트 기준 입력 경로와 비공개 출력 경계.
- `agent_runner.py`: C 실행. 모델을 감싼 `RouteProbe`로 Router 첫 검색어를 기록하고, 통제 실험에서는 첫 검색어만 대체한다(Agent 코드는 그대로).
- `run_eval.py`: 실제 MCP 서버 하나에서 A/B/C 실행. `--systems A,B,C`, `--control`(C-ko), gold 승인 해시 검증. 실행 중인 API는 먼저 종료해 임베딩 모델의 중복 로딩을 피한다.
- `dataset.example.jsonl`: 공개 합성 예시. 실제 영상 정답이 아니다.
- `private/`: 로컬 전용 개발 질문·gold 초안·고정 영어 검색어·실행 결과. Git 제외.

실제 corpus 실행:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m eval.run_eval --dataset eval/private/dev.jsonl --rewrites eval/private/dev.rewrites.json --output eval/private/day1-baselines.review2.json
```

LLM 백엔드는 `WISH_LLM_BACKEND`(ollama 기본 | openai)를 따른다. 결과의 `agent_model`에 백엔드와 모델명이, `llm_usage`와 각 C 레코드의 `llm_tokens_in/out`에 토큰이 기록된다. **OpenAI는 과금되므로 `--max-llm-calls N`으로 상한을 둔다**(한 질문의 최악 6회를 넘길 수 있으면 다음 질문을 시작하지 않고 `run_error=llm_budget_reached`로 부분 결과를 저장). OpenAI 실행 예:

```sh
set -a; source .env; set +a   # OPENAI_API_KEY 등 (이 스크립트는 .env를 직접 읽지 않는다)
WISH_LLM_BACKEND=openai WISH_AGENT_TRACE=eval/private/traces-openai HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.venv/bin/python -m eval.run_eval --dataset eval/private/gold.jsonl --systems A,B,C --control \
  --max-llm-calls 150 --output eval/private/day2-abc-gold-openai.json
```

**LangSmith에서 토큰·비용 보기**: `--langsmith`를 붙이면 C/C-ko 실행의 그래프 노드와 LLM 호출이 프로젝트 `wish-finder-eval`(웹 트래픽과 분리, `LANGSMITH_PROJECT`로 변경 가능)에 올라가 호출별 입출력 토큰을 볼 수 있다. `.env`에 `WISH_LANGSMITH_ENABLED=1`과 `LANGSMITH_API_KEY`가 있어야 하며, 없으면 조용히 건너뛰지 않고 실행을 거부한다. **질문과 후보 자막 원문이 업로드되므로** 개인 워크스페이스에서만 쓴다. 로컬 토큰 합계는 결과의 `llm_usage`와 `eval/private/agent-eval.jsonl`에도 남는다.

추가 모델 다운로드 없이 기존 bge-m3 캐시를 사용한다. 영어 재구성은 실행 중 다시 생성하지 않고 저장된 문자열을 모든 방식에서 재사용한다. 질문 ID와 문항 수가 다르면 실행을 거부한다. 다른 manifest는 `--manifest`로 지정하고 프로젝트 루트 기준으로 해석한다.

## 라벨과 측정 규칙

각 문항은 `id`, `query`, `split`, `category`, `answerability`, `expected_video_id`, `accepted_intervals`, `evidence_cue_ids`, `expected_speaker_status`, `label_status`를 가진다. 시각 상태는 중복 라벨 없이 manifest에서 읽고 결과에 기록한다. 호환 필드 `timing_verified=true`는 사용자가 일부 시점의 내용을 확인했다는 뜻이며 전수 검증이 아니다.

- 정답 영상과 실제 링크 시각 `floor(start_seconds)`가 허용 구간 ±10초 안이면 성공이다. 반환 구간이 길게 겹친다는 이유로 성공 처리하지 않는다.
- Scene Success@1·Hit@3의 분모는 장면 정답이 있는 문항이다. 화자 미확인 문항도 관련 장면 정답은 가질 수 있으나 화자 확인 성공을 뜻하지 않는다.
- 복수 장면은 떨어진 정답 구간을 별도로 적고, 하나의 긴 구간으로 합치지 않는다.
- 모든 근거 cue는 정답 구간에 완전히 포함되어야 하며 각 정답 구간에도 근거 cue가 하나 이상 있어야 한다.
- 시각 표본 확인과 gold 내용 확정을 구별한다. 모델·코드의 source cue 대조를 사람의 gold 승인으로 기록하지 않는다.
- `gold_draft` 또는 미승인 `gold`는 실행을 거부한다. `pending_not_found`는 부재 여부 미확인 후보이며 지표에 포함하지 않는다.
- 개발 질문은 반복 실행·문제 분석용이다. gold는 검색 결과를 보며 튜닝하지 않는다. 현재 초안은 질문 분리이며 엄격한 영상 단위 독립 분할은 아니다.

한 번의 검색 latency는 MCP 검색·문맥 조회·원문 검증을 포함하고, 모델/인덱스 초기화·메타데이터 준비·영어 재구성 생성 시간은 별도로 둔다. 각 조건은 문항당 1회이며 캐시·실행 순서 영향을 받는다. 소표본으로 시스템 일반 품질이나 p95를 결론 내리지 않는다.

## API 공통 경로와 오류 기록

API와 평가는 `backend/app/services/search.py`를 함께 호출한다. 한국어·고정 영어 모두 `SearchRequest`의 길이 검사와 공백 제거·빈 입력 거부를 적용한다. 후보별 원문 검증 실패는 해당 후보만 제외하고 `evidence_rejected`를 남긴다. 전부 실패하면 `unsupported`, 검색 자체가 0건이면 `not_found`, 도구 장애는 `error`다. 정상 결과가 있을 때만 `video_timing_sampled` 또는 `video_timing_unverified`가 붙는다.

문항 결과에는 상태·경고·안전한 오류 코드·도구 호출 수·검색 라운드·시각 상태를 저장한다. 개별 오류도 장면 지표의 분모에 남긴다. 연결이 끊기면 완료분과 오류 문항을 저장하고 `complete=false`, `not_run`을 남긴다. `complete=true`는 모든 문항 실행을 뜻하며 오류 0건을 뜻하지 않는다. 오류 문항이 있거나 실행이 불완전하면 CLI는 종료 코드 1을 반환한다.

- 확정된 부재 문항: 빈 결과와 `not_found` 상태가 모두 맞는지 계산한다.
- 화자 미확인 문항: A/B는 고정 경고를 사용하므로 정확도는 N/A, 사유는 `constant_speaker_warning`이다. 예정 문항 수는 유지한다. 근거 없는 화자 단정 건수도 기록하되 A/B는 화자 필드를 채우지 않아 구조상 0이며 질문 인식 성능이 아니다.
- 범위 밖 요청: A/B에 의도 라우터가 없어 N/A다. 원문 검증 실패를 범위 밖 판정 성공으로 세지 않는다.
- 해당 문항이 없거나 실행되지 않았다면 `accuracy=null`과 사유·실행/예정 분모를 기록한다.

모든 CLI 상대 경로는 실행 디렉터리와 무관하게 프로젝트 루트 기준이다. 출력은 정규화한 `eval/private/` 내부만 허용한다. 절대 경로·`..`·심볼릭 링크로 경계를 벗어나면 거부하며, 기존 출력 파일은 덮어쓰지 않는다. 매 문항 후 비공개 폴더 안에서 원자적으로 체크포인트를 저장한다.

## C 화자 평가 계약 (구현·측정 완료)

화자 정답은 Router의 `speaker_query` 분류, 관련 장면의 Scene Success@1 성공, 사용자에게 자막만으로 화자를 확인할 수 없다는 안내 제공을 모두 만족해야 한다. 오류·무응답·장면 누락은 실패다. 세 조건을 따로 기록하며 speaker=null만으로 정답 처리하지 않는다.

근거 없는 화자 단정은 `speaker` 필드와 사용자에게 보이는 `explanation_ko` 등 설명문을 모두 대상으로 한다. 설명문의 발화자 주장을 사람 검토로 판정하고 인용·호명 대상·편집 설명과 구별해 근거 및 필드/설명별 건수를 남긴다. 단정이 있으면 화자 정답에서도 제외한다. C의 장면·화자 성공은 `status=found`일 때만 인정하고 `partial`·`ambiguous`의 원시 후보 적중은 `retrieval_metrics`로 따로 기록한다(A/B 규칙은 그대로). 오류 시 LLM 호출 수는 모델 래퍼가 센 값을, 정상 반환 fallback의 원인은 `telemetry_error`를 보존한다. `python -m eval.aggregate --input eval/private/<결과>.json`으로 보고서 수치를 재집계한다. 판정 코드는 `metrics.agent_metrics`이며 사용자에게 보이는 설명문은 고정 문구 4종이라 전수 점검했다.

실측 요약은 [Day 1 마무리 보고서](../docs/reports/day1-completion.md)에 기록한다. 같은 실제 corpus를 재현하려면 공개하지 않은 자막을 별도로 확보해야 한다.

## C 실행 (Ollama `qwen3:8b` 필요)

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m eval.run_eval --dataset eval/private/gold.jsonl --systems A,B,C --control --output eval/private/day2-abc-gold.json
```

사설 gold는 `gold-approval.json`의 사람 승인 기록과 해시·ID가 일치할 때만 실행한다. 조건 `router_en`의 A/B는 C의 Router 첫 검색어를 재사용하고 `raw_ko`의 C-ko는 한국어 원문을 첫 검색어로 쓴다. `eval/private/agent-eval.jsonl`에는 Agent 단계별 지연 로그가 쌓인다(Git 제외).
