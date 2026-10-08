/**
 * @module mod.tests.sdk
 * @description A session with no terminal behind it - the desktop app's Code
 *              tab, the Agent SDK, a -p run - where Claude Code refuses a
 *              mod's in-process compaction. There the mod runs /compact as
 *              the person would, the request's focus as its text, and reads
 *              the outcome from the compaction that command makes.
 */
import { expect, test } from 'claude-code/testing'
import { KEPT, QUEUE, SESSION, STATE, turnEnd, world } from './world.ts'

const NOW = 1_790_000_000_000
const SECONDS = NOW / 1000
const SDK = { surface: null, isInteractive: false, cwd: 'C:/work/project' }
const TERMINAL = { surface: 'terminal', isInteractive: true, cwd: 'C:/work/project' }
const ASK = STATE + '/mod/ask/' + SESSION + '.json'
const ANSWER = STATE + '/mod/answer/' + SESSION + '.json'

function json(w: any, path: string) {
  return JSON.parse(w.files.get(path.replace(/^[A-Za-z]:/, '')))
}

/**
 * /compact as the engine runs it: the command waits until the test plays the
 * engine (`w.engine($)`), which compacts with the trigger `manual` and then
 * answers the command - with its own line when it could make no compaction,
 * or, `silent`, with neither a compaction nor a line.
 * The test plays it because the test host lets a stub make no calls of its own.
 */
function sdkWorld(on: any, options: Parameters<typeof world>[1] = {}) {
  const w: any = world(on, options)
  const waiting: { e: any; resolve: (r: unknown) => void }[] = []
  on('command.run', (_$: any, e: any) => {
    w.commands.push({ command: e.command, args: e.args })
    return new Promise((resolve) => waiting.push({ e, resolve }))
  })
  w.engine = async ($: any, { silent = false } = {}) => {
    while (waiting.length > 0) {
      const { e, resolve } = waiting.shift()!
      let text = ''
      try {
        if (silent) throw new Error('compacted nothing')
        await $.session.compact({ ...(e.args ? { instructions: e.args } : {}), trigger: 'manual', messages: KEPT })
      } catch {
        text = silent ? '' : 'Not enough messages to compact.'
      }
      resolve(silent ? {} : { text })
    }
    await w.clock.settle()
  }
  return w
}

function toastAsks(w: any) {
  w.files.set(ASK.replace(/^[A-Za-z]:/, ''), JSON.stringify({
    session_id: SESSION, request_id: 'r1', requested_at: SECONDS, expires_at: SECONDS + 10,
  }))
}

test('in an SDK session a queued request runs /compact with its focus after the turn', async ($, on) => {
  const w = sdkWorld(on, { now: NOW })
  await $.session.start(SDK)
  await $.tool.call({ tool: QUEUE, focus: 'keep the plan' })
  await $.turn.complete(turnEnd())
  expect(w.commands).toEqual([])            // not inside the turn's own event
  await w.clock.settle()
  expect(w.commands).toEqual([{ command: 'compact', args: 'keep the plan' }])
  await w.engine($)
  expect(w.compactions).toEqual([{ instructions: 'keep the plan', trigger: 'manual' }])
  expect(w.saved.has('request:' + SESSION)).toBe(false)
  expect(w.saved.get('result:' + SESSION)).toEqual({
    action: 'compacted', reason: '', at: NOW, started_at: NOW, focus: 'keep the plan', context_tokens: 412_880,
    min_context_tokens: null, tokens_before: 412_880, tokens_after: 37_400, attempts: 1,
  })
  expect(w.logs).toEqual([])
  expect(w.toasts).toEqual([])
})

test('with no focus /compact runs with nothing after it', async ($, on) => {
  const w = sdkWorld(on)
  await $.session.start(SDK)
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.commands).toEqual([{ command: 'compact', args: '' }])
  await w.engine($)
  expect(w.compactions.map((c) => c.instructions)).toEqual([undefined])
})

test('a terminal session still compacts in-process and runs no command', async ($, on) => {
  const w = sdkWorld(on)
  await $.session.start(TERMINAL)
  await $.tool.call({ tool: QUEUE, focus: 'f' })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.commands).toEqual([])
  expect(w.compactions.map((c) => c.instructions)).toEqual(['f'])
  expect((w.saved.get('result:' + SESSION) as any).action).toBe('compacted')
})

test("a /compact that compacts nothing is tried at the next turn ends, then fails in the engine's words", async ($, on) => {
  const w = sdkWorld(on, { compact: () => 'reject' })
  await $.session.start(SDK)
  await $.tool.call({ tool: QUEUE })
  for (const turnId of ['t1', 't2']) {
    await $.turn.complete(turnEnd({ turnId }))
    await w.clock.settle()
    await w.engine($)
    expect((w.saved.get('request:' + SESSION) as any).state).toBe('queued')
    expect((w.saved.get('request:' + SESSION) as any).reason).toBe('Not enough messages to compact.')
  }
  await $.turn.complete(turnEnd({ turnId: 't3' }))
  await w.clock.settle()
  await w.engine($)
  expect(w.commands.length).toBe(3)
  expect(w.saved.has('request:' + SESSION)).toBe(false)
  const result = w.saved.get('result:' + SESSION) as any
  expect(result.action).toBe('error')
  expect(result.reason).toBe('Not enough messages to compact.')
  expect(w.toasts).toEqual(['compaction failed: Not enough messages to compact.'])
})

test('a hook that vetoes the /compact is recorded as skipped', async ($, on) => {
  const w = sdkWorld(on, { compact: () => ({ skip: 'not now' }) })
  await $.session.start(SDK)
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  await w.engine($)
  expect((w.saved.get('result:' + SESSION) as any).action).toBe('skipped')
  expect(w.logs).toEqual([])
})

test("the person's own /compact in an SDK session still spends a queued request", async ($, on) => {
  const w = sdkWorld(on)
  await $.session.start(SDK)
  await $.tool.call({ tool: QUEUE })
  await $.session.compact({ trigger: 'manual', messages: KEPT })
  expect(w.saved.has('request:' + SESSION)).toBe(false)
  expect((w.saved.get('result:' + SESSION) as any).action).toBe('superseded')
})

test("in an SDK session the idle toast runs /compact, and the agent's request stays queued", async ($, on) => {
  const w = sdkWorld(on, { now: NOW })
  await $.session.start(SDK)
  await $.tool.call({ tool: QUEUE, focus: 'mine' })
  toastAsks(w)
  await w.clock.advance(2_000)
  expect(w.commands).toEqual([{ command: 'compact', args: '' }])
  expect(json(w, ANSWER).action).toBe('claimed')
  await w.engine($)
  expect(json(w, ANSWER)).toEqual({
    session_id: SESSION, request_id: 'r1', at: SECONDS + 2, action: 'compacted', reason: '',
    tokens_before: 412_880, tokens_after: 37_400,
  })
  expect((w.saved.get('request:' + SESSION) as any).state).toBe('queued')
})

test('in an SDK session a toast request that compacts nothing is answered as an error', async ($, on) => {
  const w = sdkWorld(on, { now: NOW, compact: () => 'reject' })
  await $.session.start(SDK)
  toastAsks(w)
  await w.clock.advance(2_000)
  await w.engine($)
  expect(json(w, ANSWER).action).toBe('error')
  expect(json(w, ANSWER).reason).toBe('Not enough messages to compact.')
})

test('a /compact that compacts nothing and says nothing still fails, in words of the mod', async ($, on) => {
  const w = sdkWorld(on)
  await $.session.start(SDK)
  await $.tool.call({ tool: QUEUE })
  for (const turnId of ['t1', 't2', 't3']) {
    await $.turn.complete(turnEnd({ turnId }))
    await w.clock.settle()
    await w.engine($, { silent: true })
  }
  const result = w.saved.get('result:' + SESSION) as any
  expect(result.action).toBe('error')
  expect(result.reason).toBe('/compact did not compact the session')
})

test("after the mod's own /compact, the person's next /compact is theirs again", async ($, on) => {
  const w = sdkWorld(on)
  await $.session.start(SDK)
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  await w.engine($)
  expect((w.saved.get('result:' + SESSION) as any).action).toBe('compacted')
  await $.tool.call({ tool: QUEUE, focus: 'again' })
  await $.session.compact({ trigger: 'manual', messages: KEPT })
  expect(w.saved.has('request:' + SESSION)).toBe(false)
  expect((w.saved.get('result:' + SESSION) as any).action).toBe('superseded')
})
