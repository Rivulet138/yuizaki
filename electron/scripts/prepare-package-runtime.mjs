import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = path.resolve(electronRoot, '..')
const stagingRoot = path.join(electronRoot, '.package-runtime')

const pythonFiles = [
  'app_factory.py',
  'app.py',
  'i18n.py',
  'lifespan.py',
  'middleware_registry.py',
  'migration_bootstrap.py',
  'migration_check.py',
  'route_manifest.py',
  'router_registry.py',
  'runtime_container.py',
  'socket_events.py',
  'socket_server.py',
  'requirements-core.txt',
  'requirements.txt',
  '.env.example',
]
const pythonDirectories = [
  'alembic',
  'config',
  'database',
  'evals',
  'locales',
  'modules',
  'routes',
  'scripts',
  'socket_compositions',
  'socket_handlers',
]
const scriptFiles = ['ensure_qdrant_docker.ps1']
const soulxFiles = ['Dockerfile', 'docker-compose.yml', 'download_models.py', 'server.py']
const soulxDirectories = ['references']

await fs.rm(stagingRoot, { recursive: true, force: true })
await fs.mkdir(path.join(stagingRoot, 'python'), { recursive: true })
await fs.mkdir(path.join(stagingRoot, 'node-mcp'), { recursive: true })
await fs.mkdir(path.join(stagingRoot, 'scripts'), { recursive: true })
await fs.mkdir(path.join(stagingRoot, 'services', 'soulx-svc'), { recursive: true })

const shouldStage = (source) => {
  const relativePath = path.relative(projectRoot, source)
  const segments = relativePath.split(path.sep)
  if (segments.includes('__pycache__') || segments.includes('.cache') || segments.includes('node_modules')) return false
  if (/\.(pyc|pyo|pt|onnx|safetensors|bin)$/i.test(path.basename(source))) return false
  return true
}

const copy = async (source, target) => {
  await fs.mkdir(path.dirname(target), { recursive: true })
  await fs.cp(source, target, { recursive: true, filter: shouldStage })
}

for (const file of pythonFiles) await copy(path.join(projectRoot, 'python', file), path.join(stagingRoot, 'python', file))
for (const directory of pythonDirectories) await copy(path.join(projectRoot, 'python', directory), path.join(stagingRoot, 'python', directory))
for (const file of scriptFiles) await copy(path.join(projectRoot, 'scripts', file), path.join(stagingRoot, 'scripts', file))
for (const file of soulxFiles) await copy(path.join(projectRoot, 'services', 'soulx-svc', file), path.join(stagingRoot, 'services', 'soulx-svc', file))
for (const directory of soulxDirectories) await copy(path.join(projectRoot, 'services', 'soulx-svc', directory), path.join(stagingRoot, 'services', 'soulx-svc', directory))
for (const file of ['server.mjs', 'package.json', 'package-lock.json']) {
  await copy(path.join(projectRoot, 'node-mcp', file), path.join(stagingRoot, 'node-mcp', file))
}
await copy(path.join(projectRoot, 'resources.lock.json'), path.join(stagingRoot, 'resources.lock.json'))

for (const launcher of ['YuizakiLauncher.exe', 'YuizakiLauncher']) {
  try {
    await copy(path.join(projectRoot, launcher), path.join(stagingRoot, launcher))
    break
  } catch {
    // The source package can still be prepared when Go is not installed.
  }
}

console.log(`[OK] Prepared packaged runtime at ${stagingRoot}`)
