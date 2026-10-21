<script setup>
import { ref, watch } from 'vue'
import SceneVideo from './SceneVideo.vue'
import { timestamp } from '../api/search'
import { urlAt } from '../api/media'
import { EVIDENCE_TAGS } from '../api/resultText'

const props = defineProps({
  item: Object,        // selected result card
  cues: Array,         // exact source cues around the quoted cue
  targetCueId: String,
  loading: Boolean,
  error: String,
  timingSampled: Boolean,
})
defineEmits(['close'])
const player = ref(null)

// Replay from a moment; falls back to YouTube when the embed is unavailable.
function playAt(seconds) {
  if (!player.value?.seek(seconds)) window.open(urlAt(props.item.url, seconds), '_blank', 'noopener,noreferrer')
}
// Same video, other card: move the existing player without starting playback.
watch(() => props.item, (item, old) => {
  if (item && old && item.video_id === old.video_id) player.value?.seek(item.start_seconds, false)
})
</script>

<template>
  <aside class="detail" aria-label="선택한 장면">
    <button type="button" class="close" aria-label="장면 패널 닫기" @click="$emit('close')">✕</button>
    <p v-if="!item" class="placeholder">결과 카드를 선택하면 영상과 앞뒤 자막을 볼 수 있어요.</p>
    <template v-else>
      <SceneVideo :key="item.video_id" ref="player" :video-id="item.video_id" :start="item.start_seconds" :title="`${item.title} ${timestamp(item.start_seconds)} 장면`" />
      <h3>{{ item.title }} <span class="at">{{ timestamp(item.start_seconds) }}</span></h3>
      <a class="yt" :href="urlAt(item.url, item.start_seconds)" target="_blank" rel="noopener noreferrer">YouTube에서 {{ timestamp(item.start_seconds) }}부터 보기 ↗<span class="sr-only"> (새 창)</span></a>
      <h4>주요 자막 <span>앞뒤 맥락</span></h4>
      <p v-if="loading" role="status" class="muted">앞뒤 자막을 불러오는 중이에요.</p>
      <p v-else-if="error" role="alert" class="notice error">{{ error }}</p>
      <ol v-else class="cues">
        <li v-for="cue in cues" :key="cue.cue_id" :class="{ target: String(cue.cue_id) === String(targetCueId) }">
          <button type="button" class="t" :aria-label="`${timestamp(cue.start_seconds)} 지점부터 재생`" @click="playAt(cue.start_seconds)">{{ timestamp(cue.start_seconds) }}</button>
          <span class="text">{{ cue.text }}<em v-if="cue.caption_type === 'editorial' || cue.caption_type === 'mixed'">{{ EVIDENCE_TAGS[cue.caption_type] }}</em></span>
        </li>
      </ol>
      <p class="fine">화자 미확인 · 번역 자막 기준. 괄호 속 문장은 화면 편집 설명일 수 있고, 호명된 멤버가 말한 사람은 아니에요.</p>
      <p class="fine">{{ timingSampled ? '영상별 일부 시점만 표본 확인했어요. 전체 자막 시각의 정확도를 보장하지는 않아요.' : '원본 영상과 자막 시각의 일치 여부는 추가 확인 중이에요.' }}</p>
    </template>
  </aside>
</template>
