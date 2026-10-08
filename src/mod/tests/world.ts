/**
 * @module mod.tests.world
 * @description A stand-in for everything the mod asks Claude Code for, so a
 *              test can fire events without a session: the store, the
 *              session's id, directory and context size, environment
 *              variables, files under conPACT's home (read and written), the
 *              transcript's log lines, toasts, the clock, and the compaction
 *              itself, the engine's empty band above the prompt, and the commands run (an SDK session's /compact is
 *              stood in for where it is tested, mod.tests.sdk). Each test builds one and reads back what the mod did.
 * @input      the test's `on`, and what the world should hold
 * @output     the world: what the mod saved, showed and asked to compact
 * @dependencies claude-code/testing
 */
import { mock } from 'claude-code/testing'

export const HOME = 'C:/Users/someone'
export const STATE = HOME + '/.conpact'
export const SESSION = '0b6e4d6f-e5a9-441e-4c56-5248db621442'

export type Compaction =
  | { messages: unknown[]; tokensBefore?: number; tokensAfter?: number }
  | { skip: string }

export type WorldOptions = {
  id?: string | null
  cwd?: string
  tokens?: number | null
  env?: Record<string, string>
  files?: Record<string, string>
  compact?: (e: { instructions?: string; trigger?: string }) => Compaction | 'reject'
  now?: number
  // session.usage fails, as a host that cannot say might
  failUsage?: boolean
  // Awaited before session.usage answers: a test holds a drawing part-way with it.
  beforeUsage?: () => unknown
}

export type World = {
  saved: Map<string, unknown>
  files: Map<string, string>
  logs: string[]
  toasts: string[]
  compactions: { instructions?: string; trigger?: string }[]
  commands: { command: string; args: string }[]
  clock: ReturnType<typeof mock.clock>
  id: string
  tokens: number | null
}

// The test host hands fs.read an absolute path, with a drive on Windows.
function plain(path: string): string {
  return path.replace(/\\/g, '/').replace(/^[A-Za-z]:/, '')
}

export const KEPT = [{ role: 'assistant', text: 'the summary', toolUses: [] }]

export function world(on: any, options: WorldOptions = {}): World {
  const w: World = {
    saved: new Map(),
    files: new Map(Object.entries(options.files ?? {}).map(([k, v]) => [plain(k), v])),
    logs: [],
    toasts: [],
    compactions: [],
    commands: [],
    clock: undefined as any,
    id: 'id' in options ? (options.id as string) : SESSION,
    tokens: options.tokens === undefined ? 412_880 : options.tokens,
  }
  const env = options.env ?? { USERPROFILE: HOME }
  on('store.get', ($: any, e: any) => ({ value: w.saved.get(e.key) }))
  on('store.set', ($: any, e: any) => {
    w.saved.set(e.key, JSON.parse(JSON.stringify(e.value)))
    return { value: undefined }
  })
  on('store.delete', ($: any, e: any) => {
    w.saved.delete(e.key)
    return { value: undefined }
  })
  on('store.keys', () => ({ value: [...w.saved.keys()] }))
  on('session.id', () => ({ value: w.id }))
  on('session.cwd', () => ({ value: options.cwd ?? 'C:/work/project' }))
  on('session.usage', async () => {
    await options.beforeUsage?.()
    return usage()
  })
  const usage = () => options.failUsage ? { deny: 'usage unavailable' } : ({
    value: {
      context: w.tokens === null ? { window: 1_000_000 } : { tokens: w.tokens, window: 1_000_000, percent: Math.round(w.tokens / 10_000) },
      rateLimits: [],
    },
  })
  on('env.get', ($: any, e: any) => ({ value: env[e.name] }))
  on('fs.read', ($: any, e: any) => {
    const path = plain(e.path)
    return w.files.has(path) ? { value: w.files.get(path) } : { deny: 'ENOENT: no such file: ' + path }
  })
  on('fs.write', ($: any, e: any) => {
    w.files.set(plain(e.path), e.text)
    return { value: undefined }
  })
  on('ui.log', ($: any, e: any) => {
    w.logs.push(e.text)
    return { value: undefined }
  })
  on('ui.toast', ($: any, e: any) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  on('session.compact', ($: any, e: any) => {
    w.compactions.push({ instructions: e.instructions, trigger: e.trigger })
    const answer = options.compact ? options.compact(e) : { messages: KEPT, tokensBefore: w.tokens ?? undefined, tokensAfter: 37_400 }
    if (answer === 'reject') throw new Error('a turn is running')
    return answer
  })
  on('turn.complete', () => ({ text: '' }))
  // What the plugins beneath draw in the band above the prompt: one line, so a test can see it kept.
  on('ui.render', ($: any, e: any) => $.ui.resolve(e).Box({ children: $.ui.resolve(e).Text({ children: 'beneath' }) }))
  on('session.start', () => ({ cwd: 'C:/work/project' }))
  on('session.end', () => ({ sessionId: w.id }))
  w.clock = mock.clock(on, { now: options.now ?? 1_790_000_000_000 })
  return w
}

export const QUEUE = 'mcp__conpact__queue_compaction'
export const CANCEL = 'mcp__conpact__cancel_compaction'
export const STATUS = 'mcp__conpact__compaction_status'

/** The prose and the data of a tool answer, as the model reads them. */
export function read(answer: any): { text: string; data: any } {
  const blocks = answer.result
  return { text: blocks[0].text, data: JSON.parse(blocks[1].text) }
}

export function turnEnd(fields: Record<string, unknown> = {}) {
  return { turnId: 't1', answer: 'done', durationMs: 1000, isAborted: false, usage: null, reason: 'answer', ...fields }
}
