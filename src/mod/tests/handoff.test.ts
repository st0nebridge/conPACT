/**
 * @module mod.tests.handoff
 * @description The idle toast's way in: the mod's beat, and a request the
 *              watcher leaves in ~/.conpact/mod/ask/ - taken once, never once
 *              it has lapsed, the session compacted for it and the outcome
 *              answered beside it.
 */
import { expect, test } from 'claude-code/testing'
import { claim, readAsk } from '../hooks/handoff.js'
import { HOME, QUEUE, SESSION, STATE, turnEnd, world } from './world.ts'

const NOW = 1_790_000_000_000
const SECONDS = NOW / 1000
const BEAT = STATE + '/mod/beat/' + SESSION + '.json'
const ASK = STATE + '/mod/ask/' + SESSION + '.json'
const ANSWER = STATE + '/mod/answer/' + SESSION + '.json'
const START = { surface: 'terminal', isInteractive: true, cwd: 'C:/work/project' }
const END = { reason: 'exit', sessionId: SESSION }

function ask(fields: Record<string, unknown> = {}) {
  return JSON.stringify({ session_id: SESSION, request_id: 'r1', requested_at: SECONDS, expires_at: SECONDS + 10, ...fields })
}

function json(w: any, path: string) {
  return JSON.parse(w.files.get(path.replace(/^[A-Za-z]:/, '')))
}

test('readAsk takes this session\'s well-formed request until it lapses', () => {
  expect(readAsk(ask(), SESSION, NOW)).toEqual({ request_id: 'r1' })
  expect(readAsk(ask(), SESSION, NOW + 10_000)).toEqual({ request_id: 'r1' })   // the lapse itself is still in time
  expect(readAsk(ask(), SESSION, NOW + 10_001)).toBe(null)
  expect(readAsk(ask({ session_id: 'other' }), SESSION, NOW)).toBe(null)
  for (const request_id of ['', 'a/b', 'a b', 7, null, 'x'.repeat(65)]) {
    expect(readAsk(ask({ request_id }), SESSION, NOW)).toBe(null)
  }
  expect(readAsk(ask({ request_id: 'x'.repeat(64) }), SESSION, NOW)).toEqual({ request_id: 'x'.repeat(64) })
  expect(readAsk(ask({ expires_at: '1' }), SESSION, NOW)).toBe(null)
  for (const text of [undefined, '', 'not json', '[]', 'null', '"r1"']) expect(readAsk(text, SESSION, NOW)).toBe(null)
})

test('a starting session beats at once and every thirty seconds, and says when it ends', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.session.start(START)
  expect(json(w, BEAT)).toEqual({ session_id: SESSION, at: SECONDS, ended: false })
  await w.clock.advance(29_999)
  expect(json(w, BEAT).at).toBe(SECONDS)
  await w.clock.advance(1)
  expect(json(w, BEAT).at).toBe(SECONDS + 30)
  await $.session.end(END)
  expect(json(w, BEAT)).toEqual({ session_id: SESSION, at: SECONDS + 30, ended: true })
})

test('a session whose id is not plain neither beats nor looks for requests', async ($, on) => {
  const w = world(on, { id: '../x', now: NOW })
  await $.session.start(START)
  await w.clock.advance(60_000)
  expect([...w.files.keys()]).toEqual([])
})

test('a request is taken within two seconds, the session compacted, and the outcome answered', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.session.start(START)
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), ask())
  await w.clock.advance(1_999)
  expect(w.compactions).toEqual([])
  await w.clock.advance(1)
  expect(w.compactions).toEqual([{ instructions: undefined, trigger: undefined }])
  expect(json(w, ANSWER)).toEqual({
    session_id: SESSION, request_id: 'r1', at: SECONDS + 2, action: 'compacted', reason: '',
    tokens_before: 412_880, tokens_after: 37_400,
  })
  expect(w.saved.get('handoff:' + SESSION)).toEqual({ request_id: 'r1', at: NOW + 2_000 })
  // Its outcome is the session's last result, for the band; the running mark is gone.
  expect(w.saved.get('result:' + SESSION)).toEqual({ action: 'compacted', reason: '', tokens_before: 412_880,
    tokens_after: 37_400, at: NOW + 2_000, started_at: NOW + 2_000, via: 'idle toast' })
  expect(w.saved.has('running:' + SESSION)).toBe(false)
  expect(w.logs).toEqual([])
  // The ask is still there - a mod cannot delete it - and is not taken again.
  await w.clock.advance(6_000)
  expect(w.compactions.length).toBe(1)
})

test('the answer says claimed, and the band shows it running, while the compaction runs', async ($, on) => {
  let seen: any
  let mark: any
  const w = world(on, {
    now: NOW,
    compact: () => {
      seen = json(w, ANSWER)
      mark = w.saved.get('running:' + SESSION)
      return { messages: [], tokensBefore: 10, tokensAfter: 5 }
    },
  })
  await $.session.start(START)
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), ask())
  await w.clock.advance(2_000)
  expect(seen).toEqual({ session_id: SESSION, request_id: 'r1', at: SECONDS + 2, action: 'claimed' })
  expect(mark).toEqual({ started_at: NOW + 2_000 })
})

test('a new request id is taken again; a lapsed one never is', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.session.start(START)
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), ask())
  await w.clock.advance(2_000)
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), ask({ request_id: 'r2' }))
  await w.clock.advance(2_000)
  expect(w.compactions.length).toBe(2)
  expect(json(w, ANSWER).request_id).toBe('r2')
  // at SECONDS + 6: lapsed a second ago
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), ask({ request_id: 'r3', expires_at: SECONDS + 5 }))
  await w.clock.advance(2_000)
  expect(w.compactions.length).toBe(2)
})

test('a compaction refused while a turn runs is answered as an error, and shown', async ($, on) => {
  const w = world(on, { now: NOW, compact: () => 'reject' })
  await $.session.start(START)
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), ask())
  await w.clock.advance(2_000)
  const answered = json(w, ANSWER)
  expect(answered).toMatchObject({ request_id: 'r1', action: 'error' })
  expect(answered.reason).toMatch(/\S/)                      // the test host words the refusal its own way
  expect(w.toasts).toEqual(['compaction failed: ' + answered.reason])
  expect(w.saved.get('result:' + SESSION)).toMatchObject({ action: 'error', reason: answered.reason, via: 'idle toast' })
})

test('a skipped compaction is answered as skipped', async ($, on) => {
  const w = world(on, { now: NOW, compact: () => ({ skip: 'not now' }) })
  await $.session.start(START)
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), ask())
  await w.clock.advance(2_000)
  expect(json(w, ANSWER)).toMatchObject({ action: 'skipped', reason: 'not now' })
  expect(w.logs).toEqual([])
})

test('another session\'s ask is not taken', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.session.start(START)
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), ask({ session_id: 'someone-else' }))
  await w.clock.advance(4_000)
  expect(w.compactions).toEqual([])
  expect(w.files.has(ANSWER.replace(/^[A-Za-z]:/, ''))).toBe(false)
})

test('an agent\'s queued request stays queued through an idle compaction', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.session.start(START)
  await $.tool.call({ tool: QUEUE })
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), ask())
  await w.clock.advance(2_000)
  expect((w.saved.get('request:' + SESSION) as any).state).toBe('queued')
  expect((w.saved.get('result:' + SESSION) as any).via).toBe('idle toast')
  // and that request still runs at its own turn end
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.compactions.length).toBe(2)
})

test('the mod writes only beats and answers, and only under ~/.conpact/mod/', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.session.start(START)
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), ask())
  await w.clock.advance(31_000)
  await $.session.end(END)
  const written = [...w.files.keys()].filter((path) => path !== ASK.replace(/^[A-Za-z]:/, '')).sort()
  expect(written).toEqual([ANSWER, BEAT].map((p) => p.replace(/^[A-Za-z]:/, '')).sort())
})

test('a week-old record of a taken request is cleared when a session starts', async ($, on) => {
  const w = world(on, { now: NOW })
  w.saved.set('handoff:old', { request_id: 'r0', at: NOW - 8 * 24 * 3600 * 1000 })
  w.saved.set('handoff:new', { request_id: 'r9', at: NOW - 1000 })
  await $.session.start(START)
  expect(w.saved.has('handoff:old')).toBe(false)
  expect(w.saved.has('handoff:new')).toBe(true)
})

test('a home with .. in it is written nothing: the host refuses the path', async ($, on) => {
  const w = world(on, { now: NOW, env: { USERPROFILE: 'C:/Users/../someone' } })
  await $.session.start(START)
  await w.clock.advance(31_000)
  expect([...w.files.keys()]).toEqual([])
})

test('claim answers null, not just nothing, for no request, a lapsed one and one already taken', async () => {
  // A plain object of the calls register.js lends, as host() builds it.
  const files = new Map<string, string>()
  const saved = new Map<string, unknown>()
  const host = {
    env: { get: async (name: string) => (name === 'USERPROFILE' ? HOME : undefined) },
    fs: { read: async (path: string) => { if (!files.has(path)) throw new Error('ENOENT'); return files.get(path) } },
    store: { get: async (key: string) => saved.get(key), set: async (key: string, value: unknown) => { saved.set(key, value) } },
  }
  expect(await claim(host, SESSION, NOW)).toBe(null)
  files.set(ASK, ask())
  expect(await claim(host, SESSION, NOW + 10_001)).toBe(null)
  expect(await claim(host, SESSION, NOW)).toEqual({ request_id: 'r1' })
  expect(await claim(host, SESSION, NOW)).toBe(null)
})
