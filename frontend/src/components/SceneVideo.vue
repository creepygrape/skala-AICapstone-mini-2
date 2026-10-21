<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { loadYouTubeApi, isVideoId, playerErrorMessage, createScenePlayer } from '../api/youtube'

const props = defineProps({
  videoId: String, start: Number, title: String,
})
const host = ref(null)
const errorCode = ref(null)
const blocked = ref(false)
let scene

onMounted(async () => {
  if (!isVideoId(props.videoId)) return
  try {
    const YT = await loadYouTubeApi()
    if (!host.value) return
    // YT.Player swaps the target node for an iframe, so give it a node Vue does not patch.
    const target = document.createElement('div')
    host.value.appendChild(target)
    scene = createScenePlayer(YT, target, {
      videoId: props.videoId, start: props.start, origin: location.origin,
      onChange: state => { errorCode.value = state.errorCode; blocked.value = state.blocked },
    })
  } catch { errorCode.value = 'api' }
})
// Jump to a moment and play; false whenever the embed is unavailable or errored (caller opens YouTube).
const seek = at => scene?.seek(at) ?? false
defineExpose({ seek })
onBeforeUnmount(() => scene?.destroy())
</script>

<template>
  <div v-if="isVideoId(videoId)" class="player" :class="{ blocked }">
    <div v-show="!blocked" ref="host" class="frame" role="group" :aria-label="title"></div>
    <p v-if="blocked" role="status" class="notice">이 영상은 현재 접속 환경에서 페이지 안 재생이 제한돼 있어요(영상 소유자 설정 또는 접속 주소 문제일 수 있어요). 아래 'YouTube에서 열기'로 해당 시점부터 볼 수 있어요.</p>
    <p v-else-if="errorCode !== null" role="alert" class="notice error">영상을 불러오지 못했어요 (코드 {{ errorCode }}). {{ playerErrorMessage(errorCode) }} 아래 'YouTube에서 열기'를 이용해 주세요.</p>
  </div>
</template>
