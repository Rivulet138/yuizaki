export type E2ERendererControl =
  | 'pauseHealthPolling'
  | 'pollHealthOnce'
  | 'resumeHealthPolling'
  | 'sampleVisualOnce'
  | 'pauseCompanionPolling'
  | 'pollCompanionOnce'
  | 'resumeCompanionPolling'
  | 'advanceCompanionCooldown'
  | 'pauseHeartbeat'
  | 'emitHeartbeatOnce'
  | 'teardownRuntime'

export type E2ERendererControlRequest = {
  requestId: string
  control: E2ERendererControl
  payload?: unknown
}

export type E2EActivationProof = { proof: string }
