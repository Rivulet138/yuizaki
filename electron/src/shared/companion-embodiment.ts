import type { CompanionEventSource } from './companion-event'

export const COMPANION_EMBODIMENT_INTENT_VERSION = 1 as const

export type CompanionEmbodimentState =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'executing'
  | 'speaking'
  | 'waiting-permission'
  | 'interrupted'
  | 'success'
  | 'error'
  | 'offline'

/** Operational presentation only. Persona text remains in the conversation layer. */
export interface CompanionEmbodimentIntent {
  version: typeof COMPANION_EMBODIMENT_INTENT_VERSION
  id: string
  kind: 'operational'
  state: CompanionEmbodimentState
  source: CompanionEventSource
  confidence: number
  issuedAt: number
  expiresAt: number | null
  reducedMotion: boolean
  petLinkEnabled: boolean
}

export type CompanionEmbodimentBehavior =
  | 'idle'
  | 'thinking'
  | 'speaking'
  | 'reacting'
  | 'sleepy'
  | 'waiting'
  | 'curious'
  | 'focused'
  | 'interrupted'

export interface ResolvedCompanionEmbodiment {
  behavior: CompanionEmbodimentBehavior
  durationMs?: number
  motionAllowed: boolean
  fallbackReason?: 'expired' | 'pet_link_disabled'
}

const behaviorByState: Record<CompanionEmbodimentState, CompanionEmbodimentBehavior> = {
  idle: 'idle',
  listening: 'waiting',
  thinking: 'thinking',
  executing: 'focused',
  speaking: 'speaking',
  'waiting-permission': 'waiting',
  interrupted: 'interrupted',
  success: 'curious',
  error: 'reacting',
  offline: 'sleepy',
}

export const resolveCompanionEmbodiment = (
  intent: CompanionEmbodimentIntent,
  now = Date.now(),
): ResolvedCompanionEmbodiment => {
  if (!intent.petLinkEnabled) {
    return { behavior: 'idle', motionAllowed: false, fallbackReason: 'pet_link_disabled' }
  }
  if (intent.expiresAt !== null && intent.expiresAt <= now) {
    return { behavior: 'idle', motionAllowed: false, fallbackReason: 'expired' }
  }

  const remainingMs = intent.expiresAt === null ? undefined : Math.max(0, intent.expiresAt - now)
  let behavior = behaviorByState[intent.state]
  if (intent.reducedMotion && (intent.state === 'success' || intent.state === 'error')) {
    behavior = intent.state === 'error' ? 'waiting' : 'idle'
  }
  return {
    behavior,
    ...(remainingMs === undefined ? {} : { durationMs: remainingMs }),
    motionAllowed: !intent.reducedMotion,
  }
}

/** Final renderer delivery guard. Semantic state is retained while active motion is suppressed. */
export const resolveCompanionEmbodimentDelivery = (
  intent: CompanionEmbodimentIntent,
  now = Date.now(),
): ResolvedCompanionEmbodiment => {
  const resolved = resolveCompanionEmbodiment(intent, now)
  if (resolved.motionAllowed || resolved.fallbackReason !== undefined) return resolved

  const waitingState = intent.state === 'listening'
    || intent.state === 'waiting-permission'
    || intent.state === 'interrupted'
    || intent.state === 'error'
  return {
    ...resolved,
    behavior: waitingState ? 'waiting' : 'idle',
    motionAllowed: false,
  }
}
