// Conversation history lives only in this browser (no login, nothing stored on the server).
export const STORAGE_KEY = 'wish-finder:conversations:v1'
export const MAX_CONVERSATIONS = 30
const MAX_HISTORY_TURNS = 3
const MAX_EXCLUDE = 20

export const evidenceKey = item => `${item.video_id}:${item.cue_ids[0]}`

let counter = 0
const uid = () => `${Date.now().toString(36)}-${(counter++).toString(36)}${Math.random().toString(36).slice(2, 6)}`

export const newTurn = query => ({ id: uid(), query, status: 'running', steps: [], response: null, error: '', doneMs: null })
export const newConversation = (query, now = Date.now()) => ({ id: uid(), title: query.slice(0, 40), createdAt: now, updatedAt: now, turns: [] })

function safeStorage() {
  try { return globalThis.localStorage ?? null } catch { return null }
}

// A turn that was still running when the page closed can never finish: show it as interrupted.
function sanitize(list) {
  if (!Array.isArray(list)) return []
  return list.filter(c => c && typeof c.id === 'string' && Array.isArray(c.turns)).map(c => ({
    ...c,
    turns: c.turns.filter(t => t && typeof t.query === 'string').map(t => t.status === 'running'
      ? { ...t, status: 'error', error: '검색이 중단되었어요. 다시 시도해 주세요.',
          steps: (t.steps || []).map(s => s.state === 'running' ? { ...s, state: 'aborted' } : s) }
      : t),
  }))
}

export function loadConversations(storage = safeStorage()) {
  try { return sanitize(JSON.parse(storage?.getItem(STORAGE_KEY) || '[]')) }
  catch { return [] }
}

// Quota errors drop the oldest conversation and retry; never throws (history is a convenience).
export function saveConversations(list, storage = safeStorage()) {
  if (!storage) return false
  let kept = [...list].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CONVERSATIONS)
  while (kept.length) {
    try { storage.setItem(STORAGE_KEY, JSON.stringify(kept)); return true }
    catch { kept = kept.slice(0, -1) }
  }
  try { storage.removeItem(STORAGE_KEY) } catch { /* ignore */ }
  return false
}

// Compact previous turns (reference resolution only) and the scenes already shown in this conversation.
export function followUpPayload(conversation) {
  const answered = (conversation?.turns || []).filter(t => t.status === 'done' && t.response)
  const history = answered.slice(-MAX_HISTORY_TURNS).map(t => {
    const top = t.response.results[0]
    return { query: t.query.slice(0, 300), top: top ? { video_id: top.video_id, title: top.title.slice(0, 200),
      start_seconds: top.start_seconds, evidence_text: top.evidence_text.slice(0, 120) } : null }
  })
  const exclude = [...new Set(answered.flatMap(t => t.response.results.map(evidenceKey)))].slice(-MAX_EXCLUDE)
  return { history, exclude }
}
