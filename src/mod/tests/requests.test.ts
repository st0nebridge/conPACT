/**
 * @module mod.tests.requests
 * @description The request records on their own, through a host that is a
 *              plain in-memory store: when a request may run, what a claim
 *              keeps, and what a release puts back.
 */
import { expect, test } from 'claude-code/testing'
import { claim, release, runnable } from '../hooks/requests.js'
import { STALE_RUN_MS } from '../hooks/rules.js'

function host() {
  const saved = new Map<string, unknown>()
  return {
    saved,
    store: {
      get: async (key: string) => saved.get(key),
      set: async (key: string, value: unknown) => { saved.set(key, value) },
      delete: async (key: string) => { saved.delete(key) },
      keys: async () => [...saved.keys()],
    },
  }
}

test('a request may run when queued, or when a run of it has gone stale', async () => {
  expect(runnable(null, 0)).toBe(false)
  expect(runnable({ state: 'queued' }, 0)).toBe(true)
  expect(runnable({ state: 'executing', started_at: 1000 }, 1000 + STALE_RUN_MS - 1)).toBe(false)
  expect(runnable({ state: 'executing', started_at: 1000 }, 1000 + STALE_RUN_MS)).toBe(true)
  expect(runnable({ state: 'executing' }, STALE_RUN_MS)).toBe(true)
  expect(runnable({ state: 'executing' }, STALE_RUN_MS - 1)).toBe(false)
  expect(runnable({ state: 'done' }, 10 * STALE_RUN_MS)).toBe(false)
})

test('a claim marks the request running, counts the try and keeps it', async () => {
  const h = host()
  h.saved.set('request:s', { state: 'queued', focus: 'f', min_context_tokens: null, requested_at: 5 })
  const claimed = await claim(h, 's', 99)
  expect(claimed).toEqual({ state: 'executing', focus: 'f', min_context_tokens: null, requested_at: 5, started_at: 99, attempts: 1 })
  expect(h.saved.get('request:s')).toEqual(claimed)
  expect(await claim(h, 's', 100)).toBe(null)
  expect(await claim(h, 'nobody', 100)).toBe(null)
})

test('a release puts the request back in the queue with its reason and its tries', async () => {
  const h = host()
  await release(h, 's', { state: 'executing', focus: '', started_at: 9, attempts: 2 }, 'busy')
  expect(h.saved.get('request:s')).toEqual({ state: 'queued', focus: '', attempts: 2, reason: 'busy' })
})
