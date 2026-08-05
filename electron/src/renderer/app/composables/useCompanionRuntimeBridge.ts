import { ref } from 'vue'
import { logger } from '@/logger'
import type { PetCompanionIdleProfile } from '@/../shared/pet-control'
import { useChatStore } from '@/stores/chatStore'
import { useCompanionStore } from '@/stores/companionStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { petControlClient, settingsClient, systemClient } from '@/api/client'
import { workspaceClient } from '@/api/clients/workspace-client'
import { syncCompanionVoiceSettings } from './companion-voice-settings'
import {
  createCompanionRuntimeController,
  installCompanionRuntimeController,
  type CompanionRuntimeSinkName,
  type CompanionRuntimeController,
  type ProactivePollResult,
} from '../runtime/companionRuntime'

const LEGACY_DEFAULT_MODEL_ID = 'hiyori'
const PROACTIVITY_STORAGE_KEY = 'yuizaki.companion.proactivity-preset'
export type CompanionProactivityPreset = 'conservative' | 'standard'

const PROACTIVITY_PRESETS: Record<CompanionProactivityPreset, {
  cooldownMs: number
  frequencyBudget: number
  frequencyWindowMs: number
}> = {
  conservative: { cooldownMs: 15 * 60_000, frequencyBudget: 2, frequencyWindowMs: 60 * 60_000 },
  standard: { cooldownMs: 5 * 60_000, frequencyBudget: 3, frequencyWindowMs: 60 * 60_000 },
}

const isLegacyDefaultModelSelection = (modelId: string | null | undefined, modelType: string | undefined): boolean =>
  modelId === LEGACY_DEFAULT_MODEL_ID && (modelType === undefined || modelType === 'live2d')

const normalizeProactivityPreset = (value: unknown): CompanionProactivityPreset =>
  value === 'standard' ? 'standard' : 'conservative'

const readStoredProactivityPreset = (): CompanionProactivityPreset => {
  try {
    return normalizeProactivityPreset(window.localStorage.getItem(PROACTIVITY_STORAGE_KEY))
  } catch {
    return 'conservative'
  }
}

let runtimeController: CompanionRuntimeController | null = null
const activeProactivityPreset = ref<CompanionProactivityPreset>('conservative')
const activeDoNotDisturb = ref(false)
let e2eClockOffsetMs = 0

export const advanceCompanionCooldownForE2E = (): number => {
  if (!window.petApi?.e2e) throw new Error('Companion E2E clock is unavailable')
  e2eClockOffsetMs += 16 * 60_000
  return e2eClockOffsetMs
}

export const reportCompanionRuntimeSinkError = (failure: { sink: CompanionRuntimeSinkName; message: string }) => {
  logger.error('[CompanionRuntime] sink delivery failed', {
    event: 'companion_runtime.sink_failure',
    ...failure,
  })
}

export const reportCompanionRuntimePollResult = (result: ProactivePollResult) => {
  if (typeof result !== 'object' || result.status === 'delivered') return
  const payload = { event: 'companion_runtime.poll_delivery', ...result }
  if (result.status === 'failed') logger.error('[CompanionRuntime] proactive delivery failed', payload)
  else logger.warn('[CompanionRuntime] proactive delivery partial', payload)
}

export function useCompanionRuntimeBridge() {
  const companionStore = useCompanionStore()
  const chatStore = useChatStore()
  const workspaceStore = useWorkspaceStore()
  const runtimeSinks = {
    behavior: (state: Parameters<typeof petControlClient.setBehaviorState>[0], durationMs?: number) =>
      petControlClient.setBehaviorState(state, durationMs),
    emotion: (emotionId: string, context: { signal: AbortSignal; eventVersion: string }) =>
      petControlClient.triggerEmotion(emotionId, { source: 'automation' as const, ...context }),
    motion: (group: string, context: { signal: AbortSignal; eventVersion: string }) =>
      petControlClient.triggerMotion(group, 0, { source: 'automation' as const, ...context }),
    advice: (message: string) => chatStore.appendLocalAdvice(message, 'heartbeat'),
    notification: (message: string) => chatStore.addNotification(message),
  }

  if (!runtimeController) {
    activeProactivityPreset.value = readStoredProactivityPreset()
    runtimeController = createCompanionRuntimeController({
      pollSnapshot: () => systemClient.companionRuntime(8),
      isAvailable: () => true,
      readDoNotDisturb: async () => {
        const state = await petControlClient.getState()
        activeDoNotDisturb.value = state.doNotDisturb
        return state.doNotDisturb
      },
      sinks: runtimeSinks,
      onSinkError: reportCompanionRuntimeSinkError,
      onPollResult: reportCompanionRuntimePollResult,
      ...(window.petApi?.e2e ? {
        now: () => Date.now() + e2eClockOffsetMs,
        pollIntervalMs: 250,
      } : {}),
      ...PROACTIVITY_PRESETS[activeProactivityPreset.value],
    })
    installCompanionRuntimeController(runtimeController)
  }
  const controller = runtimeController
  controller.configure({ sinks: runtimeSinks })

  const startCompanionRuntime = (isAvailable: () => boolean) => {
    controller.configure({ isAvailable })
    controller.start()
  }

  const stopCompanionRuntime = () => controller.stop()
  const pollCompanionOnce = () => controller.pollOnce()
  const setProactivityPreset = (value: CompanionProactivityPreset): boolean => {
    const preset = normalizeProactivityPreset(value)
    const previous = activeProactivityPreset.value
    try {
      controller.configure(PROACTIVITY_PRESETS[preset])
      window.localStorage.setItem(PROACTIVITY_STORAGE_KEY, preset)
      activeProactivityPreset.value = preset
      return true
    } catch {
      controller.configure(PROACTIVITY_PRESETS[previous])
      return false
    }
  }

  const setDoNotDisturb = async (enabled: boolean): Promise<void> => {
    const state = await petControlClient.setDoNotDisturb(enabled)
    activeDoNotDisturb.value = state.doNotDisturb
  }

  const buildIdleProfileFromCompanion = (): PetCompanionIdleProfile | null => {
    const companion = companionStore.activeCompanion
    if (!companion) {
      return null
    }

    return {
      supportStyle: companion.support_style ?? null,
      mood: companion.emotion_state ?? null,
      energy: companion.energy_state ?? null,
      affinity: companion.affinity_state ?? null,
      trust: companion.trust_state ?? null,
      intimacy: companion.intimacy_state ?? null,
      interruptibility: companion.interruptibility_state ?? null,
      fatigue: companion.fatigue_state ?? null,
    }
  }

  const syncCompanionIdleProfile = async () => {
    const baseProfile = buildIdleProfileFromCompanion()
    if (!baseProfile) {
      return
    }

    try {
      const runtime = await systemClient.companionRuntime(4)
      const summary = runtime.relationship?.summary
      await petControlClient.updateCompanionIdleProfile({
        ...baseProfile,
        mood: runtime.companion_state?.mood ?? baseProfile.mood,
        energy: runtime.companion_state?.energy ?? baseProfile.energy,
        trust: runtime.companion_state?.trust ?? baseProfile.trust,
        intimacy: runtime.companion_state?.intimacy ?? baseProfile.intimacy,
        interruptibility: runtime.companion_state?.interruptibility ?? baseProfile.interruptibility,
        fatigue: runtime.companion_state?.fatigue ?? baseProfile.fatigue,
        relationshipStage: summary?.relationship_stage,
        relationshipTrend: summary?.relationship_trend,
        recentTrustShiftCount: summary?.recent_trust_shift_count,
        recentGratitudeCount: summary?.recent_gratitude_count,
      })
    } catch (error) {
      logger.warn('Failed to sync relationship runtime idle profile, using companion fallback:', error)
      try {
        await petControlClient.updateCompanionIdleProfile(baseProfile)
      } catch (fallbackError) {
        logger.warn('Failed to sync companion idle profile:', fallbackError)
      }
    }
  }

  const applyActiveCompanionRuntime = async () => {
    const companion = companionStore.activeCompanion
    if (!companion) {
      chatStore.setCompanionPersonaPrompt(null)
      return
    }

    chatStore.setCompanionPersonaPrompt(companion.persona_prompt || null)

    if (companion.model_id && !isLegacyDefaultModelSelection(companion.model_id, companion.model_type)) {
      const modelType = typeof companion.model_type === 'string' ? companion.model_type : undefined
      try {
        await petControlClient.setModelSelection(companion.model_id, modelType)
      } catch (error) {
        logger.warn('Failed to sync companion model selection:', error)
      }
    }

    await syncCompanionIdleProfile()

    if (companion.voice_profile && typeof companion.voice_profile === 'object') {
      await syncCompanionVoiceSettings(settingsClient, companion.voice_profile)
    }
  }

  const handleCompanionChange = async (companionId: string) => {
    try {
      await workspaceClient.update(workspaceStore.activeWorkspaceId, { companion_profile_id: companionId })
      await workspaceStore.syncFromBackend()
    } catch (error) {
      logger.error('Failed to update workspace companion binding', error)
    }
    companionStore.setActiveCompanion(companionId)
    await applyActiveCompanionRuntime()
  }

  return {
    applyActiveCompanionRuntime,
    buildIdleProfileFromCompanion,
    handleCompanionChange,
    syncCompanionIdleProfile,
    runtimeState: controller.state,
    runtimeSnapshot: controller.lastSnapshot,
    presentationState: controller.presentationState,
    startCompanionRuntime,
    stopCompanionRuntime,
    pollCompanionOnce,
    proactivityPreset: activeProactivityPreset,
    setProactivityPreset,
    doNotDisturb: activeDoNotDisturb,
    setDoNotDisturb,
  }
}
