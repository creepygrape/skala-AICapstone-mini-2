import { describe, it, expect } from 'vitest'
import { applyEvent, abortRunning, totalDuration } from './steps'

const play = (events, start = []) => events.reduce((steps, [event, data, now]) => applyEvent(steps, event, data, now), start)
const states = steps => steps.map(step => `${step.event}:${step.state}`)

describe('progress steps', () => {
  it('closes a normal run with server node times', () => {
    const steps = play([
      ['routing', { elapsed_ms: 5, stage_ms: {} }, 0],
      ['searching', { attempt: 0, elapsed_ms: 300, stage_ms: { router: 290 } }, 300],
      ['validating', { attempt: 0, elapsed_ms: 400, stage_ms: { search: 100 } }, 400],
      ['result', {}, 1000],
      ['done', { status: 'found', elapsed_ms: 1500, stage_ms: { context: 400, verification: 600, finalize: 50 } }, 1500],
    ])
    expect(states(steps)).toEqual(['routing:done', 'searching:done', 'validating:done'])
    expect(steps.map(step => step.durationMs)).toEqual([290, 100, 1000])
    expect(totalDuration(steps, 1500)).toBe(1500)
  })

  it('marks the running step failed on error then done(status=error)', () => {
    const steps = play([
      ['routing', { elapsed_ms: 0 }, 0],
      ['searching', { attempt: 0, elapsed_ms: 100 }, 100],
      ['validating', { attempt: 0, elapsed_ms: 200 }, 200],
      ['error', { code: 'model_timeout' }, 700],
      ['done', { status: 'error', elapsed_ms: 800 }, 800],
    ])
    expect(states(steps)).toEqual(['routing:done', 'searching:done', 'validating:failed'])
  })

  it('treats done(status=error) alone as failure and cancel as aborted', () => {
    const base = play([['routing', { elapsed_ms: 0 }, 0]])
    expect(states(applyEvent(base, 'done', { status: 'error', elapsed_ms: 10 }))).toEqual(['routing:failed'])
    expect(states(abortRunning(base, 50))).toEqual(['routing:aborted'])
  })

  it('attributes a slow rewrite to replanning, not to the preceding validating step', () => {
    const steps = play([
      ['routing', { elapsed_ms: 0, stage_ms: {} }, 0],
      ['searching', { attempt: 0, elapsed_ms: 10, stage_ms: { router: 10 } }, 10],
      ['validating', { attempt: 0, elapsed_ms: 20, stage_ms: { search: 10 } }, 20],
      ['replanning', { attempt: 1, elapsed_ms: 5400, stage_ms: { context: 100, verification: 300, replan: 5000 } }, 5400],
      ['searching', { attempt: 1, elapsed_ms: 5401, stage_ms: {} }, 5401],
    ])
    expect(steps.find(step => step.event === 'validating').durationMs).toBe(400)
    const replanning = steps.find(step => step.event === 'replanning')
    expect(replanning.state).toBe('done')
    expect(replanning.durationMs).toBe(5000)
  })

  it('falls back to event gaps when the server sends no stage_ms', () => {
    const steps = play([
      ['searching', { attempt: 0, elapsed_ms: 100 }, 0],
      ['validating', { attempt: 0, elapsed_ms: 350 }, 0],
    ])
    expect(steps[0].durationMs).toBe(250)
  })
})
