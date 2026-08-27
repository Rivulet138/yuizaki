import { logger } from '@/logger'
import { watch, type WatchStopHandle } from 'vue'
import type { PetCompanionIdleProfile } from '@/../shared/pet-control'
import { legacyDirectiveToAvatarCommand } from '@/../shared/avatar-command'
import { resolveCompanionEmbodimentDelivery } from '@/../shared/companion-embodiment'
import { useChatStore } from '@/stores/chatStore'
import { useCompanionStore } from '@/stores/companionStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { petControlClient, settingsClient, systemClient } from '@/api/client'
import { workspaceClient } from '@/api/clients/workspace-client'
import { parseProactiveOpportunityIdentity } from '@/../shared/proactive'
import { currentLocale } from '@/i18n'
import { syncCompanionVoiceSettings } from './companion-voice-settings'
import { useProactiveControls } from './useProactiveControls'
import {
  createCompanionRuntimeController,
  installCompanionRuntimeController,
  type CompanionRuntimeSinkName,
  type CompanionRuntimeController,
  type ProactivePollResult,
} from '../runtime/companionRuntime'

let runtimeController: CompanionRuntimeController | null = null
let runtimeVisibilityHandler: (() => void) | null = null
let stopPetLinkWatcher: WatchStopHandle | null = null
let e2eClockOffsetMs = 0

export const advanceCompanionCooldownForE2E = (): number => {
  if (!window.petApi?.e2e) throw new Error('Companion E2E clock is unavailable')
  e2eClockOffsetMs += 16 * 60_000
  return e2eClockOffsetMs
}

export const reportCompanionRuntimeSinkError = (failure: { sink: CompanionRuntimeSinkName; message: string }) => {
  const payload = {
    event: 'companion_runtime.sink_failure',
    ...failure,
  }
  if (failure.message.includes('未授权')) {
    logger.warn('[CompanionRuntime] sink unavailable without control authorization', payload)
    return
  }
  logger.error('[CompanionRuntime] sink delivery failed', payload)
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
  const proactiveControls = useProactiveControls()
  let avatarCommandSequence = 0
  const avatarCommandStreamId = `companion:${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`
  const createAutomationAvatarCommand = (directive: Parameters<typeof legacyDirectiveToAvatarCommand>[0]) => {
    const sequence = avatarCommandSequence++
    return legacyDirectiveToAvatarCommand(directive, {
      id: `companion-avatar-${Date.now()}-${sequence}`,
      streamId: avatarCommandStreamId,
      sequence,
      issuedAt: Date.now(),
      priority: 40,
      interrupt: 'replace',
    })
  }
  const runtimeSinks = {
    embodiment: (intent: Parameters<typeof resolveCompanionEmbodiment>[0]) => {
      const resolved = resolveCompanionEmbodimentDelivery(intent)
      // Keep semantic waiting visible, but never forward an active animation
      // state when the platform/user requested reduced motion.
      const behavior = resolved.motionAllowed
        ? resolved.behavior
        : resolved.behavior === 'waiting' ? 'waiting' : 'idle'
      return petControlClient.setBehaviorState(
        behavior,
        resolved.durationMs,
        { source: 'automation' as const },
      )
    },
    behavior: (state: Parameters<typeof petControlClient.setBehaviorState>[0], durationMs?: number) =>
      petControlClient.setBehaviorState(state, durationMs, { source: 'automation' as const }),
    emotion: (emotionId: string, context: { signal: AbortSignal; eventVersion: string }) => {
      const command = createAutomationAvatarCommand({
        expressionMix: [],
        parameterOverrides: [],
        intensity: 1,
        durationMs: 1800,
      })
      command.actions.unshift({ type: 'affect', emotion: emotionId, intensity: 1, decayMs: 1800 })
      return petControlClient.triggerAvatarCommand(command, { source: 'automation' as const, ...context })
    },
    motion: (group: string, context: { signal: AbortSignal; eventVersion: string }) =>
      petControlClient.triggerAvatarCommand(createAutomationAvatarCommand({
        expressionMix: [],
        parameterOverrides: [],
        motion: { group, index: 0 },
        intensity: 1,
        durationMs: 1000,
      }), { source: 'automation' as const, ...context }),
    advice: (message: string) => chatStore.appendLocalAdvice(message, 'heartbeat'),
    notification: (message: string) => chatStore.addNotification(message),
  }

  if (!runtimeController) {
    runtimeController = createCompanionRuntimeController({
      pollSnapshot: () => systemClient.companionRuntime(8),
      isAvailable: () => true,
      readDoNotDisturb: async () => {
        try {
          const state = await petControlClient.getState()
          return state.doNotDisturb || proactiveControls.settings.value.dnd
        } catch {
          return true
        }
      },
      getWorkspaceId: () => workspaceStore.activeWorkspaceId,
      isPetLinkEnabled: () => chatStore.chatOptions.pet_link_enabled !== false,
      getLocale: () => currentLocale.value,
      authorizeOpportunity: async (candidate, snapshot) => {
        const identity = parseProactiveOpportunityIdentity(candidate)
        if (!identity || snapshot.active_workspace_id !== workspaceStore.activeWorkspaceId) return false
        if (!await proactiveControls.load()) return false
        if (!proactiveControls.allows(identity.sourceKind)) return false
        const frame = proactiveControls.visibleFrames.value.find((item) =>
          item.frameId === identity.frameId
          && item.workspaceId === workspaceStore.activeWorkspaceId,
        )
        if (!frame || frame.expiresAt * 1_000 <= Date.now()) return false
        controller?.configure({
          cooldownMs: proactiveControls.settings.value.cooldownSeconds * 1_000,
          frequencyBudget: proactiveControls.settings.value.dailyBudget,
          frequencyWindowMs: 24 * 60 * 60_000,
        })
        return true
      },
      sinks: runtimeSinks,
      onSinkError: reportCompanionRuntimeSinkError,
      onPollResult: reportCompanionRuntimePollResult,
      reportOpportunityOutcome: (jobId, requestId, outcome, reason) => systemClient.resolveCompanionOpportunity(jobId, {
        request_id: requestId,
        outcome,
        ...(reason ? { reason } : {}),
      }),
      ...(window.petApi?.e2e ? {
        now: () => Date.now() + e2eClockOffsetMs,
        pollIntervalMs: 250,
      } : {}),
    })
    installCompanionRuntimeController(runtimeController)
  }
  const controller = runtimeController
  controller.configure({
    sinks: runtimeSinks,
    isPetLinkEnabled: () => chatStore.chatOptions.pet_link_enabled !== false,
  })
  if (!stopPetLinkWatcher) {
    stopPetLinkWatcher = watch(
      () => chatStore.chatOptions.pet_link_enabled,
      () => { void controller.refreshPresentation() },
    )
  }

  const startCompanionRuntime = (isAvailable: () => boolean) => {
    controller.configure({ isAvailable })
    controller.start()
    if (runtimeVisibilityHandler === null) {
      runtimeVisibilityHandler = () => {
        const visible = document.visibilityState !== 'hidden'
        controller.setPollingEnabled(visible)
        if (visible && controller.isStarted()) void controller.pollOnce()
      }
      document.addEventListener('visibilitychange', runtimeVisibilityHandler)
    }
    runtimeVisibilityHandler()
  }

  const stopCompanionRuntime = () => {
    if (runtimeVisibilityHandler !== null) {
      document.removeEventListener('visibilitychange', runtimeVisibilityHandler)
      runtimeVisibilityHandler = null
    }
    controller.stop()
  }
  const pollCompanionOnce = () => controller.pollOnce()
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

    if (companion.model_id) {
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
  }
}
