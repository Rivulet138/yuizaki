import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const artifactRoot = path.join(electronRoot, 'test-results', 'e2e')
const token = '0123456789abcdef'.repeat(4)
const backendToken = 'backend_control_token_for_e2e_probe_1234567890'
const tokenHash = crypto.createHash('sha256').update(token).digest('hex')
const backendTokenHash = crypto.createHash('sha256').update(backendToken).digest('hex')

const listCaseDirectories = () => {
  if (!fs.existsSync(artifactRoot)) return new Set()
  return new Set(fs.readdirSync(artifactRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(artifactRoot, entry.name, 'E2E-02'))
    .filter((entry) => fs.existsSync(entry)))
}

const listFiles = (directory) => fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
  const target = path.join(directory, entry.name)
  return entry.isDirectory() ? listFiles(target) : [target]
})

test('failure artifacts and captured output never expose the E2E token', { timeout: 150_000 }, () => {
  const before = listCaseDirectories()
  const result = spawnSync(process.execPath, [
    path.join(electronRoot, 'scripts', 'run-electron-e2e.mjs'),
    '--case=E2E-02',
    '--failure-probe=redaction',
  ], {
    cwd: electronRoot,
    env: {
      ...process.env,
      YUIZAKI_E2E_TEST_TOKEN: token,
      YUIZAKI_E2E_TEST_BACKEND_TOKEN: backendToken,
    },
    encoding: 'utf8',
    timeout: 140_000,
    maxBuffer: 10 * 1024 * 1024,
  })
  assert.notEqual(result.status, 0, 'the intentional failure probe unexpectedly passed')

  const created = [...listCaseDirectories()]
    .filter((directory) => !before.has(directory))
    .filter((directory) => {
      const auditPath = path.join(directory, 'fixture-security.json')
      if (!fs.existsSync(auditPath)) return false
      return JSON.parse(fs.readFileSync(auditPath, 'utf8')).backend_token_hash === backendTokenHash
    })
  assert.equal(created.length, 1, `expected one E2E-02 artifact directory, received ${created.length}`)
  const artifactDir = created[0]
  const captured = `${result.stdout}\n${result.stderr}`
  const encodedToken = encodeURIComponent(token)
  assert.equal(captured.includes(token), false, 'captured supervisor output exposed the raw token')
  assert.equal(captured.includes(encodedToken), false, 'captured supervisor output exposed the encoded token')
  assert.equal(captured.includes(backendToken), false, 'captured supervisor output exposed the backend token')
  assert.match(captured, /lip-sync audio URL token did not match the run/)

  const files = listFiles(artifactDir)
  assert.ok(files.some((file) => file.endsWith('electron-error.txt')))
  assert.ok(files.some((file) => file.endsWith('renderer-console.jsonl')))
  assert.ok(files.some((file) => file.endsWith('electron.log')))
  assert.ok(files.some((file) => file.endsWith('supervisor-error.txt')))
  for (const file of files) {
    const contents = fs.readFileSync(file)
    assert.equal(contents.includes(Buffer.from(token)), false, `${file} exposed the raw token`)
    assert.equal(contents.includes(Buffer.from(encodedToken)), false, `${file} exposed the encoded token`)
    assert.equal(contents.includes(Buffer.from(backendToken)), false, `${file} exposed the backend token`)
  }

  const rendererConsole = fs.readFileSync(path.join(artifactDir, 'renderer-console.jsonl'), 'utf8')
  const electronError = fs.readFileSync(path.join(artifactDir, 'electron-error.txt'), 'utf8')
  const electronLog = fs.readFileSync(path.join(artifactDir, 'electron.log'), 'utf8')
  assert.match(rendererConsole, /probe URL/)
  assert.match(rendererConsole, /\[redacted\]/)
  assert.match(electronError, /lip-sync audio URL token did not match the run/)
  assert.match(electronError, /--token \[redacted\]/)
  assert.match(electronLog, new RegExp(tokenHash))
})
