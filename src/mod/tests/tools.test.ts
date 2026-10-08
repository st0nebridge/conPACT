/**
 * @module mod.tests.tools
 * @description The three conPACT tools the mod answers in the MCP server's
 *              place - queue, cancel, status - fired as Claude would call them:
 *              what the model reads back, and what is kept for the turn end.
 *              The fourth tool, the early toast's hold, is left to the server.
 */
import { expect, test } from 'claude-code/testing'
import { CANCEL, HOME, QUEUE, SESSION, STATE, STATUS, read, world } from './world.ts'

const REFUSAL = 'Nothing was queued: this session is working in a .claude/worktrees/... checkout, which is a '
  + 'throwaway spin-off. Those are merged and archived rather than resumed, so the summary a '
  + 'compaction writes here is never read and the compaction spends a turn on nothing. This is not '
  + 'an error and there is nothing to retry: finish your answer, and say in one clause that you '
  + 'skipped the compaction because this is a spin-off session. (The user can turn this off in the '
  + 'conPACT settings.)'

test('queue keeps one request for this session and says when it runs', async ($, on) => {
  const w = world(on)
  const answer = await $.tool.call({ tool: QUEUE, focus: '  keep the\nplan ', min_context_tokens: 300_000 })
  expect(answer.result.map((block: any) => block.type)).toEqual(['text', 'text'])
  const { text, data } = read(answer)
  expect(data).toEqual({
    queued: true, replaced: false, session_id: SESSION, focus: 'keep the plan',
    min_context_tokens: 300_000, context_tokens: 412_880, transport: 'mod',
  })
  expect(text).toBe('Compaction queued for this session. It runs at the end of this turn, after your final '
    + 'answer, only if the context is then at least 300000 tokens. The context is about 412880 tokens now. '
    + 'Finish your answer normally; do not call this again.')
  expect(w.saved.get('request:' + SESSION)).toEqual({
    state: 'queued', focus: 'keep the plan', min_context_tokens: 300_000, requested_at: 1_790_000_000_000, attempts: 0,
  })
})

test('queuing again replaces the request rather than adding one', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: QUEUE, focus: 'first' })
  const { text, data } = read(await $.tool.call({ tool: QUEUE }))
  expect(data.replaced).toBe(true)
  expect(data.focus).toBe('')
  expect(data.min_context_tokens).toBe(null)
  expect(text).toMatch(/This replaced the request that was already queued\. Finish/)
  expect(text).toMatch(/after your final answer\. The context/)
  expect([...w.saved.keys()]).toEqual(['request:' + SESSION])
  expect((w.saved.get('request:' + SESSION) as any).focus).toBe('')
})

test('an unmeasured context is left out of the words', async ($, on) => {
  world(on, { tokens: null })
  const { text, data } = read(await $.tool.call({ tool: QUEUE }))
  expect(data.context_tokens).toBe(null)
  expect(text).toBe('Compaction queued for this session. It runs at the end of this turn, after your final '
    + 'answer. Finish your answer normally; do not call this again.')
})

test('a throwaway worktree session is refused in words, not as an error', async ($, on) => {
  const w = world(on, { cwd: 'C:/dev/app/.claude/worktrees/eager-shannon' })
  const { text, data } = read(await $.tool.call({ tool: QUEUE, focus: 'x' }))
  expect(data).toEqual({
    queued: false, replaced: false, session_id: SESSION, focus: 'x', min_context_tokens: null,
    context_tokens: 412_880, transport: 'mod',
  })
  expect(text).toBe(REFUSAL)
  expect(w.saved.size).toBe(0)
})

test('the worktree refusal is one setting away from off', async ($, on) => {
  const w = world(on, {
    cwd: 'C:/dev/app/.claude/worktrees/eager-shannon',
    files: { [STATE + '/settings.json']: '{"guard_spin_off_sessions": false}' },
  })
  expect(read(await $.tool.call({ tool: QUEUE })).data.queued).toBe(true)
  expect(w.saved.has('request:' + SESSION)).toBe(true)
})

test('a bad focus, a bad minimum or a target argument is refused and nothing is kept', async ($, on) => {
  const w = world(on)
  const tooLong = await $.tool.call({ tool: QUEUE, focus: 'x'.repeat(501) })
  const notText = await $.tool.call({ tool: QUEUE, focus: 7 })
  const badMinimum = await $.tool.call({ tool: QUEUE, min_context_tokens: 0 })
  const target = await $.tool.call({ tool: QUEUE, session_id: 'someone-else', focus: 'x' })
  expect(tooLong).toEqual({ deny: 'focus must be text of at most 500 characters. Nothing was queued.' })
  expect(notText).toEqual({ deny: 'focus must be text of at most 500 characters. Nothing was queued.' })
  expect(badMinimum).toEqual({ deny: 'min_context_tokens must be a whole number from 1 to 10000000. Nothing was queued.' })
  expect(target).toEqual({ deny: 'Unexpected argument(s): session_id. This tool never takes a target session - '
    + 'it always acts on the session that called it. Nothing was queued.' })
  expect(w.saved.size).toBe(0)
})

test('what Claude Code adds to a call is not taken for an argument', async ($, on) => {
  world(on)
  const fromSubagent = read(await $.tool.call({ tool: QUEUE, agentId: 'a1', consent: 'the user asked' }))
  expect(fromSubagent.data.queued).toBe(true)
})

test('a session with no id at all is refused, named as the server names it', async ($, on) => {
  world(on, { id: null })
  expect(await $.tool.call({ tool: STATUS })).toEqual({
    deny: 'This session has no usable session id (None). Nothing was changed. Tell the user and stop.',
  })
})

test('status takes no arguments either', async ($, on) => {
  world(on)
  expect(await $.tool.call({ tool: STATUS, session_id: 'x' })).toEqual({
    deny: 'Unexpected argument(s): session_id. This tool never takes a target session - it always acts on the '
      + 'session that called it. Nothing was changed.',
  })
})

test('a session with no usable id is refused', async ($, on) => {
  const w = world(on, { id: '../escape' })
  expect(await $.tool.call({ tool: QUEUE })).toEqual({
    deny: "This session has no usable session id ('../escape'). Nothing was queued. Tell the user and stop.",
  })
  expect(w.saved.size).toBe(0)
})

test('a request queued while a compaction runs is not taken', async ($, on) => {
  const w = world(on)
  w.saved.set('request:' + SESSION, { state: 'executing', focus: '', min_context_tokens: null, requested_at: 1, attempts: 1 })
  const { text, data } = read(await $.tool.call({ tool: QUEUE, focus: 'later' }))
  expect(data.queued).toBe(false)
  expect(text).toBe('A compaction of this session is already running, so nothing more was queued.')
  expect((w.saved.get('request:' + SESSION) as any).state).toBe('executing')
})

test('cancel withdraws a queued request', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: QUEUE })
  const { text, data } = read(await $.tool.call({ tool: CANCEL }))
  expect(data).toEqual({ cancelled: true, session_id: SESSION, transport: 'mod' })
  expect(text).toBe('Cancelled the queued compaction.')
  expect(w.saved.size).toBe(0)
})

test('cancel with nothing queued, and cancel too late, both say so', async ($, on) => {
  const w = world(on)
  expect(read(await $.tool.call({ tool: CANCEL })).text).toBe('Nothing was queued for this session.')
  w.saved.set('request:' + SESSION, { state: 'executing', focus: '', min_context_tokens: null, requested_at: 1,
    started_at: 1_790_000_000_000, attempts: 1 })
  const late = read(await $.tool.call({ tool: CANCEL }))
  expect(late.data.cancelled).toBe(false)
  expect(late.text).toBe('The compaction has already begun and cannot be withdrawn.')
  expect(w.saved.has('request:' + SESSION)).toBe(true)
  expect(await $.tool.call({ tool: CANCEL, now: true })).toEqual({
    deny: 'Unexpected argument(s): now. This tool never takes a target session - it always acts on the session '
      + 'that called it. Nothing was cancelled.',
  })
})

test('status reports the request, the context, the hold and the last result', async ($, on) => {
  const now = 1_790_000_000_000
  const w = world(on, { now, files: { [STATE + '/idle/hold/' + SESSION + '.json']: JSON.stringify({ until: now / 1000 + 600 }) } })
  w.saved.set('result:' + SESSION, { action: 'compacted', reason: '', at: now - 60_000, tokens_before: 500_000, tokens_after: 40_000 })
  await $.tool.call({ tool: QUEUE, focus: 'keep', min_context_tokens: 5 })
  const { text, data } = read(await $.tool.call({ tool: STATUS }))
  expect(data).toEqual({
    pending: true, session_id: SESSION, focus: 'keep', min_context_tokens: 5, context_tokens: 412_880,
    hold_minutes_left: 10, transport: 'mod', state: 'queued',
    last: { action: 'compacted', reason: '', at: now - 60_000, tokens_before: 500_000, tokens_after: 40_000 },
  })
  expect(text).toBe('A compaction is queued for the end of this turn. The context is about 412880 tokens. '
    + 'The early idle toast is held for another 10 minutes. The last compaction here: compacted, '
    + '500,000 to 40,000 tokens.')
})

test('status with nothing queued, nothing held and nothing done', async ($, on) => {
  world(on, { tokens: null })
  const { text, data } = read(await $.tool.call({ tool: STATUS }))
  expect(data).toEqual({
    pending: false, session_id: SESSION, focus: null, min_context_tokens: null, context_tokens: null,
    hold_minutes_left: null, transport: 'mod', state: null, last: null,
  })
  expect(text).toBe('Nothing is queued for this session.')
})

test('status names a result that was not a compaction by its reason', async ($, on) => {
  const w = world(on)
  w.saved.set('result:' + SESSION, { action: 'below_threshold', reason: 'context 4 tokens < minimum 5; not compacting', at: 1 })
  expect(read(await $.tool.call({ tool: STATUS })).text).toMatch(
    / The last compaction here: below_threshold \(context 4 tokens < minimum 5; not compacting\)\.$/)
})

test('a compaction whose sizes were not recorded is still named as one', async ($, on) => {
  const w = world(on)
  w.saved.set('result:' + SESSION, { action: 'compacted', reason: '', at: 1, tokens_before: 500, tokens_after: null })
  expect(read(await $.tool.call({ tool: STATUS })).text).toMatch(/ The last compaction here: compacted\.$/)
})

test('a home written with a trailing separator still finds the settings', async ($, on) => {
  world(on, {
    env: { USERPROFILE: HOME + '\\' },
    files: { [STATE + '/settings.json']: '{"guard_spin_off_sessions": false}' },
    cwd: 'C:/dev/app/.claude/worktrees/x',
  })
  expect(read(await $.tool.call({ tool: QUEUE })).data.queued).toBe(true)
})

test('without a home directory the settings and the hold are simply absent', async ($, on) => {
  world(on, { env: {}, cwd: 'C:/dev/app/.claude/worktrees/x' })
  expect(read(await $.tool.call({ tool: QUEUE })).data.queued).toBe(false)
  expect(read(await $.tool.call({ tool: STATUS })).data.hold_minutes_left).toBe(null)
})

test('the home falls back to HOME where there is no USERPROFILE', async ($, on) => {
  const w = world(on, {
    env: { HOME: '/home/someone' },
    files: { '/home/someone/.conpact/settings.json': '{"guard_spin_off_sessions": false}' },
    cwd: '/home/someone/app/.claude/worktrees/x',
  })
  expect(read(await $.tool.call({ tool: QUEUE })).data.queued).toBe(true)
  expect(w.saved.size).toBe(1)
})

test('the early toast hold is left to the server', async ($, on) => {
  const seen: string[] = []
  world(on)
  on('tool.call', ($: any, e: any) => {
    seen.push(e.tool)
    return { result: 'from the server' }
  })
  const answer = await $.tool.call({ tool: 'mcp__conpact__hold_idle_toast', minutes: 30 })
  expect(answer).toEqual({ result: 'from the server' })
  expect(seen).toEqual(['mcp__conpact__hold_idle_toast'])
})
