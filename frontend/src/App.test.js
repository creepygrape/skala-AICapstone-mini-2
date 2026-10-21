import { readFileSync } from 'node:fs'
import { describe, it, expect } from 'vitest'
import * as Vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import { parse } from '@vue/compiler-sfc'
import { compile } from '@vue/compiler-dom'

const source = readFileSync(new URL('./App.vue', import.meta.url), 'utf8')
const template = parse(source).descriptor.template.content
const render = new Function('Vue', compile(template, { mode: 'function' }).code)(Vue)
async function page(status, warnings, results = []) {
  return renderToString(Vue.createSSRApp({ render, data: () => ({
    response: { status, warnings, results }, query: '', busy: false, error: '',
    videoCount: 3, timingSampled: true, examples: [], progress: null,
  }), methods: { timestamp: () => '0:03', submit() {} } }))
}

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
