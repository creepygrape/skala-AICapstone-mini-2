export function timestamp(seconds) {
  const value = Math.floor(seconds)
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`
}

export function formatElapsed(ms) {
  return ms < 100 ? '<0.1초' : `${(ms / 1000).toFixed(1)}초`
}

// Group ranked results by video, keeping rank order: the first item is the top-ranked moment.
export function groupByVideo(results) {
  const groups = new Map()
  for (const item of results) {
    if (!groups.has(item.video_id)) groups.set(item.video_id, { video_id: item.video_id, title: item.title, url: item.url, items: [] })
    groups.get(item.video_id).items.push(item)
  }
  return [...groups.values()]
}

function httpMessage(body) {
  const detail = body?.detail
  return typeof detail === 'string' ? detail : detail?.message || '검색을 완료하지 못했습니다. 다시 시도해 주세요.'
}

export function parseEventFrame(frame) {
  let event = 'message'
  const data = []
  for (const line of frame.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon < 0 ? line : line.slice(0, colon)
    let value = colon < 0 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    if (field === 'data') data.push(value)
  }
  if (!data.length) return null
  try { return { event, data: JSON.parse(data.join('\n')) } }
  catch { throw new Error('검색 응답 형식을 해석하지 못했습니다. 다시 시도해 주세요.') }
}

export async function searchScenes(query, signal, onEvent = () => {}) {
  const response = await fetch('/api/search/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ query, thread_id: null }),
    signal,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(httpMessage(body))
  }
  if (!response.body) throw new Error('검색 스트림을 시작하지 못했습니다. 다시 시도해 주세요.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = '', result = null, streamError = null, completed = false
  const dispatch = (frame) => {
    const parsed = parseEventFrame(frame)
    if (!parsed) return
    onEvent(parsed.event, parsed.data)
    if (parsed.event === 'result') result = parsed.data
    if (parsed.event === 'error') streamError = new Error(parsed.data?.message || '검색 중 오류가 발생했습니다.')
    if (parsed.event === 'done') completed = true
  }
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    let match
    while ((match = /\r?\n\r?\n/.exec(buffer))) {
      dispatch(buffer.slice(0,match.index))
      buffer = buffer.slice(match.index+match[0].length)
    }
    if (done) break
  }
  if (buffer.trim()) dispatch(buffer)
  if (streamError) throw streamError
  if (!completed) throw new Error('검색 연결이 완료 전에 종료됐습니다. 다시 시도해 주세요.')
  if (!result) throw new Error('검색 결과를 받지 못했습니다. 다시 시도해 주세요.')
  return result
}
