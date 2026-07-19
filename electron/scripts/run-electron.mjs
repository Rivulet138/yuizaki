import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const development = process.argv.includes('--dev')
const checkOnly = process.argv.includes('--check')
const rendererUrl = process.env.VITE_DEV_SERVER_URL || 'http://localhost:5173'
const mainEntry = path.join(electronRoot, 'dist', 'main', 'index.js')
const electronCli = path.join(electronRoot, 'node_modules', 'electron', 'cli.js')

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const waitForDevelopmentRuntime = async () => {
  const deadline = Date.now() + 120_000
  while (Date.now() < deadline) {
    if (fs.existsSync(mainEntry)) {
      try {
        const response = await fetch(rendererUrl, { signal: AbortSignal.timeout(1_000) })
        if (response.ok) return
      } catch {
        // Build watcher and Vite may still be starting.
      }
    }
    await sleep(250)
  }
  throw new Error(`Electron development runtime did not become ready: ${rendererUrl}`)
}

if (!fs.existsSync(electronCli)) {
  throw new Error(`Electron CLI is missing: ${electronCli}`)
}
if (development) {
  await waitForDevelopmentRuntime()
} else if (!fs.existsSync(mainEntry)) {
  throw new Error(`Electron main build is missing: ${mainEntry}`)
}

if (checkOnly) {
  console.log(`[OK] Electron runtime is ready: ${electronCli}`)
  process.exit(0)
}

const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE
if (development) {
  env.VITE_DEV_SERVER_URL = rendererUrl
} else {
  delete env.VITE_DEV_SERVER_URL
}

const child = spawn(process.execPath, [electronCli, '.'], {
  cwd: electronRoot,
  env,
  stdio: 'inherit',
})

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal))
}

child.on('error', (error) => {
  console.error(error)
  process.exitCode = 1
})
child.on('exit', (code, signal) => {
  process.exitCode = code ?? (signal ? 1 : 0)
})
