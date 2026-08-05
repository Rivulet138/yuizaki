import { spawn, ChildProcess } from 'child_process';
import fs from 'fs';
import path from 'path';
import axios from 'axios';
import util from 'util';
import { resolvePythonApiOrigin } from './http/python-origin';
import { resolvePythonRuntime } from './python-runtime';

export class PythonService {
  private process: ChildProcess | null = null;
  private readonly pythonDir = this.resolvePythonDir();
  private readonly pythonExe = this.resolvePythonExe();
  private readonly pythonEnvFile = path.join(this.pythonDir, '.env');
  private readonly backendOrigin = resolvePythonApiOrigin();
  private readonly backendEndpoint = this.resolveBackendEndpoint();
  private readonly livenessCheckUrl = `${this.backendOrigin}/api/ping`;
  private readonly maxRetries = 120;
  private readonly retryDelayMs = 1000;
  private readonly guardedStreams = new WeakSet<NodeJS.WriteStream>();
  private readonly managedExternally = this.resolveManagedExternally();

  constructor(
    private readonly backendApiToken: string = process.env['YUIZAKI_BACKEND_API_TOKEN']?.trim() || '',
    private readonly providerCredentialEnvironment: Record<string, string> = {},
  ) {}

  async start(): Promise<void> {
    if (this.process) {
      this.safeConsole('log', 'Python service already running');
      return;
    }

    if (this.managedExternally) {
      this.safeConsole('log', 'Python service is managed externally; waiting for liveness endpoint %s', this.livenessCheckUrl);
      await this.waitForHealth();
      return;
    }

    this.safeConsole('log', 'Starting Python service...');

    const args = ['-m', 'uvicorn', 'app:app', '--host', this.backendEndpoint.host, '--port', this.backendEndpoint.port];
    if (fs.existsSync(this.pythonEnvFile)) {
      args.push('--env-file', this.pythonEnvFile);
    }

    // 启动 uvicorn
    this.process = spawn(this.pythonExe, args, {
      cwd: this.pythonDir,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        ...this.providerCredentialEnvironment,
        ...(this.backendApiToken ? { YUIZAKI_BACKEND_API_TOKEN: this.backendApiToken } : {}),
      },
    });

    this.process.stdout?.on('data', (data) => {
      this.safeConsole('log', '[Python] %s', String(data).trimEnd());
    });

    this.process.stderr?.on('data', (data) => {
      this.safeConsole('error', '[Python Error] %s', String(data).trimEnd());
    });

    this.process.on('error', (err) => {
      this.safeConsole('error', 'Failed to start Python service: %o', err);
      this.process = null;
    });

    this.process.on('exit', (code) => {
      this.safeConsole('log', `Python service exited with code ${code}`);
      this.process = null;
    });

    // 等待服务启动
    await this.waitForHealth();
  }

  async stop(): Promise<void> {
    if (!this.process) {
      this.safeConsole('log', 'Python service not running');
      return;
    }

    this.safeConsole('log', 'Stopping Python service...');
    this.process.kill('SIGTERM');

    // 等待进程退出
    await new Promise((resolve) => {
      const timeout = setTimeout(() => {
        if (this.process) {
          this.process.kill('SIGKILL');
        }
        resolve(null);
      }, 5000);

      this.process?.on('exit', () => {
        clearTimeout(timeout);
        resolve(null);
      });
    });

    this.process = null;
  }

  async health(): Promise<boolean> {
    try {
      const response = await axios.get(this.livenessCheckUrl, { timeout: 2000 });
      const status = response.data?.status;
      return status === 'healthy' || status === 'ok' || response.data?.healthy === true || response.data?.ok === true;
    } catch {
      return false;
    }
  }

  private async waitForHealth(): Promise<void> {
    for (let i = 0; i < this.maxRetries; i++) {
      if (await this.health()) {
        this.safeConsole('log', 'Python service is healthy');
        return;
      }

      await new Promise((resolve) => setTimeout(resolve, this.retryDelayMs));
    }

    throw new Error('Python service failed to start after retries');
  }

  isRunning(): boolean {
    return this.process !== null;
  }

  private resolvePythonDir(): string {
    const candidates = [
      path.resolve(__dirname, '../../../python'), // dist/main -> yuizaki/python
      path.resolve(__dirname, '../../python'), // fallback for legacy layout
      path.resolve(process.cwd(), '../python'), // launched from electron/
    ];

    for (const candidate of candidates) {
      if (fs.existsSync(path.join(candidate, 'app.py'))) {
        return candidate;
      }
    }

    throw new Error(`Python project directory not found. Tried: ${candidates.join(', ')}`);
  }

  private resolvePythonExe(): string {
    return resolvePythonRuntime(this.pythonDir).executable;
  }

  private resolveManagedExternally(): boolean {
    const value = process.env['DESKTOP_PET_SKIP_INTERNAL_PYTHON']?.trim().toLowerCase();
    return value === '1' || value === 'true' || value === 'yes' || value === 'external';
  }

  private resolveBackendEndpoint(): { host: string; port: string } {
    try {
      const parsed = new URL(this.backendOrigin);
      return {
        host: parsed.hostname || process.env['SERVER_HOST']?.trim() || '127.0.0.1',
        port: parsed.port || (parsed.protocol === 'https:' ? '443' : '80'),
      };
    } catch {
      return {
        host: process.env['SERVER_HOST']?.trim() || '127.0.0.1',
        port: process.env['SERVER_PORT']?.trim() || '8001',
      };
    }
  }

  private safeConsole(method: 'log' | 'error', fmt: string, ...args: unknown[]): void {
    const stream = method === 'error' ? process.stderr : process.stdout;
    if (!stream) {
      return;
    }

    if (!this.guardedStreams.has(stream)) {
      stream.on('error', () => {
        // Swallow stdout/stderr pipe failures so logging never crashes the app.
      });
      this.guardedStreams.add(stream);
    }

    if (stream.destroyed || !stream.writable || stream.writableEnded || stream.errored) {
      return;
    }

    const message = `${util.format(fmt, ...args)}\n`;

    try {
      stream.write(message, (err?: Error | null) => {
        const code = (err as NodeJS.ErrnoException | undefined)?.code;
        if (code === 'EPIPE' || code === 'ERR_STREAM_DESTROYED') {
          return;
        }
      });
    } catch (err: any) {
      if (err?.code !== 'EPIPE' && err?.code !== 'ERR_STREAM_DESTROYED') {
        // Ignore logging errors to avoid crashing the main process.
      }
    }
  }
}
