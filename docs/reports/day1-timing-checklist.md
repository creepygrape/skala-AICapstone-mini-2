# Day 1 영상 시각 확인표

제목·채널은 YouTube 공식 oEmbed에서 확인했다. 아래 항목은 SRT 시간으로 생성한 **사용자가 내용 일치를 확인한 링크**다. 링크를 만들었다는 사실과 실제 영상 장면이 맞는다는 사실은 구분한다.

| 영상 | cue | SRT 시각 | 짧은 확인 내용 | 링크 | 실제 재생 확인 |
|---|---|---|---|---|---|
| 1HJgbE66GI4 | 69 | 03:09 | 자기 자신을 뽑은 편집 설명 | [재생](https://www.youtube.com/watch?v=1HJgbE66GI4&t=189s) | 사용자 확인: 일치 |
| 1HJgbE66GI4 | 1151 | 45:53 | 구운 오징어가 왔다는 말 | [재생](https://www.youtube.com/watch?v=1HJgbE66GI4&t=2753s) | 사용자 확인: 일치 |
| 1HJgbE66GI4 | 1451 | 58:04 | 곰이 입에 물고 있는 물고기 | [재생](https://www.youtube.com/watch?v=1HJgbE66GI4&t=3484s) | 사용자 확인: 일치 |
| vWjPXwKV_Y8 | 3 | 00:39 | 한우 축제 여행 이야기 | [재생](https://www.youtube.com/watch?v=vWjPXwKV_Y8&t=39s) | 사용자 확인: 일치 |
| vWjPXwKV_Y8 | 350 | 10:33 | 마트 김치찌개 이야기 | [재생](https://www.youtube.com/watch?v=vWjPXwKV_Y8&t=633s) | 사용자 확인: 일치 |
| vWjPXwKV_Y8 | 1501 | 47:39 | 아프다는 반응을 재연하는 편집 설명 | [재생](https://www.youtube.com/watch?v=vWjPXwKV_Y8&t=2859s) | 사용자 확인: 일치 |
| zOgJILPNzbE | 21 | 01:17 | 사쿠야가 료에게 음식을 건넨 편집 설명 | [재생](https://www.youtube.com/watch?v=zOgJILPNzbE&t=77s) | 사용자 확인: 일치 |
| zOgJILPNzbE | 405 | 21:47 | 재희가 리쿠를 최종 선택한 편집 설명 | [재생](https://www.youtube.com/watch?v=zOgJILPNzbE&t=1307s) | 사용자 확인: 일치 |
| zOgJILPNzbE | 651 | 34:46 | 4월 20일 앨범 발매 언급 | [재생](https://www.youtube.com/watch?v=zOgJILPNzbE&t=2086s) | 사용자 확인: 일치 |

## 확인 방법

각 링크를 재생해 표시된 상황이나 대사가 실제로 그 시점에 있는지 확인한다. 시작이 어긋나면 실제 관측 시각과 차이를 기록한다. 영상별 3개 지점이 비슷하게 어긋나는지 확인하고, 확인 전에는 원문 cue 시간이나 링크에 임의 오프셋을 적용하지 않는다.

음성·화자 판독 결과를 자막의 확정 화자 정보로 바꾸지 않는다. 사용자 확인 결과를 받은 뒤 해당 영상의 timing_verified를 갱신한다.

## 확인 결과

2026-10-20 사용자 응답: “9개 모두 일치”. 영상별 3점의 링크 내용 일치를 확인한 것으로 기록한다. 실제 관측 초를 별도로 측정한 것은 아니므로 offset_seconds는 미측정이다. 전체 자막의 전수 정확도를 보장하지 않으며 확인 주체를 AI로 기록하지 않는다. 로컬 manifest의 timing_verified는 이 표본 확인을 뜻한다.
