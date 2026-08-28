import type { AvatarManifest, ExpressionLayer, PetCompanionIdleProfile, PetControlConfigPatch, PetExpressionMixPayload, PetLipSyncViseme, PetParameterOverrideItem, PetRendererStatePayload } from '../../shared/pet-control'
import type {
  AvatarAction,
  AvatarActionExecutionResult,
  AvatarCapabilitySnapshot,
} from '../../shared/avatar-command'

export interface PetRuntimeRenderPolicy {
  targetFps: number
  paused: boolean
}

export interface PetRuntimeAdapter {
  readonly modelType: 'live2d' | 'vrm'
  loadModel(config: PetControlConfigPatch): Promise<void>
  cancelPendingLoad?(): void
  applyConfig(config: PetControlConfigPatch): void
  getCapabilities(): AvatarCapabilitySnapshot
  executeAvatarAction(action: AvatarAction): AvatarActionExecutionResult
  setCompanionIdleProfile?(profile: PetCompanionIdleProfile): void
  triggerExpression?(name: string): void
  triggerExpressionMix?(payload: PetExpressionMixPayload): void
  applyExpressionMix?(layers: ExpressionLayer[]): void
  applyParameterOverrides?(overrides: PetParameterOverrideItem[]): void
  getCurrentModelManifest?(): AvatarManifest | null
  triggerMotion?(group: string, index?: number): void
  triggerRandomMotion?(): void
  setLipSyncLevel?(level: number, active: boolean): void
  setLipSyncViseme?(viseme: PetLipSyncViseme, weight: number, active: boolean): void
  setExternalViseme?(weight: number, active: boolean): void
  setRenderPolicy?(policy: PetRuntimeRenderPolicy): void
  getState(): PetRendererStatePayload
  destroy(): void
}
