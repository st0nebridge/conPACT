/**
 * @module mod.tests.run
 * @description The turn end: a queued request is run once the turn is over,
 *              in-process, with its focus and the provenance clause as the
 *              compaction's instructions -
 *              or not run, for a reason it records. Also what the mod does
 *              when another compaction or a new session gets there first,
 *              and when a reload loses a run mid-compaction.
 */
import { expect, test } from 'claude-code/testing'
import { adopt, execute } from '../hooks/run.js'
import { PROVENANCE_CLAUSE } from '../hooks/rules.js'
import { KEPT, QUEUE, SESSION, STATE, STATUS, read, turnEnd, world } from './world.ts'

const NOW = 1_790_000_000_000

test('a queued request runs after the turn, once, with its focus', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.tool.call({ tool: QUEUE, focus: 'keep the plan' })
  await $.turn.complete(turnEnd())
  expect(w.compactions).toEqual([])            // not inside the turn's own event
  await w.clock.settle()
  // The engine marks the mod's own call trigger 'plugin'; the test host leaves it unset.
  expect(w.compactions.map((c) => c.instructions)).toEqual(['keep the plan ' + PROVENANCE_CLAUSE])
  expect(w.saved.has('request:' + SESSION)).toBe(false)
  expect(w.saved.get('result:' + SESSION)).toEqual({
    action: 'compacted', reason: '', at: NOW, started_at: NOW, focus: 'keep the plan', context_tokens: 412_880,
    min_context_tokens: null, tokens_before: 412_880, tokens_after: 37_400, attempts: 1,
  })
  expect(w.logs).toEqual([])                   // the band shows it; no line in the transcript
  expect(w.toasts).toEqual([])
  await $.turn.complete(turnEnd({ turnId: 't2' }))
  await w.clock.settle()
  expect(w.compactions.length).toBe(1)
})

test('with no focus the compaction gets only the provenance clause', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.compactions.map((c) => c.instructions)).toEqual([PROVENANCE_CLAUSE])
})

test('nothing queued, nothing run', async ($, on) => {
  const w = world(on)
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.compactions).toEqual([])
  expect(w.saved.size).toBe(0)
})

test('a subagent ending its turn, an interrupted turn and a failed turn leave the request queued', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd({ agentId: 'a1' }))
  await $.turn.complete(turnEnd({ reason: 'aborted', isAborted: true }))
  await $.turn.complete(turnEnd({ reason: 'error' }))
  await w.clock.settle()
  expect(w.compactions).toEqual([])
  expect((w.saved.get('request:' + SESSION) as any).state).toBe('queued')
})

test('below the request\'s minimum nothing is compacted, and the request is spent', async ($, on) => {
  const w = world(on, { tokens: 120_000, now: NOW })
  await $.tool.call({ tool: QUEUE, min_context_tokens: 150_000 })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.compactions).toEqual([])
  expect(w.saved.has('request:' + SESSION)).toBe(false)
  expect(w.saved.get('result:' + SESSION)).toMatchObject({
    action: 'below_threshold', reason: 'context 120000 tokens < minimum 150000; not compacting',
    context_tokens: 120_000, min_context_tokens: 150_000,
  })
  expect(w.logs).toEqual([])
  expect(w.toasts).toEqual([])
})

test('the user\'s default minimum applies when the request sets none', async ($, on) => {
  const w = world(on, { tokens: 120_000, files: { [STATE + '/settings.json']: '{"closure_min_context_tokens": 200000}' } })
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.compactions).toEqual([])
  expect((w.saved.get('result:' + SESSION) as any).min_context_tokens).toBe(200_000)
})

test('a request\'s own minimum wins over the default', async ($, on) => {
  const w = world(on, { tokens: 120_000, files: { [STATE + '/settings.json']: '{"closure_min_context_tokens": 200000}' } })
  await $.tool.call({ tool: QUEUE, min_context_tokens: 100_000 })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.compactions.length).toBe(1)
})

test('a minimum that cannot be checked does not compact', async ($, on) => {
  const w = world(on, { tokens: null })
  await $.tool.call({ tool: QUEUE, min_context_tokens: 5 })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.compactions).toEqual([])
  expect((w.saved.get('result:' + SESSION) as any).action).toBe('error')
  expect(w.toasts).toEqual(['compaction failed: context size could not be measured; not compacting'])
})

test('a compaction another mod vetoes is recorded as skipped', async ($, on) => {
  const w = world(on, { compact: () => ({ skip: 'not now' }) })
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.saved.get('result:' + SESSION)).toMatchObject({ action: 'skipped', reason: 'not now' })
  expect(w.logs).toEqual([])
  expect(w.toasts).toEqual([])
  expect(w.saved.has('request:' + SESSION)).toBe(false)
})

test('a compaction refused because the session is busy waits for the next turn end', async ($, on) => {
  let refusals = 1
  const w = world(on, { compact: () => (refusals-- > 0 ? 'reject' : { messages: KEPT, tokensBefore: 9, tokensAfter: 1 }) })
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.saved.get('request:' + SESSION)).toMatchObject({ state: 'queued', attempts: 1 })
  expect((w.saved.get('request:' + SESSION) as any).reason).toMatch(/\S/)
  await $.turn.complete(turnEnd({ turnId: 't2' }))
  await w.clock.settle()
  expect(w.saved.get('result:' + SESSION)).toMatchObject({ action: 'compacted', tokens_before: 9, tokens_after: 1, attempts: 2 })
})

test('a compaction that keeps failing gives up after three tries and says so', async ($, on) => {
  const w = world(on, { compact: () => 'reject' })
  await $.tool.call({ tool: QUEUE })
  for (const turnId of ['t1', 't2', 't3', 't4']) {
    await $.turn.complete(turnEnd({ turnId }))
    await w.clock.settle()
  }
  expect(w.compactions.length).toBe(3)
  expect(w.saved.has('request:' + SESSION)).toBe(false)
  expect(w.saved.get('result:' + SESSION)).toMatchObject({ action: 'error', attempts: 3 })
  expect(w.toasts.length).toBe(1)
  expect(w.toasts[0]).toMatch(/^compaction failed: \S/)
})

test('a request withdrawn before its run starts is not run', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await $.tool.call({ tool: 'mcp__conpact__cancel_compaction' })
  await w.clock.settle()
  expect(w.compactions).toEqual([])
})

test('a run is for the session that queued it, even if the id has moved on', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  w.id = 'another-session'
  await w.clock.settle()
  expect(w.compactions).toEqual([])
  expect(w.saved.has('request:' + SESSION)).toBe(true)
})

test('a request left running by a reload is run again once it is stale, and not before', async ($, on) => {
  const w = world(on, { now: NOW })
  w.saved.set('request:' + SESSION, { state: 'executing', focus: '', min_context_tokens: null, requested_at: NOW - 1, started_at: NOW - 60_000, attempts: 1 })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.compactions).toEqual([])
  await w.clock.advance(10 * 60_000)
  await $.turn.complete(turnEnd({ turnId: 't2' }))
  await w.clock.settle()
  expect(w.compactions.length).toBe(1)
})

// A reload mid-run: the run went with the old load, the request is still marked running.
const LOST = { state: 'executing', focus: 'keep the plan', min_context_tokens: 150_000, requested_at: NOW - 70_000,
  started_at: NOW - 65_000, attempts: 1 }

for (const trigger of ['manual', 'plugin', 'auto']) {
  test(`the ${trigger} compaction a run lost in a reload started ends its request, and is not run again`, async ($, on) => {
    const w = world(on, { now: NOW })
    w.saved.set('request:' + SESSION, LOST)
    expect(await $.session.compact({ trigger, messages: KEPT })).toEqual({ messages: KEPT, tokensBefore: 412_880, tokensAfter: 37_400 })
    expect(w.saved.has('request:' + SESSION)).toBe(false)
    expect(w.saved.get('result:' + SESSION)).toEqual({
      action: 'compacted', reason: '', tokens_before: 412_880, tokens_after: 37_400, at: NOW, started_at: NOW - 65_000,
      focus: 'keep the plan', context_tokens: null, min_context_tokens: 150_000, attempts: 1,
    })
    expect(w.logs).toEqual([])
    await w.clock.advance(10 * 60_000)
    await $.turn.complete(turnEnd())
    await w.clock.settle()
    expect(w.compactions.length).toBe(1)        // only the one adopted
  })
}

test('a lost run\'s compaction that reports no sizes is recorded without them', async ($, on) => {
  const w = world(on, { now: NOW, compact: () => ({ messages: KEPT }) })
  const { min_context_tokens: _, ...rest } = LOST
  w.saved.set('request:' + SESSION, rest)
  await $.session.compact({ trigger: 'manual', messages: KEPT })
  expect(w.saved.get('result:' + SESSION)).toMatchObject({ action: 'compacted', tokens_before: null, tokens_after: null,
    min_context_tokens: null })
})

test('a precompute, a subagent\'s or a vetoed compaction leaves a lost run\'s request; a plugin\'s spends no queued one', async ($, on) => {
  const w = world(on, { now: NOW, compact: (e) => (e.trigger === 'manual' ? { skip: 'vetoed' } : { messages: KEPT }) })
  w.saved.set('request:' + SESSION, LOST)
  await $.session.compact({ trigger: 'precompute', messages: KEPT })
  await $.session.compact({ trigger: 'auto', agentId: 'a1', messages: KEPT })
  await $.session.compact({ trigger: 'manual', messages: KEPT })
  expect(w.saved.get('request:' + SESSION)).toEqual(LOST)
  expect(w.saved.has('result:' + SESSION)).toBe(false)
  const queued = { state: 'queued', focus: '', min_context_tokens: null, requested_at: NOW, attempts: 0 }
  w.saved.set('request:' + SESSION, queued)
  await $.session.compact({ trigger: 'plugin', messages: KEPT })
  expect(w.saved.get('request:' + SESSION)).toEqual(queued)
  expect(w.saved.has('result:' + SESSION)).toBe(false)
})

test('a session with no usable id adopts nothing', async ($, on) => {
  const w = world(on, { now: NOW, id: '../escape' })
  w.saved.set('request:../escape', LOST)
  await $.session.compact({ trigger: 'manual', messages: KEPT })
  expect(w.saved.get('request:../escape')).toEqual(LOST)
})

test('the mod\'s own compaction, while its run is live, is the run\'s to record, and a second run of it waits', async () => {
  const saved = new Map<string, unknown>([['request:' + SESSION, { state: 'queued', focus: '', min_context_tokens: 1,
    requested_at: NOW, attempts: 0 }]])
  const seen: unknown[] = []
  const host: any = {
    clock: { now: async () => NOW },
    session: {
      id: async () => SESSION,
      usage: async () => ({ context: { tokens: 500 } }),
      compact: async () => {
        // The engine's session.compact event for this call reaches the mod while the run is live,
        // as does a second turn end's run.
        await execute(host, SESSION)
        seen.push(await adopt(host, SESSION, { tokensBefore: 1, tokensAfter: 1 }), saved.get('request:' + SESSION))
        return { tokensBefore: 500, tokensAfter: 40 }
      },
    },
    store: { get: async (k: string) => saved.get(k), set: async (k: string, v: unknown) => { saved.set(k, v) },
      delete: async (k: string) => { saved.delete(k) } },
    ui: { changed: () => {}, toast: () => {} },
  }
  await execute(host, SESSION)
  expect(seen).toEqual([false, { state: 'executing', focus: '', min_context_tokens: 1, requested_at: NOW, started_at: NOW,
    attempts: 1 }])
  expect(saved.get('result:' + SESSION)).toMatchObject({ action: 'compacted', tokens_before: 500, tokens_after: 40,
    context_tokens: 500 })
  // Once the run has ended, a compaction finds nothing of the run's to adopt,
  expect(await adopt(host, SESSION, {})).toBe(false)
  // and a request left running by an earlier load is adopted, which it says.
  saved.set('request:' + SESSION, { state: 'executing', started_at: NOW - 1, attempts: 1 })
  expect(await adopt(host, SESSION, {})).toBe(true)
  expect(saved.has('request:' + SESSION)).toBe(false)
})

test('a manual or automatic compaction before the run supersedes the request', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.tool.call({ tool: QUEUE })
  await $.session.compact({ trigger: 'auto', messages: KEPT })
  expect(w.saved.has('request:' + SESSION)).toBe(false)
  expect(w.saved.get('result:' + SESSION)).toMatchObject({
    action: 'superseded', reason: 'the session was compacted (auto) before the queued compaction ran',
  })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.compactions.length).toBe(1)          // only the auto one itself
})

test('a precompute, a subagent\'s compaction or a vetoed one leaves the request alone', async ($, on) => {
  const w = world(on, { compact: (e) => (e.trigger === 'manual' ? { skip: 'vetoed' } : { messages: KEPT }) })
  await $.tool.call({ tool: QUEUE })
  await $.session.compact({ trigger: 'precompute', messages: KEPT })
  await $.session.compact({ trigger: 'auto', agentId: 'a1', messages: KEPT })
  await $.session.compact({ trigger: 'manual', messages: KEPT })
  expect((w.saved.get('request:' + SESSION) as any).state).toBe('queued')
})

test('a session that starts keeps its queued request, and old records are cleared', async ($, on) => {
  const w = world(on, { now: NOW })
  const week = 7 * 24 * 3600 * 1000
  w.saved.set('request:' + SESSION, { state: 'queued', focus: '', min_context_tokens: null, requested_at: NOW - 1000, attempts: 0 })
  w.saved.set('request:old', { state: 'queued', focus: '', min_context_tokens: null, requested_at: NOW - week - 1, attempts: 0 })
  w.saved.set('result:old', { action: 'compacted', reason: '', at: NOW - week - 1 })
  w.saved.set('result:recent', { action: 'compacted', reason: '', at: NOW - week + 1 })
  w.saved.set('result:broken', 'not a record')
  w.saved.set('running:old', { started_at: NOW - week - 1 })
  w.saved.set('running:recent', { started_at: NOW - week + 1 })
  w.saved.set('running:broken', 3)
  w.saved.set('unrelated', 1)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: 'C:/work/project' })
  expect([...w.saved.keys()].sort()).toEqual(['request:' + SESSION, 'result:recent', 'running:recent', 'unrelated'])
})

test('every hook hands back what Claude Code answered', async ($, on) => {
  const w = world(on)
  expect(await $.session.start({ surface: 'terminal', isInteractive: true, cwd: 'C:/work/project' }))
    .toEqual({ cwd: 'C:/work/project' })
  expect(await $.turn.complete(turnEnd())).toEqual({ text: '' })
  await $.tool.call({ tool: QUEUE })
  expect(await $.turn.complete(turnEnd({ agentId: 'a1' }))).toEqual({ text: '' })
  expect(await $.turn.complete(turnEnd({ turnId: 't2' }))).toEqual({ text: '' })
  expect(await $.session.compact({ trigger: 'auto', messages: KEPT })).toEqual({ messages: KEPT, tokensBefore: 412_880, tokensAfter: 37_400 })
  expect(await $.session.compact({ trigger: 'precompute', messages: KEPT })).toEqual({ messages: KEPT, tokensBefore: 412_880, tokensAfter: 37_400 })
  await w.clock.settle()
})

test('a session that starts with nothing queued keeps nothing', async ($, on) => {
  const w = world(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: 'C:/work/project' })
  expect([...w.saved.keys()]).toEqual([])
})

test('a manual compaction supersedes the request too', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: QUEUE })
  await $.session.compact({ trigger: 'manual', messages: KEPT })
  expect(w.saved.get('result:' + SESSION)).toMatchObject({ action: 'superseded' })
  expect(w.saved.has('request:' + SESSION)).toBe(false)
})

test('a compaction with nothing queued records nothing', async ($, on) => {
  const w = world(on)
  await $.session.compact({ trigger: 'auto', messages: KEPT })
  expect(w.saved.size).toBe(0)
})

test('a compaction that reports no sizes is shown as compacted', async ($, on) => {
  const w = world(on, { compact: () => ({ messages: KEPT }) })
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.logs).toEqual([])
  expect(w.saved.get('result:' + SESSION)).toMatchObject({ action: 'compacted', tokens_before: 412_880, tokens_after: null })
})

test('status after a run shows the result and no request', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  const { data } = read(await $.tool.call({ tool: STATUS }))
  expect(data.pending).toBe(false)
  expect(data.last.action).toBe('compacted')
})
