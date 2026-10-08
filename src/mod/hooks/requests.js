/**
 * @module mod.requests
 * @description Each session's compaction request and its last result, kept in
 *              the mod's own store ($.store), which every session on the
 *              machine shares and which outlives a reload of the mod. Keys are
 *              per session - `request:<id>` and `result:<id>` - so no session
 *              can see or spend another's. A request is `queued` until a turn
 *              end claims it (`executing`), then gone; the result stays until
 *              it is a week old. Beside them, `handoff:<id>` names the last
 *              idle toast request the session took (mod.handoff), so that one
 *              is never taken twice; it too goes after a week. `running:<id>`
 *              marks the idle toast's compaction while it runs, for the band;
 *              its outcome becomes the session's last result.
 * @input      the host (the mods API calls register.js lends it), a plain session id, the time
 * @output     the request and result records
 * @dependencies mod.rules
 */
import { KEEP_MS, STALE_RUN_MS } from './rules.js'

const REQUEST = 'request:'
const RESULT = 'result:'
const TAKEN = 'handoff:'
const RUNNING = 'running:'

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export async function pending(host, id) {
  const request = await host.store.get(REQUEST + id)
  return isRecord(request) ? request : null
}

export async function lastResult(host, id) {
  const result = await host.store.get(RESULT + id)
  return isRecord(result) ? result : null
}

export async function put(host, id, request) {
  await host.store.set(REQUEST + id, request)
}

export async function drop(host, id) {
  await host.store.delete(REQUEST + id)
}

/** Whether a turn end may run this request now: queued, or claimed by a run that was lost. It may be withdrawn too. */
export function runnable(request, now) {
  if (request === null) return false
  if (request.state === 'queued') return true
  return request.state === 'executing' && now - (request.started_at ?? 0) >= STALE_RUN_MS
}

/** Marks the session's request as running and returns it, or null if there is none to run. */
export async function claim(host, id, now) {
  const request = await pending(host, id)
  if (!runnable(request, now)) return null
  const claimed = { ...request, state: 'executing', started_at: now, attempts: (request.attempts ?? 0) + 1 }
  await put(host, id, claimed)
  return claimed
}

/** Puts a request whose run could not start back in the queue, saying why. */
export async function release(host, id, request, reason) {
  const { started_at: _, ...rest } = request
  await put(host, id, { ...rest, state: 'queued', reason })
}

/** Marks the session's last result, if it is still the one finished `at`, as dismissed from the band. */
export async function dismiss(host, id, at) {
  const result = await lastResult(host, id)
  if (result !== null && result.at === at) await host.store.set(RESULT + id, { ...result, dismissed: true })
}

/** The idle toast's compaction of the session while it runs, or null. */
export async function running(host, id) {
  const mark = await host.store.get(RUNNING + id)
  return isRecord(mark) ? mark : null
}

/** Marks the idle toast's compaction of the session as begun at `now`. */
export async function mark(host, id, now) {
  await host.store.set(RUNNING + id, { started_at: now })
}

/** Keeps `result` as the session's last, ending the idle toast's running mark; a waiting request is left alone. */
export async function record(host, id, result) {
  await host.store.set(RESULT + id, result)
  await host.store.delete(RUNNING + id)
}

/** Ends the request with its outcome. */
export async function finish(host, id, result) {
  await host.store.set(RESULT + id, result)
  await drop(host, id)
}

function stamp(key, value) {
  if (!isRecord(value)) return null
  if (key.startsWith(REQUEST)) return value.requested_at
  return key.startsWith(RUNNING) ? value.started_at : value.at
}

/** Whether the session has taken the idle toast's request `requestId` already. */
export async function isTaken(host, id, requestId) {
  const taken = await host.store.get(TAKEN + id)
  return isRecord(taken) && taken.request_id === requestId
}

/** Records that the session took the idle toast's request `requestId`. */
export async function take(host, id, requestId, now) {
  await host.store.set(TAKEN + id, { request_id: requestId, at: now })
}

/** Clears requests, results, taken requests and running marks more than a week old, and any that are not records. */
export async function prune(host, now) {
  for (const key of await host.store.keys()) {
    if (![REQUEST, RESULT, TAKEN, RUNNING].some((prefix) => key.startsWith(prefix))) continue
    const when = stamp(key, await host.store.get(key))
    if (typeof when !== 'number' || now - when > KEEP_MS) await host.store.delete(key)
  }
}
