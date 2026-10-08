/**
 * @module mod.tools
 * @description The answers to the three conPACT tools the mod takes over from
 *              the MCP server - queue_compaction, cancel_compaction and
 *              compaction_status - for the session that calls them. The tool
 *              names, arguments, refusals and words are the server's
 *              (conpact.mcp_tools), so an agent cannot tell which side
 *              answered except by the `transport` field the mod adds. Each
 *              answer is MCP content, as the server's is: the words for the
 *              model first, then the same data as JSON. A refusal is a
 *              `{ deny }`, which the model reads as the tool's error.
 * @input      the host (the mods API calls register.js lends it) and the tool call's event (its arguments)
 * @output     `{ result: [text, json] }` or `{ deny: words }`
 * @dependencies mod.files, mod.requests, mod.rules
 */
import * as files from './files.js'
import * as requests from './requests.js'
import { MAX_FOCUS_CHARS, checkMinimum, isSessionId, isSpinOff, normalizeFocus, thousands, unexpected } from './rules.js'

export const TRANSPORT = 'mod'

// Keys tool.call carries beside a tool's own arguments.
const RESERVED = ['tool', 'tool_use_id', 'consent', 'agentId']

export const SPIN_OFF_REFUSAL = (
  'Nothing was queued: this session is working in a .claude/worktrees/... checkout, which is a '
  + 'throwaway spin-off. Those are merged and archived rather than resumed, so the summary a '
  + 'compaction writes here is never read and the compaction spends a turn on nothing. This is not '
  + 'an error and there is nothing to retry: finish your answer, and say in one clause that you '
  + 'skipped the compaction because this is a spin-off session. (The user can turn this off in the '
  + 'conPACT settings.)'
)

class Refusal extends Error {}

function reply(text, data) {
  return { result: [{ type: 'text', text }, { type: 'text', text: JSON.stringify(data) }] }
}

function argumentsOf(e) {
  return Object.fromEntries(Object.entries(e).filter(([key]) => !RESERVED.includes(key)))
}

function only(args, allowed, nothing) {
  const extra = unexpected(args, allowed)
  if (extra.length > 0) {
    throw new Refusal(`Unexpected argument(s): ${extra.join(', ')}. This tool never takes a target session - `
      + `it always acts on the session that called it. ${nothing}`)
  }
}

async function sessionId(host, nothing) {
  const id = await host.session.id()
  if (!isSessionId(id)) {
    throw new Refusal(`This session has no usable session id (${pythonRepr(id)}). ${nothing} Tell the user and stop.`)
  }
  return id
}

function pythonRepr(value) {
  return typeof value === 'string' ? `'${value}'` : 'None'
}

export async function contextTokens(host) {
  const usage = await host.session.usage()
  const tokens = usage?.context?.tokens
  return typeof tokens === 'number' ? tokens : null
}

async function answering(work) {
  try {
    return await work()
  } catch (error) {
    if (error instanceof Refusal) return { deny: error.message }
    throw error
  }
}

export function queue(host, e) {
  const nothing = 'Nothing was queued.'
  return answering(async () => {
    const args = argumentsOf(e)
    only(args, ['focus', 'min_context_tokens'], nothing)
    const focus = args.focus ?? ''
    if (typeof focus !== 'string' || Array.from(focus).length > MAX_FOCUS_CHARS) {
      throw new Refusal(`focus must be text of at most ${MAX_FOCUS_CHARS} characters. ${nothing}`)
    }
    const checked = checkMinimum(args.min_context_tokens)
    if (checked.error !== undefined) throw new Refusal(`${checked.error}. ${nothing}`)
    const minimum = checked.minimum
    const id = await sessionId(host, nothing)
    const line = normalizeFocus(focus)
    const tokens = await contextTokens(host)
    const data = { queued: false, replaced: false, session_id: id, focus: line, min_context_tokens: minimum,
      context_tokens: tokens, transport: TRANSPORT }
    const { guardSpinOff } = await files.settings(host)
    if (guardSpinOff && isSpinOff(await host.session.cwd())) return reply(SPIN_OFF_REFUSAL, data)
    const earlier = await requests.pending(host, id)
    if (earlier?.state === 'executing') {
      return reply('A compaction of this session is already running, so nothing more was queued.', data)
    }
    await requests.put(host, id, { state: 'queued', focus: line, min_context_tokens: minimum,
      requested_at: await host.clock.now(), attempts: 0 })
    host.ui.changed()
    const replaced = earlier !== null
    let text = 'Compaction queued for this session. It runs at the end of this turn, after your final answer'
    text += (minimum !== null ? `, only if the context is then at least ${minimum} tokens` : '') + '.'
    if (tokens !== null) text += ` The context is about ${tokens} tokens now.`
    if (replaced) text += ' This replaced the request that was already queued.'
    text += ' Finish your answer normally; do not call this again.'
    return reply(text, { ...data, queued: true, replaced })
  })
}

/** Withdraws the session's request if it is waiting for a run: the band's Cancel. True if it did. */
export async function withdraw(host, id) {
  if (!requests.runnable(await requests.pending(host, id), await host.clock.now())) return false
  await requests.drop(host, id)
  host.ui.changed()
  return true
}

export function cancel(host, e) {
  const nothing = 'Nothing was cancelled.'
  return answering(async () => {
    only(argumentsOf(e), [], nothing)
    const id = await sessionId(host, nothing)
    const request = await requests.pending(host, id)
    const data = { cancelled: false, session_id: id, transport: TRANSPORT }
    if (request === null) return reply('Nothing was queued for this session.', data)
    if (!requests.runnable(request, await host.clock.now())) {
      return reply('The compaction has already begun and cannot be withdrawn.', data)
    }
    await requests.drop(host, id)
    host.ui.changed()
    return reply('Cancelled the queued compaction.', { ...data, cancelled: true })
  })
}

function lastWords(last) {
  if (last.action === 'compacted' && typeof last.tokens_before === 'number' && typeof last.tokens_after === 'number') {
    return `compacted, ${thousands(last.tokens_before)} to ${thousands(last.tokens_after)} tokens`
  }
  return last.reason ? `${last.action} (${last.reason})` : String(last.action)
}

export function status(host, e) {
  return answering(async () => {
    only(argumentsOf(e), [], 'Nothing was changed.')
    const id = await sessionId(host, 'Nothing was changed.')
    const request = await requests.pending(host, id)
    const last = await requests.lastResult(host, id)
    const tokens = await contextTokens(host)
    const held = await files.holdLeft(host, id, await host.clock.now())
    const data = {
      pending: request !== null, session_id: id,
      focus: request ? normalizeFocus(request.focus) : null,
      min_context_tokens: request ? request.min_context_tokens ?? null : null,
      context_tokens: tokens, hold_minutes_left: held, transport: TRANSPORT,
      state: request ? request.state : null, last,
    }
    let text = request ? 'A compaction is queued for the end of this turn.' : 'Nothing is queued for this session.'
    if (tokens !== null) text += ` The context is about ${tokens} tokens.`
    if (held !== null) text += ` The early idle toast is held for another ${held} minutes.`
    if (last !== null) text += ` The last compaction here: ${lastWords(last)}.`
    return reply(text, data)
  })
}
