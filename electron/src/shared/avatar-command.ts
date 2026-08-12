import type { PetControlDirective, PetLipSyncViseme, PetModelType } from './pet-control'

export const AVATAR_COMMAND_VERSION = 1 as const
export const AVATAR_COMMAND_DELIVERY_TTL_MS = 1000

export type AvatarCommandInterruptPolicy = 'replace' | 'queue' | 'ignore'
export type AvatarCommandStatus =
  | 'accepted'
  | 'started'
  | 'completed'
  | 'interrupted'
  | 'degraded'
  | 'rejected'
  | 'dropped'
  | 'timeout'

export type AvatarBehavior = 'idle' | 'listen' | 'think' | 'speak' | 'backchannel' | 'react'
export type AvatarParameterPatchMode = 'set' | 'add' | 'multiply'
export type AvatarCurve = 'linear' | 'easeIn' | 'easeOut' | 'easeInOut'
export type AvatarActionType =
  | 'behavior'
  | 'affect'
  | 'gaze'
  | 'motion'
  | 'expression'
  | 'parameterPatch'
  | 'viseme'
  | 'cancel'

export interface AvatarBehaviorAction {
  type: 'behavior'
  behavior: AvatarBehavior
  durationMs?: number
}

export interface AvatarAffectAction {
  type: 'affect'
  emotion: string
  intensity?: number
  decayMs?: number
}

export interface AvatarGazeAction {
  type: 'gaze'
  target: { x: number; y: number; z?: number }
  strength?: number
  holdMs?: number
}

export interface AvatarMotionAction {
  type: 'motion'
  group?: string
  index?: number
  semantic?: string
  intensity?: number
}

export interface AvatarExpressionAction {
  type: 'expression'
  name: string
  weight?: number
  fadeInMs?: number
  fadeOutMs?: number
}

export interface AvatarParameterPatchItem {
  id: string
  value: number
  weight?: number
  mode?: AvatarParameterPatchMode
}

export interface AvatarParameterPatchAction {
  type: 'parameterPatch'
  patches: AvatarParameterPatchItem[]
  durationMs?: number
  curve?: AvatarCurve
}

export interface AvatarVisemeAction {
  type: 'viseme'
  viseme: PetLipSyncViseme
  weight?: number
  active?: boolean
}

export interface AvatarCancelAction {
  type: 'cancel'
  commandId?: string
  channel?: Exclude<AvatarActionType, 'cancel'>
}

export type AvatarAction =
  | AvatarBehaviorAction
  | AvatarAffectAction
  | AvatarGazeAction
  | AvatarMotionAction
  | AvatarExpressionAction
  | AvatarParameterPatchAction
  | AvatarVisemeAction
  | AvatarCancelAction

export interface AvatarCommand {
  version: typeof AVATAR_COMMAND_VERSION
  id: string
  streamId: string
  sequence: number
  capabilityRevision?: string
  issuedAt: number
  startAt?: number
  expiresAt?: number
  priority: number
  interrupt: AvatarCommandInterruptPolicy
  actions: AvatarAction[]
}

export interface AvatarActionCapabilities {
  behavior: boolean
  affect: boolean
  gaze: boolean
  motion: boolean
  expression: boolean
  parameterPatch: boolean
  viseme: boolean
  cancel: boolean
}

export interface AvatarCapabilityMotion {
  group: string
  index: number
  label?: string
}

export interface AvatarCapabilityParameter {
  id: string
  min: number
  max: number
  modes: AvatarParameterPatchMode[]
}

export interface AvatarCapabilitySnapshot {
  revision: string
  modelType: PetModelType
  modelId: string | null
  generatedAt: number
  actions: AvatarActionCapabilities
  expressions: string[]
  motions: AvatarCapabilityMotion[]
  parameters: AvatarCapabilityParameter[]
}

export interface AvatarCommandResult {
  commandId: string
  sequence: number
  status: AvatarCommandStatus
  modelType?: PetModelType
  capabilityRevision?: string
  unsupportedActionIndexes?: number[]
  message?: string
  at: number
}

export interface AvatarActionExecutionResult {
  status: 'completed' | 'degraded' | 'rejected'
  message?: string
}

export interface AvatarCommandNormalizationResult {
  ok: boolean
  status: 'accepted' | 'rejected' | 'dropped'
  command?: AvatarCommand
  errors: string[]
}

export interface AvatarCapabilityValidationResult {
  status: 'accepted' | 'degraded' | 'rejected'
  unsupportedActionIndexes: number[]
  message?: string
}

const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, Number.isFinite(value) ? value : min))

const clampDuration = (value: number): number => Math.round(clamp(value, 0, 10000))

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const isAvatarAction = (value: unknown): value is AvatarAction => {
  if (!isRecord(value) || typeof value['type'] !== 'string') return false
  switch (value['type']) {
    case 'behavior':
      return typeof value['behavior'] === 'string'
    case 'affect':
      return typeof value['emotion'] === 'string' && value['emotion'].length > 0
    case 'gaze':
      return isRecord(value['target'])
        && typeof value['target']['x'] === 'number'
        && typeof value['target']['y'] === 'number'
    case 'motion':
      return typeof value['group'] === 'string' || typeof value['semantic'] === 'string'
    case 'expression':
      return typeof value['name'] === 'string' && value['name'].length > 0
    case 'parameterPatch':
      return Array.isArray(value['patches'])
        && value['patches'].every((patch) => isRecord(patch) && typeof patch['id'] === 'string' && typeof patch['value'] === 'number')
    case 'viseme':
      return typeof value['viseme'] === 'string'
    case 'cancel':
      return true
    default:
      return false
  }
}

export const createAvatarCapabilityRevision = (
  modelType: PetModelType,
  modelId: string | null,
  tokens: string[],
): string => {
  const input = `${modelType}:${modelId ?? 'none'}:${tokens.join('|')}`
  let hash = 2166136261
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `${modelType}:${modelId ?? 'none'}:${(hash >>> 0).toString(36)}`
}

const normalizeAction = (action: AvatarAction): AvatarAction => {
  switch (action.type) {
    case 'behavior':
      return { ...action, ...(typeof action.durationMs === 'number' ? { durationMs: clampDuration(action.durationMs) } : {}) }
    case 'affect':
      return {
        ...action,
        ...(typeof action.intensity === 'number' ? { intensity: clamp(action.intensity, 0, 1) } : {}),
        ...(typeof action.decayMs === 'number' ? { decayMs: clampDuration(action.decayMs) } : {}),
      }
    case 'gaze':
      return {
        ...action,
        target: {
          x: clamp(action.target.x, -1, 1),
          y: clamp(action.target.y, -1, 1),
          ...(typeof action.target.z === 'number' ? { z: clamp(action.target.z, -1, 1) } : {}),
        },
        ...(typeof action.strength === 'number' ? { strength: clamp(action.strength, 0, 1) } : {}),
        ...(typeof action.holdMs === 'number' ? { holdMs: clampDuration(action.holdMs) } : {}),
      }
    case 'motion':
      return {
        ...action,
        ...(typeof action.index === 'number' ? { index: Math.max(0, Math.round(action.index)) } : {}),
        ...(typeof action.intensity === 'number' ? { intensity: clamp(action.intensity, 0, 1) } : {}),
      }
    case 'expression':
      return {
        ...action,
        ...(typeof action.weight === 'number' ? { weight: clamp(action.weight, 0, 1) } : {}),
        ...(typeof action.fadeInMs === 'number' ? { fadeInMs: clampDuration(action.fadeInMs) } : {}),
        ...(typeof action.fadeOutMs === 'number' ? { fadeOutMs: clampDuration(action.fadeOutMs) } : {}),
      }
    case 'parameterPatch':
      return {
        ...action,
        patches: action.patches.map((patch) => ({
          ...patch,
          ...(typeof patch.weight === 'number' ? { weight: clamp(patch.weight, 0, 1) } : {}),
          mode: patch.mode ?? 'set',
        })),
        ...(typeof action.durationMs === 'number' ? { durationMs: clampDuration(action.durationMs) } : {}),
      }
    case 'viseme':
      return { ...action, ...(typeof action.weight === 'number' ? { weight: clamp(action.weight, 0, 1) } : {}) }
    case 'cancel':
      return { ...action }
  }
}

export const normalizeAvatarCommand = (
  input: unknown,
  now = Date.now(),
): AvatarCommandNormalizationResult => {
  const candidate = (isRecord(input) ? input : {}) as Partial<AvatarCommand>
  const errors: string[] = []
  if (candidate.version !== AVATAR_COMMAND_VERSION) errors.push('Unsupported avatar command version')
  if (typeof candidate.id !== 'string' || !candidate.id.trim()) errors.push('Avatar command id is required')
  if (typeof candidate.streamId !== 'string' || !candidate.streamId.trim()) errors.push('Avatar command streamId is required')
  if (!Number.isInteger(candidate.sequence) || (candidate.sequence as number) < 0) errors.push('Sequence must be a non-negative integer')
  if (!Number.isFinite(candidate.issuedAt)) errors.push('issuedAt must be finite')
  if (!Array.isArray(candidate.actions) || candidate.actions.length === 0 || !candidate.actions.every(isAvatarAction)) {
    errors.push('At least one valid action is required')
  }

  if (errors.length > 0) return { ok: false, status: 'rejected', errors }
  const deliveryExpiresAt = typeof candidate.expiresAt === 'number'
    ? candidate.expiresAt
    : (candidate.issuedAt as number) + AVATAR_COMMAND_DELIVERY_TTL_MS
  if (deliveryExpiresAt <= now) {
    return { ok: false, status: 'dropped', errors: ['Avatar command expired'] }
  }

  return {
    ok: true,
    status: 'accepted',
    errors: [],
    command: {
      ...candidate,
      version: AVATAR_COMMAND_VERSION,
      id: candidate.id as string,
      streamId: candidate.streamId as string,
      sequence: candidate.sequence as number,
      issuedAt: candidate.issuedAt as number,
      expiresAt: deliveryExpiresAt,
      priority: Math.round(clamp(typeof candidate.priority === 'number' ? candidate.priority : 50, 0, 100)),
      interrupt: candidate.interrupt === 'queue' || candidate.interrupt === 'ignore' ? candidate.interrupt : 'replace',
      actions: (candidate.actions as AvatarAction[]).map(normalizeAction),
    },
  }
}

export const validateAvatarCommandAgainstCapabilities = (
  command: AvatarCommand,
  capabilities: AvatarCapabilitySnapshot,
): AvatarCapabilityValidationResult => {
  if (command.capabilityRevision && command.capabilityRevision !== capabilities.revision) {
    return {
      status: 'rejected',
      unsupportedActionIndexes: [],
      message: 'Avatar capabilities changed; refresh before retrying',
    }
  }

  const unsupportedActionIndexes = command.actions.flatMap((action, index) => {
    if (!capabilities.actions[action.type]) return [index]
    if (action.type === 'expression' && !capabilities.expressions.includes(action.name)) return [index]
    if (action.type === 'motion' && action.group) {
      const hasMatchingMotion = capabilities.motions.some((motion) => (
        motion.group === action.group
        && (action.index === undefined || motion.index === action.index)
      ))
      if (!hasMatchingMotion) return [index]
    }
    if (action.type === 'parameterPatch') {
      const supported = new Map(capabilities.parameters.map((parameter) => [parameter.id, parameter]))
      if (action.patches.some((patch) => {
        const parameter = supported.get(patch.id)
        return !parameter || !parameter.modes.includes(patch.mode ?? 'set')
      })) return [index]
    }
    return []
  })

  return {
    status: unsupportedActionIndexes.length > 0 ? 'degraded' : 'accepted',
    unsupportedActionIndexes,
    ...(unsupportedActionIndexes.length > 0
      ? { message: 'One or more avatar actions are unsupported by the active model' }
      : {}),
  }
}

export const legacyDirectiveToAvatarCommand = (
  directive: PetControlDirective,
  envelope: Pick<AvatarCommand, 'id' | 'streamId' | 'sequence' | 'issuedAt'> &
    Partial<Pick<AvatarCommand, 'capabilityRevision' | 'startAt' | 'expiresAt' | 'priority' | 'interrupt'>>,
): AvatarCommand => ({
  version: AVATAR_COMMAND_VERSION,
  id: envelope.id,
  streamId: envelope.streamId,
  sequence: envelope.sequence,
  issuedAt: envelope.issuedAt,
  ...(envelope.capabilityRevision ? { capabilityRevision: envelope.capabilityRevision } : {}),
  ...(typeof envelope.startAt === 'number' ? { startAt: envelope.startAt } : {}),
  ...(typeof envelope.expiresAt === 'number' ? { expiresAt: envelope.expiresAt } : {}),
  priority: envelope.priority ?? 50,
  interrupt: envelope.interrupt ?? 'replace',
  actions: [
    ...directive.expressionMix.map((expression) => ({
      type: 'expression' as const,
      name: expression.expression,
      weight: expression.weight ?? 1,
      fadeOutMs: directive.durationMs,
    })),
    ...(directive.parameterOverrides.length > 0
      ? [{
          type: 'parameterPatch' as const,
          patches: directive.parameterOverrides.map((parameter) => ({
            id: parameter.id,
            value: parameter.value,
            weight: parameter.weight ?? 1,
            mode: 'set' as const,
          })),
          durationMs: directive.durationMs,
        }]
      : []),
    ...(directive.motion
      ? [{
          type: 'motion' as const,
          group: directive.motion.group,
          index: directive.motion.index,
          intensity: directive.intensity,
        }]
      : []),
  ],
})
