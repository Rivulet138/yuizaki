import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { createE2ERedactor, createRedactingTransform } from './e2e-redaction.cjs'
import {
  canonicalManifestHash,
  createOwnedResourceRegistry,
  createRunIdentity,
  createTempUserData,
  parseFixtureStartupRecord,
  resolveRepositoryPython,
  installProcessLifecycleHandlers,
  spawnOwned,
  terminateOwnedChild,
  waitForJsonRecord,
  waitForLine,
} from './e2e-supervisor.mjs'

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(electronRoot, '..')
const manifestPath = path.join(electronRoot, 'src', 'shared', 'runtime-protocol-manifest.json')
const fixturePath = path.join(repositoryRoot, 'python', 'tests', 'fixtures', 'e2e_backend.py')
const electronCli = path.join(electronRoot, 'node_modules', 'electron', 'cli.js')
const caseArg = process.argv.find((arg) => arg.startsWith('--case='))?.slice('--case='.length)
const fixtureOnly = process.argv.includes('--fixture-only')
const failureProbe = process.argv.find((arg) => arg.startsWith('--failure-probe='))?.slice('--failure-probe='.length)
const trustedSocketOrigin = 'yuizaki-app://renderer'
const loopbackNoProxy = [...new Set([
  ...(process.env['NO_PROXY'] ?? '').split(','),
  ...(process.env['no_proxy'] ?? '').split(','),
  '127.0.0.1',
  'localhost',
].map((value) => value.trim()).filter(Boolean))].join(',')
const caseIds = caseArg ? [caseArg] : ['E2E-01', 'E2E-02', 'E2E-03', 'E2E-04', 'E2E-05', 'E2E-05T', 'E2E-06', 'E2E-07', 'E2E-08']
const ownedResources = createOwnedResourceRegistry()
let activeRedactor = createE2ERedactor([])
const lifecycle = installProcessLifecycleHandlers(ownedResources, {
  sanitizeError: (error) => activeRedactor.redactText(error instanceof Error ? error.stack || error.message : String(error)),
})

const requestJson = async (url, init = {}) => {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(5_000) })
  const body = await response.json()
  if (!response.ok) throw new Error(`${init.method || 'GET'} ${url} failed (${response.status}): ${JSON.stringify(body)}`)
  return body
}

const runCase = async (caseId) => {
  if (lifecycle.isStopping()) throw new Error('E2E supervisor is stopping')
  const fixedToken = failureProbe === 'redaction' ? process.env['YUIZAKI_E2E_TEST_TOKEN'] : undefined
  const fixedBackendToken = failureProbe === 'redaction' ? process.env['YUIZAKI_E2E_TEST_BACKEND_TOKEN'] : undefined
  if (fixedToken !== undefined && !/^[a-f0-9]{64}$/.test(fixedToken)) {
    throw new Error('YUIZAKI_E2E_TEST_TOKEN must be exactly 64 lowercase hexadecimal characters')
  }
  if (fixedBackendToken !== undefined && !/^[A-Za-z0-9_-]{32,128}$/.test(fixedBackendToken)) {
    throw new Error('YUIZAKI_E2E_TEST_BACKEND_TOKEN must be a base64url-style token')
  }
  const identity = createRunIdentity(fixedToken, fixedBackendToken)
  const redactor = createE2ERedactor([identity.token, identity.backendToken])
  activeRedactor = redactor
  const artifactDir = path.join(electronRoot, 'test-results', 'e2e', identity.runId, caseId)
  fs.mkdirSync(artifactDir, { recursive: true })
  const fixtureLog = fs.createWriteStream(path.join(artifactDir, 'fixture-stderr.log'), { flags: 'a' })
  const electronLog = fs.createWriteStream(path.join(artifactDir, 'electron.log'), { flags: 'a' })
  const python = resolveRepositoryPython(repositoryRoot)
  const expectedHash = canonicalManifestHash(manifestPath)
  const fixture = ownedResources.registerChild(spawnOwned(python, [
    fixturePath,
    '--host', '127.0.0.1',
    '--port', '0',
    '--token', identity.token,
    '--artifact-dir', artifactDir,
  ], {
    cwd: repositoryRoot,
    env: {
      ...process.env,
      NO_PROXY: loopbackNoProxy,
      no_proxy: loopbackNoProxy,
      YUIZAKI_E2E_BACKEND_TOKEN: identity.backendToken,
      YUIZAKI_E2E_SOCKET_ORIGIN: trustedSocketOrigin,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  }))
  fixture.stderr.pipe(createRedactingTransform(redactor)).pipe(fixtureLog)
  let electron = null
  const userData = ownedResources.registerTempDirectory(createTempUserData())
  const hardTimeout = setTimeout(() => {
    void terminateOwnedChild(electron)
    void terminateOwnedChild(fixture)
  }, 120_000)
  try {
    const startupLine = await waitForLine(fixture.stdout, 10_000, 'fixture startup record')
    const startup = parseFixtureStartupRecord(startupLine, expectedHash)
    const origin = `http://127.0.0.1:${startup.port}`
    await requestJson(`${origin}/api/ping`)
    await requestJson(`${origin}/__e2e__/case/start`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'X-Yuizaki-E2E-Token': identity.token },
      body: JSON.stringify({ case_id: caseId }),
    })
    if (fixtureOnly) {
      return { ...identity.publicIdentity, case: caseId, status: 'fixture-ready', artifactDir }
    }
    if (!fs.existsSync(electronCli)) throw new Error(`Electron CLI is missing: ${electronCli}`)
    electron = ownedResources.registerChild(spawnOwned(process.execPath, [electronCli, '.', `--user-data-dir=${userData}`], {
      cwd: electronRoot,
      env: {
        ...process.env,
        NO_PROXY: loopbackNoProxy,
        no_proxy: loopbackNoProxy,
        DESKTOP_PET_SKIP_INTERNAL_PYTHON: '1',
        SERVER_HOST: '127.0.0.1',
        SERVER_PORT: String(startup.port),
        YUIZAKI_E2E: '1',
        YUIZAKI_E2E_TOKEN: identity.token,
        YUIZAKI_E2E_CASE: caseId,
        YUIZAKI_E2E_RUN_ID: identity.runId,
        YUIZAKI_E2E_TOKEN_HASH: identity.tokenHash,
        YUIZAKI_E2E_ARTIFACT_DIR: artifactDir,
        YUIZAKI_E2E_FAILURE_PROBE: failureProbe ?? '',
        YUIZAKI_CONTROL_TOKEN: identity.backendToken,
        YUIZAKI_BACKEND_API_TOKEN: identity.backendToken,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    }))
    electron.stdout.pipe(createRedactingTransform(redactor)).pipe(electronLog, { end: false })
    electron.stderr.pipe(createRedactingTransform(redactor)).pipe(electronLog, { end: false })
    const { line: resultLine, record: result } = await waitForJsonRecord(
      electron.stdout,
      110_000,
      'Electron E2E result',
      (record) => record?.type === 'yuizaki-e2e-result',
    )
    if (
      result?.type !== 'yuizaki-e2e-result'
      || result.run_id !== identity.runId
      || result.token_hash !== identity.tokenHash
      || result.backend_token_hash !== identity.backendTokenHash
      || result.case !== caseId
      || result.status !== 'passed'
    ) {
      throw new Error(`Invalid Electron E2E result: ${redactor.redactText(resultLine)}`)
    }
    return { ...identity.publicIdentity, case: caseId, status: 'passed', artifactDir }
  } catch (error) {
    const safeError = redactor.redactText(error instanceof Error ? error.stack || error.message : String(error))
    fs.writeFileSync(path.join(artifactDir, 'supervisor-error.txt'), safeError)
    const sanitizedError = new Error(safeError)
    sanitizedError.stack = safeError
    throw sanitizedError
  } finally {
    clearTimeout(hardTimeout)
    await terminateOwnedChild(electron)
    await terminateOwnedChild(fixture)
    ownedResources.unregisterChild(electron)
    ownedResources.unregisterChild(fixture)
    fixtureLog.end()
    electronLog.end()
    try {
      fs.rmSync(userData, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
      ownedResources.unregisterTempDirectory(userData)
    } catch (error) {
      fs.appendFileSync(
        path.join(artifactDir, 'supervisor-cleanup-warning.txt'),
        redactor.redactText(error instanceof Error ? error.stack || error.message : String(error)),
      )
    }
  }
}

const results = []
for (const caseId of caseIds) {
  if (lifecycle.isStopping()) break
  results.push(await runCase(caseId))
}
console.log(JSON.stringify({ type: 'yuizaki-e2e-supervisor-result', status: 'passed', results }))
lifecycle.dispose()
