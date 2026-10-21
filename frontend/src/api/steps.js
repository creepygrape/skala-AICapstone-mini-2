// Pure progress-step reducer so real SSE event sequences can be tested without the UI.
export const STAGE_NODES = {
  routing: ['router'],
  searching: ['search'],
  validating: ['context', 'verification'],
  replanning: ['replan'],
}

const isNum = value => Number.isFinite(value)

// Prefer the server's per-node time (stage_ms); fall back to the gap between public events.
function duration(step, data, now) {
  const stage = data?.stage_ms
  const keys = STAGE_NODES[step.event].filter(key => isNum(stage?.[key]))
  if (keys.length) return keys.reduce((sum, key) => sum + stage[key], 0)
  if (isNum(data?.elapsed_ms) && isNum(step.serverStart)) return Math.max(0, data.elapsed_ms - step.serverStart)
  return now - step.clientStart
}

function closeRunning(steps, state, data, now) {
  return steps.map(step => step.state === 'running'
    ? { ...step, state, durationMs: duration(step, data, now) } : step)
}

export function applyEvent(steps, event, data = {}, now = 0) {
  if (event in STAGE_NODES) {
    const closed = closeRunning(steps, 'done', data, now)
    const step = { event, attempt: data.attempt, state: 'running', serverStart: data.elapsed_ms,
      clientStart: now, durationMs: 0 }
    // replanning is announced after the rewrite finished: its own time is already known.
    if (event === 'replanning' && isNum(data.stage_ms?.replan)) {
      step.state = 'done'; step.durationMs = data.stage_ms.replan
    }
    return [...closed, step]
  }
  if (event === 'error') return closeRunning(steps, 'failed', data, now)
  if (event === 'done') return closeRunning(steps, data.status === 'error' ? 'failed' : 'done', data, now)
  return steps
}

// Connection loss, timeout or user cancel: nothing is known to have failed on the server.
export const abortRunning = (steps, now = 0) => closeRunning(steps, 'aborted', {}, now)

export const totalDuration = (steps, doneMs) =>
  isNum(doneMs) ? doneMs : steps.reduce((sum, step) => sum + step.durationMs, 0)
