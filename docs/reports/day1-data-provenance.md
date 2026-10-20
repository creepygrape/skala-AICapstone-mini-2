# Day 1 데이터 출처와 확인 범위

- 확인일: 2026-10-20
- 자막 확보 방법: 사용자가 영상 URL을 [Wave YouTube Transcript](https://wave.co/ko/tools/youtube-transcript)에 입력해 SRT/TXT를 추출했다고 확인했다.
- 이번 작업에서 자막 재추출, 영상 다운로드, 로그인 우회, 유료 호출은 하지 않았다.

## 영상 메타데이터

제목·채널명은 사용자 제공 영상 ID로 YouTube 공식 oEmbed를 조회해 확인했다. 세 영상의 채널명은 NCT WISH다. 아래 제목은 식별을 위한 요약이며, 전체 원제는 로컬 manifest에 보존한다.

| 파일 | 영상 | 확인한 시리즈·제목 | 상태 |
|---|---|---|---|
| hokkaido_1.srt / .txt | [1HJgbE66GI4](https://www.youtube.com/watch?v=1HJgbE66GI4) | 함께라서 좋다 / WISH's Wish in Hokkaido EP.1 | 공식 메타데이터 확인 |
| camp_1.srt / .txt | [vWjPXwKV_Y8](https://www.youtube.com/watch?v=vWjPXwKV_Y8) | 날씨 요정 돌아와 / WISH’s Wish in Camp EP.1 | 공식 메타데이터 확인 |
| oth_5.srt / .txt | [zOgJILPNzbE](https://www.youtube.com/watch?v=zOgJILPNzbE) | 진심이 스미다 / Ode to Love HOUSE EP.5 | 공식 메타데이터 확인 |

실제 조회 경로는 `https://www.youtube.com/oembed?url=<영상 URL>&format=json`이며, 전체 응답 중 제목·채널·조회 URL만 로컬 확인 기록에 사용했다. 제목을 검색 결과 스니펫에서 추측하지 않았다.

## 추출 조건과 공개 범위

Wave의 [도구 안내](https://wave.co/ko/tools/youtube-transcript)는 자막을 TXT/SRT로 내려받는 기능과 언어 선택·번역 기능을 설명한다. 현재 파일의 추출 언어는 영어지만, 사용자가 당시 선택한 번역 옵션과 원래 영어 트랙의 생성 방식은 확인하지 않았다. 이를 공식 영문 자막 또는 사람이 번역한 자막으로 단정하지 않는다.

[Wave 이용약관](https://wave.co/terms)은 타인의 권리를 침해하는 서비스 이용을 금지하고, AI 전사·요약 오류 가능성을 안내한다. 확인한 페이지에서 제삼자 YouTube 자막 전문의 공개 재배포 허용을 확정하지 못했다. 이는 이용 권한을 법적으로 판정한 문서가 아니다.

원본 SRT/TXT, 파생 cue·인덱스, 전체 로컬 manifest, 비공개 gold·문항별 결과는 계속 Git에서 제외한다. 공개 코드에는 합성 fixture·스키마·측정 요약만 포함하고, 실제 영상 링크와 짧은 근거를 UI에 제공한다. 자료 사용 조건이나 권리 관계가 달라지면 공개·배포 범위를 재검토한다.

## 시각 정합성

사용자가 [9개 시점 확인표](day1-timing-checklist.md)의 링크 내용을 모두 확인해 일치한다고 응답했다. 영상별 3점 표본 확인이며 전체 cue 전수 검증이나 정확한 오프셋 측정은 아니다. `timing_verified=true`는 이 사용자 표본 확인을 뜻한다.

`oth_5` 제공 URL의 t=186s는 원래 재생 위치다. SRT 전체에 186초를 더하지 않는다. 원문 시각과 `floor(cue.start_seconds)` 기반 링크 정책을 유지한다.
