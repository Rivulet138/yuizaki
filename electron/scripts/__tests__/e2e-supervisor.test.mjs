import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { createE2ERedactor, createRedactingTransform } from '../e2e-redaction.cjs'
import {
  createRunIdentity,
  parseFixtureStartupRecord,
  resolveRepositoryPython,
  waitForJsonRecord,
} from '../e2e-supervisor.mjs'
import { PassThrough } from 'node:stream'

test('selects only the repository virtualenv interpreter', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-e2e-python-'))
  try {
    const windowsPython = path.join(root, 'python', '.venv', 'Scripts', 'python.exe')
    fs.mkdirSync(path.dirname(windowsPython), { recursive: true })
    fs.writeFileSync(windowsPython, '')

    assert.equal(resolveRepositoryPython(root, 'win32'), windowsPython)
    assert.throws(() => resolveRepositoryPython(root, 'linux'), /repository Python virtualenv is missing/i)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('parses one bounded startup record with the expected manifest hash', () => {
  const record = parseFixtureStartupRecord(JSON.stringify({
    type: 'yuizaki-e2e-fixture',
    port: 43123,
    manifest_hash: 'a'.repeat(64),
  }), 'a'.repeat(64))

  assert.deepEqual(record, { type: 'yuizaki-e2e-fixture', port: 43123, manifest_hash: 'a'.repeat(64) })
  assert.throws(() => parseFixtureStartupRecord('x'.repeat(4097), 'a'.repeat(64)), /exceeds 4096 bytes/)
  assert.throws(() => parseFixtureStartupRecord('{"port":1}', 'a'.repeat(64)), /invalid fixture startup record/i)
})

test('creates a random run token but exposes only its hash in identity metadata', () => {
  const first = createRunIdentity()
  const second = createRunIdentity()

  assert.match(first.token, /^[a-f0-9]{64}$/)
  assert.match(first.tokenHash, /^[a-f0-9]{64}$/)
  assert.match(first.backendToken, /^[A-Za-z0-9_-]{43}$/)
  assert.match(first.backendTokenHash, /^[a-f0-9]{64}$/)
  assert.notEqual(first.token, first.tokenHash)
  assert.notEqual(first.token, first.backendToken)
  assert.notEqual(first.token, second.token)
  assert.equal(JSON.stringify(first.publicIdentity).includes(first.token), false)
  assert.equal(JSON.stringify(first.publicIdentity).includes(first.backendToken), false)
})

test('ignores unrelated Electron stdout until the bounded result record', async () => {
  const stream = new PassThrough()
  const pending = waitForJsonRecord(stream, 1_000, 'result', (record) => record?.type === 'yuizaki-e2e-result')
  stream.write('Chromium startup log\n')
  stream.write('{"type":"other"}\n')
  stream.end('{"type":"yuizaki-e2e-result","status":"passed"}\n')
  const { record } = await pending
  assert.deepEqual(record, { type: 'yuizaki-e2e-result', status: 'passed' })
})

test('recursively redacts E2E tokens while retaining token_hash evidence', () => {
  const token = 'raw token/+with?reserved=value'
  const encoded = encodeURIComponent(token)
  const tokenHash = 'a'.repeat(64)
  const error = new Error(`failed URL https://127.0.0.1/audio.wav?token=${encoded}`)
  error.cause = new Error(`argv --token ${token}`)
  const redactor = createE2ERedactor(token)
  const safe = redactor.stringify({
    token_hash: tokenHash,
    nested: [{
      url: `https://127.0.0.1/audio.wav?token=${encoded}`,
      argv: ['fixture.py', '--token', token],
      env: `YUIZAKI_E2E_TOKEN=${token}`,
      headers: {
        'X-Yuizaki-E2E-Token': token,
        Authorization: `Bearer ${token}`,
      },
      error,
    }],
  })

  assert.equal(safe.includes(token), false)
  assert.equal(safe.includes(encoded), false)
  assert.match(safe, /"token_hash":"a{64}"/)
  assert.match(safe, /lip-sync|failed URL/)
  assert.match(safe, /\[redacted\]/)
})

test('redacts secrets split across stream chunks before writing logs', async () => {
  const token = 'b'.repeat(64)
  const source = new PassThrough()
  const transform = createRedactingTransform(createE2ERedactor(token))
  let output = ''
  transform.on('data', (chunk) => { output += chunk.toString('utf8') })
  const completed = new Promise((resolve, reject) => {
    transform.once('end', resolve)
    transform.once('error', reject)
  })
  source.pipe(transform)
  source.write(`renderer https://127.0.0.1/audio.wav?token=${token.slice(0, 20)}`)
  source.end(`${token.slice(20)}\nAuthorization: Bearer ${token}`)
  await completed

  assert.equal(output.includes(token), false)
  assert.match(output, /token=\[redacted\]/)
  assert.match(output, /Bearer \[redacted\]/)
})
