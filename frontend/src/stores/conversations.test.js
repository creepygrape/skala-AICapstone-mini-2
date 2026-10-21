import { describe, it, expect } from 'vitest'
import { STORAGE_KEY, loadConversations, saveConversations, followUpPayload, newConversation, newTurn, evidenceKey, MAX_CONVERSATIONS } from './conversations'

const memory = (limit = Infinity) => {
  const data = new Map()
  return { data, getItem: k => data.get(k) ?? null, removeItem: k => data.delete(k),
    setItem(k, v) { if (v.length > limit) throw new Error('quota'); data.set(k, v) } }
}
const result = (cue, text = 'quote') => ({ video_id: 'VID00000001', cue_ids: [cue], title: 'T', start_seconds: 5, evidence_text: text })
const answered = (query, results) => ({ ...newTurn(query), status: 'done', response: { results } })

describe('conversation persistence', () => {
  it('round-trips and tolerates corrupt or blocked storage', () => {
    const storage = memory()
    const c = newConversation('q', 1)
    expect(saveConversations([c], storage)).toBe(true)
    expect(loadConversations(storage)[0].id).toBe(c.id)
    storage.data.set(STORAGE_KEY, '{not json')
    expect(loadConversations(storage)).toEqual([])
    expect(loadConversations(null)).toEqual([])
    expect(saveConversations([c], null)).toBe(false)
  })
  it('marks turns that were running at close as interrupted', () => {
    const storage = memory()
    const c = newConversation('q', 1)
    c.turns.push({ ...newTurn('q'), steps: [{ event: 'searching', state: 'running' }] })
    saveConversations([c], storage)
    const [turn] = loadConversations(storage)[0].turns
    expect(turn.status).toBe('error')
    expect(turn.steps[0].state).toBe('aborted')
  })
  it('keeps the newest conversations and drops the oldest on quota errors', () => {
    const list = Array.from({ length: MAX_CONVERSATIONS + 3 }, (_, i) => newConversation(`q${i}`, i))
    const storage = memory()
    saveConversations(list, storage)
    expect(JSON.parse(storage.getItem(STORAGE_KEY))).toHaveLength(MAX_CONVERSATIONS)
    const tiny = memory(1200)
    saveConversations(list, tiny)
    const kept = JSON.parse(tiny.getItem(STORAGE_KEY))
    expect(kept.length).toBeGreaterThan(0)
    expect(kept.length).toBeLessThan(MAX_CONVERSATIONS)
    expect(kept[0].updatedAt).toBe(list.length - 1)
  })
})

describe('follow-up payload', () => {
  it('sends the last three answered turns and every shown scene key', () => {
    const c = newConversation('a')
    c.turns = [answered('1', [result('1')]), answered('2', [result('2')]), answered('3', [result('3'), result('4')]),
      answered('4', []), { ...newTurn('5'), status: 'error' }]
    const { history, exclude } = followUpPayload(c)
    expect(history.map(h => h.query)).toEqual(['2', '3', '4'])
    expect(history[2].top).toBeNull()
    expect(history[1].top).toMatchObject({ video_id: 'VID00000001', evidence_text: 'quote' })
    expect(exclude).toEqual(['1', '2', '3', '4'].map(n => `VID00000001:${n}`))
  })
  it('truncates long text and is empty for a new conversation', () => {
    expect(followUpPayload(null)).toEqual({ history: [], exclude: [] })
    const c = newConversation('a')
    c.turns = [answered('x'.repeat(500), [result('1', 'y'.repeat(500))])]
    const { history } = followUpPayload(c)
    expect(history[0].query).toHaveLength(300)
    expect(history[0].top.evidence_text).toHaveLength(120)
    expect(evidenceKey(result('9'))).toBe('VID00000001:9')
  })
})
