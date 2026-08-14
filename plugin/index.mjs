/**
 * Cordis host plugin. Pins a pet into the DSH index HTML and launches a
 * titled desktop window on the primary display (not the virtual desktop edge).
 */
import { spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-desk-pet'
export const inject = ['webServer']

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const LAUNCHER = path.join(ROOT, 'bin', 'dsh-desk-pet')
const OVERLAY = readFileSync(path.join(ROOT, 'plugin', 'overlay.js'), 'utf8')

export function apply(ctx) {
  const python = process.platform === 'darwin' ? '/usr/bin/python3' : 'python3'
  const child = spawn(python, [LAUNCHER], {
    cwd: ROOT,
    detached: false,
    stdio: 'ignore',
  })
  child.on('error', (err) => {
    ctx.logger?.warn?.(`[dsh-desk-pet] failed to launch desktop companion: ${err.message}`)
  })

  const stop = () => {
    if (child.killed || child.exitCode != null) return
    child.kill()
  }

  const unroute = ctx.webServer.register({
    kind: 'exact',
    path: '/dsh-desk-pet/state',
    handler: async (req, res) => {
      if (req.method !== 'GET') {
        res.writeHead(405)
        res.end()
        return
      }
      res.writeHead(200, {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store',
      })
      res.end(JSON.stringify({ state: 'idle' }))
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
    unroute()
    untap()
  })
}
