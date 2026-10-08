/**
 * @module mod.tests.rules
 * @description The rules the mod shares with conPACT's Python side, checked
 *              value by value: the focus line, the minimum context size, a
 *              plain session id, a throwaway worktree session, the user's
 *              settings, the early toast's hold, when a turn-end
 *              compaction goes ahead, and which files the mod may write.
 */
import { expect, test } from 'claude-code/testing'
import {
  ATTEMPTS, KEEP_MS, MAX_CONTEXT_TOKENS, MAX_FOCUS_CHARS, STALE_RUN_MS, checkMinimum, decide, holdMinutesLeft, isSessionId, isSpinOff,
  isWritable,
  normalizeFocus, readSettings, roundHalfEven, thousands, unexpected,
} from '../hooks/rules.js'

test('the limits are what the pages say they are', async () => {
  expect(STALE_RUN_MS).toBe(600_000)
  expect(ATTEMPTS).toBe(3)
  expect(KEEP_MS).toBe(604_800_000)
})

test('the focus is one printable line of at most 500 characters', async () => {
  expect(MAX_FOCUS_CHARS).toBe(500)
  expect(normalizeFocus('  keep\tthe\nplan  ')).toBe('keep the plan')
  expect(normalizeFocus('a\u0000b\u2028c\u00a0d')).toBe('a b c d')
  expect(normalizeFocus('x'.repeat(501))).toBe('x'.repeat(500))
  expect(normalizeFocus('x'.repeat(499) + ' y')).toBe('x'.repeat(499))
  expect(normalizeFocus('😀'.repeat(501))).toBe('😀'.repeat(500))
  expect(normalizeFocus(undefined)).toBe('')
  expect(normalizeFocus(42)).toBe('')
})

test('a minimum is absent or a whole number of tokens from 1 to ten million', async () => {
  expect(MAX_CONTEXT_TOKENS).toBe(10_000_000)
  expect(checkMinimum(undefined)).toEqual({ minimum: null })
  expect(checkMinimum(null)).toEqual({ minimum: null })
  expect(checkMinimum(1)).toEqual({ minimum: 1 })
  expect(checkMinimum(10_000_000)).toEqual({ minimum: 10_000_000 })
  for (const bad of [0, -5, 10_000_001, 1.5, '100', true, Number.NaN]) {
    expect(checkMinimum(bad)).toEqual({ error: 'min_context_tokens must be a whole number from 1 to 10000000' })
  }
})

test('a session id is plain: letters, digits, dash and underscore, at most 128', async () => {
  expect(isSessionId('0b6e4d6f-e5a9-441e-4c56-5248db621442')).toBe(true)
  expect(isSessionId('a_b')).toBe(true)
  expect(isSessionId('a'.repeat(128))).toBe(true)
  expect(isSessionId('a'.repeat(129))).toBe(false)
  expect(isSessionId('')).toBe(false)
  expect(isSessionId('../x')).toBe(false)
  expect(isSessionId(undefined)).toBe(false)
})

test('a throwaway session is one inside a checkout under .claude/worktrees', async () => {
  expect(isSpinOff('C:\\dev\\app\\.claude\\worktrees\\eager-shannon')).toBe(true)
  expect(isSpinOff('/home/u/app/.Claude/WorkTrees/x/src')).toBe(true)
  expect(isSpinOff('.claude/worktrees/x')).toBe(true)
  expect(isSpinOff('C:/dev/app/.claude/worktrees')).toBe(false)
  expect(isSpinOff('C:/dev/app/.claude/x/worktrees/y')).toBe(false)
  expect(isSpinOff('C:/dev/app')).toBe(false)
  expect(isSpinOff(undefined)).toBe(false)
})

test('the settings the mod reads, with a value out of range ignored as the Python side does', async () => {
  expect(readSettings(undefined)).toEqual({ closureMinimum: null, guardSpinOff: true })
  expect(readSettings('not json')).toEqual({ closureMinimum: null, guardSpinOff: true })
  expect(readSettings('[1]')).toEqual({ closureMinimum: null, guardSpinOff: true })
  expect(readSettings('{"closure_min_context_tokens": 150000, "guard_spin_off_sessions": false}'))
    .toEqual({ closureMinimum: 150_000, guardSpinOff: false })
  expect(readSettings('{"closure_min_context_tokens": 0, "guard_spin_off_sessions": "no"}'))
    .toEqual({ closureMinimum: null, guardSpinOff: true })
  expect(readSettings('{"closure_min_context_tokens": null}')).toEqual({ closureMinimum: null, guardSpinOff: true })
})

test('minutes left on a hold round as Python rounds, and an expired or broken hold is none', async () => {
  const now = 1_000_000_000_000
  const at = (seconds: number) => JSON.stringify({ until: now / 1000 + seconds })
  expect(holdMinutesLeft(at(30 * 60), now)).toBe(30)
  expect(holdMinutesLeft(at(90), now)).toBe(2)
  expect(holdMinutesLeft(at(150), now)).toBe(2)
  expect(holdMinutesLeft(at(20), now)).toBe(0)
  expect(holdMinutesLeft(at(0.5), now)).toBe(0)
  expect(holdMinutesLeft(at(0), now)).toBe(null)
  expect(holdMinutesLeft(at(-60), now)).toBe(null)
  expect(holdMinutesLeft('{"until": true}', now)).toBe(null)
  expect(holdMinutesLeft('{"until": "soon"}', now)).toBe(null)
  expect(holdMinutesLeft('[]', now)).toBe(null)
  expect(holdMinutesLeft('nope', now)).toBe(null)
  expect(holdMinutesLeft(undefined, now)).toBe(null)
})

test('halves round to the even neighbour', async () => {
  expect(roundHalfEven(0.5)).toBe(0)
  expect(roundHalfEven(1.5)).toBe(2)
  expect(roundHalfEven(2.5)).toBe(2)
  expect(roundHalfEven(2.4)).toBe(2)
  expect(roundHalfEven(2.6)).toBe(3)
})

test('the arguments a tool does not take are named, sorted', async () => {
  expect(unexpected({ focus: 'x', session: 's', agent: 1 }, ['focus'])).toEqual(['agent', 'session'])
  expect(unexpected({}, [])).toEqual([])
})

test('a token count reads with thousands separators', async () => {
  expect(thousands(412880)).toBe('412,880')
  expect(thousands(999)).toBe('999')
  expect(thousands(1_000_000)).toBe('1,000,000')
})

test('a turn-end compaction goes ahead unless a minimum says no or cannot be checked', async () => {
  expect(decide(500, null)).toBe(null)
  expect(decide(null, null)).toBe(null)
  expect(decide(500, 500)).toBe(null)
  expect(decide(499, 500)).toEqual({ action: 'below_threshold', reason: 'context 499 tokens < minimum 500; not compacting' })
  expect(decide(null, 500)).toEqual({ action: 'error', reason: 'context size could not be measured; not compacting' })
})

test('the mod may write only a session\'s beat or answer under ~/.conpact/mod/', () => {
  for (const path of ['C:/Users/a/.conpact/mod/beat/s1.json', 'C:\\Users\\a\\.conpact\\mod\\answer\\s-1_x.json',
    '/home/a/.conpact/mod/beat/' + 'x'.repeat(128) + '.json']) {
    expect(isWritable(path)).toBe(true)
  }
  for (const path of ['C:/Users/a/.conpact/mod/ask/s1.json', 'C:/Users/a/.conpact/settings.json',
    'C:/Users/a/.conpact/mod/beat/s1.json.bak', 'C:/Users/a/.conpact/mod/beat/a/../s1.json',
    'C:/Users/../a/.conpact/mod/beat/s1.json', '../.conpact/mod/beat/s1.json',
    'C:/Users/a/.conpact/mod/beat/.json', 'C:/Users/a/x.conpact/mod/beat/s1.json',
    '/home/a/.conpact/mod/beat/' + 'x'.repeat(129) + '.json', 'C:/Users/a/.conpact/mod/beat/s 1.json',
    undefined, null, 7]) {
    expect(isWritable(path as any)).toBe(false)
  }
})
