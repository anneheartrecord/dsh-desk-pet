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

  if (typeof ctx.effect === 'function') {
    ctx.effect(() => stop)
  } else if (typeof ctx.on === 'function') {
    ctx.on('dispose', stop)
  }
}
