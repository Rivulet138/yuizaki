import { computed, ref } from 'vue'
import { proactiveClient } from '@/api/client'
import {
  createFailClosedProactiveSettings,
  isProactiveQuietHoursClear,
  type ActivityFrameSummary,
  type ProactiveFeedbackKind,
  type ProactiveFeedbackSummary,
  type ProactiveOpportunityIdentity,
  type ProactiveSettings,
  type ProactiveSettingsPatch,
  type ProactiveSource,
} from '@/../shared/proactive'

const LEGACY_PRESET_KEY = 'yuizaki.companion.proactivity-preset'

interface ProactiveApi {
  settings: typeof proactiveClient.settings
  updateSettings: typeof proactiveClient.updateSettings
  frames: typeof proactiveClient.frames
  rebuildFrames: typeof proactiveClient.rebuildFrames
  deleteFrame: typeof proactiveClient.deleteFrame
  feedback: typeof proactiveClient.feedback
  feedbackSummary?: typeof proactiveClient.feedbackSummary
}

const feedbackIdentityPrefix = (opportunity: ProactiveOpportunityIdentity): string =>
  `${opportunity.jobId}:${opportunity.requestId}:${opportunity.frameId}:${opportunity.sourceKind}:`

const feedbackIdentity = (opportunity: ProactiveOpportunityIdentity, feedback: ProactiveFeedbackKind): string =>
  `${feedbackIdentityPrefix(opportunity)}${feedback}`

const createFeedbackId = (): string => {
  const uuid = globalThis.crypto?.randomUUID?.()
  return uuid ? `feedback_${uuid}` : `feedback_${Date.now()}_${Math.random().toString(36).slice(2, 12)}`
}

const applyRestrictivePatch = (settings: ProactiveSettings, patch: ProactiveSettingsPatch): ProactiveSettings => ({
  ...settings,
  enabled: patch.enabled === false ? false : settings.enabled,
  dnd: patch.dnd === true ? true : settings.dnd,
  sourceEnabled: {
    completed_turn_followup: patch.sourceEnabled?.completed_turn_followup === false
      ? false
      : settings.sourceEnabled.completed_turn_followup,
  },
})

const migrateLegacyPreset = () => {
  try {
    window.localStorage.removeItem(LEGACY_PRESET_KEY)
  } catch {
    // Backend settings still remain authoritative when local storage is unavailable.
  }
}

export const createProactiveControls = (api: ProactiveApi = proactiveClient) => {
  const settings = ref<ProactiveSettings>(createFailClosedProactiveSettings())
  const frames = ref<ActivityFrameSummary[]>([])
  const loaded = ref(false)
  const policyClosed = ref(true)
  const loading = ref(false)
  const saving = ref(false)
  const rebuilding = ref(false)
  const error = ref<string | null>(null)
  const pendingFeedback = ref(new Set<string>())
  const acknowledgedFeedback = ref(new Map<string, ProactiveFeedbackKind>())
  const feedbackSummary = ref<ProactiveFeedbackSummary | null>(null)
  const hiddenFrameIds = ref(new Set<string>())
  const feedbackIds = new Map<string, string>()
  let requestGeneration = 0

  const visibleFrames = computed(() => frames.value.filter((frame) =>
    !hiddenFrameIds.value.has(frame.frameId),
  ))

  const beginRequest = (): number => {
    requestGeneration += 1
    return requestGeneration
  }

  const isCurrent = (generation: number): boolean => generation === requestGeneration

  const invalidate = () => {
    requestGeneration += 1
    policyClosed.value = true
    loaded.value = false
  }

  const load = async (): Promise<boolean> => {
    const generation = beginRequest()
    loading.value = true
    policyClosed.value = true
    error.value = null
    try {
      const [nextSettings, nextFrames] = await Promise.all([api.settings(), api.frames()])
      if (!isCurrent(generation)) return false
      let nextFeedbackSummary: ProactiveFeedbackSummary | null = null
      if (api.feedbackSummary) {
        try {
          const candidate = await api.feedbackSummary()
          if (candidate.workspaceId === nextSettings.workspaceId) nextFeedbackSummary = candidate
        } catch {
          // A telemetry summary is advisory; policy and activity frames remain usable.
        }
      }
      if (!isCurrent(generation)) return false
      settings.value = nextSettings
      frames.value = nextFrames
      feedbackSummary.value = nextFeedbackSummary
      loaded.value = true
      policyClosed.value = false
      migrateLegacyPreset()
      return true
    } catch (loadError) {
      if (!isCurrent(generation)) return false
      settings.value = createFailClosedProactiveSettings()
      frames.value = []
      feedbackSummary.value = null
      loaded.value = false
      policyClosed.value = true
      error.value = loadError instanceof Error ? loadError.message : 'proactive_load_failed'
      return false
    } finally {
      if (isCurrent(generation)) loading.value = false
    }
  }

  const updateSettings = async (patch: ProactiveSettingsPatch): Promise<boolean> => {
    const generation = beginRequest()
    saving.value = true
    policyClosed.value = true
    settings.value = applyRestrictivePatch(settings.value, patch)
    error.value = null
    try {
      const next = await api.updateSettings(patch, settings.value.revision)
      if (!isCurrent(generation)) return false
      settings.value = next
      loaded.value = true
      policyClosed.value = false
      return true
    } catch (updateError) {
      if (!isCurrent(generation)) return false
      loaded.value = false
      policyClosed.value = true
      error.value = updateError instanceof Error ? updateError.message : 'proactive_update_failed'
      return false
    } finally {
      if (isCurrent(generation)) saving.value = false
    }
  }

  const deleteFrame = async (frameId: string): Promise<boolean> => {
    hiddenFrameIds.value = new Set(hiddenFrameIds.value).add(frameId)
    try {
      const result = await api.deleteFrame(frameId)
      if (!result.ok) throw new Error('activity_frame_delete_rejected')
      frames.value = frames.value.filter((frame) => frame.frameId !== frameId)
      return true
    } catch (deleteError) {
      policyClosed.value = true
      loaded.value = false
      error.value = deleteError instanceof Error ? deleteError.message : 'activity_frame_delete_failed'
      return false
    }
  }

  const rebuildFrames = async (limit = 1000): Promise<boolean> => {
    if (rebuilding.value) return false
    rebuilding.value = true
    error.value = null
    try {
      await api.rebuildFrames(limit)
      hiddenFrameIds.value = new Set()
      return await load()
    } catch (rebuildError) {
      error.value = rebuildError instanceof Error ? rebuildError.message : 'activity_frame_rebuild_failed'
      return false
    } finally {
      rebuilding.value = false
    }
  }

  const submitFeedback = async (
    opportunity: ProactiveOpportunityIdentity,
    feedback: ProactiveFeedbackKind,
  ): Promise<boolean> => {
    const identity = feedbackIdentity(opportunity, feedback)
    if (pendingFeedback.value.has(identity)) return false
    const feedbackId = feedbackIds.get(identity) ?? createFeedbackId()
    feedbackIds.set(identity, feedbackId)
    pendingFeedback.value = new Set(pendingFeedback.value).add(identity)
    error.value = null
    try {
      const result = await api.feedback({ ...opportunity, feedback, feedbackId })
      if (!result.ok) throw new Error('proactive_feedback_rejected')
      acknowledgedFeedback.value = new Map(acknowledgedFeedback.value).set(
        `${opportunity.jobId}:${opportunity.requestId}`,
        feedback,
      )
      if (feedback === 'never_source') {
        settings.value = {
          ...settings.value,
          sourceEnabled: { ...settings.value.sourceEnabled, [opportunity.sourceKind]: false },
        }
      }
      if (api.feedbackSummary) {
        try {
          const candidate = await api.feedbackSummary()
          if (candidate.workspaceId === settings.value.workspaceId) feedbackSummary.value = candidate
        } catch {
          // Keep the last known summary when the optional refresh is unavailable.
        }
      }
      feedbackIds.delete(identity)
      return true
    } catch (feedbackError) {
      error.value = feedbackError instanceof Error ? feedbackError.message : 'proactive_feedback_failed'
      return false
    } finally {
      const next = new Set(pendingFeedback.value)
      next.delete(identity)
      pendingFeedback.value = next
    }
  }

  const isFeedbackPending = (opportunity: ProactiveOpportunityIdentity): boolean => {
    const prefix = feedbackIdentityPrefix(opportunity)
    return [...pendingFeedback.value].some((identity) => identity.startsWith(prefix))
  }

  const allows = (source: ProactiveSource, epochMillis: number = Date.now()): boolean =>
    loaded.value
    && !policyClosed.value
    && settings.value.enabled
    && !settings.value.dnd
    && settings.value.sourceEnabled[source]
    && isProactiveQuietHoursClear(settings.value.quietHours, epochMillis)

  return {
    settings,
    frames,
    visibleFrames,
    loaded,
    policyClosed,
    loading,
    saving,
    rebuilding,
    error,
    acknowledgedFeedback,
    feedbackSummary,
    load,
    updateSettings,
    deleteFrame,
    rebuildFrames,
    submitFeedback,
    isFeedbackPending,
    allows,
    invalidate,
  }
}

let proactiveControls: ReturnType<typeof createProactiveControls> | null = null

export const useProactiveControls = () => {
  proactiveControls ??= createProactiveControls()
  return proactiveControls
}
