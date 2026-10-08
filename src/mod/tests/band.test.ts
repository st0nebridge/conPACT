/**
 * @module mod.tests.band
 * @description The band above the prompt, one row: what it shows while a
 *              request waits, while it runs and once it has run - before ->
 *              after, a meter of what was kept (Unicode on the terminal, a
 *              drawing on the desktop), the saving and the time - and its two
 *              buttons, cancel and the dismiss mark. Every drawing is checked
 *              on the terminal and on the desktop.
 */
import { expect, test } from 'claude-code/testing'
import { SETTLE_MS, SHOW_MS, draw, meter, model, picture, settled, short, took } from '../hooks/band.js'
import { STALE_RUN_MS } from '../hooks/rules.js'
import { withdraw } from '../hooks/tools.js'
import { CANCEL, KEPT, QUEUE, SESSION, STATE, read, turnEnd, world } from './world.ts'

const NOW = 1_790_000_000_000
const SURFACES = ['terminal', 'desktop'] as const
const BAND = {
  component: 'AbovePrompt' as const,
  props: { hasSurvey: false, isWorking: false, maxRows: 12, bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 12 }, view: {} },
}

function mount($: any, surface: string, props: Record<string, unknown> = {}) {
  return $.ui.mount({ plugin: 'conpact', surface, ...BAND, props: { ...BAND.props, ...props } })
}

// Our row's words; `beneath` is what the plugins beneath drew, checked on its own.
async function shown(ui: any): Promise<string> {
  return (await ui.findAll({ type: 'Text' })).map((t: any) => t.text).filter((t: string) => t !== 'beneath').join(' | ')
}

async function kept(ui: any): Promise<boolean> {
  return (await ui.find({ type: 'Text', text: 'beneath' })) !== undefined
}

const START = { surface: 'terminal', isInteractive: true, cwd: 'C:/work/project' }

const COMPACTED = { action: 'compacted', reason: '', at: NOW - 1_000, started_at: NOW - 85_700, focus: 'keep the plan',
  context_tokens: 285_423, min_context_tokens: null, tokens_before: 285_423, tokens_after: 18_550, attempts: 1 }

test('with nothing queued and nothing run, the band is not ours', async ($, on) => {
  world(on, { now: NOW })
  for (const surface of SURFACES) {
    const ui = await mount($, surface)
    expect(await shown(ui)).not.toMatch(/conPACT/)
    await ui.unmount()
  }
})

test('a queued request is one row: the context, its minimum and its focus, and cancel withdraws it', async ($, on) => {
  const w = world(on, { now: NOW })
  for (const surface of SURFACES) {
    w.saved.clear()
    await $.tool.call({ tool: QUEUE, focus: 'keep the plan', min_context_tokens: 150_000 })
    const ui = await mount($, surface)
    const text = await shown(ui)
    expect(text).toBe((surface === 'terminal' ? '◇ ' : '') + 'conPACT | queued | 412.9k now · ≥ 150k · keep: keep the plan')
    expect((await ui.find({ type: 'Text', text: /conPACT/ }))?.props.color).toBe('warning')
    expect((await ui.find({ key: 'conpact-cancel' }))?.props).toMatchObject({ label: 'cancel', plain: true })
    expect(await ui.find({ key: 'conpact-dismiss' })).toBeUndefined()
    expect((await ui.find({ key: 'conpact' }))?.props.flexDirection).toBe('row')
    if (surface === 'desktop') {
      const mark = await ui.find({ type: 'Svg' })
      expect(mark?.props).toMatchObject({ alt: 'conPACT queued', width: 16, height: 16, isInteractive: true })
      expect(String(mark?.props.source)).toMatch(/<animate attributeName="opacity"/)
    } else {
      expect(await ui.find({ type: 'Svg' })).toBeUndefined()
    }
    await ui.press({ key: 'conpact-cancel' })
    expect(w.saved.has('request:' + SESSION)).toBe(false)
    expect(await shown(ui)).not.toMatch(/conPACT/)
    await ui.unmount()
  }
})

test('a queued request with no focus, minimum or size says only that it is queued', async ($, on) => {
  world(on, { now: NOW, tokens: null })
  await $.tool.call({ tool: QUEUE })
  const ui = await mount($, 'terminal')
  expect(await shown(ui)).toBe('◇ conPACT | queued')
  await ui.unmount()
})

test('a request tried again says which try is next and why the last did not run', async ($, on) => {
  const w = world(on, { now: NOW })
  w.saved.set('request:' + SESSION, { state: 'queued', focus: '', min_context_tokens: null, requested_at: NOW,
    attempts: 1, reason: 'a turn is running' })
  const ui = await mount($, 'desktop')
  expect(await shown(ui)).toBe('conPACT | queued | 412.9k now · try 2/3 (a turn is running)')
  await ui.unmount()
})

test('a running compaction shows the size it is compacting, turning, with no buttons', async ($, on) => {
  const w = world(on, { now: NOW })
  for (const surface of SURFACES) {
    w.saved.clear()
    w.saved.set('request:' + SESSION, { state: 'executing', focus: 'keep the plan', min_context_tokens: null,
      requested_at: NOW, started_at: NOW, attempts: 2 })
    const ui = await mount($, surface)
    expect(await shown(ui)).toBe((surface === 'terminal' ? '◆ ' : '') + 'conPACT | compacting 412.9k | try 2/3 · keep: keep the plan')
    expect(await ui.findAll({ type: 'Button' })).toEqual([])
    if (surface === 'desktop') {
      expect(String((await ui.find({ type: 'Svg' }))?.props.source)).toMatch(/<animateTransform attributeName="transform" type="rotate"/)
    }
    await ui.unmount()
  }
})

test('a compaction is one row: before -> after, a meter of what was kept, the saving and the time, until dismissed', async ($, on) => {
  const w = world(on, { now: NOW })
  for (const surface of SURFACES) {
    w.saved.clear()
    w.saved.set('result:' + SESSION, COMPACTED)
    const ui = await mount($, surface)
    const text = await shown(ui)
    if (surface === 'terminal') {
      expect(text).toBe('✓ conPACT | 285.4k → 18.6k | ━ | ' + '─'.repeat(15) + ' | −93.5% | 1m 25s')
      expect((await ui.find({ type: 'Text', text: '━' }))?.props.color).toBe('success')
      expect(await ui.find({ type: 'Svg' })).toBeUndefined()
    } else {
      expect(text).toBe('conPACT | 285.4k → 18.6k | −93.5% | 1m 25s')
      const chart = await ui.find({ type: 'Svg' })
      expect(chart?.props).toMatchObject({ alt: '285,423 tokens before, 18,550 after', width: 96, height: 16 })
      expect(chart?.props.isInteractive).toBeUndefined()
      expect(String(chart?.props.source)).toBe(picture('compacted', 18_550 / 285_423))
    }
    expect((await ui.find({ type: 'Text', text: /conPACT/ }))?.props.color).toBe('success')
    expect((await ui.find({ key: 'conpact-dismiss' }))?.props).toMatchObject({ label: '×', role: 'dismiss', plain: true })
    await ui.press({ key: 'conpact-dismiss' })
    expect((w.saved.get('result:' + SESSION) as any).dismissed).toBe(true)
    expect(await shown(ui)).not.toMatch(/conPACT/)
    await ui.unmount()
  }
})

test('a compaction whose sizes are unknown says only that it compacted', async ($, on) => {
  const w = world(on, { now: NOW })
  w.saved.set('result:' + SESSION, { ...COMPACTED, tokens_after: null, started_at: undefined })
  for (const surface of SURFACES) {
    const ui = await mount($, surface)
    expect(await shown(ui)).toBe((surface === 'terminal' ? '✓ ' : '') + 'conPACT | compacted')
    if (surface === 'desktop') expect((await ui.find({ type: 'Svg' }))?.props.width).toBe(16)
    await ui.unmount()
  }
})

test('a failed compaction is red with its reason', async ($, on) => {
  const w = world(on, { now: NOW })
  for (const surface of SURFACES) {
    w.saved.clear()
    w.saved.set('result:' + SESSION, { action: 'error', reason: 'Not enough messages to compact.', at: NOW })
    const ui = await mount($, surface)
    expect(await shown(ui)).toBe((surface === 'terminal' ? '✗ ' : '') + 'conPACT | failed | Not enough messages to compact.')
    expect((await ui.find({ type: 'Text', text: /conPACT/ }))?.props.color).toBe('error')
    expect((await ui.find({ type: 'Text', text: 'failed' }))?.props.color).toBe('error')
    expect(await ui.find({ key: 'conpact-dismiss' })).toBeDefined()
    await ui.unmount()
  }
})

test('a request that did not compact says why, dimmed', async ($, on) => {
  const w = world(on, { now: NOW })
  w.saved.set('result:' + SESSION, { action: 'below_threshold', reason: 'context 9 tokens < minimum 10; not compacting', at: NOW })
  const ui = await mount($, 'terminal')
  expect(await shown(ui)).toBe('○ conPACT | not compacted | context 9 tokens < minimum 10; not compacting')
  expect((await ui.find({ type: 'Text', text: /conPACT/ }))?.props.dimColor).toBe(true)
  await ui.unmount()
})

test('an old or dismissed result, or a survey, keeps the band clear', async ($, on) => {
  const w = world(on, { now: NOW })
  w.saved.set('result:' + SESSION, { ...COMPACTED, at: NOW - SHOW_MS - 1 })
  let ui = await mount($, 'terminal')
  expect(await shown(ui)).not.toMatch(/conPACT/)
  await ui.unmount()
  w.saved.set('result:' + SESSION, { ...COMPACTED, dismissed: true })
  ui = await mount($, 'terminal')
  expect(await shown(ui)).not.toMatch(/conPACT/)
  await ui.unmount()
  w.saved.set('result:' + SESSION, COMPACTED)
  ui = await mount($, 'terminal', { hasSurvey: true })
  expect(await shown(ui)).not.toMatch(/conPACT/)
  await ui.unmount()
})

test('a new request takes the band over from the last result', async ($, on) => {
  const w = world(on, { now: NOW })
  w.saved.set('result:' + SESSION, COMPACTED)
  await $.tool.call({ tool: QUEUE })
  const ui = await mount($, 'terminal')
  expect(await shown(ui)).toMatch(/queued/)
  expect(await shown(ui)).not.toMatch(/285\.4k/)
  await ui.unmount()
})

test('the band follows a request from queued to compacted without being asked to redraw', async ($, on) => {
  const w = world(on, { now: NOW })
  const ui = await mount($, 'terminal')
  await $.tool.call({ tool: QUEUE, focus: 'keep the plan' })
  expect(await shown(ui)).toMatch(/queued/)
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(await shown(ui)).toMatch(/412\.9k → 37\.4k/)
  expect((w.saved.get('result:' + SESSION) as any).started_at).toBe(NOW)
  await ui.unmount()
})

/** A compaction the test lets finish when it chooses, so the band can be read while it runs. */
function held() {
  const gate: { settle?: (answer: unknown) => void, fail?: (error: Error) => void } = {}
  const compact = (() => new Promise((resolve, reject) => { gate.settle = resolve; gate.fail = reject })) as any
  return { gate, compact }
}

async function until(w: any, ready: () => boolean) {
  for (let i = 0; i < 200 && !ready(); i++) await w.clock.advance(0)
}

test('the band is drawn again as the run claims the request, and again as it ends', async ($, on) => {
  const { gate, compact } = held()
  const w = world(on, { now: NOW, compact })
  await $.tool.call({ tool: QUEUE })
  const ui = await mount($, 'terminal')
  expect(await shown(ui)).toMatch(/queued/)
  await $.turn.complete(turnEnd())
  await until(w, () => gate.settle !== undefined)
  expect(await shown(ui)).toBe('◆ conPACT | compacting 412.9k')
  gate.settle!({ messages: KEPT, tokensBefore: 412_880, tokensAfter: 37_400 })
  await w.clock.settle()
  expect(await shown(ui)).toMatch(/^✓ conPACT \| 412\.9k → 37\.4k/)
  await ui.unmount()
})

test('a band drawn while the run ends shows the end: what it read is read again once it changed', async () => {
  let version = 0
  const looks: string[] = []
  // The run ends while the first look is under way.
  const found = await settled(() => version, async () => {
    looks.push(looks.length === 0 ? 'compacting' : 'compacted')
    if (looks.length === 1) version += 1
    return looks[looks.length - 1]
  })
  expect(found).toBe('compacted')
  expect(looks).toEqual(['compacting', 'compacted'])
  const still: number[] = []
  expect(await settled(() => 7, async () => still.push(1))).toBe(1)
  expect(still).toEqual([1])
})

test('a band that keeps changing while it is drawn is looked at three times, no more', async () => {
  let version = 0
  let looks = 0
  expect(await settled(() => version, async () => { version += 1; return ++looks })).toBe(3)
  expect(looks).toBe(3)
})

test('a drawing under way as the run ends reads again, so it draws the end and not compacting', async ($, on) => {
  const { gate, compact } = held()
  const hold: { armed: boolean, release?: () => void } = { armed: false }
  const w = world(on, {
    now: NOW, compact, beforeUsage: () => {
      if (!hold.armed || hold.release !== undefined) return
      return new Promise<void>((resolve) => { hold.release = resolve })
    },
  })
  await $.tool.call({ tool: QUEUE })
  const ui = await mount($, 'desktop')
  await $.turn.complete(turnEnd())
  await until(w, () => gate.settle !== undefined)
  expect(await shown(ui)).toMatch(/compacting/)
  // The turn stops working as the compaction ends: the surface asks for the band, and the
  // drawing has read the request (still running) when the run records its end.
  hold.armed = true
  const drawing = ui.redraw({ ...BAND.props, isWorking: false })
  await until(w, () => hold.release !== undefined)
  gate.settle!({ messages: KEPT, tokensBefore: 412_880, tokensAfter: 37_400 })
  await w.clock.settle()
  hold.release!()
  await drawing
  hold.armed = false
  // Read once, this drawing would stand as "compacting": the end's own ask is folded into it.
  expect(await shown(ui)).toMatch(/412\.9k → 37\.4k/)
  await ui.unmount()
})

test('the band is asked for again SETTLE_MS after the run ends, for a surface that drew it a moment before', async ($, on) => {
  const { gate, compact } = held()
  const w = world(on, { now: NOW, compact })
  const asked: number[] = []
  on('ui.invalidate', ($: any, e: any, next: any) => {
    asked.push(w.clock.now() - NOW)
    return next(e)
  })
  await $.tool.call({ tool: QUEUE })
  await $.turn.complete(turnEnd())
  await until(w, () => gate.settle !== undefined)
  // Queued, then claimed: each asked for now, and again SETTLE_MS on.
  expect(asked).toEqual([0, 0])
  await w.clock.advance(SETTLE_MS)
  expect(asked).toEqual([0, 0, SETTLE_MS, SETTLE_MS])
  asked.length = 0
  gate.settle!({ messages: KEPT, tokensBefore: 412_880, tokensAfter: 37_400 })
  await w.clock.settle()
  expect(asked).toEqual([SETTLE_MS])
  await w.clock.advance(SETTLE_MS - 1)
  expect(asked).toEqual([SETTLE_MS])
  await w.clock.advance(1)
  expect(asked).toEqual([SETTLE_MS, 2 * SETTLE_MS])
  await w.clock.advance(SETTLE_MS * 10)
  expect(asked.length).toBe(2)
})

test('the band is drawn again when a run that could not start goes back in the queue', async ($, on) => {
  const { gate, compact } = held()
  const w = world(on, { now: NOW, compact })
  await $.tool.call({ tool: QUEUE })
  const ui = await mount($, 'terminal')
  await $.turn.complete(turnEnd())
  await until(w, () => gate.fail !== undefined)
  expect(await shown(ui)).toMatch(/compacting/)
  gate.fail!(new Error('a turn is running'))
  await w.clock.settle()
  // The words are the test host's for a rejected compaction; the row is what matters.
  expect(await shown(ui)).toMatch(/^◇ conPACT \| queued \| 412\.9k now · try 2\/3 \(\S/)
  await ui.unmount()
})

test('the band shows the idle toast\'s compaction while it runs, then its result', async ($, on) => {
  const { gate, compact } = held()
  const w = world(on, { now: NOW, compact })
  await $.session.start(START)
  const ui = await mount($, 'terminal')
  w.files.set((STATE + '/mod/ask/' + SESSION + '.json').replace(/^[A-Za-z]:/, ''),
    JSON.stringify({ session_id: SESSION, request_id: 'r1', expires_at: NOW / 1000 + 10 }))
  await w.clock.advance(2_000)
  await until(w, () => gate.settle !== undefined)
  expect(await shown(ui)).toBe('◆ conPACT | compacting 412.9k')
  gate.settle!({ messages: KEPT, tokensBefore: 412_880, tokensAfter: 37_400 })
  await until(w, () => !w.saved.has('running:' + SESSION))
  expect(await shown(ui)).toMatch(/^✓ conPACT \| 412\.9k → 37\.4k/)
  await ui.unmount()
})

test('a run lost in a reload, once its compaction ends, shows as compacted', async ($, on) => {
  const w = world(on, { now: NOW })
  w.saved.set('request:' + SESSION, { state: 'executing', focus: '', min_context_tokens: null, requested_at: NOW - 5_000,
    started_at: NOW - 60_000, attempts: 1 })
  const ui = await mount($, 'terminal')
  expect(await shown(ui)).toBe('◆ conPACT | compacting 412.9k')
  await $.session.compact({ trigger: 'manual', messages: KEPT })
  expect(await shown(ui)).toMatch(/^✓ conPACT \| 412\.9k → 37\.4k/)
  await ui.unmount()
})

test('cancel_compaction clears the band', async ($, on) => {
  world(on, { now: NOW })
  await $.tool.call({ tool: QUEUE })
  const ui = await mount($, 'terminal')
  expect(await shown(ui)).toMatch(/queued/)
  await $.tool.call({ tool: CANCEL })
  expect(await shown(ui)).not.toMatch(/conPACT/)
  await ui.unmount()
})

test('cancel on a request that has begun withdraws nothing', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.tool.call({ tool: QUEUE })
  const ui = await mount($, 'terminal')
  w.saved.set('request:' + SESSION, { ...(w.saved.get('request:' + SESSION) as any), state: 'executing', started_at: NOW })
  await ui.press({ key: 'conpact-cancel' })
  expect((w.saved.get('request:' + SESSION) as any).state).toBe('executing')
  expect(read(await $.tool.call({ tool: CANCEL })).data.cancelled).toBe(false)
  await ui.unmount()
})

test('dismissing a result that was replaced since it was drawn leaves the new one', async ($, on) => {
  const w = world(on, { now: NOW })
  w.saved.set('result:' + SESSION, COMPACTED)
  const ui = await mount($, 'terminal')
  w.saved.set('result:' + SESSION, { ...COMPACTED, at: NOW })
  await ui.press({ key: 'conpact-dismiss' })
  expect((w.saved.get('result:' + SESSION) as any).dismissed).toBeUndefined()
  await ui.unmount()
})

test('short, took and meter', () => {
  expect(short(999)).toBe('999')
  expect(short(1000)).toBe('1k')
  expect(short(150_000)).toBe('150k')
  expect(short(285_423)).toBe('285.4k')
  expect(short(999_999)).toBe('1000k')
  expect(short(1_000_000)).toBe('1M')
  expect(short(2_540_000)).toBe('2.5M')
  expect(took(0.4)).toBe('0s')
  expect(took(59.4)).toBe('59s')
  expect(took(59.5)).toBe('1m 0s')
  expect(took(84.7)).toBe('1m 25s')
  expect(meter(1, 4)).toEqual(['━━━━', ''])
  expect(meter(0.5, 4)).toEqual(['━━', '──'])
  expect(meter(0.375, 4)).toEqual(['━╸', '──'])
  expect(meter(0.001, 4)).toEqual(['╸', '───'])
  expect(meter(0, 4)).toEqual(['', '────'])
  expect(meter(2, 4)).toEqual(['━━━━', ''])
})

test('picture: a mark of 16 px, and a compaction its 72 px meter beside it', () => {
  expect(picture('failed', null)).toMatch(/^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" viewBox="0 0 16 16" width="16" height="16">/)
  // Clear in a dark theme too: the frame a moving mark is drawn in takes the page's scheme.
  for (const kind of ['queued', 'running', 'compacted', 'failed', 'idle']) {
    expect(picture(kind, null)).toContain('<style>:root{color-scheme:light dark;background:transparent;overflow:hidden}body{margin:0}</style>')
  }
  const kept = picture('compacted', 18_550 / 285_423)
  expect(kept).toMatch(/viewBox="0 0 96 16" width="96"/)
  expect(kept).toMatch(/<rect x="24" y="5" width="72" height="6" rx="3" fill="#8b949e" fill-opacity="0.3"\/>/)
  expect(kept).toMatch(/<rect x="24" y="5" width="5" height="6" rx="3" fill="#3fb950"\/>/)
  expect(picture('compacted', 0)).toMatch(/width="2" height="6" rx="3" fill="#3fb950"/)
  expect(picture('compacted', 3)).toMatch(/<rect x="24" y="5" width="72" height="6" rx="3" fill="#3fb950"\/>/)
})

test('model: nothing to show without a request or a fresh result', () => {
  expect(model(null, null, NOW, null)).toBeNull()
  expect(model(null, { action: 'compacted', at: 'then' }, NOW, null)).toBeNull()
  expect(model(null, { ...COMPACTED, at: NOW - SHOW_MS }, NOW, null)?.kind).toBe('compacted')
  expect(model(null, { ...COMPACTED, at: NOW - SHOW_MS - 1 }, NOW, null)).toBeNull()
  expect(model(null, { ...COMPACTED, started_at: undefined }, NOW, null)?.seconds).toBeNull()
  expect(model(null, { ...COMPACTED, tokens_after: null }, NOW, null)?.after).toBeNull()
  expect(model({ state: 'gone' }, null, NOW, 5)).toBeNull()
  expect(model({ state: 'queued' }, null, NOW, 5)).toEqual({ kind: 'queued', focus: '', minimum: null, tokens: 5,
    attempt: 1, last: '' })
  expect(model({ state: 'executing', started_at: NOW - STALE_RUN_MS + 1 }, null, NOW, 5))
    .toEqual({ kind: 'running', focus: '', tokens: 5, attempt: 1 })
  // A run not ended in STALE_RUN_MS was lost: it waits for its next try.
  expect(model({ state: 'executing', started_at: NOW - STALE_RUN_MS, attempts: 2, focus: 'f', min_context_tokens: 9 },
    null, NOW, 5)).toEqual({ kind: 'queued', focus: 'f', minimum: 9, tokens: 5, attempt: 3, last: 'the last run did not finish' })
  expect(model({ state: 'executing', started_at: 'then' }, null, NOW, 5)).toEqual({ kind: 'queued', focus: '', minimum: null,
    tokens: 5, attempt: 2, last: 'the last run did not finish' })
  expect(model(null, { action: 'skipped', at: NOW }, NOW, 5)).toEqual({ kind: 'idle', at: NOW, reason: '' })
})
test('what the plugins beneath draw stays: alone when we have nothing, below our row when we do', async ($, on) => {
  const w = world(on, { now: NOW })
  let ui = await mount($, 'terminal')
  expect(await kept(ui)).toBe(true)
  await ui.unmount()
  w.saved.set('result:' + SESSION, COMPACTED)
  for (const surface of SURFACES) {
    ui = await mount($, surface)
    const root = await ui.drawn() as any
    expect(root.props.flexDirection).toBe('column')
    expect(await ui.find({ key: 'conpact' })).toBeDefined()
    // ours first, then what was beneath
    expect((await ui.findAll({ type: 'Text' })).map((t: any) => t.text).at(-1)).toBe('beneath')
    await ui.unmount()
  }
  ui = await mount($, 'terminal', { hasSurvey: true })
  expect(await kept(ui)).toBe(true)
  await ui.unmount()
})

test('a session with no plain id, or a host that cannot say the context size, keeps the band as it was', async ($, on) => {
  const w = world(on, { now: NOW, id: 'not a session', failUsage: true })
  w.saved.set('result:not a session', COMPACTED)
  let ui = await mount($, 'desktop')
  expect(await shown(ui)).toBe('')
  expect(await kept(ui)).toBe(true)
  await ui.unmount()
  w.id = SESSION
  w.saved.set('result:' + SESSION, COMPACTED)
  ui = await mount($, 'terminal')
  expect(await shown(ui)).toBe('')
  expect(await kept(ui)).toBe(true)
  await ui.unmount()
})

test('the idle toast\'s compaction shows as running, over a waiting request, then as the result', async ($, on) => {
  const w = world(on, { now: NOW })
  w.saved.set('running:' + SESSION, { started_at: NOW - 5_000 })
  let ui = await mount($, 'terminal')
  expect(await shown(ui)).toBe('◆ conPACT | compacting 412.9k')
  await ui.unmount()
  await $.tool.call({ tool: QUEUE, focus: 'keep the plan' })
  ui = await mount($, 'terminal')
  expect(await shown(ui)).toBe('◆ conPACT | compacting 412.9k')
  await ui.unmount()
  w.saved.set('running:' + SESSION, { started_at: NOW - STALE_RUN_MS })
  ui = await mount($, 'terminal')
  expect(await shown(ui)).toMatch(/^◇ conPACT \| queued/)
  await ui.unmount()
})

test('a toast compaction run through the mod ends in the band as its result', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.session.start(START)
  const ui = await mount($, 'terminal')
  w.files.set((STATE + '/mod/ask/' + SESSION + '.json').replace(/^[A-Za-z]:/, ''),
    JSON.stringify({ session_id: SESSION, request_id: 'r1', expires_at: NOW / 1000 + 10 }))
  await w.clock.advance(2_000)
  expect(await shown(ui)).toMatch(/^✓ conPACT \| 412\.9k → 37\.4k/)
  expect(w.saved.has('running:' + SESSION)).toBe(false)
  await ui.unmount()
})

test('withdraw: only a request that waits for a run, and says whether it did', async () => {
  const saved = new Map<string, unknown>()
  let changed = 0
  const host = {
    clock: { now: async () => NOW },
    store: { get: async (k: string) => saved.get(k), set: async (k: string, v: unknown) => { saved.set(k, v) },
      delete: async (k: string) => { saved.delete(k) } },
    ui: { changed: () => { changed += 1 } },
  }
  expect(await withdraw(host, SESSION)).toBe(false)
  saved.set('request:' + SESSION, { state: 'executing', started_at: NOW - STALE_RUN_MS + 1 })
  expect(await withdraw(host, SESSION)).toBe(false)
  expect(changed).toBe(0)
  saved.set('request:' + SESSION, { state: 'queued' })
  expect(await withdraw(host, SESSION)).toBe(true)
  expect(saved.size).toBe(0)
  expect(changed).toBe(1)
  // A lost run's request waits for its next try, so it can be withdrawn.
  saved.set('request:' + SESSION, { state: 'executing', started_at: NOW - STALE_RUN_MS })
  expect(await withdraw(host, SESSION)).toBe(true)
  expect(saved.size).toBe(0)
})

test('a run lost in a reload is not shown compacting for ever: it waits for its next try, and cancel withdraws it', async ($, on) => {
  const w = world(on, { now: NOW })
  const lost = { state: 'executing', focus: 'keep the plan', min_context_tokens: null, requested_at: NOW - STALE_RUN_MS - 5_000,
    started_at: NOW - STALE_RUN_MS, attempts: 1 }
  for (const surface of SURFACES) {
    w.saved.set('request:' + SESSION, lost)
    const ui = await mount($, surface)
    expect(await shown(ui)).toBe((surface === 'terminal' ? '◇ ' : '')
      + 'conPACT | queued | 412.9k now · try 2/3 (the last run did not finish) · keep: keep the plan')
    await ui.press({ key: 'conpact-cancel' })
    expect(w.saved.has('request:' + SESSION)).toBe(false)
    await ui.unmount()
  }
  w.saved.set('request:' + SESSION, lost)
  const { text, data } = read(await $.tool.call({ tool: CANCEL }))
  expect(text).toBe('Cancelled the queued compaction.')
  expect(data.cancelled).toBe(true)
  expect(w.saved.has('request:' + SESSION)).toBe(false)
})

// Elements as plain records, so a row can be compared whole.
const EL = new Proxy({}, { get: (_, type) => (props: any) => ({ type, props }) }) as any
const ACT = { cancel: () => {}, dismiss: () => {} }

function plainRow(tree: any): any {
  return JSON.parse(JSON.stringify(tree))
}

test('draw: the compacted row, whole, on the terminal and on the desktop', () => {
  const m = model(null, COMPACTED, NOW, null)
  const tail = [
    { type: 'Text', props: { color: 'success', children: '−93.5%' } },
    { type: 'Text', props: { dimColor: true, wrap: 'truncate-end', children: '1m 25s' } },
    { type: 'Box', props: { flexGrow: 1 } },
    { type: 'Button', props: { key: 'conpact-dismiss', label: '×', plain: true, dimColor: true, role: 'dismiss' } },
  ]
  expect(plainRow(draw(EL, 'terminal', m, ACT, null))).toEqual({ type: 'Box', props: {
    key: 'conpact', flexDirection: 'row', gap: 1, alignItems: 'center', children: [
      { type: 'Text', props: { color: 'success', bold: true, children: '✓ conPACT' } },
      { type: 'Text', props: { bold: true, children: '285.4k → 18.6k' } },
      { type: 'Box', props: { flexDirection: 'row', children: [
        { type: 'Text', props: { color: 'success', children: '━' } },
        { type: 'Text', props: { dimColor: true, children: '─'.repeat(15) } }] } },
      ...tail] } })
  expect(plainRow(draw(EL, 'desktop', m, ACT, null)).props.children.slice(0, 3)).toEqual([
    { type: 'Svg', props: { source: picture('compacted', 18_550 / 285_423), alt: '285,423 tokens before, 18,550 after',
      width: 96, height: 16 } },
    { type: 'Text', props: { color: 'success', bold: true, children: 'conPACT' } },
    { type: 'Text', props: { bold: true, children: '285.4k → 18.6k' } },
  ])
  const below = { type: 'Text', props: { children: 'beneath' } }
  expect(plainRow(draw(EL, 'terminal', m, ACT, below))).toMatchObject({ type: 'Box', props: { flexDirection: 'column',
    children: [{ props: { key: 'conpact' } }, below] } })
})

test('draw: the waiting, running, failed and idle rows', () => {
  const queued = plainRow(draw(EL, 'desktop', model({ state: 'queued', focus: 'f', min_context_tokens: 2000, attempts: 2,
    reason: 'busy' }, null, NOW, 1500), ACT, null)).props.children
  expect(queued[0]).toEqual({ type: 'Svg', props: { source: picture('queued', null), alt: 'conPACT queued', width: 16,
    height: 16, isInteractive: true } })
  expect(queued.slice(1)).toEqual([
    { type: 'Text', props: { color: 'warning', bold: true, children: 'conPACT' } },
    { type: 'Text', props: { children: 'queued' } },
    { type: 'Text', props: { dimColor: true, wrap: 'truncate-end', children: '1.5k now · ≥ 2k · try 3/3 (busy) · keep: f' } },
    { type: 'Box', props: { flexGrow: 1 } },
    { type: 'Button', props: { key: 'conpact-cancel', label: 'cancel', plain: true, dimColor: true } },
  ])
  const running = plainRow(draw(EL, 'terminal', model({ state: 'executing', started_at: NOW }, null, NOW, null), ACT, null)).props.children
  expect(running).toEqual([
    { type: 'Text', props: { color: 'warning', bold: true, children: '◆ conPACT' } },
    { type: 'Text', props: { children: 'compacting' } },
    null,
    { type: 'Box', props: { flexGrow: 1 } },
  ])
  const failed = plainRow(draw(EL, 'terminal', model(null, { action: 'error', at: NOW, reason: 'r' }, NOW, null), ACT, null))
  expect(failed.props.children.slice(0, 3)).toEqual([
    { type: 'Text', props: { color: 'error', bold: true, children: '✗ conPACT' } },
    { type: 'Text', props: { color: 'error', children: 'failed' } },
    { type: 'Text', props: { dimColor: true, wrap: 'truncate-end', children: 'r' } },
  ])
  const idle = plainRow(draw(EL, 'desktop', model(null, { action: 'skipped', at: NOW }, NOW, null), ACT, null))
  expect(idle.props.children.slice(0, 4)).toEqual([
    { type: 'Svg', props: { source: picture('idle', null), alt: 'conPACT not compacted', width: 16, height: 16 } },
    { type: 'Text', props: { dimColor: true, bold: true, children: 'conPACT' } },
    { type: 'Text', props: { children: 'not compacted' } },
    null,
  ])
})

test('picture: each mark, whole', () => {
  const svg = (w: number, body: string) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} 16" width="${w}" height="16">`
    + '<style>:root{color-scheme:light dark;background:transparent;overflow:hidden}body{margin:0}</style>' + body + '</svg>'
  expect(picture('queued', null)).toBe(svg(16, '<circle cx="8" cy="8" r="6" fill="none" stroke="#d29922" stroke-width="1.6"/>'
    + '<circle cx="8" cy="8" r="2.6" fill="#d29922"><animate attributeName="opacity" values="1;0.2;1" dur="1.6s" repeatCount="indefinite"/></circle>'))
  expect(picture('running', null)).toBe(svg(16, '<circle cx="8" cy="8" r="6" fill="none" stroke="#8b949e" stroke-opacity="0.35" stroke-width="2"/>'
    + '<path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="#d29922" stroke-width="2" stroke-linecap="round">'
    + '<animateTransform attributeName="transform" type="rotate" from="0 8 8" to="360 8 8" dur="0.9s" repeatCount="indefinite"/></path>'))
  expect(picture('failed', null)).toBe(svg(16, '<circle cx="8" cy="8" r="7" fill="#f85149"/>'
    + '<path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>'))
  expect(picture('idle', null)).toBe(svg(16, '<circle cx="8" cy="8" r="6" fill="none" stroke="#8b949e" stroke-width="1.6"/>'
    + '<path d="M5.5 8h5" stroke="#8b949e" stroke-width="1.6" stroke-linecap="round"/>'))
  expect(picture('compacted', 0.5)).toBe(svg(96, '<circle cx="8" cy="8" r="7" fill="#3fb950"/>'
    + '<path d="M4.6 8.3l2.2 2.2 4.4-4.7" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
    + '<rect x="24" y="5" width="72" height="6" rx="3" fill="#8b949e" fill-opacity="0.3"/>'
    + '<rect x="24" y="5" width="36" height="6" rx="3" fill="#3fb950"/>'))
})

test('the model and words at their edges', () => {
  expect(SHOW_MS).toBe(15 * 60_000)
  expect(short(1_050_000)).toBe('1.1M')
  expect(model(null, { ...COMPACTED, tokens_before: Infinity }, NOW, null)?.before).toBeNull()
  expect(model({ state: 'queued', attempts: 0, reason: 'stale words' }, null, NOW, null)?.last).toBe('')
  expect(model({ state: 'queued', attempts: 1 }, null, NOW, null)?.last).toBe('')
  expect(model({ state: 'gone' }, COMPACTED, NOW, null)).toBeNull()
  expect(model(null, COMPACTED, NOW, null)?.seconds).toBe(84.7)
  const even = plainRow(draw(EL, 'terminal', model(null, { ...COMPACTED, tokens_before: 1, tokens_after: 1 }, NOW, null), ACT, null))
  expect(even.props.children.map((c: any) => c?.props?.children).filter((t: any) => typeof t === 'string')).toContain('−0.0%')
  const empty = plainRow(draw(EL, 'terminal', model(null, { ...COMPACTED, tokens_before: 0, tokens_after: 0 }, NOW, null), ACT, null))
  expect(JSON.stringify(empty)).not.toMatch(/%|━|─/)
  const turning = plainRow(draw(EL, 'desktop', model({ state: 'executing', started_at: NOW }, null, NOW, null), ACT, null))
  expect(turning.props.children[0].props).toMatchObject({ alt: 'conPACT compacting', isInteractive: true })
})

test('a compaction of your own that supersedes the request redraws the band', async ($, on) => {
  const w = world(on, { now: NOW })
  await $.tool.call({ tool: QUEUE })
  const ui = await mount($, 'terminal')
  expect(await shown(ui)).toMatch(/queued/)
  await $.session.compact({ trigger: 'auto', messages: [{ role: 'assistant', text: 'the summary', toolUses: [] }] })
  expect(await shown(ui)).toBe('○ conPACT | not compacted | the session was compacted (auto) before the queued compaction ran')
  await ui.unmount()
})
