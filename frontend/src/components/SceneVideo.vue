<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { loadYouTubeApi, isVideoId, playerErrorMessage } from '../api/youtube'

const props = defineProps({
  videoId: String, start: Number, title: String,
})
const host = ref(null)
const errorCode = ref(null)
const blocked = ref(false)
let player
let ready = false

onMounted(async () => {
  if (!isVideoId(props.videoId)) return
  try {
    const YT = await loadYouTubeApi()
    if (!host.value) return
    // YT.Player swaps the target node for an iframe, so give it a node Vue does not patch.
    const target = document.createElement('div')
    host.value.appendChild(target)
    const playerVars = { start: Math.floor(props.start), rel: 0, playsinline: 1, origin: location.origin }
    player = new YT.Player(target, {
      videoId: props.videoId, width: '100%', height: '100%', playerVars,
      events: { onReady: () => { ready = true }, onError: e => {
        errorCode.value = e.data
        if (e.data === 101 || e.data === 150) {
          blocked.value = true
          try { player.destroy() } catch { /* already removed */ }
          player = undefined; ready = false
        }
      } },
    })
  } catch { errorCode.value = 'api' }
})
// Jump to a moment (default: the player's start) and play; false when the embedded player is unavailable.
function seek(at = props.start) {
  if (!player || !ready) return false
  try { player.seekTo(Math.floor(at), true); player.playVideo(); return true } catch { return false }
}
defineExpose({ seek })
onBeforeUnmount(() => { try { player?.destroy() } catch { /* already removed */ } })
</script>

<template>
  <div v-if="isVideoId(videoId)" class="player" :class="{ blocked }">
    <div v-show="!blocked" ref="host" class="frame" role="group" :aria-label="title"></div>
    <p v-if="blocked" role="status" class="notice">이 영상은 현재 접속 환경에서 페이지 안 재생이 제한돼 있어요(영상 소유자 설정 또는 접속 주소 문제일 수 있어요). 아래 'YouTube에서 열기'로 해당 시점부터 볼 수 있어요.</p>
    <p v-else-if="errorCode !== null" role="alert" class="notice error">영상을 불러오지 못했어요 (코드 {{ errorCode }}). {{ playerErrorMessage(errorCode) }} 아래 'YouTube에서 열기'를 이용해 주세요.</p>
  </div>
</template>
