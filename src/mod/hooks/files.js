/**
 * @module mod.files
 * @description conPACT's own files, the only ones the mod touches, all under
 *              ~/.conpact/. It reads the user's settings (settings.json) and
 *              the early idle toast's hold for this session
 *              (idle/hold/<id>.json), both written by the Python side; and,
 *              for the idle toast's hand-off (mod.handoff), it reads the
 *              watcher's ask and writes its own beat and answer under mod/.
 *              The home is USERPROFILE where it is set and HOME otherwise,
 *              which is where Python's expanduser("~") looks. A file that is
 *              missing or unreadable reads as absent.
 * @input      the host (the mods API calls register.js lends it), a plain session id, the time
 * @output     the settings the mod acts on; minutes left on a hold; the text
 *              of a file under ~/.conpact/; a record written as JSON
 * @dependencies mod.rules
 */
import { holdMinutesLeft, readSettings } from './rules.js'

async function home(host) {
  const profile = await host.env.get('USERPROFILE')
  if (profile) return profile
  const posix = await host.env.get('HOME')
  return posix || null
}

async function place(host, relative) {
  const base = await home(host)
  return base === null ? null : base.replace(/[\\/]+$/, '') + '/.conpact/' + relative
}

/** The text of a file under ~/.conpact/, or undefined. */
export async function read(host, relative) {
  const path = await place(host, relative)
  if (path === null) return undefined
  try {
    return await host.fs.read(path)
  } catch {
    return undefined
  }
}

/** Writes `data` as JSON to a file under ~/.conpact/; rejects when it cannot. */
export async function write(host, relative, data) {
  const path = await place(host, relative)
  if (path === null) throw new Error('no home folder to write in')
  await host.fs.write(path, JSON.stringify(data))
}

export async function settings(host) {
  return readSettings(await read(host, 'settings.json'))
}

export async function holdLeft(host, id, now) {
  return holdMinutesLeft(await read(host, 'idle/hold/' + id + '.json'), now)
}
