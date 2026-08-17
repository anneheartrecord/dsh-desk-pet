/**
 * Cordis host plugin.
 *
 * Does two things and nothing else:
 *
 *  1. Launches the Tk desktop pet — the real product. It floats over every
 *     window, which is the whole point and something an injected `<div>`
 *     cannot do.
 *  2. Serves that pet's art and its current state to the DSH page, so the
 *     in-page overlay is a *mirror* of the desktop pet rather than a second,
 *     separately-observed pet that can disagree with it.
 *
 * The desktop process owns observation and writes `~/.dsh-desk-pet/state.json`;
 * the route below only reads it. That keeps one implementation of "what is the
 * agent doing" instead of reimplementing the heuristics in Node.
 */
import { spawn } from 'node:child_process'
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-desk-pet'
export const inject = ['webServer']

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const LAUNCHER = path.join(ROOT, 'bin', 'dsh-desk-pet')
const OVERLAY_FILE = path.join(ROOT, 'plugin', 'overlay.js')

// Read per use, not once at import. `dsh web` is a long-running server, so a
// module-level read pinned whatever the overlay looked like when the server
// booted: a session started before a fifth skin was added kept inlining the
// four-skin overlay into every page, with no way to tell from the browser side.
// The file is a few KB of local disk next to code we already trust.
function overlaySource() {
  try {
    return readFileSync(OVERLAY_FILE, 'utf8')
  } catch {
    return '/* dsh-desk-pet: overlay.js unreadable */'
  }
}
const WEB_ASSETS = path.join(ROOT, 'assets', 'web')
const MANIFEST = path.join(ROOT, 'assets', 'skins', 'manifest.json')
const STATE_FILE = path.join(os.homedir(), '.dsh-desk-pet', 'state.json')

// Registered WITHOUT a trailing slash. DSH matches a prefix `p` against `p` and
// `p/<anything>`, so registering '/dsh-desk-pet/frames/' matched only that exact
// path and would have needed a doubled slash to match anything below it: every
// frame request fell through to the SPA and the page got index.html where it
// expected a PNG, which renders as a broken-image icon.
const FRAMES_PREFIX = '/dsh-desk-pet/frames'


// The fallback shown when no desktop pet is publishing. `skin` has to name a
// skin that actually ships: it read 'whale' long after that folder was renamed,
// so every no-pet page asked for /frames/whale/idle/00.png, got a 404 and
// rendered nothing at all rather than a resting pet.
const IDLE_STATE = { skin: 'deepseek', state: 'idle', epoch_ms: 0 }
// Must stay above the desktop pet's heartbeat (HEARTBEAT_MS in app.py).
const STALE_AFTER_MS = 6000

function sendJson(res, body, status = 200) {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

/** Resolve a request path inside `root`, or null if it tries to escape. */
function safeJoin(root, relative) {
  const resolved = path.resolve(root, '.' + path.posix.normalize('/' + relative))
  const prefix = root.endsWith(path.sep) ? root : root + path.sep
  return resolved.startsWith(prefix) ? resolved : null
}

export function apply(ctx) {
  const python = process.platform === 'darwin' ? '/usr/bin/python3' : 'python3'
  // Declared before the exit handler that closes over it, so the ordering is
  // obvious rather than merely correct-by-timing.
  let stopping = false
  // Pipe rather than ignore: the pet prints the reason it declined to start
  // (another instance already running) and any traceback, and with 'ignore'
  // both vanish. A desktop pet that silently fails to appear is impossible to
  // tell apart from one that is merely invisible.
  const child = spawn(python, [LAUNCHER], { cwd: ROOT, detached: false, stdio: ['ignore', 'pipe', 'pipe'] })
  let tail = ''
  const collect = (chunk) => {
    tail = (tail + chunk.toString()).slice(-2000)
  }
  child.stdout?.on('data', collect)
  child.stderr?.on('data', collect)
  child.on('error', (err) => {
    ctx.logger?.warn?.(`[dsh-desk-pet] desktop companion did not start: ${err.message}`)
  })
  child.on('exit', (code, signal) => {
    // SIGTERM is us shutting it down on plugin teardown; anything else means
    // the pet is gone and the user should be able to find out why.
    if (signal === 'SIGTERM' || stopping) return
    const why = tail.trim() || `exit code ${code}`
    ctx.logger?.warn?.(`[dsh-desk-pet] desktop companion exited: ${why}`)
  })

  const stop = () => {
    stopping = true
    if (child.killed || child.exitCode != null) return
    child.kill()
  }

  // Current skin/state, as published by the desktop process.
  const unstate = ctx.webServer.register({
    kind: 'exact',
    path: '/dsh-desk-pet/state',
    handler: async (req, res) => {
      if (req.method !== 'GET') return sendJson(res, { error: 'method not allowed' }, 405)
      try {
        const raw = await readFile(STATE_FILE, 'utf8')
        const parsed = JSON.parse(raw)
        // The desktop pet rewrites this every couple of seconds. A file that
        // has stopped moving is one a killed process left behind — without
        // this check the page cheerfully animates a pet that no longer exists.
        const age = Date.now() - (Number(parsed.wall_ms) || 0)
        const live = Number.isFinite(age) && age >= 0 && age < STALE_AFTER_MS
        sendJson(res, { ...IDLE_STATE, ...parsed, live })
      } catch {
        // No desktop pet running (or mid-write): a calm idle beats a 500.
        sendJson(res, { ...IDLE_STATE, live: false })
      }
    },
  })

  // Frame lists and per-state timings, so the overlay plays the same rhythm.
  const unmanifest = ctx.webServer.register({
    kind: 'exact',
    path: '/dsh-desk-pet/manifest.json',
    handler: async (req, res) => {
      if (req.method !== 'GET') return sendJson(res, { error: 'method not allowed' }, 405)
      try {
        sendJson(res, JSON.parse(await readFile(MANIFEST, 'utf8')))
      } catch (err) {
        ctx.logger?.warn?.(`[dsh-desk-pet] manifest unreadable: ${err.message}`)
        sendJson(res, { frame_size: 200, skins: {} })
      }
    },
  })

  // The overlay itself, so `client.js` can pull the same code the index tap
  // inlines. One implementation, two ways in.
  const unoverlay = ctx.webServer.register({
    kind: 'exact',
    path: '/dsh-desk-pet/overlay.js',
    handler: async (req, res) => {
      if (req.method !== 'GET') return sendJson(res, { error: 'method not allowed' }, 405)
      res.writeHead(200, {
        'content-type': 'application/javascript; charset=utf-8',
        'cache-control': 'no-store',
      })
      res.end(overlaySource())
    },
  })

  // RGBA frames. The desktop window uses the GIF twins of these; the browser
  // gets real alpha because it can actually composite it.
  const unframes = ctx.webServer.register({
    kind: 'prefix',
    path: FRAMES_PREFIX,
    handler: async (req, res) => {
      if (req.method !== 'GET') return sendJson(res, { error: 'method not allowed' }, 405)
      let rel
      try {
        // A stray '%' makes decodeURIComponent throw, and an unhandled throw in
        // an async handler is a rejected promise, not a response.
        rel = decodeURIComponent(new URL(req.url, 'http://x').pathname)
          .slice(FRAMES_PREFIX.length)
          .replace(/^\/+/, '')
      } catch {
        res.writeHead(400)
        return res.end()
      }
      const file = safeJoin(WEB_ASSETS, rel)
      if (!file || !file.endsWith('.png') || !existsSync(file)) {
        res.writeHead(404)
        return res.end()
      }
      // Revalidate rather than cache outright. Frame URLs are stable across
      // rebuilds — `deepseek/idle/00.png` is the same path before and after the
      // art changes — so a plain max-age served a whole day of stale art: after
      // rebuilding every frame, the page kept showing the pre-key pastel-plate
      // version it had already downloaded. An ETag keeps the bytes off the wire
      // (304s) without letting the browser skip asking.
      let tag
      try {
        const st = statSync(file)
        tag = `"${st.size.toString(36)}-${st.mtimeMs.toString(36)}"`
      } catch {
        res.writeHead(404)
        return res.end()
      }
      if (req.headers?.['if-none-match'] === tag) {
        res.writeHead(304, { etag: tag, 'cache-control': 'no-cache' })
        return res.end()
      }
      res.writeHead(200, {
        'content-type': 'image/png',
        'cache-control': 'no-cache',
        etag: tag,
      })
      createReadStream(file).pipe(res)
    },
  })

  const untap = ctx.webServer.tapIndex((html) => {
    if (html.includes('dsh-desk-pet-root') || html.includes('__dshDeskPetMounted')) return html
    const tag = `<script>${overlaySource()}</script>`
    if (html.includes('</body>')) return html.replace('</body>', `${tag}</body>`)
    return html + tag
  })

  ctx.effect(() => () => {
    stop()
    unstate()
    unmanifest()
    unoverlay()
    unframes()
    untap()
  })
}
