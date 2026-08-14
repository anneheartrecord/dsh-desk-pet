/**
 * Cordis host plugin. Starts the always-on-top desktop pet when DSH boots,
 * and kills it when this plugin unloads. Not an in-page widget.
 */
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-desk-pet'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const LAUNCHER = path.join(ROOT, 'bin', 'dsh-desk-pet')

function currentKind() {
  const raw = process.env.DSH_PET_ACTIVITY
  if (raw) return raw
  return 'idle'
}

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

  const webServer = typeof ctx.get === 'function' ? ctx.get('webServer') : undefined
  const unroute =
    webServer !== undefined && typeof webServer.register === 'function'
      ? webServer.register({
          kind: 'exact',
          path: '/dsh-desk-pet/state',
          handler: async (req, res) => {
            if (req.method !== 'GET') {
              res.writeHead(405)
              res.end()
              return
            }
            const kind = currentKind()
            const state =
              /wait|approv|input|block/i.test(kind)
                ? 'waiting'
                : /error|fail/i.test(kind)
                  ? 'error'
                  : /run|work|tool|active|progress/i.test(kind)
                    ? 'working'
                    : 'idle'
            res.writeHead(200, {
              'content-type': 'application/json; charset=utf-8',
              'cache-control': 'no-store',
            })
            res.end(JSON.stringify({ state, kind }))
          },
        })
      : undefined

  if (typeof ctx.effect === 'function') {
    ctx.effect(() => () => {
      stop()
      if (typeof unroute === 'function') unroute()
    })
  } else if (typeof ctx.on === 'function') {
    ctx.on('dispose', () => {
      stop()
      if (typeof unroute === 'function') unroute()
    })
  }
}
