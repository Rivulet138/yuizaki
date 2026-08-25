export type PerceptionCapability =
  | 'screenshot'
  | 'target_window'
  | 'active_application'
  | 'selected_file'
  | 'clipboard'
  | 'ocr'

export interface PerceptionEvidenceProjection {
  evidenceId: string
  capability: PerceptionCapability
  capturedAt: number
  expiresAt: number
  redacted: boolean
  payload: unknown
  provenance: { trust: 'untrusted'; authority: 'evidence' }
}

export type PerceptionBridgeResult =
  | { ok: true; evidence: PerceptionEvidenceProjection }
  | { ok: false; code: string; message: string }
