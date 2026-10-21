import { describe, it, expect } from 'vitest'
import { createScenePlayer } from './youtube'

function fakeYT() {
  const calls = []
  const instances = []
  class Player {
    constructor(target, options) { this.options = options; this.events = options.events; instances.push(this) }
    seekTo(at, allow) { calls.push(['seekTo', at, allow]) }
    playVideo() { calls.push(['playVideo']) }
    cueVideoById(options) { calls.push(['cue', options]) }
    destroy() { calls.push(['destroy']) }
  }
  return { YT: { Player }, calls, instances }
}
const make = (fake, onChange) => createScenePlayer(fake.YT, {}, { videoId: '1HJgbE66GI4', start: 189.6, origin: 'http://localhost:5173', onChange })

describe('createScenePlayer', () => {
  it('starts at the floored start with an origin and seeks only when ready', () => {
    const fake = fakeYT()
    const scene = make(fake)
    expect(fake.instances[0].options.playerVars).toMatchObject({ start: 189, origin: 'http://localhost:5173' })
    expect(scene.seek(250)).toBe(false)
    fake.instances[0].events.onReady()
    expect(scene.seek(250.9)).toBe(true)
    expect(fake.calls).toEqual([['seekTo', 250, true], ['playVideo']])
  })

  it('moves without playing when play is false (always re-cued)', () => {
    const fake = fakeYT()
    const scene = make(fake)
    fake.instances[0].events.onReady()
    expect(scene.seek(40, false)).toBe(true)
    expect(fake.calls).toEqual([['cue', { videoId: '1HJgbE66GI4', startSeconds: 40 }]])
    fake.calls.length = 0
    fake.instances[0].events.onStateChange({ data: 1 })
    expect(scene.seek(50, false)).toBe(true)  // even while playing: re-cued, never seekTo/play
    expect(fake.calls).toEqual([['cue', { videoId: '1HJgbE66GI4', startSeconds: 50 }]])
  })
  it.each([100, 5, 153, 2])('refuses to seek after recoverable error %i so the caller falls back', code => {
    const fake = fakeYT()
    const scene = make(fake)
    fake.instances[0].events.onReady()
    fake.instances[0].events.onError({ data: code })
    expect(scene.seek(250)).toBe(false)
    expect(scene.state).toMatchObject({ failed: true, blocked: false, errorCode: code })
    expect(fake.calls).toEqual([])
  })

  it.each([101, 150])('destroys the player and reports blocked on %i', code => {
    const fake = fakeYT()
    const changes = []
    const scene = make(fake, change => changes.push(change))
    fake.instances[0].events.onReady()
    fake.instances[0].events.onError({ data: code })
    expect(fake.calls).toEqual([['destroy']])
    expect(changes.at(-1)).toMatchObject({ blocked: true, ready: false, errorCode: code })
    expect(scene.seek()).toBe(false)
  })

  it('recovers only after playback is confirmed', () => {
    const fake = fakeYT()
    const scene = make(fake)
    fake.instances[0].events.onReady()
    fake.instances[0].events.onError({ data: 100 })
    fake.instances[0].events.onStateChange({ data: 3 })
    expect(scene.seek()).toBe(false)
    fake.instances[0].events.onStateChange({ data: 1 })
    expect(scene.state).toMatchObject({ failed: false, errorCode: null })
    expect(scene.seek(10)).toBe(true)
  })

  it('does not recover from a blocked player', () => {
    const fake = fakeYT()
    const scene = make(fake)
    fake.instances[0].events.onError({ data: 150 })
    fake.instances[0].events.onStateChange({ data: 1 })
    expect(scene.state.blocked).toBe(true)
  })
})
