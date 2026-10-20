import { describe, it, expect, vi, afterEach } from 'vitest'
import { timestamp, searchScenes } from './search'

afterEach(() => vi.unstubAllGlobals())
describe('search client', () => {
  it('uses cue seconds without carrying a URL offset', () => {
    expect(timestamp(189.606)).toBe('3:09')
  })
  it('displays structured HTTP errors instead of rendering results', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: { message: '도구 오류' } }) }))
    await expect(searchScenes('장면')).rejects.toThrow('도구 오류')
  })
})
