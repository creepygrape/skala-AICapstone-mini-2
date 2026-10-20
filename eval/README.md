# 평가 준비와 실행

Day 1에는 개발 질문 5개의 A=BM25Plus/B=Hybrid를 비교한다. C=Hybrid+Agent는 아직 구현·측정하지 않았다. 데이터·질문·정답을 동일하게 두며, 한국어 원문과 고정한 모델 영어 재구성 조건을 따로 보고한다.

## 파일

- `dataset.py`: 질문·정답 타입과 원문 cue 연결 검증.
- `metrics.py`: 실제 클릭 링크 시각 한 점과 부재·화자 미확인 지표를 분리 계산.
- `paths.py`: 프로젝트 루트 기준 입력 경로와 비공개 출력 경계.
- `run_eval.py`: 실제 MCP 서버 하나에서 A/B 실행. 실행 중인 API는 먼저 종료해 임베딩 모델의 중복 로딩을 피한다.
- `dataset.example.jsonl`: 공개 합성 예시. 실제 영상 정답이 아니다.
- `private/`: 로컬 전용 개발 질문·gold 초안·고정 영어 검색어·실행 결과. Git 제외.

실제 corpus 실행:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m eval.run_eval --dataset eval/private/dev.jsonl --rewrites eval/private/dev.rewrites.json --output eval/private/day1-baselines.review2.json
```

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
- 화자 미확인 문항: `speaker_unknown` 고지와 모든 결과의 unknown/null을 확인하고 장면 성공과 별도 집계한다. 빈 결과라도 명시적인 미확인 고지는 안전성 지표로 인정하되 장면 성공을 의미하지 않는다. 근거 없는 화자 단정 건수도 별도 기록한다.
- 범위 밖 요청: A/B에 의도 라우터가 없어 N/A다. 원문 검증 실패를 범위 밖 판정 성공으로 세지 않는다.
- 해당 문항이 없거나 실행되지 않았다면 `accuracy=null`과 사유·실행/예정 분모를 기록한다.

모든 CLI 상대 경로는 실행 디렉터리와 무관하게 프로젝트 루트 기준이다. 출력은 정규화한 `eval/private/` 내부만 허용한다. 절대 경로·`..`·심볼릭 링크로 경계를 벗어나면 거부하며, 기존 출력 파일은 덮어쓰지 않는다. 매 문항 후 비공개 폴더 안에서 원자적으로 체크포인트를 저장한다.

실측 요약은 [Day 1 마무리 보고서](../docs/reports/day1-completion.md)에 기록한다. 같은 실제 corpus를 재현하려면 공개하지 않은 자막을 별도로 확보해야 한다.
