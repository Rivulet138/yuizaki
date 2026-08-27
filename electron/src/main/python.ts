import { spawn, type ChildProcess } from 'child_process'
import fs from 'fs'
import path from 'path'
import axios from 'axios'
import { randomBytes, randomUUID } from 'crypto'
import util from 'util'
import { resolvePythonApiOrigin } from './http/python-origin'
import { resolvePythonRuntime } from './python-runtime'

export type PythonServiceState = 'idle' | 'starting' | 'running' | 'failed' | 'cancelled'

export interface PythonServiceRecoveryOptions {
  maxAttempts?: number
  baseDelayMs?: number
  startupMaxAttempts?: number
  startupRetryDelayMs?: number
  pythonEnvFile?: string | null
  logOutput?: boolean
}

type PythonRuntimeIdentity = {
  instanceId: string
  generation: number
  startupNonce: string
  pid: number | null
}

export class PythonService {
  private process: ChildProcess | null = null
  private readonly backendOrigin = resolvePythonApiOrigin()
  private readonly backendEndpoint = this.resolveBackendEndpoint()
  private readonly livenessCheckUrl = `${this.backendOrigin}/api/ping`
  private readonly maxRetries: number
  private readonly retryDelayMs: number
  private readonly guardedStreams = new WeakSet<NodeJS.WriteStream>()
  private readonly managedExternally = this.resolveManagedExternally()
  private operationGeneration = 0
  private startPromise: Promise<void> | null = null
  private state: PythonServiceState = 'idle'
  private lastError: string | null = null
  private recoveryAllowed = false
  private recoveryAttempts = 0
  private recoveryTimer: ReturnType<typeof setTimeout> | null = null
  private startupExitPromise: Promise<never> | null = null
  private startupExitReject: ((error: Error) => void) | null = null
  private runtimeIdentity: PythonRuntimeIdentity | null = null
  private readonly maxRecoveryAttempts: number
  private readonly recoveryBaseDelayMs: number
  private readonly pythonEnvFile: string | null | undefined
  private readonly logOutput: boolean

  constructor(
    private readonly backendApiToken: string = process.env['YUIZAKI_BACKEND_API_TOKEN']?.trim() || '',
    private readonly providerCredentialEnvironment: Record<string, string> = {},
    private readonly hostPerceptionToken: string = process.env['YUIZAKI_HOST_PERCEPTION_TOKEN']?.trim() || '',
    private readonly hostDesktopActionToken: string = '',
    recoveryOptions: PythonServiceRecoveryOptions = {},
  ) {
    this.maxRecoveryAttempts = Math.max(0, Math.floor(recoveryOptions.maxAttempts ?? 3))
    this.recoveryBaseDelayMs = Math.max(0, recoveryOptions.baseDelayMs ?? 1000)
    this.maxRetries = Math.max(1, Math.floor(recoveryOptions.startupMaxAttempts ?? 120))
    this.retryDelayMs = Math.max(0, recoveryOptions.startupRetryDelayMs ?? 1000)
    this.pythonEnvFile = recoveryOptions.pythonEnvFile
    this.logOutput = recoveryOptions.logOutput ?? true
  }

  async start(): Promise<void> {
    this.recoveryAllowed = true
    this.clearRecoveryTimer()
    this.recoveryAttempts = 0
    return this.beginStart()
  }

  private async beginStart(): Promise<void> {
    if (this.state === 'running' && (this.process || this.managedExternally)) return
    if (this.startPromise) return this.startPromise

    const generation = ++this.operationGeneration
    this.state = 'starting'
    this.lastError = null
    const operation = this.startOperation(generation)
    this.startPromise = operation
    try {
      await operation
    } finally {
      if (this.startPromise === operation) this.startPromise = null
    }
  }

  async stop(): Promise<void> {
    const pendingStart = this.startPromise
    this.recoveryAllowed = false
    this.clearRecoveryTimer()
    this.operationGeneration += 1
    await this.terminateCurrentProcess()
    await pendingStart?.catch(() => undefined)
    this.state = 'idle'
  }

  async cancelStart(): Promise<void> {
    const pendingStart = this.startPromise
    this.recoveryAllowed = false
    this.clearRecoveryTimer()
    this.operationGeneration += 1
    this.state = 'cancelled'
    await this.terminateCurrentProcess()
    await pendingStart?.catch(() => undefined)
  }

  async health(expectedIdentity: PythonRuntimeIdentity | null = this.runtimeIdentity): Promise<boolean> {
    try {
      const response = await axios.get(this.livenessCheckUrl, { timeout: 2000 })
      const status = response.data?.status
      const healthy = status === 'healthy' || status === 'ok' || response.data?.healthy === true || response.data?.ok === true
      if (!healthy) return false
      if (this.managedExternally) return true
      if (expectedIdentity === null) return false
      const runtime = response.data?.runtime
      return Boolean(
        runtime
        && runtime.instance_id === expectedIdentity.instanceId
        && Number(runtime.generation) === expectedIdentity.generation
        && runtime.startup_nonce === expectedIdentity.startupNonce
      )
    } catch {
      return false
    }
  }

  isRunning(): boolean {
    return this.state === 'running' || this.process !== null
  }

  getStatus(): {
    state: PythonServiceState
    generation: number
    error: string | null
    instanceId: string | null
    pid: number | null
    recoveryAttempts: number
  } {
    return {
      state: this.state,
      generation: this.operationGeneration,
      error: this.lastError,
      instanceId: this.runtimeIdentity?.instanceId ?? null,
      pid: this.runtimeIdentity?.pid ?? null,
      recoveryAttempts: this.recoveryAttempts,
    }
  }

  private async startOperation(generation: number): Promise<void> {
    try {
      if (this.managedExternally) {
        this.safeConsole('log', 'Python service is managed externally; waiting for liveness endpoint %s', this.livenessCheckUrl)
        await this.waitForHealth(generation, null)
        this.assertCurrentGeneration(generation)
        this.state = 'running'
        this.startupExitPromise = null
        this.startupExitReject = null
        this.recoveryAttempts = 0
        return
      }

      const pythonDir = this.resolvePythonDir()
      const pythonExe = resolvePythonRuntime(pythonDir).executable
      const configuredEnvFile = this.pythonEnvFile?.trim()
      const pythonEnvFile = this.pythonEnvFile === null
        ? null
        : configuredEnvFile || path.join(pythonDir, '.env')
      const args = ['-m', 'uvicorn', 'app:app', '--host', this.backendEndpoint.host, '--port', this.backendEndpoint.port]
      if (pythonEnvFile && fs.existsSync(pythonEnvFile)) args.push('--env-file', pythonEnvFile)

      const runtimeIdentity: PythonRuntimeIdentity = {
        instanceId: randomUUID(),
        generation,
        startupNonce: randomBytes(24).toString('hex'),
        pid: null,
      }
      this.runtimeIdentity = runtimeIdentity

      const child = spawn(pythonExe, args, {
        cwd: pythonDir,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: {
          ...process.env,
          ...this.providerCredentialEnvironment,
          ...(this.backendApiToken ? { YUIZAKI_BACKEND_API_TOKEN: this.backendApiToken } : {}),
           ...(this.hostPerceptionToken ? { YUIZAKI_HOST_PERCEPTION_TOKEN: this.hostPerceptionToken } : {}),
           ...(this.hostDesktopActionToken ? { YUIZAKI_HOST_DESKTOP_ACTION_TOKEN: this.hostDesktopActionToken } : {}),
          YUIZAKI_RUNTIME_INSTANCE_ID: runtimeIdentity.instanceId,
          YUIZAKI_RUNTIME_GENERATION: String(runtimeIdentity.generation),
          YUIZAKI_RUNTIME_STARTUP_NONCE: runtimeIdentity.startupNonce,
        },
      })
      runtimeIdentity.pid = child.pid ?? null
      if (generation !== this.operationGeneration) {
        child.kill('SIGTERM')
        throw new Error('Python service start was cancelled')
      }
      this.process = child
      this.attachProcessLogging(child, runtimeIdentity)
      this.startupExitPromise = new Promise<never>((_, reject) => {
        this.startupExitReject = reject
      })
      await this.waitForHealth(generation, runtimeIdentity)
      this.assertCurrentGeneration(generation)
      this.state = 'running'
      this.startupExitPromise = null
      this.startupExitReject = null
      this.recoveryAttempts = 0
    } catch (error) {
      this.startupExitPromise = null
      this.startupExitReject = null
      await this.terminateCurrentProcess()
      if (generation === this.operationGeneration) {
        this.state = 'failed'
        this.lastError = error instanceof Error ? error.message : String(error)
      }
      throw error
    }
  }

  private attachProcessLogging(child: ChildProcess, runtimeIdentity: PythonRuntimeIdentity): void {
    child.stdout?.on('data', (data) => this.safeConsole('log', '[Python] %s', String(data).trimEnd()))
    child.stderr?.on('data', (data) => this.safeConsole('error', '[Python Error] %s', String(data).trimEnd()))
    child.on('error', (error) => {
      this.safeConsole('error', 'Failed to start Python service: %o', error)
      if (this.process !== child) return
      this.process = null
      if (this.runtimeIdentity === runtimeIdentity) this.runtimeIdentity = null
      const runtimeError = new Error(`Python service process error: ${error.message}`)
      this.lastError = runtimeError.message
      if (this.state === 'starting') {
        this.startupExitReject?.(runtimeError)
        this.startupExitReject = null
      }
      if ((this.state === 'starting' || this.state === 'running') && this.recoveryAllowed) {
        this.state = 'failed'
        this.scheduleRecovery()
      }
    })
    child.on('exit', (code, signal) => {
      this.safeConsole('log', 'Python service exited with code %s', code)
      if (this.process === child) {
        this.process = null
        if (this.runtimeIdentity === runtimeIdentity) this.runtimeIdentity = null
        if (this.state === 'running' && this.recoveryAllowed) {
          this.state = 'failed'
          this.lastError = `Python service exited unexpectedly (${signal ? `signal ${signal}` : `code ${String(code)}`})`
          this.scheduleRecovery()
        } else if (this.state === 'starting') {
          const error = new Error(`Python service exited before becoming healthy (${signal ? `signal ${signal}` : `code ${String(code)}`})`)
          this.lastError = error.message
          this.startupExitReject?.(error)
          this.startupExitReject = null
          this.state = 'failed'
          this.scheduleRecovery()
        }
      }
    })
  }

  private scheduleRecovery(): void {
    if (
      !this.recoveryAllowed
      || this.recoveryTimer
      || this.recoveryAttempts >= this.maxRecoveryAttempts
    ) return

    const attempt = ++this.recoveryAttempts
    const delayMs = this.recoveryBaseDelayMs * (2 ** (attempt - 1))
    const generation = this.operationGeneration
    this.recoveryTimer = setTimeout(() => {
      this.recoveryTimer = null
      if (
        !this.recoveryAllowed
        || generation !== this.operationGeneration
        || this.process
        || this.state !== 'failed'
      ) return
      void this.beginStart().catch(() => this.scheduleRecovery())
    }, delayMs)
  }

  private clearRecoveryTimer(): void {
    if (!this.recoveryTimer) return
    clearTimeout(this.recoveryTimer)
    this.recoveryTimer = null
  }

  private async waitForHealth(
    generation: number,
    expectedIdentity: PythonRuntimeIdentity | null,
  ): Promise<void> {
    for (let attempt = 0; attempt < this.maxRetries; attempt += 1) {
      this.assertCurrentGeneration(generation)
      const health = this.health(expectedIdentity)
      if (await (this.startupExitPromise ? Promise.race([health, this.startupExitPromise]) : health)) {
        this.assertCurrentGeneration(generation)
        return
      }
      await new Promise((resolve) => setTimeout(resolve, this.retryDelayMs))
    }
    throw new Error('Python service failed to start after retries')
  }

  private assertCurrentGeneration(generation: number): void {
    if (generation !== this.operationGeneration) throw new Error('Python service start was cancelled')
  }

  private async terminateCurrentProcess(): Promise<void> {
    const child = this.process
    this.process = null
    this.runtimeIdentity = null
    if (!child || child.killed) return
    child.kill('SIGTERM')
    await new Promise<void>((resolve) => {
      const timeout = setTimeout(() => {
        child.kill('SIGKILL')
        resolve()
      }, 5000)
      child.once('exit', () => {
        clearTimeout(timeout)
        resolve()
      })
    })
  }

  private resolvePythonDir(): string {
    const configured = process.env['YUIZAKI_PYTHON_DIR']?.trim()
    const candidates = [
      ...(configured ? [configured] : []),
      ...(process.resourcesPath ? [path.join(process.resourcesPath, 'runtime', 'python')] : []),
      path.resolve(__dirname, '../../../python'),
      path.resolve(process.cwd(), '../python'),
    ]
    for (const candidate of candidates) {
      if (fs.existsSync(path.join(candidate, 'app.py'))) return candidate
    }
    throw new Error(`Python project directory not found. Tried: ${candidates.join(', ')}`)
  }

  private resolveManagedExternally(): boolean {
    const value = process.env['DESKTOP_PET_SKIP_INTERNAL_PYTHON']?.trim().toLowerCase()
    return value === '1' || value === 'true' || value === 'yes' || value === 'external'
  }

  private resolveBackendEndpoint(): { host: string; port: string } {
    try {
      const parsed = new URL(this.backendOrigin)
      return {
        host: parsed.hostname || process.env['SERVER_HOST']?.trim() || '127.0.0.1',
        port: parsed.port || (parsed.protocol === 'https:' ? '443' : '80'),
      }
    } catch {
      return {
        host: process.env['SERVER_HOST']?.trim() || '127.0.0.1',
        port: process.env['SERVER_PORT']?.trim() || '8001',
      }
    }
  }

  private safeConsole(method: 'log' | 'error', format: string, ...args: unknown[]): void {
    if (!this.logOutput) return
    const stream = method === 'error' ? process.stderr : process.stdout
    if (!stream) return
    if (!this.guardedStreams.has(stream)) {
      stream.on('error', () => undefined)
      this.guardedStreams.add(stream)
    }
    if (stream.destroyed || !stream.writable || stream.writableEnded || stream.errored) return
    try {
      stream.write(`${util.format(format, ...args)}\n`, () => undefined)
    } catch {
      // Logging must not terminate the main process.
    }
  }
}
