export type PetModelType = 'live2d' | 'vrm'

export type PetPlacement = 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left' | 'center' | 'free'

export type PetModelSource = 'bundled' | 'local' | 'plugin'

export type PetControlSource = 'manual' | 'automation'

export interface PetControlTriggerOptions {
  source?: PetControlSource
}

export type ExpressionId = string


export type ExpressionKind = 'emotion' | 'pose' | 'prop' | 'effect'

export interface ExpressionLayer {
  key: ExpressionId
  weight: number
}

export interface ExpressionFileBinding {
  mode: 'file'
  file: string
}

export interface ExpressionPresetBinding {
  mode: 'preset'
  params: Record<string, number>
}

export type ExpressionBinding = ExpressionFileBinding | ExpressionPresetBinding

export interface AvatarExpression {
  id: ExpressionId
  label: string
  kind: ExpressionKind
  prompt: string
  binding: ExpressionBinding
  aliases?: string[]
}

export type ParameterId = string

export interface ParameterOverride {
  id: ParameterId
  value: number
}

export interface AvatarParameterControl {
  id: ParameterId
  label: string
  prompt: string
  min: number
  max: number
}

export interface MotionBinding {
  file: string
  group?: string
}

export interface AvatarManifest {
  id: string
  name: string
  summary: string
  persona: {
    tone: string
    traits: string[]
    styleRules: string[]
  }
  modelJson: string
  modelTransform: {
    scale: number
    offsetX: number
    offsetY: number
  }
  transformDefaults: {
    scale: number
    offsetX: number
    offsetY: number
  }
  expressions: AvatarExpression[]
  parameterControls: AvatarParameterControl[]
  motions: Record<string, MotionBinding>
  lipSync?: {
    parameterIds: string[]
  }
}

export interface AvatarPromptContext {
  modelId: string
  modelName: string
  expressions: AvatarExpression[]
  parameterControls: AvatarParameterControl[]
  prompt: string
}

export interface PetModelMotionOption {
  id: string
  group: string
  index: number
  label: string
}

export interface PetModelExpressionOption {
  name: string
  label: string
}

export interface PetExpressionMixItem {
  expression: string
  weight?: number
}

export interface PetExpressionMixPayload {
  expressions: PetExpressionMixItem[]
  intensity?: number
  durationMs?: number
  parameterOverrides?: PetParameterOverrideItem[]
  motion?: PetMotionTarget
}

export interface PetParameterOverrideItem {
  id: string
  value: number
  weight?: number
}

export interface PetMotionTarget {
  group: string
  index: number
}

export interface PetControlDirective {
  expressionMix: PetExpressionMixItem[]
  parameterOverrides: PetParameterOverrideItem[]
  motion?: PetMotionTarget
  intensity: number
  durationMs: number
}

export interface PetControlValidation {
  valid: boolean
  errors: string[]
  warnings: string[]
  fallbackExpression?: string
}

export interface PetControlValidationResult extends PetControlValidation {
  directive: PetControlDirective
}

export interface PetSentenceEmotionCue {
  sentenceIndex?: number
  text?: string
  offsetMs?: number
  emotionId?: string
  motionGroup?: string
  motionIndex?: number
  expressionName?: string
  expressionMix?: PetExpressionMixItem[]
  parameterOverrides?: PetParameterOverrideItem[]
  intensity?: number
  durationMs?: number
}

export type PetLipSyncLevelSource = 'realtime' | 'tts-pcm'
export const PET_LIP_SYNC_VISEMES = ['sil', 'aa', 'ih', 'ou', 'ee', 'oh'] as const
export type PetLipSyncViseme = typeof PET_LIP_SYNC_VISEMES[number]

export const isPetLipSyncViseme = (value: unknown): value is PetLipSyncViseme =>
  typeof value === 'string' && PET_LIP_SYNC_VISEMES.includes(value as PetLipSyncViseme)

export interface PetLipSyncLevelPayload {
  level: number
  active: boolean
  source: PetLipSyncLevelSource
}

export interface PetVisemeCue {
  viseme: PetLipSyncViseme
  offsetMs: number
  durationMs?: number
  weight?: number
}

export interface PetLipSyncVisemePayload {
  viseme: PetLipSyncViseme
  weight: number
  active: boolean
  source: 'tts-pcm'
}

export interface PetLipSyncProfile {
  gain: number
  noiseGate: number
  maxOpen: number
  attack: number
  release: number
}

export interface PetCompanionIdleProfile {
  supportStyle?: string | null
  mood?: string | null
  relationshipStage?: string | null
  relationshipTrend?: string | null
  energy?: number | null
  affinity?: number | null
  trust?: number | null
  intimacy?: number | null
  interruptibility?: number | null
  fatigue?: number | null
  recentTrustShiftCount?: number | null
  recentGratitudeCount?: number | null
}

export interface PetEmotionMotionTarget {
  group: string
  index: number
  label: string
}

export interface PetEmotionPreset {
  id: string
  label: string
  motions: PetEmotionMotionTarget[]
  expressions: string[]
}

export interface PetResolvedEmotionTrigger {
  id: string
  label: string
  motion?: PetEmotionMotionTarget
  expressionName?: string
}

export interface PetModelDefinition {
  id: string
  name: string
  type: PetModelType
  source?: PetModelSource
  assetPath: string
  motions: PetModelMotionOption[]
  expressions: PetModelExpressionOption[]
  emotions: PetEmotionPreset[]
  animationPaths?: string[]
  manifest?: AvatarManifest
  promptContext?: string
}

export interface PetModelCatalogPayload {
  activeModelId: string | null
  models: PetModelDefinition[]
}

export interface PetDisplayInfo {
  id: number
  label: string
  primary: boolean
  bounds: {
    x: number
    y: number
    width: number
    height: number
  }
  workArea: {
    x: number
    y: number
    width: number
    height: number
  }
}

export interface PetPlacementPreset {
  id: string
  name: string
  placement: Exclude<PetPlacement, 'free'>
}

export interface PetControlState {
  modelType: PetModelType
  modelId: string | null
  displayId: number | null
  scale: number
  positionX: number | null
  positionY: number | null
  placement: PetPlacement
  visible: boolean
  doNotDisturb: boolean
  interactMode: boolean
  clickThrough: boolean
  locked: boolean
  opacity: number
  lipSyncProfile: PetLipSyncProfile
  ready: boolean
}

export interface PetControlConfigPatch {
  modelType?: PetModelType
  modelId?: string | null
  modelPath?: string | undefined
  modelManifest?: AvatarManifest | null
  animationPaths?: string[]
  displayId?: number | null
  scale?: number
  positionX?: number | null
  positionY?: number | null
  placement?: PetPlacement
  visible?: boolean
  doNotDisturb?: boolean
  interactMode?: boolean
  clickThrough?: boolean
  locked?: boolean
  opacity?: number
  lipSyncProfile?: Partial<PetLipSyncProfile>
}

export interface PetRendererStatePayload {
  modelType: PetModelType
  modelId: string | null
  displayId?: number | null
  scale: number
  positionX: number | null
  positionY: number | null
  placement: PetPlacement
  clickThrough?: boolean
  locked?: boolean
  ready: boolean
}

export interface PetInteractionBoundsPayload {
  x: number
  y: number
  width: number
  height: number
}

export const DEFAULT_PET_CONTROL_STATE: PetControlState = {
  modelType: 'live2d',
  modelId: null,
  displayId: null,
  scale: 0.28,
  positionX: null,
  positionY: null,
  placement: 'bottom-right',
  visible: true,
  doNotDisturb: false,
  interactMode: false,
  clickThrough: true,
  locked: false,
  opacity: 1.0,
  lipSyncProfile: {
    gain: 4.2,
    noiseGate: 0.008,
    maxOpen: 1,
    attack: 0.42,
    release: 0.22,
  },
  ready: false,
}

const clampLipSyncValue = (value: unknown, fallback: number, min: number, max: number): number => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.max(min, Math.min(max, parsed)) : fallback
}

export const normalizePetLipSyncProfile = (
  value?: Partial<PetLipSyncProfile> | null,
  base: PetLipSyncProfile = DEFAULT_PET_CONTROL_STATE.lipSyncProfile,
): PetLipSyncProfile => ({
  gain: clampLipSyncValue(value?.gain, base.gain, 0.5, 12),
  noiseGate: clampLipSyncValue(value?.noiseGate, base.noiseGate, 0, 0.1),
  maxOpen: clampLipSyncValue(value?.maxOpen, base.maxOpen, 0.1, 1),
  attack: clampLipSyncValue(value?.attack, base.attack, 0.05, 1),
  release: clampLipSyncValue(value?.release, base.release, 0.05, 1),
})
