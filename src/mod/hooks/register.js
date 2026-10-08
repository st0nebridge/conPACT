/**
 * @module mod.register
 * @description conPACT's Claude Code mod: compacts a session in-process at the
 *              end of the turn that asked for it, with no Remote Control and
 *              no /compact typed into the session. It answers the conPACT MCP
 *              server's queue, cancel and status tools itself (mod.tools), so
 *              the agent keeps the tools it knows; where the mod does not load,
 *              the server answers them and its Stop hook compacts over Remote
 *              Control as before. At each main-loop turn end that answered, a
 *              queued request is run just after the turn's own event
 *              (mod.run). A manual or automatic compaction that gets there
 *              first spends the request, so a session is not compacted twice;
 *              one that ends a run lost in a reload of the mod ends its
 *              request too.
 *              The early toast's hold, and everything else, stays the server's.
 *              The idle toast reaches the session through it too (mod.handoff):
 *              from the session's start it beats every 30 s and looks every
 *              2 s for the toast's request, which it runs at once - the
 *              session is idle - and says it has ended when it ends.
 *
 *              A session with no terminal behind it - the desktop app's Code
 *              tab, the Agent SDK, a -p run - refuses a mod's in-process
 *              compaction, so there the mod runs /compact as the person
 *              would ($.command.run, the one command it runs), the focus as
 *              its text, and takes the outcome from the compaction that
 *              command makes: the same operation, reached the other way.
 *
 *              The band above the prompt (mod.band) draws the request while
 *              it waits and runs and what it came to, with cancel and
 *              dismiss; it is drawn again whenever any of that changes, and
 *              once more a moment later, and a drawing that saw a change
 *              under way reads again.
 *
 *              Claude Code lists what a mod calls by reading this file, so
 *              every call is spelled out here, in `host`, and the other
 *              modules are handed `host` rather than $ itself. `host` is the
 *              whole of what the mod can reach.
 * @input      Claude Code's events: session.start, tool.call, turn.complete,
 *              session.compact, session.end, ui.render (the band above the
 *              prompt); the clock's two timers; whether
 *              the session has a terminal (session.start's isInteractive)
 * @output     tool answers; compactions between turns and for the idle toast;
 *              the beat and the toast's answers; the band; a toast when one failed
 * @dependencies mod.band, mod.handoff, mod.requests, mod.rules, mod.run, mod.tools
 */
import * as band from './band.js'
import * as handoff from './handoff.js'
import * as requests from './requests.js'
import { isSessionId, isWritable } from './rules.js'
import { adopt, execute } from './run.js'
import { cancel, contextTokens, queue, status, withdraw } from './tools.js'

/** The mods API calls the other modules may make, and no others. */
function host($) {
  return {
    clock: { now: () => $.clock.now() },
    session: {
      id: () => $.session.id(),
      cwd: () => $.session.cwd(),
      usage: () => $.session.usage(),
      compact: (args) => (headless ? compactByCommand($, args) : $.session.compact(args)),
    },
    env: {
      get: async (name) => {
        if (name === 'USERPROFILE') return $.env.get('USERPROFILE')
        if (name === 'HOME') return $.env.get('HOME')
        return undefined
      },
    },
    fs: {
      read: (path) => $.fs.read(path),
      write: async (path, text) => {
        if (!isWritable(path)) throw new Error('not a file conPACT writes')
        return $.fs.write(path, text)
      },
    },
    store: {
      get: (key) => $.store.get(key),
      set: (key, value) => $.store.set(key, value),
      delete: (key) => $.store.delete(key),
      keys: () => $.store.keys(),
    },
    ui: {
      // What the session's request or last result is has changed: the band draws it again,
      // and once more SETTLE_MS later, for a surface that kept a drawing begun before it.
      changed: () => {
        changes += 1
        $.ui.invalidate('ui.render')
        $.clock.after(band.SETTLE_MS, () => $.ui.invalidate('ui.render'))
      },
      toast: (text) => $.ui.toast(text),
    },
  }
}

let timers = []
// How many changes to the band this load has made: a drawing that saw one happen reads again.
let changes = 0
// A session with no terminal (session.start's isInteractive false), where
// $.session.compact is refused and /compact is the way in.
let headless = false
// While the mod's own /compact runs: what the compaction it made came to.
let commanded = null

/**
 * Compacts as /compact does, by running it: in an SDK session the engine
 * refuses $.session.compact outright. Resolves as $.session.compact would -
 * the compaction, or `{ skip }` - and rejects, in the engine's own words, when
 * the command made none.
 */
async function compactByCommand($, args) {
  const own = { result: null }
  commanded = own
  try {
    const ran = await $.command.run({ command: 'compact', args: args?.instructions ?? '' })
    if (own.result !== null) return own.result
    throw new Error(ran?.text || '/compact did not compact the session')
  } finally {
    if (commanded === own) commanded = null
  }
}

/** Runs `job` for the session as it is now: after a /clear it is another one. Never throws. */
function forSession($, job) {
  return async () => {
    try {
      const id = await $.session.id()
      if (isSessionId(id)) await job(host($), id)
    } catch {
      // The next tick tries again.
    }
  }
}

/** The idle toast's way in: a beat that says the mod is here, and a look for the toast's request. */
async function serveTheToast($) {
  for (const timer of timers) timer.cancel()
  await forSession($, handoff.beat)()
  timers = [
    $.clock.every(handoff.BEAT_MS, forSession($, handoff.beat)),
    $.clock.every(handoff.POLL_MS, forSession($, handoff.serve)),
  ]
}

export function register(on) {
  on('session.start', async ($, e, next) => {
    headless = e.isInteractive === false
    const result = await next(e)
    try {
      await requests.prune(host($), await $.clock.now())
    } catch {
      // Housekeeping only: a session starts whether or not it could be done.
    }
    await serveTheToast($)
    return result
  })

  // The watcher stops asking a session whose mod says it has ended.
  on('session.end', async ($, e, next) => {
    await forSession($, (lent, id) => handoff.beat(lent, id, true))()
    return next(e)
  })

  // Spelled out, so `claude plugin validate` shows which tools are taken over.
  on('tool.call', { tool: 'mcp__conpact__queue_compaction' }, async ($, e) => queue(host($), e))
  on('tool.call', { tool: 'mcp__conpact__cancel_compaction' }, async ($, e) => cancel(host($), e))
  on('tool.call', { tool: 'mcp__conpact__compaction_status' }, async ($, e) => status(host($), e))

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId !== undefined || e.reason !== 'answer') return result
    const id = await $.session.id()
    if (!isSessionId(id) || !requests.runnable(await requests.pending(host($), id), await $.clock.now())) return result
    // Compacting is refused while a turn runs, and this event is still the
    // turn's: the run starts once it has returned.
    $.clock.after(0, () => execute(host($), id))
    return result
  })

  // The band above the prompt: drawn over whatever the plugins beneath draw there.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const below = await next(e)
    if (e.props.hasSurvey) return below
    try {
      const lent = host($)
      const id = await $.session.id()
      if (!isSessionId(id)) return below
      const shown = await band.settled(() => changes, async () => band.model(await requests.pending(lent, id),
        await requests.lastResult(lent, id), await $.clock.now(), await contextTokens(lent),
        await requests.running(lent, id)))
      if (shown === null) return below
      return band.draw($.ui.resolve(e), e.surface, shown, {
        cancel: () => withdraw(host($), id),
        dismiss: async () => {
          await requests.dismiss(host($), id, shown.at)
          host($).ui.changed()
        },
      }, below)
    } catch {
      return below
    }
  })

  on('session.compact', async ($, e, next) => {
    const result = await next(e)
    const asked = e.trigger === 'manual' || e.trigger === 'auto'
    if (e.agentId !== undefined || (!asked && e.trigger !== 'plugin')) return result
    // The mod's own /compact: its run takes the outcome, and spends nothing else.
    if (commanded !== null && e.trigger === 'manual') {
      commanded.result = result
      return result
    }
    if (typeof result?.skip === 'string') return result
    const id = await $.session.id()
    if (!isSessionId(id)) return result
    // A run the mod lost in a reload mid-compaction: this is the compaction it started.
    if (await adopt(host($), id, result)) return result
    if (asked && (await requests.pending(host($), id))?.state === 'queued') {
      await requests.finish(host($), id, {
        action: 'superseded', reason: `the session was compacted (${e.trigger}) before the queued compaction ran`,
        at: await $.clock.now(),
      })
      host($).ui.changed()
    }
    return result
  })
}
