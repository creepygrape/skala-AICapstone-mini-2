import { describe, it, expect } from 'vitest'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import AgentProgress from './components/AgentProgress.vue'
import ResultList from './components/ResultList.vue'
import DetailPanel from './components/DetailPanel.vue'
import SidebarHistory from './components/SidebarHistory.vue'

const render = (component, props) => renderToString(createSSRApp(component, props))
const card = { video_id:'1HJgbE66GI4', cue_ids:['1'], title:'합성 장면', evidence_text:'synthetic',
  explanation_ko:'합성 근거', evidence_type:'dialogue', start_seconds:3, end_seconds:4,
  url:'https://www.youtube.com/watch?v=1HJgbE66GI4&t=3s' }
const response = (status, warnings = [], results = []) => ({ status, warnings, results })

describe('result guidance', () => {
  it('distinguishes source rejection, scope, and other unsupported outcomes', async () => {
    expect(await render(ResultList, { response: response('unsupported', ['evidence_rejected']) })).toContain('원문 근거를 확인하지 못했어요')
    expect(await render(ResultList, { response: response('unsupported', ['subtitle_only_scope']) })).toContain('자막으로 확인할 수 없는 요청이에요')
    expect(await render(ResultList, { response: response('unsupported') })).toContain('확인할 근거가 부족해요')
  })
  it.each(['partial', 'ambiguous'])('keeps speaker guidance with %s notice', async status => {
    const html = await render(ResultList, { response: response(status, ['speaker_unknown'], [card]) })
    expect(html).toContain('자막에는 화자 정보가 없어 발화자는 확인할 수 없습니다.')
    expect(html).toContain(status === 'partial' ? '의미 검증을 완료하지 못했습니다.' : '일치를 확정하기 어렵습니다.')
  })
  it('renders thumbnail cards in rank order and marks the selection', async () => {
    const second = { ...card, cue_ids:['2'], start_seconds:60, evidence_text:'second moment' }
    const html = await render(ResultList, { response: response('found', [], [card, second]), selectedKey: '1HJgbE66GI4:2' })
    expect(html).toContain('https://i.ytimg.com/vi/1HJgbE66GI4/hqdefault.jpg')
    expect(html.indexOf('synthetic')).toBeLessThan(html.indexOf('second moment'))
    expect(html).toContain('가장 유력')
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1)
  })
})

describe('grouped result cards', () => {
  const at = (video_id, cue, start, text) => ({ ...card, video_id, cue_ids:[cue], start_seconds:start, evidence_text:text, title:`영상 ${video_id}` })
  const results = [at('AAAAAAAAAAA','1',10,'first A'), at('BBBBBBBBBBB','5',20,'only B'), at('AAAAAAAAAAA','9',90,'second A')]

  it('shows one card per video and lists its moments in rank order', async () => {
    const html = await render(ResultList, { response: response('found', [], results) })
    expect(html.match(/<article class=/g)).toHaveLength(2)                // A and B, not three cards
    expect(html.match(/<button[^>]*aria-pressed/g)).toHaveLength(3)       // every moment stays selectable
    expect(html.indexOf('first A')).toBeLessThan(html.indexOf('second A'))
    expect(html.indexOf('second A')).toBeLessThan(html.indexOf('only B')) // A's card comes first: it holds the best moment
    expect(html).toContain('영상 2개 · 시점 3개')
    expect(html).toContain('시점 2개')                                    // badge on the card holding two moments
    expect(html.match(/영상 AAAAAAAAAAA/g)).toHaveLength(1)               // title is not repeated per moment
  })

  it('puts the best-match marker on the top moment chip only', async () => {
    const html = await render(ResultList, { response: response('found', [], results) })
    expect(html.match(/가장 유력/g)).toHaveLength(1)
    expect(html.indexOf('가장 유력')).toBeLessThan(html.indexOf('first A'))
    expect(html.indexOf('가장 유력')).toBeGreaterThan(html.indexOf('class="stamps"'))
  })

  it('marks the selected moment and its card, and keeps other moments unselected', async () => {
    const html = await render(ResultList, { response: response('found', [], results), selectedKey: 'AAAAAAAAAAA:9' })
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1)
    const withClass = name => new RegExp('class="(?=[^"]*\\b'+name+'\\b)(?=[^"]*\\bselected\\b)[^"]*"', 'g')
    expect(html.match(withClass('stamp'))).toHaveLength(1)
    expect(html.match(withClass('card'))).toHaveLength(1)
  })

  it('has no count badge or "most likely" marker for a single moment', async () => {
    const html = await render(ResultList, { response: response('found', [], [results[0]]) })
    expect(html).not.toContain('class="count"')
    expect(html).not.toContain('가장 유력')
    expect(html).toContain('영상 1개')
    expect(html).not.toContain('시점 1개')
  })
})

describe('agent progress bubble', () => {
  it('keeps finished steps with durations and shows the running one', async () => {
    const html = await render(AgentProgress, { busy: true, now: 0, steps: [
      { event:'routing', state:'done', durationMs:300, clientStart:0 },
      { event:'searching', attempt:0, state:'running', durationMs:0, clientStart:0 },
    ] })
    expect(html).toContain('질문 유형 파악 완료')
    expect(html).toContain('0.3초')
    expect(html).toContain('관련 장면을 검색 중이에요.')
  })
  it('shows a failed step instead of a completed check', async () => {
    const html = await render(AgentProgress, { busy: false, now: 0, steps: [
      { event:'validating', attempt:0, state:'failed', durationMs:500, clientStart:0 },
    ] })
    expect(html).toContain('원문과 시점을 확인하지 못했어요')
    expect(html).not.toContain('원문과 시점 확인 완료')
    expect(html).toContain('검색 진행 과정 보기')
  })
})

describe('scene detail panel', () => {
  const cues = [
    { cue_id:'1', start_seconds:1, end_seconds:3, text:'What is a ryokan?', caption_type:'dialogue' },
    { cue_id:'2', start_seconds:3, end_seconds:4, text:'(RIKU chose RIKU) Got myself', caption_type:'mixed' },
  ]
  it('highlights the quoted cue and labels editorial text without a speaker', async () => {
    const html = await render(DetailPanel, { item: card, cues, targetCueId: '2', loading: false, error: '', timingSampled: true })
    expect(html).toContain('class="target"')
    expect(html.indexOf('What is a ryokan?')).toBeLessThan(html.indexOf('RIKU chose RIKU'))
    expect(html).toContain('대사·편집 설명 혼합')
    expect(html).toContain('화자 미확인')
    expect(html).toContain('t=3s')
  })
  it('shows a placeholder before any selection', async () => {
    expect(await render(DetailPanel, { cues: [] })).toContain('결과 카드를 선택하면')
  })
})

describe('history sidebar', () => {
  it('lists conversations and states that history stays in the browser', async () => {
    const html = await render(SidebarHistory, { activeId: 'a', busy: false, conversations: [
      { id:'a', title:'료칸 장면', updatedAt: 0, turns:[{}, {}] }] })
    expect(html).toContain('료칸 장면')
    expect(html).toContain('2개 질문')
    expect(html).toContain('이 브라우저에만 저장')
  })
})
