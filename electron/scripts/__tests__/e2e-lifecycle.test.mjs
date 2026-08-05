import assert from 'node:assert/strict'
import { fork } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { spawnOwned, terminateOwnedChild, waitForLine } from '../e2e-supervisor.mjs'

const fixture = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'e2e-lifecycle-probe.mjs')

const isAlive = (pid) => {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

const waitUntil = async (predicate, timeoutMs = 8_000) => {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 25))
  }
  assert.fail('condition did not become true before timeout')
}

const runLifecycleScenario = async (action, expectedExitCode, useOsSignal = false) => {
  const nonOwned = spawnOwned(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' })
  const supervisor = fork(fixture, [], { silent: true })
  try {
    const ready = JSON.parse(await waitForLine(supervisor.stdout, 5_000, 'lifecycle probe readiness'))
    assert.equal(ready.type, 'ready')
    assert.equal(isAlive(ready.ownedPid), true)
    assert.equal(fs.existsSync(ready.tempDirectory), true)
    if (useOsSignal && process.platform !== 'win32') {
      supervisor.kill(action.signal)
      supervisor.kill(action.signal)
    } else {
      supervisor.send(action)
      supervisor.send(action)
    }
    const exit = await new Promise((resolve) => supervisor.once('exit', (code, signal) => resolve({ code, signal })))
    assert.deepEqual(exit, { code: expectedExitCode, signal: null })
    await waitUntil(() => !isAlive(ready.ownedPid) && !fs.existsSync(ready.tempDirectory))
    assert.equal(isAlive(nonOwned.pid), true)
  } finally {
    await terminateOwnedChild(supervisor)
    await terminateOwnedChild(nonOwned)
  }
}

test('SIGTERM cleanup is owned-only and idempotent', { timeout: 20_000 }, async () => {
  await runLifecycleScenario({ action: 'signal', signal: 'SIGTERM' }, 143, true)
})

test('cancel cleanup removes owned resources', { timeout: 20_000 }, async () => {
  await runLifecycleScenario({ action: 'cancel' }, 130)
})

test('uncaught and unhandled failures clean owned resources', { timeout: 30_000 }, async () => {
  await runLifecycleScenario({ action: 'failure' }, 1)
  await runLifecycleScenario({ action: 'rejection' }, 1)
})
