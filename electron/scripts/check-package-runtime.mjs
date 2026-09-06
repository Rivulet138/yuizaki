import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const stagingRoot = path.join(electronRoot, '.package-runtime')

const requiredFiles = [
  'resources.lock.json',
  'python/app.py',
  'python/app_factory.py',
  'python/lifespan.py',
  'python/migration_check.py',
  'python/socket_compositions/__init__.py',
  'python/socket_handlers/__init__.py',
  'python/scripts/download_sherpa_sensevoice.py',
  'python/scripts/download_sherpa_streaming_zipformer.py',
  'python/scripts/prefetch_embedding_model.py',
  'python/scripts/prefetch_genie_tts.py',
  'services/soulx-svc/download_models.py',
  'node-mcp/server.mjs',
  'node-mcp/package.json',
  'node-mcp/package-lock.json',
]

const missing = requiredFiles.filter((relativePath) => !fs.existsSync(path.join(stagingRoot, relativePath)))
const bundledModelFiles = []
const walk = (directory) => {
  if (!fs.existsSync(directory)) return
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) walk(fullPath)
    else if (/\.(pt|onnx|safetensors|bin)$/i.test(entry.name)) bundledModelFiles.push(fullPath)
  }
}
walk(stagingRoot)

if (missing.length || bundledModelFiles.length) {
  if (missing.length) console.error(`Missing packaged runtime files:\n${missing.join('\n')}`)
  if (bundledModelFiles.length) console.error(`Model weights must not be bundled by default:\n${bundledModelFiles.join('\n')}`)
  process.exit(1)
}

console.log(`Package runtime check passed (${requiredFiles.length} required files; no model weights bundled).`)
