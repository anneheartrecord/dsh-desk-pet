/**
 * Exercise the host plugin against a stand-in cordis context.
 *
 * `plugin/index.mjs` is otherwise only string-matched, which cannot tell a
 * plugin that loads from one that throws the moment it is applied.
 *
 * This used to exercise four HTTP routes. Those are gone along with the in-page
 * pet, and the plugin now has one job: start the desktop process, stop it again
 * on teardown, and touch the page not at all.
 *
 * Run: node tests/plugin_smoke.mjs   (exits non-zero on failure)
 */
import assert from 'node:assert/strict'
import { apply, inject, name } from '../plugin/index.mjs'

let failures = 0
const check = async (label, fn) => {
  try { await fn(); console.log(`  ok   ${label}`) }
  catch (err) { failures++; console.log(`  FAIL ${label}\n       ${err.message}`) }
}

/** A context that records everything the plugin does to its host. */
const makeCtx = () => {
  const calls = { registered: [], tapped: 0, effects: [], warnings: [] }
  return {
    calls,
    logger: { warn: (m) => calls.warnings.push(m) },
    webServer: {
      register(entry) { calls.registered.push(entry); return () => {} },
      tapIndex() { calls.tapped++; return () => {} },
    },
    effect(fn) { calls.effects.push(fn()) },
  }
}

await check('declares the surface DSH loads it by', async () => {
  assert.equal(name, 'dsh-desk-pet')
  assert.equal(typeof apply, 'function')
  // The gate that keeps a window off the screen during a headless run.
  assert.deepEqual(inject, ['webServer'])
})

await check('applies without throwing, and registers a teardown', async () => {
  const ctx = makeCtx()
  apply(ctx)
  assert.equal(ctx.calls.effects.length, 1, 'nothing registered for teardown')
  assert.equal(typeof ctx.calls.effects[0], 'function', 'teardown is not callable')
  ctx.calls.effects[0]()
})

await check('puts nothing into the page', async () => {
  const ctx = makeCtx()
  apply(ctx)
  try {
    assert.deepEqual(ctx.calls.registered, [], 'a route was registered')
    assert.equal(ctx.calls.tapped, 0, 'the index was tapped')
  } finally {
    ctx.calls.effects[0]?.()
  }
})

await check('teardown is safe to run twice', async () => {
  const ctx = makeCtx()
  apply(ctx)
  const stop = ctx.calls.effects[0]
  stop()
  stop() // a second dispose must not throw on an already-killed child
})

console.log(failures ? `\n${failures} failed` : '\nall plugin checks ok')
process.exit(failures ? 1 : 0)
