# 평가 준비와 실행

Day 1에는 개발 질문 5개의 A=BM25Plus/B=Hybrid를 비교한다. C=Hybrid+Agent는 아직 구현·측정하지 않았다. 데이터·질문·정답을 동일하게 두며, 한국어 원문과 고정한 모델 영어 재구성 조건을 따로 보고한다.

## 파일

- `dataset.py`: 질문·정답 타입과 원문 cue 연결 검증.
- `metrics.py`: 실제 클릭 링크 시각 한 점의 정답 여부 계산.
- `run_eval.py`: 실제 MCP 서버 하나에서 A/B 실행. 실행 중인 API는 먼저 종료해 임베딩 모델의 중복 로딩을 피한다.
- `dataset.example.jsonl`: 공개 합성 예시. 실제 영상 정답이 아니다.
- `private/`: 로컬 전용 개발 질문·gold 초안·고정 영어 검색어·실행 결과. Git 제외.

실제 corpus 실행:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m eval.run_eval --dataset eval/private/dev.jsonl --rewrites eval/private/dev.rewrites.json --output eval/private/day1-baselines.json
```

추가 모델 다운로드 없이 기존 bge-m3 캐시를 사용한다. 영어 재구성은 실행 중 다시 생성하지 않고 저장된 문자열을 모든 방식에서 재사용한다. 질문 ID와 문항 수가 다르면 실행을 거부한다. 다른 manifest는 `--manifest`로 지정하고 프로젝트 루트 기준으로 해석한다.

## 라벨과 측정 규칙

각 문항은 `id`, `query`, `split`, `category`, `answerability`, `expected_video_id`, `accepted_intervals`, `evidence_cue_ids`, `expected_speaker_status`, `label_status`, `video_timing_verified`를 가진다.

- 정답 영상과 실제 링크 시각 `floor(start_seconds)`가 허용 구간 ±10초 안이면 성공이다. 반환 구간이 길게 겹친다는 이유로 성공 처리하지 않는다.
- Scene Success@1·Hit@3의 분모는 장면 정답이 있는 문항이다. 화자 미확인 문항도 관련 장면 정답은 가질 수 있으나 화자 확인 성공을 뜻하지 않는다.
- 복수 장면은 떨어진 정답 구간을 별도로 적고, 하나의 긴 구간으로 합치지 않는다.
- 시각 표본 확인과 gold 내용 확정을 구별한다. 모델·코드의 source cue 대조를 사람의 gold 승인으로 기록하지 않는다.
- `gold_draft` 또는 미승인 `gold`는 실행을 거부한다. `pending_not_found`는 부재 여부 미확인 후보이며 지표에 포함하지 않는다.
- 개발 질문은 반복 실행·문제 분석용이다. gold는 검색 결과를 보며 튜닝하지 않는다. 현재 초안은 질문 분리이며 엄격한 영상 단위 독립 분할은 아니다.

한 번의 검색 latency는 MCP 검색·문맥 조회·원문 검증을 포함하고, 모델/인덱스 초기화·메타데이터 준비·영어 재구성 생성 시간은 별도로 둔다. 각 조건은 문항당 1회이며 캐시·실행 순서 영향을 받는다. 소표본으로 시스템 일반 품질이나 p95를 결론 내리지 않는다.

실측 요약은 [Day 1 마무리 보고서](../docs/reports/day1-completion.md)에 기록한다. 같은 실제 corpus를 재현하려면 공개하지 않은 자막을 별도로 확보해야 한다.
