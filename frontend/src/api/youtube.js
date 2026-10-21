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
