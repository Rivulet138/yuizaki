import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import {
  createOwnedResourceRegistry,
  installProcessLifecycleHandlers,
  spawnOwned,
} from '../../e2e-supervisor.mjs'

const registry = createOwnedResourceRegistry()
const tempDirectory = registry.registerTempDirectory(fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-e2e-lifecycle-')))
const ownedChild = registry.registerChild(spawnOwned(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
  stdio: 'ignore',
}))
const lifecycle = installProcessLifecycleHandlers(registry)

process.on('message', (message) => {
  if (message?.action === 'cancel') void lifecycle.requestShutdown('SIGINT')
  if (message?.action === 'signal') void lifecycle.requestShutdown(message.signal)
  if (message?.action === 'failure') setImmediate(() => { throw new Error('intentional lifecycle probe failure') })
  if (message?.action === 'rejection') void Promise.reject(new Error('intentional lifecycle probe rejection'))
})

process.stdout.write(`${JSON.stringify({ type: 'ready', ownedPid: ownedChild.pid, tempDirectory })}\n`)
