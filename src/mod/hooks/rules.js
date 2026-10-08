/**
 * @module mod.rules
 * @description The rules the mod shares with conPACT's Python side, as plain
 *              functions of their inputs: the focus line, the minimum context
 *              size, a plain session id, a throwaway worktree session, the
 *              user's settings file, the early toast's hold, whether a
 *              turn-end compaction goes ahead, and the only files the mod may
 *              write. Each one matches its Python twin
 *              (conpact.compaction, conpact.session_registry, conpact.spin_off,
 *              conpact.settings, conpact.mcp_tools) value for value, so a
 *              request means the same whichever side handles it.
 * @input      values: text, numbers, a settings file's text, the time
 * @output     normalised values, refusals as words, verdicts
 * @dependencies none
 */

export const MAX_FOCUS_CHARS = 500
// A sanity bound for min_context_tokens, well above any context window.
export const MAX_CONTEXT_TOKENS = 10_000_000
// A request a reload left marked as running is retried after this long.
export const STALE_RUN_MS = 10 * 60_000
// How many times a turn end tries to compact before it gives up.
export const ATTEMPTS = 3
// Records older than this are cleared when a session starts.
export const KEEP_MS = 7 * 24 * 3600 * 1000

const SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/
// The only files the mod writes: its beat and its answers to the idle toast,
// under ~/.conpact/mod/ (D-20261002-066).
const WRITABLE = /[\\/]\.conpact[\\/]mod[\\/](beat|answer)[\\/][A-Za-z0-9_-]{1,128}\.json$/
const UPWARD = /(^|[\\/])\.\.([\\/]|$)/

// What Python's str.isprintable() refuses: control, format, surrogate,
// private-use and unassigned characters, and every separator but the space.
const UNPRINTABLE = /[\p{C}\p{Z}]/gu

/** One line, printable characters only, at most MAX_FOCUS_CHARS long. */
export function normalizeFocus(focus) {
  if (typeof focus !== 'string') return ''
  const words = focus.replace(UNPRINTABLE, ' ').split(' ').filter(Boolean)
  return Array.from(words.join(' ')).slice(0, MAX_FOCUS_CHARS).join('').trimEnd()
}

/** `{ minimum }` (null for none) or `{ error }` in the server's words. */
export function checkMinimum(value) {
  if (value === undefined || value === null) return { minimum: null }
  if (!Number.isInteger(value) || value < 1 || value > MAX_CONTEXT_TOKENS) {
    return { error: `min_context_tokens must be a whole number from 1 to ${MAX_CONTEXT_TOKENS}` }
  }
  return { minimum: value }
}

export function isSessionId(id) {
  return typeof id === 'string' && SESSION_ID.test(id)
}

/**
 * True when `cwd` is inside a checkout under `.claude/worktrees/`: the two
 * names adjacent, in that order, with something after them.
 */
export function isSpinOff(cwd) {
  if (typeof cwd !== 'string') return false
  const parts = cwd.replace(/\\/g, '/').split('/').filter(Boolean).map((p) => p.toLowerCase())
  for (let i = 0; i < parts.length - 2; i++) {
    if (parts[i] === '.claude' && parts[i + 1] === 'worktrees') return true
  }
  return false
}

function parse(text) {
  if (typeof text !== 'string') return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * The two settings the mod acts on, from settings.json's text. A value the
 * Python side would reject is ignored there, so it is ignored here too.
 */
export function readSettings(text) {
  const data = parse(text)
  const settings = { closureMinimum: null, guardSpinOff: true }
  if (!isRecord(data)) return settings
  const minimum = checkMinimum(data.closure_min_context_tokens)
  if (minimum.error === undefined) settings.closureMinimum = minimum.minimum
  if (typeof data.guard_spin_off_sessions === 'boolean') settings.guardSpinOff = data.guard_spin_off_sessions
  return settings
}

/** Whether `path` is one the mod may write: a session's beat or answer, under ~/.conpact/mod/, with no `..`. */
export function isWritable(path) {
  return typeof path === 'string' && WRITABLE.test(path) && !UPWARD.test(path)
}

/** Python's round(): halves go to the even neighbour. */
export function roundHalfEven(x) {
  const floor = Math.floor(x)
  const diff = x - floor
  if (diff > 0.5) return floor + 1
  if (diff < 0.5) return floor
  return floor % 2 === 0 ? floor : floor + 1
}

/** Whole minutes left on a hold file's text, or null when none is running. */
export function holdMinutesLeft(text, nowMs) {
  const data = parse(text)
  if (!isRecord(data) || typeof data.until !== 'number') return null
  const left = data.until - nowMs / 1000
  return left > 0 ? roundHalfEven(left / 60) : null
}

/** The argument names a tool does not take, sorted. */
export function unexpected(args, allowed) {
  return Object.keys(args).filter((key) => !allowed.includes(key)).sort()
}

export function thousands(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/**
 * Null when a turn-end compaction goes ahead; otherwise the outcome that
 * stops it. A minimum is a one-shot condition, checked once at the turn end.
 */
export function decide(tokens, minimum) {
  if (minimum === null) return null
  if (tokens === null) return { action: 'error', reason: 'context size could not be measured; not compacting' }
  if (tokens < minimum) {
    return { action: 'below_threshold', reason: `context ${tokens} tokens < minimum ${minimum}; not compacting` }
  }
  return null
}
