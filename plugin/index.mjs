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
import { createReadStream, existsSync, readFileSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-desk-pet'
export const inject = ['webServer']

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const LAUNCHER = path.join(ROOT, 'bin', 'dsh-desk-pet')
const OVERLAY = readFileSync(path.join(ROOT, 'plugin', 'overlay.js'), 'utf8')
const WEB_ASSETS = path.join(ROOT, 'assets', 'web')
const MANIFEST = path.join(ROOT, 'assets', 'skins', 'manifest.json')
const STATE_FILE = path.join(os.homedir(), '.dsh-desk-pet', 'state.json')

const IDLE_STATE = { skin: 'whale', state: 'idle', epoch_ms: 0 }

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
  const child = spawn(python, [LAUNCHER], { cwd: ROOT, detached: false, stdio: 'ignore' })
  child.on('error', (err) => {
    ctx.logger?.warn?.(`[dsh-desk-pet] desktop companion did not start: ${err.message}`)
  })

  const stop = () => {
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
        sendJson(res, { ...IDLE_STATE, ...parsed, live: true })
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
      res.end(OVERLAY)
    },
  })

  // RGBA frames. The desktop window uses the GIF twins of these; the browser
  // gets real alpha because it can actually composite it.
  const unframes = ctx.webServer.register({
    kind: 'prefix',
    path: '/dsh-desk-pet/frames/',
    handler: async (req, res) => {
      if (req.method !== 'GET') return sendJson(res, { error: 'method not allowed' }, 405)
      const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname)
        .slice('/dsh-desk-pet/frames/'.length)
      const file = safeJoin(WEB_ASSETS, rel)
      if (!file || !file.endsWith('.png') || !existsSync(file)) {
        res.writeHead(404)
        return res.end()
      }
      res.writeHead(200, {
        'content-type': 'image/png',
        'cache-control': 'public, max-age=86400',
      })
      createReadStream(file).pipe(res)
    },
  })

  const untap = ctx.webServer.tapIndex((html) => {
    if (html.includes('dsh-desk-pet-root') || html.includes('__dshDeskPetMounted')) return html
    const tag = `<script>${OVERLAY}</script>`
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
