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
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } from 'node:fs'
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

/**
 * Resolve a URL the way DSH's web server does, rather than by exact key.
 *
 * From packages/host/webserver: "'exact' matches the pathname verbatim;
 * 'prefix' p matches p and p/<anything>". Looking routes up by the string they
 * were registered under is what let a prefix registered WITH a trailing slash
 * pass every test here while matching nothing but itself in the real server —
 * every frame request fell through to the SPA and the page showed a broken
 * image. Longest match wins, as it must for '/api' and '/api/deep' to coexist.
 */
const resolve = (url) => {
  const pathname = new URL(url, 'http://x').pathname
  let best
  for (const [routePath, entry] of routes) {
    const hit = entry.kind === 'exact'
      ? pathname === routePath
      : pathname === routePath || pathname.startsWith(routePath + '/')
    if (!hit) continue
    if (!best || routePath.length > best.routePath.length) best = { routePath, entry }
  }
  return best
}

const call = async (routePath, url = routePath, method = 'GET', headers = undefined) => {
  const match = resolve(url)
  assert.ok(match, `nothing in the router matches ${url}`)
  const res = fakeRes()
  // `headers` stays undefined by default on purpose: a handler must not assume
  // the property exists, and leaving it out is what caught that assumption.
  await match.entry.handler({ method, url, headers }, res)
  return res
}


let failures = 0
const check = async (label, fn) => {
  try { await fn(); console.log(`  ok   ${label}`) }
  catch (err) { failures++; console.log(`  FAIL ${label}\n       ${err.message}`) }
}

await check('routes are reachable at the URLs the page actually requests', async () => {
  for (const url of [
    '/dsh-desk-pet/state',
    '/dsh-desk-pet/manifest.json',
    '/dsh-desk-pet/overlay.js',
    '/dsh-desk-pet/frames/deepseek/idle/00.png',
  ]) {
    assert.ok(resolve(url), `no route would serve ${url}; the page would get the SPA`)
  }
})

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

// The bug these two exist for: frame URLs never change across an art rebuild,
// so a plain max-age let a browser keep showing art that had been replaced —
// a whole day of the pre-key pastel-plate whale in a page that looked fine.
await check('a frame carries a validator and is not blindly cacheable', async () => {
  const res = await call('/dsh-desk-pet/frames/', '/dsh-desk-pet/frames/deepseek/idle/00.png')
  assert.equal(res.status, 200)
  assert.ok(res.headers.etag, 'no etag, so the browser cannot revalidate')
  assert.doesNotMatch(
    String(res.headers['cache-control'] ?? ''),
    /max-age=(?!0)\d+/,
    'a non-zero max-age lets stale art survive a rebuild',
  )
})

await check('an unchanged frame answers 304, a rebuilt one does not', async () => {
  const first = await call('/dsh-desk-pet/frames/', '/dsh-desk-pet/frames/deepseek/idle/00.png')
  const tag = first.headers.etag
  const again = await call(
    '/dsh-desk-pet/frames/', '/dsh-desk-pet/frames/deepseek/idle/00.png', 'GET',
    { 'if-none-match': tag },
  )
  assert.equal(again.status, 304)
  // A rebuild changes size or mtime, so the old validator must stop matching.
  const stale = await call(
    '/dsh-desk-pet/frames/', '/dsh-desk-pet/frames/deepseek/idle/00.png', 'GET',
    { 'if-none-match': '"stale-from-a-previous-build"' },
  )
  assert.equal(stale.status, 200)
})

await check('the no-pet fallback names a skin that actually ships', async () => {
  const res = await call('/dsh-desk-pet/state')
  const { skin } = JSON.parse(res.body)
  const frame = await call('/dsh-desk-pet/frames/', `/dsh-desk-pet/frames/${skin}/idle/00.png`)
  assert.equal(frame.status, 200, `fallback skin ${skin} has no frames on disk`)
})

await check('path traversal is refused', async () => {
  // Percent-encoded, because that is the form that actually reaches a handler:
  // `new URL()` collapses a literal '../..' before routing, so the plain version
  // resolves to /etc/passwd, matches no route of ours, and tests nothing.
  const res = await call(
    '/dsh-desk-pet/frames',
    '/dsh-desk-pet/frames/%2e%2e%2f%2e%2e%2f%2e%2e%2f%2e%2e%2fetc/passwd',
  )
  assert.equal(res.status, 404)
})

await check('a traversal that resolves outside our prefix never reaches us', async () => {
  // The other half of the defence, and the reason the check above changed:
  // the router must not hand us a path that has already escaped.
  assert.equal(resolve('/dsh-desk-pet/frames/../../../../etc/passwd'), undefined)
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

await check('the client factory returns a module DSH will accept', async () => {
  // The client module runs in the browser, so nothing else here touches it. DSH
  // rejected the whole plugin because this factory returned descriptive metadata
  // ({ id, root }) instead of a module whose `apply` is a function: the page lost
  // its pet, and the only symptom was a loader error naming a hash.
  const src = readFileSync(new URL('../plugin/client.js', import.meta.url), 'utf8')
  let loaded
  const sandbox = {
    window: { __ModuleLoader__: { load: (entry) => { loaded = entry } } },
    document: {
      readyState: 'complete',
      querySelector: () => null,
      getElementById: () => null,
      createElement: () => ({ setAttribute() {} }),
      addEventListener() {},
      removeEventListener() {},
      body: { appendChild() {} },
    },
    console,
  }
  new Function(...Object.keys(sandbox), src)(...Object.values(sandbox))

  assert.ok(loaded, 'client.js never registered with the module loader')
  assert.equal(loaded.id, 'dsh-desk-pet')
  const exported = loaded.factory(() => {})
  // Verbatim what vendor/cordis/src/registry.ts uses to decide validity.
  const applicable = exported && typeof exported === 'object'
    && typeof exported.apply === 'function'
  assert.ok(applicable, `factory returned ${typeof exported} without a callable apply`)
})

rmSync(home, { recursive: true, force: true })
console.log(failures ? `\n${failures} failed` : '\nall plugin routes ok')
process.exit(failures ? 1 : 0)
