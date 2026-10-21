import { readFileSync } from 'node:fs'
import { describe, it, expect } from 'vitest'
import * as Vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import { parse } from '@vue/compiler-sfc'
import { compile } from '@vue/compiler-dom'
import { groupByVideo } from './api/search'

const source = readFileSync(new URL('./App.vue', import.meta.url), 'utf8')
const template = parse(source).descriptor.template.content
const render = new Function('Vue', compile(template, { mode: 'function' }).code)(Vue)
const LABELS = {
  routing: ['질문 유형을 파악하고 있어요.', '질문 유형 파악 완료'],
  searching: ['관련 장면을 검색 중이에요.', '관련 장면 검색 완료'],
  validating: ['원문과 시점을 확인하고 있어요.', '원문과 시점 확인 완료', '원문과 시점을 확인하지 못했어요'],
}
async function page(status, warnings, results = [], extra = {}) {
  const app = Vue.createSSRApp({ render, data: () => ({
    response: { status, warnings, results }, query: '', busy: false, error: '',
    videoCount: 3, timingSampled: true, examples: [], steps: [], now: 0,
    LABELS, ...extra,
  }), methods: { timestamp: () => '0:03', submit() {}, playAt() {}, setPlayer() {}, groupByVideo, cardKey: item => item.video_id,
    formatElapsed: ms => `${(ms / 1000).toFixed(1)}초`, totalMs: () => 1500 } })
  app.component('SceneVideo', { props: ['videoId', 'start'], template: '<div class="player-stub" :data-id="videoId" :data-start="start"></div>' })
  return renderToString(app)
}
const card = { video_id:'1HJgbE66GI4', cue_ids:[1], title:'합성 장면', evidence_text:'synthetic',
  explanation_ko:'합성 근거', evidence_type:'dialogue', start_seconds:3, end_seconds:4,
  url:'https://example.com' }

describe('result guidance', () => {
  it('distinguishes source rejection, scope, and other unsupported outcomes', async () => {
    expect(await page('unsupported', ['evidence_rejected'])).toContain('원문 근거를 확인하지 못했어요')
    expect(await page('unsupported', ['subtitle_only_scope'])).toContain('자막으로 확인할 수 없는 요청이에요')
    expect(await page('unsupported', [])).toContain('확인할 근거가 부족해요')
  })
  it.each(['partial', 'ambiguous'])('keeps speaker guidance with %s notice', async status => {
    const html = await page(status, ['speaker_unknown'], [{ video_id:'test', cue_ids:[1],
      title:'합성 장면', evidence_text:'synthetic', explanation_ko:'합성 근거',
      evidence_type:'dialogue', start_seconds:3, end_seconds:4, url:'https://example.com' }])
    expect(html).toContain('자막에는 화자 정보가 없어 발화자는 확인할 수 없습니다.')
    expect(html).toContain(status === 'partial' ? '의미 검증을 완료하지 못했습니다.' : '일치를 확정하기 어렵습니다.')
  })
})

describe('progress steps and inline player', () => {
  it('keeps finished steps with durations and shows the running one', async () => {
    const html = await page('found', [], [], { response: null, busy: true, steps: [
      { event:'routing', state:'done', durationMs:300, clientStart:0 },
      { event:'searching', attempt:0, state:'running', durationMs:0, clientStart:0 },
    ] })
    expect(html).toContain('질문 유형 파악 완료')
    expect(html).toContain('0.3초')
    expect(html).toContain('관련 장면을 검색 중이에요.')
  })
  it('shows a failed step instead of a completed check', async () => {
    const html = await page('found', [], [], { response: null, steps: [
      { event:'validating', attempt:0, state:'failed', durationMs:500, clientStart:0 },
    ] })
    expect(html).toContain('원문과 시점을 확인하지 못했어요')
    expect(html).not.toContain('원문과 시점 확인 완료')
    expect(html).toContain('실패')
  })
  it('renders the player inside each card with the YouTube link as fallback', async () => {
    const html = await page('found', [], [card])
    expect(html).toContain('data-id="1HJgbE66GI4"')
    expect(html).toContain('data-start="3"')
    expect(html).toContain('YouTube에서 열기')
    expect(html).not.toContain('여기서 재생')
    expect(html).toContain('0:03 지점부터 재생')
  })
  it('merges results from the same video into one card, in rank order', async () => {
    const second = { ...card, cue_ids:[2], start_seconds:60, end_seconds:62, evidence_text:'second moment' }
    const html = await page('found', [], [card, second])
    expect(html.match(/data-id="1HJgbE66GI4"/g)).toHaveLength(1)
    expect(html.indexOf('synthetic')).toBeLessThan(html.indexOf('second moment'))
    expect(html).toContain('가장 유력')
    expect(html).toContain('data-start="3"')
  })
})
