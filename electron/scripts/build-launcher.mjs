import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = path.resolve(electronRoot, '..')
const launcherSource = path.join(projectRoot, 'tools', 'yuizaki-launcher')

const requestedTarget = process.argv
  .find(argument => argument.startsWith('--target='))
  ?.slice('--target='.length) || 'all'
const requestedArch = process.argv
  .find(argument => argument.startsWith('--arch='))
  ?.slice('--arch='.length) || (process.arch === 'arm64' ? 'arm64' : 'amd64')

const hostTarget = process.platform === 'win32' ? 'windows' : 'linux'
const validTargets = new Set(['current', 'windows', 'linux', 'all'])
const validArchitectures = new Set(['amd64', 'arm64'])
if (!validTargets.has(requestedTarget)) {
  console.error(`[ERROR] Unsupported launcher target: ${requestedTarget}`)
  process.exit(2)
}
if (!validArchitectures.has(requestedArch)) {
  console.error(`[ERROR] Unsupported launcher architecture: ${requestedArch}`)
  process.exit(2)
}

const targets = requestedTarget === 'all'
  ? ['windows', 'linux']
  : [requestedTarget === 'current' ? hostTarget : requestedTarget]

for (const target of targets) {
  const output = path.join(projectRoot, target === 'windows' ? 'YuizakiLauncher.exe' : 'YuizakiLauncher')
  const result = spawnSync('go', [
    'build',
    '-trimpath',
    '-ldflags',
    '-s -w',
    '-o',
    output,
    '.',
  ], {
    cwd: launcherSource,
    env: {
      ...process.env,
      CGO_ENABLED: '0',
      GOOS: target,
      GOARCH: requestedArch,
    },
    stdio: 'inherit',
    shell: false,
  })
  if (result.error) {
    console.error(`[ERROR] Go toolchain is required to build ${target}/${requestedArch}: ${result.error.message}`)
    process.exit(1)
  }
  if (result.status !== 0) process.exit(result.status ?? 1)
  if (target === 'linux' && process.platform !== 'win32') fs.chmodSync(output, 0o755)
  console.log(`[OK] Built ${target}/${requestedArch}: ${output}`)
}
