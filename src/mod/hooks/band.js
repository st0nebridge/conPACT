/**
 * @module mod.band
 * @description The band above the prompt: what conPACT has for this session,
 *              on one row. A request waiting shows the context now, the
 *              minimum, its try and its focus, with cancel; one running, the
 *              size it is compacting; one that ran, before -> after, a meter
 *              of what was kept, the saving and the time, or why it did not
 *              compact, with a dismiss mark. The terminal draws its mark and
 *              meter in Unicode; every other surface draws them as a small
 *              SVG (a pulsing dot while queued, a turning ring while running,
 *              a check or a cross after). A run that has not ended in
 *              STALE_RUN_MS was lost and shows as waiting for its next try.
 *              A result stays SHOW_MS or until
 *              dismissed; a new request replaces it. A change made while the
 *              band is drawn is read again (settled), and the band is asked
 *              for once more SETTLE_MS after each change. Pure: it is handed
 *              the surface's elements, never $.
 * @input      the session's request, last result and the idle toast's running
 *              mark (mod.requests), the time, the context size now; the
 *              surface's element table and name
 * @output     a model of what to show, and the row that shows it
 * @dependencies mod.rules
 */
import { ATTEMPTS, STALE_RUN_MS, thousands } from './rules.js'

/** How long a result stays in the band, in milliseconds. */
export const SHOW_MS = 15 * 60_000

/**
 * How long after a change the band is asked for once more, in milliseconds: a
 * surface may keep a drawing it asked for a moment before the change.
 */
export const SETTLE_MS = 2_000

/**
 * What `look` finds, looked at again while `version()` moved during the look,
 * up to `tries` looks: a change made while the band is drawn - a run ending -
 * is drawn with it, as a surface may take this drawing for the one the change
 * asked for.
 */
export async function settled(version, look, tries = 3) {
  let seen
  let found
  do {
    seen = version()
    found = await look()
  } while (version() !== seen && --tries > 0)
  return found
}

const METER = 16
const GREEN = '#3fb950'
const AMBER = '#d29922'
const RED = '#f85149'
const GREY = '#8b949e'
// A moving mark is drawn in a frame of its own, and a frame whose colour
// scheme differs from the page's is painted opaque - white, in a dark
// theme. Declaring both schemes makes it match either, and keeps it clear.
const CLEAR = '<style>:root{color-scheme:light dark;background:transparent;overflow:hidden}body{margin:0}</style>'

/** 285423 -> "285.4k", 150000 -> "150k", 2500000 -> "2.5M". */
export function short(n) {
  if (n < 1000) return String(n)
  const [value, unit] = n < 1_000_000 ? [n / 1000, 'k'] : [n / 1_000_000, 'M']
  return value.toFixed(1).replace(/\.0$/, '') + unit
}

/** 84.7 -> "1m 25s", 42.3 -> "42s". */
export function took(seconds) {
  const whole = Math.round(seconds)
  return whole < 60 ? `${whole}s` : `${Math.floor(whole / 60)}m ${whole % 60}s`
}

/** A thin meter of `cells`: the kept share heavy, in half cells, at least one half for anything kept. */
export function meter(share, cells) {
  const halves = share > 0 ? Math.max(1, Math.round(Math.min(share, 1) * cells * 2)) : 0
  const kept = '━'.repeat(Math.floor(halves / 2)) + (halves % 2 ? '╸' : '')
  return [kept, '─'.repeat(cells - Array.from(kept).length)]
}

function number(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/**
 * What the band shows for this session, or null for nothing: its request, the
 * idle toast's compaction while it runs (`toast`, its mark), or its last result.
 */
export function model(request, result, now, tokens, toast = null) {
  if (request?.state === 'executing') {
    const tried = request.attempts ?? 1
    // A run that has not ended in STALE_RUN_MS was lost (a reload mid-run): the next turn end tries it again.
    if (now - (number(request.started_at) ?? 0) >= STALE_RUN_MS) {
      return { kind: 'queued', focus: request.focus ?? '', minimum: number(request.min_context_tokens), tokens,
        attempt: tried + 1, last: 'the last run did not finish' }
    }
    return { kind: 'running', focus: request.focus ?? '', tokens, attempt: tried }
  }
  const begun = number(toast?.started_at)
  // A mark left by a session that ended mid-run is not shown for ever.
  if (begun !== null && now - begun < STALE_RUN_MS) return { kind: 'running', focus: '', tokens, attempt: 1 }
  if (request?.state === 'queued') {
    const tried = request.attempts ?? 0
    return { kind: 'queued', focus: request.focus ?? '', minimum: number(request.min_context_tokens), tokens,
      attempt: tried + 1, last: tried > 0 ? request.reason ?? '' : '' }
  }
  if (request !== null && request !== undefined) return null
  const at = number(result?.at)
  if (at === null || result.dismissed === true || now - at > SHOW_MS) return null
  if (result.action === 'compacted') {
    const started = number(result.started_at)
    return { kind: 'compacted', at, before: number(result.tokens_before), after: number(result.tokens_after),
      seconds: started === null ? null : (at - started) / 1000 }
  }
  return { kind: result.action === 'error' ? 'failed' : 'idle', at, reason: result.reason ?? '' }
}

const MARKS = {
  queued: `<circle cx="8" cy="8" r="6" fill="none" stroke="${AMBER}" stroke-width="1.6"/>`
    + `<circle cx="8" cy="8" r="2.6" fill="${AMBER}"><animate attributeName="opacity" values="1;0.2;1" dur="1.6s" repeatCount="indefinite"/></circle>`,
  running: `<circle cx="8" cy="8" r="6" fill="none" stroke="${GREY}" stroke-opacity="0.35" stroke-width="2"/>`
    + `<path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="${AMBER}" stroke-width="2" stroke-linecap="round">`
    + '<animateTransform attributeName="transform" type="rotate" from="0 8 8" to="360 8 8" dur="0.9s" repeatCount="indefinite"/></path>',
  compacted: `<circle cx="8" cy="8" r="7" fill="${GREEN}"/>`
    + '<path d="M4.6 8.3l2.2 2.2 4.4-4.7" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
  failed: `<circle cx="8" cy="8" r="7" fill="${RED}"/>`
    + '<path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>',
  idle: `<circle cx="8" cy="8" r="6" fill="none" stroke="${GREY}" stroke-width="1.6"/>`
    + `<path d="M5.5 8h5" stroke="${GREY}" stroke-width="1.6" stroke-linecap="round"/>`,
}

/** The drawn mark, and for a compaction its meter of what was kept (72 px), as one SVG. */
export function picture(kind, share) {
  let body = MARKS[kind]
  let width = 16
  if (share !== null) {
    const kept = Math.max(2, Math.round(72 * Math.min(share, 1)))
    body += `<rect x="24" y="5" width="72" height="6" rx="3" fill="${GREY}" fill-opacity="0.3"/>`
      + `<rect x="24" y="5" width="${kept}" height="6" rx="3" fill="${GREEN}"/>`
    width = 96
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} 16" width="${width}" height="16">${CLEAR}${body}</svg>`
}

const GLYPHS = { queued: '◇', running: '◆', compacted: '✓', failed: '✗', idle: '○' }
const COLORS = { queued: 'warning', running: 'warning', compacted: 'success', failed: 'error', idle: undefined }
const SAYS = { queued: 'queued', running: 'compacting', compacted: 'compacted', failed: 'failed', idle: 'not compacted' }

function dim(el, text) {
  return text ? el.Text({ dimColor: true, wrap: 'truncate-end', children: text }) : null
}

function tries(m) {
  return m.attempt > 1 ? `try ${m.attempt}/${ATTEMPTS}` + (m.last ? ` (${m.last})` : '') : ''
}

function joined(parts) {
  return parts.filter(Boolean).join(' · ')
}

/**
 * The band's row for `m` on `surface`, above what the plugins beneath drew
 * (`below`). `act` holds what the buttons do: `cancel` and `dismiss`.
 */
export function draw(el, surface, m, act, below) {
  const drawn = surface !== 'terminal'
  const color = COLORS[m.kind]
  const sized = m.kind === 'compacted' && m.before !== null && m.after !== null
  const share = sized && m.before > 0 ? m.after / m.before : null
  const row = []
  if (drawn) {
    const alt = sized ? `${thousands(m.before)} tokens before, ${thousands(m.after)} after` : `conPACT ${SAYS[m.kind]}`
    const moving = m.kind === 'queued' || m.kind === 'running'
    // Only a drawing that moves needs the sandboxed frame its animation runs in.
    row.push(el.Svg({ source: picture(m.kind, share), alt, width: share === null ? 16 : 96, height: 16,
      ...(moving ? { isInteractive: true } : {}) }))
  }
  const mark = drawn ? 'conPACT' : `${GLYPHS[m.kind]} conPACT`
  row.push(el.Text(color ? { color, bold: true, children: mark } : { dimColor: true, bold: true, children: mark }))
  if (m.kind === 'compacted') {
    row.push(el.Text({ bold: true, children: sized ? `${short(m.before)} → ${short(m.after)}` : SAYS.compacted }))
    if (share !== null && !drawn) {
      const [kept, rest] = meter(share, METER)
      row.push(el.Box({ flexDirection: 'row', children: [
        el.Text({ color: 'success', children: kept }), el.Text({ dimColor: true, children: rest })] }))
    }
    if (share !== null) row.push(el.Text({ color: 'success', children: `−${(100 * (1 - share)).toFixed(1)}%` }))
    row.push(dim(el, m.seconds !== null ? took(m.seconds) : ''))
  } else if (m.kind === 'queued') {
    row.push(el.Text({ children: SAYS.queued }))
    row.push(dim(el, joined([m.tokens !== null ? `${short(m.tokens)} now` : '',
      m.minimum !== null ? `≥ ${short(m.minimum)}` : '', tries(m), m.focus ? `keep: ${m.focus}` : ''])))
  } else if (m.kind === 'running') {
    row.push(el.Text({ children: m.tokens !== null ? `compacting ${short(m.tokens)}` : SAYS.running }))
    row.push(dim(el, joined([tries(m), m.focus ? `keep: ${m.focus}` : ''])))
  } else {
    row.push(el.Text(color ? { color, children: SAYS[m.kind] } : { children: SAYS[m.kind] }))
    row.push(dim(el, m.reason))
  }
  row.push(el.Box({ flexGrow: 1 }))
  if (m.kind === 'queued') {
    row.push(el.Button({ key: 'conpact-cancel', label: 'cancel', plain: true, dimColor: true, onPress: () => act.cancel() }))
  } else if (m.kind !== 'running') {
    row.push(el.Button({ key: 'conpact-dismiss', label: '×', plain: true, dimColor: true, role: 'dismiss',
      onPress: () => act.dismiss() }))
  }
  const ours = el.Box({ key: 'conpact', flexDirection: 'row', gap: 1, alignItems: 'center', children: row })
  return below === null || below === undefined ? ours : el.Box({ flexDirection: 'column', children: [ours, below] })
}