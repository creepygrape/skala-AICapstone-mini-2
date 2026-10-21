import { describe, it, expect, vi, afterEach } from 'vitest'
import { timestamp, parseEventFrame, searchScenes, formatElapsed, groupByVideo } from './search'

afterEach(() => vi.unstubAllGlobals())

function responseFrom(chunks, { ok = true, body } = {}) {
  const encoder = new TextEncoder()
  return { ok, json: async () => body || {}, body: ok ? new ReadableStream({
    start(controller) {
      chunks.forEach(chunk => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  }) : null }
}

describe('search client', () => {
  it('uses cue seconds without carrying a URL offset', () => {
    expect(timestamp(189.606)).toBe('3:09')
  })
  it('groups results by video keeping rank order', () => {
    const groups = groupByVideo([{ video_id:'a', title:'A', url:'u1', start_seconds:9 }, { video_id:'b', title:'B', url:'u2', start_seconds:1 }, { video_id:'a', title:'A', url:'u3', start_seconds:2 }])
    expect(groups.map(g => g.video_id)).toEqual(['a', 'b'])
    expect(groups[0].items.map(i => i.start_seconds)).toEqual([9, 2])
    expect(groups[0].url).toBe('u1')
  })
  it('formats stage durations', () => {
    expect(formatElapsed(40)).toBe('<0.1초')
    expect(formatElapsed(1234)).toBe('1.2초')
  })
  it('parses CRLF and multiline data fields', () => {
    expect(parseEventFrame('event: progress\r\ndata: {"message":\r\ndata: "검색 중"}')).toEqual({
      event: 'progress', data: { message: '검색 중' },
    })
  })
  it('parses frames split across arbitrary chunks and returns the result', async () => {
    const events = []
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(responseFrom([
      'event: routing\ndata: {"message":"질문 ','확인"}\n\nevent: result\ndata: {"status":"found","results":[]}',
      '\n\nevent: done\ndata: {"status":"found"}\n\n',
    ])))
    const result=await searchScenes('장면',undefined,(event,data) => events.push([event,data]))
    expect(result.status).toBe('found')
    expect(events.map(([event]) => event)).toEqual(['routing','result','done'])
  })
  it('displays structured HTTP errors instead of reading a stream', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(responseFrom([],{
      ok:false,body:{ detail:{ message:'도구 오류' } },
    })))
    await expect(searchScenes('장면')).rejects.toThrow('도구 오류')
  })
  it('keeps SSE errors distinct and rejects incomplete connections', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(responseFrom([
      'event: error\ndata: {"message":"모델 오류"}\n\nevent: done\ndata: {"status":"error"}\n\n',
    ])))
    await expect(searchScenes('장면')).rejects.toThrow('모델 오류')
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(responseFrom([
      'event: routing\ndata: {"message":"확인"}\n\n',
    ])))
    await expect(searchScenes('장면')).rejects.toThrow('완료 전에 종료')
  })
})
