import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = path.resolve(electronRoot, '..')
const stagingRoot = path.join(electronRoot, '.package-runtime')

const pythonFiles = [
  'app.py',
  'i18n.py',
  'migration_bootstrap.py',
  'socket_events.py',
  'socket_server.py',
  'requirements-core.txt',
  'requirements.txt',
  '.env.example',
]
const pythonDirectories = ['alembic', 'config', 'database', 'evals', 'locales', 'modules', 'routes']
const scriptFiles = ['ensure_qdrant_docker.ps1']

await fs.rm(stagingRoot, { recursive: true, force: true })
await fs.mkdir(path.join(stagingRoot, 'python'), { recursive: true })
await fs.mkdir(path.join(stagingRoot, 'node-mcp'), { recursive: true })
await fs.mkdir(path.join(stagingRoot, 'scripts'), { recursive: true })

const copy = async (source, target) => {
  await fs.mkdir(path.dirname(target), { recursive: true })
  await fs.cp(source, target, { recursive: true })
}

for (const file of pythonFiles) await copy(path.join(projectRoot, 'python', file), path.join(stagingRoot, 'python', file))
for (const directory of pythonDirectories) await copy(path.join(projectRoot, 'python', directory), path.join(stagingRoot, 'python', directory))
for (const file of scriptFiles) await copy(path.join(projectRoot, 'scripts', file), path.join(stagingRoot, 'scripts', file))
for (const file of ['server.mjs', 'package.json', 'package-lock.json']) {
  await copy(path.join(projectRoot, 'node-mcp', file), path.join(stagingRoot, 'node-mcp', file))
}

for (const launcher of ['YuizakiLauncher.exe', 'YuizakiLauncher']) {
  try {
    await copy(path.join(projectRoot, launcher), path.join(stagingRoot, launcher))
    break
  } catch {
    // The source package can still be prepared when Go is not installed.
  }
}

console.log(`[OK] Prepared packaged runtime at ${stagingRoot}`)
