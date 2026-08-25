export interface DesktopActionStatus {
  enabled: boolean
  windowActionsAvailable: boolean
  nativeInputAvailable: boolean
  emergencyHotkeyAvailable: boolean
  emergencyStopped: boolean
  revision: number
  stopEpoch: number
  operationInFlight: boolean
  degraded: boolean
  leaseState: 'inactive' | 'confirmed' | 'unconfirmed'
  leaseExpiresAt: string | null
  lastHeartbeatAt: string | null
  authorizationGranted: boolean
  authorizationExpiresAt: string | null
  reason: string | null
  lastError: { at: string; code: string; message: string } | null
}

export type DesktopActionResult<T = Record<string, never>> =
  | { ok: true; data: T; status: DesktopActionStatus }
  | { ok: false; code: string; message: string; status: DesktopActionStatus }
