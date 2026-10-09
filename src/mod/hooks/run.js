/**
 * @module mod.run
 * @description Runs a session's queued compaction once its turn is over:
 *              claims the request, checks the minimum context size once (the
 *              request's own, else the user's default), and compacts the
 *              session in-process with $.session.compact - the same operation
 *              /compact runs - with the request's focus as its instructions,
 *              followed by the provenance clause (rules.compactInstructions,
 *              D-20261009-090).
 *              Every outcome is recorded (compacted, below_threshold, skipped,
 *              error) with when its run began, and shown outside the
 *              conversation: in the band above the prompt (mod.band), and as
 *              a toast when it failed. A run that could not start - the
 *              session busy with a new turn already - goes back in the queue
 *              for the next turn end, up to three tries. A run lost with the
 *              load of the mod that made it - the mod reloaded mid-run - is
 *              ended by the compaction it started, when that compaction
 *              reaches the load that is there now (adopt).
 * @input      the host (the mods API calls register.js lends it), the session id the turn ended in
 * @output     the outcome, kept as the session's last result and shown
 * @dependencies mod.files, mod.requests, mod.rules
 */
import * as files from './files.js'
import * as requests from './requests.js'
import { ATTEMPTS, compactInstructions, decide } from './rules.js'

// The sessions this load of the mod is running a request for. A reload starts it empty.
const live = new Set()

/** Says a failed compaction aloud, in a toast; the band shows every outcome. */
export function show(host, outcome) {
  if (outcome.action === 'error') host.ui.toast(`compaction failed: ${outcome.reason}`)
}

function count(value) {
  return typeof value === 'number' ? value : null
}

async function compact(host, request, tokens) {
  const answer = await host.session.compact({ instructions: compactInstructions(request.focus) })
  if (typeof answer?.skip === 'string') return { action: 'skipped', reason: answer.skip }
  return { action: 'compacted', reason: '', tokens_before: count(answer?.tokensBefore) ?? tokens,
    tokens_after: count(answer?.tokensAfter) }
}

/**
 * Ends the session's request with `compaction` if a run of it began and no run
 * of this load owns it: the run that began it went with an earlier load, and
 * this is the compaction it started. True if it did.
 */
export async function adopt(host, id, compaction) {
  if (live.has(id)) return false
  const request = await requests.pending(host, id)
  if (request?.state !== 'executing') return false
  await requests.finish(host, id, {
    action: 'compacted', reason: '', tokens_before: count(compaction?.tokensBefore),
    tokens_after: count(compaction?.tokensAfter), at: await host.clock.now(), started_at: request.started_at,
    focus: request.focus, context_tokens: null, min_context_tokens: request.min_context_tokens ?? null,
    attempts: request.attempts,
  })
  host.ui.changed()
  return true
}

/** Runs `id`'s request if it is still the session's and still runnable. Never throws. */
export async function execute(host, id) {
  if (live.has(id)) return
  live.add(id)
  try {
    await run(host, id)
  } finally {
    live.delete(id)
  }
}

async function run(host, id) {
  try {
    if (await host.session.id() !== id) return
    const request = await requests.claim(host, id, await host.clock.now())
    if (request === null) return
    host.ui.changed()
    let tokens = null
    let minimum = request.min_context_tokens ?? null
    let outcome
    try {
      if (minimum === null) minimum = (await files.settings(host)).closureMinimum
      const usage = await host.session.usage()
      tokens = typeof usage?.context?.tokens === 'number' ? usage.context.tokens : null
      outcome = decide(tokens, minimum) ?? await compact(host, request, tokens)
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error)
      if (request.attempts < ATTEMPTS) {
        await requests.release(host, id, request, reason)
        host.ui.changed()
        return
      }
      outcome = { action: 'error', reason }
    }
    const result = { ...outcome, at: await host.clock.now(), started_at: request.started_at, focus: request.focus,
      context_tokens: tokens, min_context_tokens: minimum, attempts: request.attempts }
    await requests.finish(host, id, result)
    host.ui.changed()
    show(host, result)
  } catch {
    // A run that fails here is run again once its claim is stale (STALE_RUN_MS).
  }
}
