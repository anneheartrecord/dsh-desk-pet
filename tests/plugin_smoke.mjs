/**
 * Exercise the host plugin against a stand-in cordis context.
 *
 * The Python side is covered thoroughly, but `plugin/index.mjs` had never been
 * executed by anything — only string-matched. Registering a route that throws,
 * or serving a frame path that escapes the asset root, would have shipped.
 *
 * Run: node tests/plugin_smoke.mjs   (exits non-zero on failure)
 */
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')

// The plugin reads the state file from the real home, so point HOME at a temp
// dir before importing it — the module resolves that path at load time.
const home = mkdtempSync(path.join(os.tmpdir(), 'dsh-pet-smoke-'))
process.env.HOME = home
mkdirSync(path.join(home, '.dsh-desk-pet'), { recursive: true })

const { apply, name, inject } = await import('../plugin/index.mjs')

assert.equal(name, 'dsh-desk-pet')
assert.deepEqual(inject, ['webServer'])

/** Minimal response recorder shaped like node's ServerResponse. */
function fakeRes() {
  const res = {
    status: null,
    headers: null,
    body: '',
    chunks: [],
    writeHead(status, headers) { res.status = status; res.headers = headers ?? null },
    end(chunk) { if (chunk) res.body += chunk; res.ended = true },
    on() {}, once() {}, emit() {}, write(c) { res.chunks.push(c) },
  }
  return res
}

const routes = new Map()
let taps = []
const teardown = []
const ctx = {
  logger: { warn() {} },
  webServer: {
    register({ kind, path: routePath, handler }) {
      routes.set(routePath, { kind, handler })
      return () => routes.delete(routePath)
    },
    tapIndex(fn) {
      taps.push(fn)
      return () => { taps = taps.filter((f) => f !== fn) }
    },
  },
  effect(fn) { teardown.push(fn()) },
}

apply(ctx)

const call = async (routePath, url = routePath, method = 'GET') => {
  const entry = routes.get(routePath)
  assert.ok(entry, `no route registered at ${routePath}`)
  const res = fakeRes()
  await entry.handler({ method, url }, res)
  return res
}

let failures = 0
const check = async (label, fn) => {
  try { await fn(); console.log(`  ok   ${label}`) }
  catch (err) { failures++; console.log(`  FAIL ${label}\n       ${err.message}`) }
}

await check('state reports not-live when no pet has ever run', async () => {
  const res = await call('/dsh-desk-pet/state')
  const body = JSON.parse(res.body)
  assert.equal(res.status, 200)
  assert.equal(body.live, false)
  assert.equal(body.state, 'idle')
})

await check('state reports live for a fresh file', async () => {
  writeFileSync(
    path.join(home, '.dsh-desk-pet', 'state.json'),
    JSON.stringify({ skin: 'nautilus', state: 'working', wall_ms: Date.now(), pid: 1 }),
  )
  const body = JSON.parse((await call('/dsh-desk-pet/state')).body)
  assert.equal(body.live, true)
  assert.equal(body.state, 'working')
  assert.equal(body.skin, 'nautilus')
})

await check('state reports not-live for a stale file', async () => {
  writeFileSync(
    path.join(home, '.dsh-desk-pet', 'state.json'),
    JSON.stringify({ skin: 'deepseek', state: 'error', wall_ms: Date.now() - 60_000, pid: 1 }),
  )
  const body = JSON.parse((await call('/dsh-desk-pet/state')).body)
  assert.equal(body.live, false, 'a killed pet must not keep the page animating')
})

await check('state survives a torn write', async () => {
  writeFileSync(path.join(home, '.dsh-desk-pet', 'state.json'), '{"skin":"wha')
  const res = await call('/dsh-desk-pet/state')
  assert.equal(res.status, 200)
  assert.equal(JSON.parse(res.body).live, false)
})

await check('non-GET is refused, not crashed on', async () => {
  const res = await call('/dsh-desk-pet/state', '/dsh-desk-pet/state', 'POST')
  assert.equal(res.status, 405)
})

await check('manifest is served and lists the skins', async () => {
  const body = JSON.parse((await call('/dsh-desk-pet/manifest.json')).body)
  assert.ok(body.skins, 'no skins in manifest')
  assert.ok(Object.keys(body.skins).length >= 4)
  for (const entry of Object.values(body.skins)) {
    assert.ok(entry.timelines, 'manifest carries no timelines for the overlay to play')
  }
})

await check('overlay script is served', async () => {
  const res = await call('/dsh-desk-pet/overlay.js')
  assert.equal(res.headers['content-type'], 'application/javascript; charset=utf-8')
  assert.ok(res.body.includes('__dshDeskPetMounted'))
})

await check('a real frame is served as png', async () => {
  const res = await call('/dsh-desk-pet/frames/', '/dsh-desk-pet/frames/deepseek/idle/00.png')
  assert.equal(res.status, 200)
  assert.equal(res.headers['content-type'], 'image/png')
})

await check('path traversal is refused', async () => {
  const res = await call('/dsh-desk-pet/frames/', '/dsh-desk-pet/frames/../../../../etc/passwd')
  assert.equal(res.status, 404)
})

await check('a malformed escape answers 400 rather than rejecting', async () => {
  const res = await call('/dsh-desk-pet/frames/', '/dsh-desk-pet/frames/%')
  assert.equal(res.status, 400)
})

await check('non-png under frames is refused', async () => {
  const res = await call('/dsh-desk-pet/frames/', '/dsh-desk-pet/frames/deepseek/idle/00.gif')
  assert.equal(res.status, 404)
})

await check('index tap injects the overlay exactly once', async () => {
  assert.equal(taps.length, 1)
  const once = taps[0]('<html><body></body></html>')
  assert.ok(once.includes('__dshDeskPetMounted'))
  assert.equal(taps[0](once), once, 'second tap injected a duplicate pet')
})

await check('teardown removes every route and tap', async () => {
  for (const fn of teardown) fn()
  assert.equal(routes.size, 0, `routes left registered: ${[...routes.keys()]}`)
  assert.equal(taps.length, 0)
})

rmSync(home, { recursive: true, force: true })
console.log(failures ? `\n${failures} failed` : '\nall plugin routes ok')
process.exit(failures ? 1 : 0)
