import { logger } from '@/logger'
import type { PetCompanionIdleProfile } from '@/../shared/pet-control'
import { useChatStore } from '@/stores/chatStore'
import { useCompanionStore } from '@/stores/companionStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { petControlClient, settingsClient, systemClient } from '@/api/client'
import { workspaceClient } from '@/api/clients/workspace-client'
import { syncCompanionVoiceSettings } from './companion-voice-settings'

const LEGACY_DEFAULT_MODEL_ID = 'hiyori'

const isLegacyDefaultModelSelection = (modelId: string | null | undefined, modelType: string | undefined): boolean =>
  modelId === LEGACY_DEFAULT_MODEL_ID && (modelType === undefined || modelType === 'live2d')

export function useCompanionRuntimeBridge() {
  const companionStore = useCompanionStore()
  const chatStore = useChatStore()
  const workspaceStore = useWorkspaceStore()

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
  }
}
