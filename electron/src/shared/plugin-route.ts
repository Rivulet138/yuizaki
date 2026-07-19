export interface PluginRouteCancellationToken {
  aborted: boolean
  reason?: 'cancelled' | 'timeout'
}

export interface PluginRouteInvocationContext {
  invocationId: string
  pluginId: string
  routeId: string
  timeoutMs: number
  cancellation: PluginRouteCancellationToken
  policy: {
    allowedHosts: string[]
    allowedPaths: string[]
    allowedCommands: string[]
  }
  runAgent: (payload: PluginRouteAgentRequest) => Promise<PluginRouteAgentResponse>
  net: PluginRouteNetworkBroker
  files: PluginRouteFileBroker
  commands: PluginRouteCommandBroker
}

export interface PluginRouteHttpRequest {
  url: string
  method?: string
  headers?: Record<string, string>
  body?: string
}

export interface PluginRouteHttpResponse {
  status: number
  ok: boolean
  headers: Record<string, string>
  text: string
}

export interface PluginRouteNetworkBroker {
  httpRequest: (payload: PluginRouteHttpRequest) => Promise<PluginRouteHttpResponse>
}

export interface PluginRouteFileBroker {
  readText: (path: string) => Promise<string>
  writeText: (path: string, content: string) => Promise<{ ok: true; bytes: number }>
  list: (path: string) => Promise<Array<{ name: string; type: 'file' | 'directory' | 'other' }>>
}

export interface PluginRouteCommandRequest {
  command: string
  args?: string[]
  timeoutMs?: number
}

export interface PluginRouteCommandResponse {
  exitCode: number | null
  stdout: string
  stderr: string
}

export interface PluginRouteCommandBroker {
  run: (payload: PluginRouteCommandRequest) => Promise<PluginRouteCommandResponse>
}

export interface PluginRouteAgentMessage {
  role: string
  content: string
}

export interface PluginRouteAgentRequest {
  prompt?: string
  messages?: PluginRouteAgentMessage[]
  sessionId?: string
  requestId?: string
  petControlContext?: unknown
}

export interface PluginRouteAgentResponse {
  choices?: Array<{ message?: { role?: string; content?: string } }>
  action_envelope?: unknown
  pet_control?: unknown
}

export interface PluginRouteRequest {
  method: string
  path: string
  query: Record<string, string>
  body: unknown
  context: PluginRouteInvocationContext
}

export interface PluginRouteResponse {
  status?: number
  body?: unknown
}

export type PluginRouteHandler = (request: PluginRouteRequest) => Promise<PluginRouteResponse> | PluginRouteResponse
