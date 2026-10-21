// YouTube IFrame Player API loader. No API key is needed; the script only exposes the player.
let loading

export const isVideoId = id => /^[A-Za-z0-9_-]{11}$/.test(id || '')

export function loadYouTubeApi() {
  if (globalThis.YT?.Player) return Promise.resolve(globalThis.YT)
  loading ??= new Promise((resolve, reject) => {
    const previous = globalThis.onYouTubeIframeAPIReady
    globalThis.onYouTubeIframeAPIReady = () => { previous?.(); resolve(globalThis.YT) }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    script.onerror = () => { loading = undefined; reject(new Error('youtube api load failed')) }
    document.head.appendChild(script)
  })
  return loading
}

const REASONS = {
  2: '잘못된 재생 요청이에요.',
  5: '브라우저 재생기에서 오류가 났어요.',
  100: '영상이 삭제됐거나 비공개예요.',
  101: '영상 소유자가 외부 사이트 재생을 허용하지 않았어요.',
  150: '영상 소유자가 외부 사이트 재생을 허용하지 않았어요.',
  153: '재생 요청에 출처(Referer) 정보가 없어요.',
  api: 'YouTube 재생기를 불러오지 못했어요. 네트워크나 차단 확장 프로그램을 확인해 주세요.',
}
export const playerErrorMessage = code => REASONS[code] || ''

const BLOCKED_CODES = new Set([101, 150])
const PLAYING = 1

// Player lifecycle without Vue/DOM so it can be tested with a fake YT namespace.
// seek() is only true while the player is ready and error-free: IFrame commands do not
// throw when playback fails, so callers must fall back to YouTube whenever it is false.
export function createScenePlayer(YT, target, { videoId, start, origin, onChange }) {
  const state = { ready: false, failed: false, blocked: false, errorCode: null }
  let player
  const emit = () => onChange?.({ ...state })
  const destroy = () => { try { player?.destroy() } catch { /* already removed */ } player = undefined }
  const playerVars = { start: Math.floor(start), rel: 0, playsinline: 1 }
  if (origin) playerVars.origin = origin
  player = new YT.Player(target, {
    videoId, width: '100%', height: '100%', playerVars,
    events: {
      onReady: () => { state.ready = true; emit() },
      onStateChange: event => {
        // Playback confirmed after a recoverable error (e.g. a transient failure).
        if (event.data === PLAYING && state.failed && !state.blocked) {
          state.failed = false; state.errorCode = null; emit()
        }
      },
      onError: event => {
        state.failed = true; state.errorCode = event.data
        if (BLOCKED_CODES.has(event.data)) { state.blocked = true; state.ready = false; destroy() }
        emit()
      },
    },
  })
  return {
    state,
    destroy,
    // play=false moves the position only (card selection must never start playback).
    // seekTo() on a video that never started (unstarted/cued) begins playing, and a playing
    // video would keep playing, so a silent move always re-cues the video at the new position.
    seek(at = start, play = true) {
      if (!player || !state.ready || state.failed) return false
      try {
        if (!play) {
          player.cueVideoById({ videoId, startSeconds: Math.floor(at) })
        } else {
          player.seekTo(Math.floor(at), true)
          if (play) player.playVideo()
        }
        return true
      } catch { return false }
    },
  }
}
