/**
 * @module mod.handoff
 * @description The idle toast's way into the session. The toast is a separate
 *              process (conpact.idle_watch) that cannot reach inside Claude
 *              Code, so the two meet in three small files of conPACT's, one
 *              each per session, under ~/.conpact/mod/ (conpact.mod_handoff
 *              is the other side):
 *              - beat/<id>.json, written here every BEAT_MS while the session
 *                runs and once more, `ended`, when it ends: how the watcher
 *                knows the mod is there to ask;
 *              - ask/<id>.json, written by the watcher: one request, with an
 *                id and a time it lapses at, which this looks for every
 *                POLL_MS;
 *              - answer/<id>.json, written here: `claimed` as a request is
 *                taken, then how the compaction went.
 *              A mod cannot delete a file, so the ask stays until the watcher
 *              removes it: a request is taken once, by its id, which the store
 *              keeps (mod.requests), and never once it has lapsed, so a
 *              watcher that gave up on it is not followed by a compaction.
 *              The compaction is the one /compact runs, with no focus - the
 *              toast has none - but with the provenance clause every conPACT
 *              compaction carries (rules.compactInstructions,
 *              D-20261009-090), as the bridge's /compact does. While it runs
 *              the band shows it running, and after it, its outcome as the
 *              session's last result; an agent's request still waiting is
 *              left as it was.
 * @input      the host (the mods API calls register.js lends it), a plain session id
 * @output     the beat; the session compacted for a new request, and the answer
 * @dependencies mod.files, mod.requests, mod.rules, mod.run
 */
import * as files from './files.js'
import * as requests from './requests.js'
import { compactInstructions } from './rules.js'
import { show } from './run.js'

// The watcher's twins are conpact.mod_handoff.BEAT_SECONDS and POLL_SECONDS.
export const BEAT_MS = 30_000
export const POLL_MS = 2_000
const REQUEST_ID = /^[A-Za-z0-9-]{1,64}$/

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** The request in an ask file's text, if it is this session's, well formed and not lapsed. */
export function readAsk(text, id, now) {
  let data
  try {
    data = JSON.parse(text)
  } catch {
    return null
  }
  if (!isRecord(data) || data.session_id !== id) return null
  if (typeof data.request_id !== 'string' || !REQUEST_ID.test(data.request_id)) return null
  if (typeof data.expires_at !== 'number' || now / 1000 > data.expires_at) return null
  return { request_id: data.request_id }
}

/** Says the mod is here (or, `ended`, that it no longer is). Never throws. */
export async function beat(host, id, ended = false) {
  try {
    const now = await host.clock.now()
    await files.write(host, 'mod/beat/' + id + '.json', { session_id: id, at: now / 1000, ended })
  } catch {
    // A missed beat is the next one's to make; three missed and the watcher uses the bridge.
  }
}

/** The session's new request, now marked taken, or null if there is none to take. */
export async function claim(host, id, now) {
  const ask = readAsk(await files.read(host, 'mod/ask/' + id + '.json'), id, now)
  if (ask === null || await requests.isTaken(host, id, ask.request_id)) return null
  await requests.take(host, id, ask.request_id, now)
  return ask
}

async function answer(host, id, ask, fields) {
  await files.write(host, 'mod/answer/' + id + '.json',
    { session_id: id, request_id: ask.request_id, at: (await host.clock.now()) / 1000, ...fields })
}

async function compact(host) {
  try {
    const result = await host.session.compact({ instructions: compactInstructions('') })
    if (typeof result?.skip === 'string') return { action: 'skipped', reason: result.skip }
    return {
      action: 'compacted', reason: '',
      tokens_before: typeof result?.tokensBefore === 'number' ? result.tokensBefore : null,
      tokens_after: typeof result?.tokensAfter === 'number' ? result.tokensAfter : null,
    }
  } catch (error) {
    return { action: 'error', reason: error instanceof Error ? error.message : String(error) }
  }
}

/** One look for a request: a new one is taken, the session compacted, and the outcome answered. Never throws. */
export async function serve(host, id) {
  try {
    const ask = await claim(host, id, await host.clock.now())
    if (ask === null) return
    await answer(host, id, ask, { action: 'claimed' })
    const started = await host.clock.now()
    await requests.mark(host, id, started)
    host.ui.changed()
    const outcome = await compact(host)
    await requests.record(host, id, { ...outcome, at: await host.clock.now(), started_at: started, via: 'idle toast' })
    host.ui.changed()
    await answer(host, id, ask, outcome)
    show(host, outcome)
  } catch {
    // An ask not answered lapses, and the watcher says the compaction failed.
  }
}
