/**
 * Cordis host plugin.
 *
 * Does one thing: launches the desktop pet alongside `dsh web`, and stops it
 * again on teardown. The pet floats over every window, which is the whole point
 * and something an injected `<div>` cannot do.
 *
 * There used to be a second pet mirrored into the DSH page, fed by four routes
 * and an index tap. It is gone. Two pets on one screen read as a bug rather than
 * a feature, and the mirror was where the failures lived: a client module whose
 * factory returned the wrong shape took the entire plugin down with it, and a
 * prefix route registered with a trailing slash quietly served the SPA's HTML in
 * place of every PNG. Deleting the surface deletes that whole class of problem.
 *
 * `webServer` is still injected, deliberately, and not because anything here
 * calls it: it is a gate. It keeps the pet from appearing during a headless or
 * scheduled run, where a window popping onto someone's screen would be a fault.
 * The pet belongs to a session that already has a UI.
 */
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-desk-pet'
export const inject = ['webServer']

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const LAUNCHER = path.join(ROOT, 'bin', 'dsh-desk-pet')

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

  ctx.effect(() => stop)
}
