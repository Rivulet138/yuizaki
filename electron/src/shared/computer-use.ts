export type ComputerUseAction =
  | { type: 'move'; x: number; y: number }
  | { type: 'click'; button: 'left' | 'middle' | 'right'; count: number }
  | { type: 'key_press'; keys: string[] }
  | { type: 'text_input'; text: string }

export interface ComputerUsePreviewRequest {
  actions: ComputerUseAction[]
}

export interface ComputerUseBridgeStatus {
  scope: 'device'
  revision: number
  stopped: boolean
  degraded: boolean
  stopInFlight: boolean
  lastStop: { at: string; source: 'ipc' | 'shortcut' | 'host'; backendRevision?: number } | null
  lastError: { at: string; code: string; message: string } | null
}

export interface ComputerUseBackendResponse {
  ok: boolean
  scope?: 'device'
  revision?: number
  stopped?: boolean
  degraded?: boolean
  controllerStopEpoch?: number
  interruptedVisual?: number
  interruptedTools?: number
  interruptedGenerations?: number
  idempotent?: boolean
  code?: string
  message?: string
}

export type ComputerUseBridgeResult<T = Record<string, never>> =
  | { ok: true; data: T; status: ComputerUseBridgeStatus }
  | { ok: false; code: string; message: string; status: ComputerUseBridgeStatus }
