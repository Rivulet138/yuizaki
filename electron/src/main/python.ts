import { spawn, type ChildProcess } from 'child_process'
import fs from 'fs'
import path from 'path'
import axios from 'axios'
import util from 'util'
import { resolvePythonApiOrigin } from './http/python-origin'
import { resolvePythonRuntime } from './python-runtime'

export type PythonServiceState = 'idle' | 'starting' | 'running' | 'failed' | 'cancelled'

export class PythonService {
  private process: ChildProcess | null = null
  private readonly backendOrigin = resolvePythonApiOrigin()
  private readonly backendEndpoint = this.resolveBackendEndpoint()
  private readonly livenessCheckUrl = `${this.backendOrigin}/api/ping`
  private readonly maxRetries = 120
  private readonly retryDelayMs = 1000
  private readonly guardedStreams = new WeakSet<NodeJS.WriteStream>()
  private readonly managedExternally = this.resolveManagedExternally()
  private operationGeneration = 0
  private startPromise: Promise<void> | null = null
  private state: PythonServiceState = 'idle'
  private lastError: string | null = null

  constructor(
    private readonly backendApiToken: string = process.env['YUIZAKI_BACKEND_API_TOKEN']?.trim() || '',
    private readonly providerCredentialEnvironment: Record<string, string> = {},
    private readonly hostPerceptionToken: string = process.env['YUIZAKI_HOST_PERCEPTION_TOKEN']?.trim() || '',
    private readonly hostDesktopActionToken: string = '',
  ) {}

  async start(): Promise<void> {
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
    this.operationGeneration += 1
    await this.terminateCurrentProcess()
    await pendingStart?.catch(() => undefined)
    this.state = 'idle'
  }

  async cancelStart(): Promise<void> {
    const pendingStart = this.startPromise
    this.operationGeneration += 1
    this.state = 'cancelled'
    await this.terminateCurrentProcess()
    await pendingStart?.catch(() => undefined)
  }

  async health(): Promise<boolean> {
    try {
      const response = await axios.get(this.livenessCheckUrl, { timeout: 2000 })
      const status = response.data?.status
      return status === 'healthy' || status === 'ok' || response.data?.healthy === true || response.data?.ok === true
    } catch {
      return false
    }
  }

  isRunning(): boolean {
    return this.state === 'running' || this.process !== null
  }

  getStatus(): { state: PythonServiceState; generation: number; error: string | null } {
    return { state: this.state, generation: this.operationGeneration, error: this.lastError }
  }

  private async startOperation(generation: number): Promise<void> {
    try {
      if (this.managedExternally) {
        this.safeConsole('log', 'Python service is managed externally; waiting for liveness endpoint %s', this.livenessCheckUrl)
        await this.waitForHealth(generation)
        this.assertCurrentGeneration(generation)
        this.state = 'running'
        return
      }

      const pythonDir = this.resolvePythonDir()
      const pythonExe = resolvePythonRuntime(pythonDir).executable
      const pythonEnvFile = path.join(pythonDir, '.env')
      const args = ['-m', 'uvicorn', 'app:app', '--host', this.backendEndpoint.host, '--port', this.backendEndpoint.port]
      if (fs.existsSync(pythonEnvFile)) args.push('--env-file', pythonEnvFile)

      const child = spawn(pythonExe, args, {
        cwd: pythonDir,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: {
          ...process.env,
          ...this.providerCredentialEnvironment,
          ...(this.backendApiToken ? { YUIZAKI_BACKEND_API_TOKEN: this.backendApiToken } : {}),
          ...(this.hostPerceptionToken ? { YUIZAKI_HOST_PERCEPTION_TOKEN: this.hostPerceptionToken } : {}),
          ...(this.hostDesktopActionToken ? { YUIZAKI_HOST_DESKTOP_ACTION_TOKEN: this.hostDesktopActionToken } : {}),
        },
      })
      if (generation !== this.operationGeneration) {
        child.kill('SIGTERM')
        throw new Error('Python service start was cancelled')
      }
      this.process = child
      this.attachProcessLogging(child)
      await this.waitForHealth(generation)
      this.assertCurrentGeneration(generation)
      this.state = 'running'
    } catch (error) {
      await this.terminateCurrentProcess()
      if (generation === this.operationGeneration) {
        this.state = 'failed'
        this.lastError = error instanceof Error ? error.message : String(error)
      }
      throw error
    }
  }

  private attachProcessLogging(child: ChildProcess): void {
    child.stdout?.on('data', (data) => this.safeConsole('log', '[Python] %s', String(data).trimEnd()))
    child.stderr?.on('data', (data) => this.safeConsole('error', '[Python Error] %s', String(data).trimEnd()))
    child.on('error', (error) => {
      this.safeConsole('error', 'Failed to start Python service: %o', error)
      if (this.process === child) this.process = null
    })
    child.on('exit', (code) => {
      this.safeConsole('log', 'Python service exited with code %s', code)
      if (this.process === child) {
        this.process = null
        if (this.state === 'running') this.state = 'failed'
      }
    })
  }

  private async waitForHealth(generation: number): Promise<void> {
    for (let attempt = 0; attempt < this.maxRetries; attempt += 1) {
      this.assertCurrentGeneration(generation)
      if (await this.health()) {
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
