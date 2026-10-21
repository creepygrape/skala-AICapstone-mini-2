// Source cues around a result cue (read-only HTTP; the UI never talks to MCP directly).
export async function fetchCueContext(videoId, cueId, signal, { before = 3, after = 3 } = {}) {
  const path = `/api/videos/${encodeURIComponent(videoId)}/cues/${encodeURIComponent(cueId)}/context`
  const response = await fetch(`${path}?before=${before}&after=${after}`, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : '앞뒤 자막을 불러오지 못했어요.')
  }
  return response.json()
}
