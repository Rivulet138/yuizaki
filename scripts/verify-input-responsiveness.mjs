import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const electronRoot = path.join(projectRoot, 'electron')
const pythonRoot = path.join(projectRoot, 'python')

const run = (label, command, args, cwd) => {
  process.stdout.write('\n[input-responsiveness] ' + label + '\n')
  const result = spawnSync(command, args, {
    cwd,
    env: process.env,
    stdio: 'inherit',
    shell: false,
  })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}

const vitestCli = path.join(electronRoot, 'node_modules', 'vitest', 'vitest.mjs')
const viteCli = path.join(electronRoot, 'node_modules', 'vite', 'bin', 'vite.js')
const tscCli = path.join(electronRoot, 'node_modules', 'typescript', 'bin', 'tsc')
const pythonCandidates = process.platform === 'win32'
  ? [path.join(pythonRoot, '.venv', 'Scripts', 'python.exe')]
  : [path.join(pythonRoot, '.venv', 'bin', 'python3'), path.join(pythonRoot, '.venv', 'bin', 'python')]
const pythonCommand = pythonCandidates.find((candidate) => fs.existsSync(candidate))
  ?? (process.platform === 'win32' ? 'python' : 'python3')

run('Full Electron unit and scheduling suite', process.execPath, [vitestCli, 'run'], electronRoot)

run('Full Python suite including OCR and screenshot contracts', pythonCommand, [
  '-m',
  'pytest',
  '-q',
], pythonRoot)

run('Electron renderer production build', process.execPath, [viteCli, 'build'], electronRoot)
run('Renderer bundle audit', process.execPath, [path.join(electronRoot, 'scripts', 'audit-renderer-bundle.mjs')], electronRoot)
run('Electron main-process build', process.execPath, [tscCli, '-p', 'tsconfig.json'], electronRoot)
run('Real Electron desktop E2E suite', process.execPath, [
  path.join(electronRoot, 'scripts', 'run-electron-e2e.mjs'),
], electronRoot)

process.stdout.write('\n[input-responsiveness] PASS\n')
