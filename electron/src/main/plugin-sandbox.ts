import { spawn, type ChildProcess } from 'node:child_process'
import path from 'node:path'
import type {
  PluginRouteAgentRequest,
  PluginRouteAgentResponse,
  PluginRouteCommandRequest,
  PluginRouteCommandResponse,
  PluginRouteHttpRequest,
  PluginRouteHttpResponse,
  PluginRouteRequest,
  PluginRouteResponse,
} from '../shared/plugin-route'

type BrokerRunAgent = (payload: PluginRouteAgentRequest) => Promise<PluginRouteAgentResponse>
type BrokerCallKind =
  | 'net:httpRequest'
  | 'files:readText'
  | 'files:writeText'
  | 'files:list'
  | 'commands:run'
type BrokerCallPayload =
  | PluginRouteHttpRequest
  | string
  | { path: string; content: string }
  | PluginRouteCommandRequest
type BrokerCallResult =
  | PluginRouteHttpResponse
  | string
  | { ok: true; bytes: number }
  | Array<{ name: string; type: 'file' | 'directory' | 'other' }>
  | PluginRouteCommandResponse
type BrokerCall = (kind: BrokerCallKind, payload: BrokerCallPayload) => Promise<BrokerCallResult>

type SandboxRequest = Omit<PluginRouteRequest, 'context'> & {
  context: Omit<PluginRouteRequest['context'], 'runAgent' | 'net' | 'files' | 'commands'>
}

interface SandboxExecutionOptions {
  handlerPath: string
  request: SandboxRequest
  timeoutMs: number
  runAgent: BrokerRunAgent
  brokerCall: BrokerCall
}

interface SandboxRunAgentMessage {
  type: 'broker:runAgent'
  requestId: string
  payload: PluginRouteAgentRequest
}

interface SandboxBrokerCallMessage {
  type: 'broker:call'
  requestId: string
  kind: BrokerCallKind
  payload: BrokerCallPayload
}

interface SandboxResultMessage {
  type: 'result'
  result: unknown
}

interface SandboxErrorMessage {
  type: 'error'
  error: string
}

interface SandboxLogMessage {
  type: 'log'
  level: 'log' | 'warn' | 'error'
  args: unknown[]
}

type SandboxWorkerMessage =
  | SandboxRunAgentMessage
  | SandboxBrokerCallMessage
  | SandboxResultMessage
  | SandboxErrorMessage
  | SandboxLogMessage

export interface PluginSandboxExecution {
  promise: Promise<PluginRouteResponse>
  terminate: () => void
}

const SANDBOX_PROCESS_SOURCE = String.raw`
const fs = require('node:fs/promises')
const vm = require('node:vm')

const pendingBrokerCalls = new Map()
let nextBrokerId = 1
let workerData = null

const postMessage = (message) => {
  if (typeof process.send === 'function') process.send(message)
}

const sanitize = (value, seen = new WeakSet()) => {
  if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value
  }
  if (typeof value === 'undefined' || typeof value === 'function' || typeof value === 'symbol' || typeof value === 'bigint') {
    return undefined
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitize(item, seen))
  }
  if (typeof value === 'object') {
    if (seen.has(value)) {
      return '[Circular]'
    }
    seen.add(value)
    const result = {}
    for (const [key, item] of Object.entries(value)) {
      const nextValue = sanitize(item, seen)
      if (typeof nextValue !== 'undefined') {
        result[key] = nextValue
      }
    }
    return result
  }
  return String(value)
}

const serializeError = (error) => error instanceof Error ? error.message : String(error)

const denyPatterns = [
  [/^\s*import\s/m, 'static import is not available in plugin sandbox'],
  [/\bimport\s*\(/, 'dynamic import is not available in plugin sandbox'],
  [/\brequire\s*\(/, 'require is not available in plugin sandbox'],
  [/\beval\s*\(/, 'eval is not available in plugin sandbox'],
  [/\bFunction\s*\(/, 'Function constructor is not available in plugin sandbox'],
]

const assertSafeSource = (source) => {
  for (const [pattern, message] of denyPatterns) {
    if (pattern.test(source)) {
      throw new Error(message)
    }
  }
}

const transformModuleSource = (source) => {
  let transformed = source
    .replace(/\bexport\s+default\s+/g, 'exports.default = ')
    .replace(/\bexport\s+async\s+function\s+handle\s*\(/g, 'async function handle(')
    .replace(/\bexport\s+function\s+handle\s*\(/g, 'function handle(')

  if (/\bexport\b/.test(transformed)) {
    throw new Error('Unsupported plugin export syntax')
  }

  return transformed + '\n;if (typeof handle === "function" && !exports.handle) exports.handle = handle;\n'
}

process.on('message', (message) => {
  if (!message || typeof message !== 'object') {
    return
  }
  if (message.type === 'init' && !workerData) {
    workerData = message.workerData
    void run()
    return
  }
  if (message.type === 'broker:runAgentResult') {
    const pending = pendingBrokerCalls.get(message.requestId)
    if (!pending) return
    pendingBrokerCalls.delete(message.requestId)
    if (message.ok) {
      pending.resolve(message.result)
    } else {
      pending.reject(new Error(String(message.error || 'Plugin agent bridge failed')))
    }
  }
})

const runAgentViaBroker = (payload) => new Promise((resolve, reject) => {
  const requestId = 'broker_' + nextBrokerId++
  pendingBrokerCalls.set(requestId, { resolve, reject })
  postMessage({
    type: 'broker:runAgent',
    requestId,
    payload: sanitize(payload),
  })
})

const callBroker = (kind, payload) => new Promise((resolve, reject) => {
  const requestId = 'broker_' + nextBrokerId++
  pendingBrokerCalls.set(requestId, { resolve, reject })
  postMessage({
    type: 'broker:call',
    requestId,
    kind,
    payload: sanitize(payload),
  })
})

const scopedConsole = {
  log: (...args) => postMessage({ type: 'log', level: 'log', args: sanitize(args) }),
  warn: (...args) => postMessage({ type: 'log', level: 'warn', args: sanitize(args) }),
  error: (...args) => postMessage({ type: 'log', level: 'error', args: sanitize(args) }),
}

const run = async () => {
  try {
    const source = await fs.readFile(workerData.handlerPath, 'utf8')
    assertSafeSource(source)
    const exports = {}
    const sandbox = {
      exports,
      console: scopedConsole,
      setTimeout,
      clearTimeout,
      Promise,
      URL,
      URLSearchParams,
      TextEncoder,
      TextDecoder,
      AbortController,
      AbortSignal,
      structuredClone,
    }
    sandbox.globalThis = sandbox
    const context = vm.createContext(sandbox, {
      name: 'yuizaki-plugin-sandbox',
      codeGeneration: { strings: false, wasm: false },
    })
    const script = new vm.Script('"use strict";\n' + transformModuleSource(source), {
      filename: workerData.handlerPath,
      displayErrors: true,
    })
    script.runInContext(context, {
      timeout: Math.max(50, Math.min(Number(workerData.timeoutMs) || 1000, 1000)),
      displayErrors: true,
    })
    const handler = exports.default || exports.handle
    if (typeof handler !== 'function') {
      throw new Error('Plugin route handler missing export')
    }
    const request = sanitize(workerData.request)
    request.context.runAgent = runAgentViaBroker
    request.context.net = {
      httpRequest: (payload) => callBroker('net:httpRequest', payload),
    }
    request.context.files = {
      readText: (targetPath) => callBroker('files:readText', String(targetPath || '')),
      writeText: (targetPath, content) => callBroker('files:writeText', {
        path: String(targetPath || ''),
        content: String(content || ''),
      }),
      list: (targetPath) => callBroker('files:list', String(targetPath || '')),
    }
    request.context.commands = {
      run: (payload) => callBroker('commands:run', payload),
    }
    const result = await handler(request)
    postMessage({ type: 'result', result: sanitize(result) })
  } catch (error) {
    postMessage({ type: 'error', error: serializeError(error) })
  }
}
`

const normalizeSandboxResponse = (value: unknown): PluginRouteResponse => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { body: { ok: true } }
  }

  const record = value as Record<string, unknown>
  const response: PluginRouteResponse = {}
  if (typeof record['status'] === 'number' && Number.isFinite(record['status'])) {
    response.status = Math.trunc(record['status'])
  }
  if ('body' in record) {
    response.body = record['body']
  }
  return response
}

export const buildPluginSandboxProcessArgs = (handlerPath: string): string[] => [
  '--max-old-space-size=64',
  '--permission',
  `--allow-fs-read=${path.resolve(handlerPath)}`,
  '-e',
  SANDBOX_PROCESS_SOURCE,
]

export const executePluginRouteInSandbox = (options: SandboxExecutionOptions): PluginSandboxExecution => {
  const resolvedHandlerPath = path.resolve(options.handlerPath)
  const childEnvironment: NodeJS.ProcessEnv = {
    ELECTRON_RUN_AS_NODE: '1',
    NODE_NO_WARNINGS: '1',
    PATH: process.env['PATH'],
    SystemRoot: process.env['SystemRoot'],
    TEMP: process.env['TEMP'],
    TMP: process.env['TMP'],
  }
  let worker: ChildProcess | null = spawn(process.execPath, buildPluginSandboxProcessArgs(resolvedHandlerPath), {
    stdio: ['ignore', 'ignore', 'pipe', 'ipc'],
    windowsHide: true,
    env: childEnvironment,
  })
  worker.send?.({
    type: 'init',
    workerData: {
      handlerPath: resolvedHandlerPath,
      request: options.request,
      timeoutMs: options.timeoutMs,
    },
  })

  let settled = false

  const terminate = (): void => {
    const activeWorker = worker
    worker = null
    if (activeWorker) {
      activeWorker.kill()
    }
  }

  const promise = new Promise<PluginRouteResponse>((resolve, reject) => {
    const settle = (callback: () => void): void => {
      if (settled) {
        return
      }
      settled = true
      callback()
      terminate()
    }

    worker?.on('message', (message: SandboxWorkerMessage) => {
      if (!message || typeof message !== 'object') {
        return
      }
      if (message.type === 'result') {
        settle(() => resolve(normalizeSandboxResponse(message.result)))
        return
      }
      if (message.type === 'error') {
        settle(() => reject(new Error(message.error)))
        return
      }
      if (message.type === 'broker:runAgent') {
        void options.runAgent(message.payload).then(
          (result) => {
            worker?.send?.({
              type: 'broker:runAgentResult',
              requestId: message.requestId,
              ok: true,
              result,
            })
          },
          (error) => {
            worker?.send?.({
              type: 'broker:runAgentResult',
              requestId: message.requestId,
              ok: false,
              error: error instanceof Error ? error.message : String(error),
            })
          },
        )
        return
      }
      if (message.type === 'broker:call') {
        void options.brokerCall(message.kind, message.payload).then(
          (result) => {
            worker?.send?.({
              type: 'broker:runAgentResult',
              requestId: message.requestId,
              ok: true,
              result,
            })
          },
          (error) => {
            worker?.send?.({
              type: 'broker:runAgentResult',
              requestId: message.requestId,
              ok: false,
              error: error instanceof Error ? error.message : String(error),
            })
          },
        )
      }
    })

    worker?.stderr?.once('data', (data) => {
      if (!settled) {
        settle(() => reject(new Error(`Plugin process error: ${String(data).trim()}`)))
      }
    })

    worker?.once('error', (error) => {
      settle(() => reject(error))
    })

    worker?.once('exit', (code) => {
      if (!settled && code !== 0) {
        settle(() => reject(new Error(`Plugin process exited with code ${code}`)))
      }
    })
  })

  return { promise, terminate }
}
