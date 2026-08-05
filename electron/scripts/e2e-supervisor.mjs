import { spawn, spawnSync } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const STARTUP_RECORD_LIMIT = 4096

export const resolveRepositoryPython = (repositoryRoot, platform = process.platform) => {
  const relative = platform === 'win32'
    ? path.join('python', '.venv', 'Scripts', 'python.exe')
    : path.join('python', '.venv', 'bin', 'python')
  const executable = path.join(repositoryRoot, relative)
  if (!fs.existsSync(executable)) {
    throw new Error(`Repository Python virtualenv is missing: ${executable}`)
  }
  return executable
}

export const createRunIdentity = (fixedToken, fixedBackendToken) => {
  const token = fixedToken ?? crypto.randomBytes(32).toString('hex')
  const backendToken = fixedBackendToken ?? crypto.randomBytes(32).toString('base64url')
  const tokenHash = crypto.createHash('sha256').update(token).digest('hex')
  const backendTokenHash = crypto.createHash('sha256').update(backendToken).digest('hex')
  const runId = `${Date.now()}-${crypto.randomBytes(6).toString('hex')}`
  return {
    token,
    backendToken,
    tokenHash,
    backendTokenHash,
    runId,
    publicIdentity: { runId, tokenHash, backendTokenHash },
  }
}

export const canonicalManifestHash = (manifestPath) => {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  return crypto.createHash('sha256').update(JSON.stringify(manifest)).digest('hex')
}

export const parseFixtureStartupRecord = (line, expectedHash) => {
  if (Buffer.byteLength(line, 'utf8') > STARTUP_RECORD_LIMIT) {
    throw new Error(`Fixture startup record exceeds ${STARTUP_RECORD_LIMIT} bytes`)
  }
  let record
  try {
    record = JSON.parse(line)
  } catch (error) {
    throw Object.assign(new Error('Invalid fixture startup record JSON'), { cause: error })
  }
  if (
    record?.type !== 'yuizaki-e2e-fixture'
    || !Number.isInteger(record.port)
    || record.port < 1
    || record.port > 65535
    || record.manifest_hash !== expectedHash
  ) {
    throw new Error('Invalid fixture startup record')
  }
  return record
}

export const waitForLine = (stream, timeoutMs, label) => new Promise((resolve, reject) => {
  let buffer = ''
  const timeout = setTimeout(() => {
    cleanup()
    reject(new Error(`${label} timed out after ${timeoutMs} ms`))
  }, timeoutMs)
  const onData = (chunk) => {
    buffer += chunk.toString('utf8')
    if (Buffer.byteLength(buffer, 'utf8') > STARTUP_RECORD_LIMIT) {
      cleanup()
      reject(new Error(`${label} exceeds ${STARTUP_RECORD_LIMIT} bytes`))
      return
    }
    const newline = buffer.indexOf('\n')
    if (newline >= 0) {
      const line = buffer.slice(0, newline).trim()
      cleanup()
      resolve(line)
    }
  }
  const onEnd = () => {
    cleanup()
    reject(new Error(`${label} ended before a record was received`))
  }
  const cleanup = () => {
    clearTimeout(timeout)
    stream.off('data', onData)
    stream.off('end', onEnd)
  }
  stream.on('data', onData)
  stream.on('end', onEnd)
})

export const waitForJsonRecord = (stream, timeoutMs, label, predicate) => new Promise((resolve, reject) => {
  let buffer = ''
  const timeout = setTimeout(() => {
    cleanup()
    reject(new Error(`${label} timed out after ${timeoutMs} ms`))
  }, timeoutMs)
  const onData = (chunk) => {
    buffer += chunk.toString('utf8')
    let newline = buffer.indexOf('\n')
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim()
      buffer = buffer.slice(newline + 1)
      if (Buffer.byteLength(line, 'utf8') > STARTUP_RECORD_LIMIT) {
        cleanup()
        reject(new Error(`${label} line exceeds ${STARTUP_RECORD_LIMIT} bytes`))
        return
      }
      if (line) {
        try {
          const record = JSON.parse(line)
          if (predicate(record)) {
            cleanup()
            resolve({ line, record })
            return
          }
        } catch {
          // Electron and Chromium may write ordinary log lines before the result record.
        }
      }
      newline = buffer.indexOf('\n')
    }
    if (Buffer.byteLength(buffer, 'utf8') > STARTUP_RECORD_LIMIT) {
      cleanup()
      reject(new Error(`${label} unterminated line exceeds ${STARTUP_RECORD_LIMIT} bytes`))
    }
  }
  const onEnd = () => {
    cleanup()
    reject(new Error(`${label} ended before a matching record was received`))
  }
  const cleanup = () => {
    clearTimeout(timeout)
    stream.off('data', onData)
    stream.off('end', onEnd)
  }
  stream.on('data', onData)
  stream.on('end', onEnd)
})

const waitForExit = (child, timeoutMs) => new Promise((resolve) => {
  if (child.exitCode !== null || child.signalCode !== null) {
    resolve(true)
    return
  }
  const timeout = setTimeout(() => {
    child.off('exit', onExit)
    resolve(false)
  }, timeoutMs)
  const onExit = () => {
    clearTimeout(timeout)
    resolve(true)
  }
  child.once('exit', onExit)
})

export const terminateOwnedChild = async (child) => {
  if (!child || child.exitCode !== null || child.signalCode !== null) return
  child.kill('SIGTERM')
  if (await waitForExit(child, 3_000)) return
  if (process.platform === 'win32' && Number.isInteger(child.pid)) {
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
  } else {
    child.kill('SIGKILL')
  }
  await waitForExit(child, 3_000)
}

export const createTempUserData = () => fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-e2e-userdata-'))

export const spawnOwned = (command, args, options) => spawn(command, args, {
  ...options,
  windowsHide: true,
})

export const createOwnedResourceRegistry = () => {
  const children = new Set()
  const tempDirectories = new Set()
  let cleanupPromise = null
  let accepting = true

  return {
    isStopping: () => !accepting,
    registerChild(child) {
      if (!accepting) throw new Error('E2E supervisor is stopping')
      children.add(child)
      return child
    },
    unregisterChild(child) {
      children.delete(child)
    },
    registerTempDirectory(directory) {
      if (!accepting) throw new Error('E2E supervisor is stopping')
      tempDirectories.add(path.resolve(directory))
      return directory
    },
    unregisterTempDirectory(directory) {
      tempDirectories.delete(path.resolve(directory))
    },
    cleanup() {
      if (cleanupPromise) return cleanupPromise
      accepting = false
      cleanupPromise = (async () => {
        await Promise.allSettled([...children].map((child) => terminateOwnedChild(child)))
        children.clear()
        for (const directory of tempDirectories) {
          try {
            fs.rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
          } catch {
            // Continue cleaning the remaining owned resources.
          }
        }
        tempDirectories.clear()
      })()
      return cleanupPromise
    },
  }
}

const SIGNAL_EXIT_CODES = { SIGINT: 130, SIGTERM: 143 }

export const installProcessLifecycleHandlers = (registry, options = {}) => {
  const exit = options.exit ?? ((code) => process.exit(code))
  const report = options.report ?? ((message) => process.stderr.write(`${message}\n`))
  const sanitizeError = options.sanitizeError ?? ((error) => error instanceof Error ? error.stack || error.message : String(error))
  let shutdownPromise = null

  const requestShutdown = (reason, error) => {
    if (shutdownPromise) return shutdownPromise
    const signalCode = SIGNAL_EXIT_CODES[reason]
    const exitCode = signalCode ?? 1
    if (error !== undefined) report(sanitizeError(error))
    shutdownPromise = registry.cleanup().finally(() => exit(exitCode))
    return shutdownPromise
  }
  const onSigint = () => { void requestShutdown('SIGINT') }
  const onSigterm = () => { void requestShutdown('SIGTERM') }
  const onUncaughtException = (error) => { void requestShutdown('uncaughtException', error) }
  const onUnhandledRejection = (reason) => { void requestShutdown('unhandledRejection', reason) }
  process.on('SIGINT', onSigint)
  process.on('SIGTERM', onSigterm)
  process.on('uncaughtException', onUncaughtException)
  process.on('unhandledRejection', onUnhandledRejection)

  return {
    isStopping: registry.isStopping,
    requestShutdown,
    dispose() {
      process.off('SIGINT', onSigint)
      process.off('SIGTERM', onSigterm)
      process.off('uncaughtException', onUncaughtException)
      process.off('unhandledRejection', onUnhandledRejection)
    },
  }
}
