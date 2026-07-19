import type { AvatarManifest, ExpressionLayer, PetControlConfigPatch, PetExpressionMixPayload, PetLipSyncViseme, PetParameterOverrideItem, PetRendererStatePayload } from '../../shared/pet-control'

export interface PetRuntimeAdapter {
  readonly modelType: 'live2d' | 'vrm'
  loadModel(config: PetControlConfigPatch): Promise<void>
  applyConfig(config: PetControlConfigPatch): void
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
