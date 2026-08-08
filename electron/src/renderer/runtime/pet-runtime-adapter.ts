import type { AvatarManifest, ExpressionLayer, PetControlConfigPatch, PetExpressionMixPayload, PetLipSyncViseme, PetParameterOverrideItem, PetRendererStatePayload } from '../../shared/pet-control'
import type {
  AvatarAction,
  AvatarActionExecutionResult,
  AvatarCapabilitySnapshot,
} from '../../shared/avatar-command'

export interface PetRuntimeAdapter {
  readonly modelType: 'live2d' | 'vrm'
  loadModel(config: PetControlConfigPatch): Promise<void>
  applyConfig(config: PetControlConfigPatch): void
  getCapabilities(): AvatarCapabilitySnapshot
  executeAvatarAction(action: AvatarAction): AvatarActionExecutionResult
  triggerExpression?(name: string): void
  triggerExpressionMix?(payload: PetExpressionMixPayload): void
  applyExpressionMix?(layers: ExpressionLayer[]): void
  applyParameterOverrides?(overrides: PetParameterOverrideItem[]): void
  getCurrentModelManifest?(): AvatarManifest | null
  triggerMotion?(group: string, index?: number): void
  triggerRandomMotion?(): void
  setLipSyncLevel?(level: number, active: boolean): void
  setLipSyncViseme?(viseme: PetLipSyncViseme, weight: number, active: boolean): void
  getState(): PetRendererStatePayload
  destroy(): void
}
