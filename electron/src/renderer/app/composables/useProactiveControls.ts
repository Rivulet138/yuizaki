import { computed, ref } from 'vue'
import { proactiveClient } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspaceStore'
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

export const createProactiveControls = (
  api: ProactiveApi = proactiveClient,
  getWorkspaceId: () => string = () => 'default',
) => {
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
  let contextGeneration = 0
  let workspaceId = getWorkspaceId()
  let loadSequence = 0
  let summarySequence = 0
  const pendingSettingsWrites = new Set<string>()

  const visibleFrames = computed(() => frames.value.filter((frame) =>
    !hiddenFrameIds.value.has(frame.frameId),
  ))

  const invalidate = () => {
    contextGeneration += 1
    loadSequence += 1
    summarySequence += 1
    workspaceId = getWorkspaceId()
    loading.value = false
    saving.value = pendingSettingsWrites.has(workspaceId)
    rebuilding.value = false
    policyClosed.value = true
    loaded.value = false
    settings.value = createFailClosedProactiveSettings()
    frames.value = []
    feedbackSummary.value = null
    error.value = null
    hiddenFrameIds.value = new Set()
    pendingFeedback.value = new Set()
    acknowledgedFeedback.value = new Map()
    feedbackIds.clear()
  }

  const context = () => {
    if (workspaceId !== getWorkspaceId()) invalidate()
    return { workspaceId, generation: contextGeneration }
  }
  type RequestContext = ReturnType<typeof context>
  const isCurrent = (target: RequestContext): boolean =>
    target.generation === contextGeneration && target.workspaceId === getWorkspaceId()

  const refreshSummary = async (target: RequestContext) => {
    if (!api.feedbackSummary) return
    const sequence = ++summarySequence
    try {
      const candidate = await api.feedbackSummary(target.workspaceId)
      if (isCurrent(target) && sequence === summarySequence && candidate.workspaceId === target.workspaceId) {
        feedbackSummary.value = candidate
      }
    } catch {
      // Optional telemetry cannot close policy or delay the main operation.
    }
  }

  const load = async (): Promise<boolean> => {
    const target = context()
    // Authorization stays closed during a write; background reads must not
    // replace its restrictive local policy or discard its confirmation.
    if (pendingSettingsWrites.has(target.workspaceId)) {
      saving.value = true
      return false
    }
    const sequence = ++loadSequence
    const current = () => isCurrent(target) && sequence === loadSequence
    loading.value = true
    policyClosed.value = true
    error.value = null
    try {
      const [nextSettings, nextFrames] = await Promise.all([
        api.settings(target.workspaceId), api.frames(target.workspaceId),
      ])
      if (!current()) return false
      if (nextSettings.workspaceId !== target.workspaceId || nextFrames.some(frame => frame.workspaceId !== target.workspaceId)) {
        throw new Error('proactive_workspace_mismatch')
      }
      settings.value = nextSettings
      frames.value = nextFrames
      loaded.value = true
      policyClosed.value = false
      migrateLegacyPreset()
      void refreshSummary(target)
      return true
    } catch (loadError) {
      if (!current()) return false
      settings.value = createFailClosedProactiveSettings()
      frames.value = []
      feedbackSummary.value = null
      loaded.value = false
      policyClosed.value = true
      error.value = loadError instanceof Error ? loadError.message : 'proactive_load_failed'
      return false
    } finally {
      if (current()) loading.value = false
    }
  }

  const finishSettingsWrite = (target: RequestContext, readback = false) => {
    pendingSettingsWrites.delete(target.workspaceId)
    if (target.workspaceId !== getWorkspaceId()) return
    const returnedToWorkspace = !isCurrent(target)
    context()
    saving.value = false
    // Returning to a workspace must reconcile a write whose old view was
    // invalidated, including requests that timed out after the server committed.
    if (readback || returnedToWorkspace) void load()
  }

  const updateSettings = async (patch: ProactiveSettingsPatch): Promise<boolean> => {
    const target = context()
    if (pendingSettingsWrites.has(target.workspaceId) || rebuilding.value || !loaded.value || settings.value.workspaceId !== target.workspaceId) return false
    loadSequence += 1
    loading.value = false
    pendingSettingsWrites.add(target.workspaceId)
    saving.value = true
    policyClosed.value = true
    const revision = settings.value.revision
    settings.value = applyRestrictivePatch(settings.value, patch)
    error.value = null
    try {
      const next = await api.updateSettings(patch, revision, target.workspaceId)
      if (!isCurrent(target)) return false
      if (next.workspaceId !== target.workspaceId) throw new Error('proactive_workspace_mismatch')
      settings.value = next
      loaded.value = true
      policyClosed.value = false
      return true
    } catch (updateError) {
      if (!isCurrent(target)) return false
      loaded.value = false
      policyClosed.value = true
      error.value = updateError instanceof Error ? updateError.message : 'proactive_update_failed'
      return false
    } finally {
      finishSettingsWrite(target)
    }
  }

  const deleteFrame = async (frameId: string): Promise<boolean> => {
    const target = context()
    if (hiddenFrameIds.value.has(frameId)) return false
    hiddenFrameIds.value = new Set(hiddenFrameIds.value).add(frameId)
    try {
      const result = await api.deleteFrame(frameId, target.workspaceId)
      if (!isCurrent(target)) return false
      if (!result.ok) throw new Error('activity_frame_delete_rejected')
      frames.value = frames.value.filter((frame) => frame.frameId !== frameId)
      return true
    } catch (deleteError) {
      if (!isCurrent(target)) return false
      const next = new Set(hiddenFrameIds.value)
      next.delete(frameId)
      hiddenFrameIds.value = next
      policyClosed.value = true
      loaded.value = false
      error.value = deleteError instanceof Error ? deleteError.message : 'activity_frame_delete_failed'
      return false
    }
  }

  const rebuildFrames = async (limit = 1000): Promise<boolean> => {
    const target = context()
    if (rebuilding.value || saving.value) return false
    rebuilding.value = true
    error.value = null
    try {
      const result = await api.rebuildFrames(limit, target.workspaceId)
      if (!isCurrent(target)) return false
      if (result.workspaceId !== target.workspaceId) throw new Error('proactive_workspace_mismatch')
      hiddenFrameIds.value = new Set()
      return await load()
    } catch (rebuildError) {
      if (!isCurrent(target)) return false
      error.value = rebuildError instanceof Error ? rebuildError.message : 'activity_frame_rebuild_failed'
      return false
    } finally {
      if (isCurrent(target)) rebuilding.value = false
    }
  }

  const submitFeedback = async (
    opportunity: ProactiveOpportunityIdentity,
    feedback: ProactiveFeedbackKind,
  ): Promise<boolean> => {
    const target = context()
    const identity = feedbackIdentity(opportunity, feedback)
    const changesSettings = feedback === 'never_source'
    if (pendingFeedback.value.has(identity) || (changesSettings && pendingSettingsWrites.has(target.workspaceId))) return false
    let readbackSettings = false
    if (changesSettings) {
      loadSequence += 1
      loading.value = false
      pendingSettingsWrites.add(target.workspaceId)
      saving.value = true
      policyClosed.value = true
    }
    const feedbackId = feedbackIds.get(identity) ?? createFeedbackId()
    feedbackIds.set(identity, feedbackId)
    pendingFeedback.value = new Set(pendingFeedback.value).add(identity)
    error.value = null
    try {
      const result = await api.feedback({ ...opportunity, feedback, feedbackId }, target.workspaceId)
      if (!isCurrent(target)) return false
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
        // This feedback also changes the server settings revision. Read it back
        // before permitting another edit against the old revision.
        loaded.value = false
        policyClosed.value = true
        readbackSettings = true
      } else {
        void refreshSummary(target)
      }
      feedbackIds.delete(identity)
      return true
    } catch (feedbackError) {
      if (!isCurrent(target)) return false
      if (changesSettings) {
        loaded.value = false
        policyClosed.value = true
      }
      error.value = feedbackError instanceof Error ? feedbackError.message : 'proactive_feedback_failed'
      return false
    } finally {
      if (changesSettings) finishSettingsWrite(target, readbackSettings)
      if (isCurrent(target)) {
        const next = new Set(pendingFeedback.value)
        next.delete(identity)
        pendingFeedback.value = next
      }
    }
  }

  const isFeedbackPending = (opportunity: ProactiveOpportunityIdentity): boolean => {
    const prefix = feedbackIdentityPrefix(opportunity)
    return [...pendingFeedback.value].some((identity) => identity.startsWith(prefix))
  }

  const allows = (source: ProactiveSource, epochMillis: number = Date.now()): boolean =>
    settings.value.workspaceId === getWorkspaceId()
    && loaded.value
    && !policyClosed.value
    && !pendingSettingsWrites.has(getWorkspaceId())
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
  if (!proactiveControls) {
    const workspaceStore = useWorkspaceStore()
    proactiveControls = createProactiveControls(proactiveClient, () => workspaceStore.activeWorkspaceId)
  }
  return proactiveControls
}
