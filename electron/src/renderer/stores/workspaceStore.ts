import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import type {
  WorkspaceContext,
  WorkspaceMemoryPolicy,
  WorkspacePromptEngineering,
  WorkspaceRecord,
  WorkspaceRoleCard,
  WorkspaceStatePayload,
  WorkspaceVisionSettings,
  WorkspaceWorldBook,
  WorkspaceWorldBookEntry,
} from '../../shared/workspace'
import { workspaceClient, type WorkspacePatchPayload } from '@/api/clients/workspace-client'
import { currentLocale, localeTables, t } from '@/i18n'
import { useCompanionStore } from './companionStore'

const STORAGE_KEY = 'deskpet-workspaces'
const ACTIVE_KEY = 'deskpet-active-workspace'
export const DEFAULT_PROMPT_VERSION = 2

/**
 * Built-in prompt for the active UI locale.
 *
 * Prompts are model instructions, so they live in the message tables
 * (`promptDefaults.*`) instead of as literals here: switching the interface
 * language switches the built-in prompts with it.
 */
export const defaultWorkPrompt = (): string => t('promptDefaults.work')
export const defaultDailyPrompt = (): string => t('promptDefaults.daily')

const builtinPromptTextCache = new Map<string, Set<string>>()

/**
 * Every locale's built-in text for one prompt key.
 *
 * A workspace stores the prompt text it was last given, so "the user never
 * edited this" has to be recognised across languages — otherwise switching the
 * interface language would look like a customised prompt.
 */
const builtinPromptTexts = (key: 'promptDefaults.work' | 'promptDefaults.daily'): Set<string> => {
  const cached = builtinPromptTextCache.get(key)
  if (cached) return cached
  const texts = new Set<string>()
  for (const table of Object.values(localeTables)) {
    const value = table[key]
    if (typeof value === 'string' && value.trim()) texts.add(value.trim())
  }
  builtinPromptTextCache.set(key, texts)
  return texts
}

export const isBuiltinWorkPrompt = (value?: string | null): boolean =>
  builtinPromptTexts('promptDefaults.work').has((value ?? '').trim())

export const isBuiltinDailyPrompt = (value?: string | null): boolean =>
  builtinPromptTexts('promptDefaults.daily').has((value ?? '').trim())

const createDefaultRoleCard = (): WorkspaceRoleCard => ({
  enabled: true,
  name: '',
  personality: '',
  scenario: '',
  instructions: '',
  firstMessage: '',
})

const createDefaultWorldBook = (): WorkspaceWorldBook => ({
  enabled: false,
  scanDepth: 8,
  maxEntries: 8,
  budgetTokens: 1200,
  entries: [],
})

const createDefaultPromptEngineering = (): WorkspacePromptEngineering => ({
  workPrompt: defaultWorkPrompt(),
  dailyPrompt: defaultDailyPrompt(),
})

const createDefaultVisionSettings = (): WorkspaceVisionSettings => ({
  enabled: false,
  displayIndex: 0,
  captureMode: 'display',
  region: { x: 0, y: 0, width: 1280, height: 720 },
  privacyMasks: [],
})

const createDefaultMemoryPolicy = (): WorkspaceMemoryPolicy => ({
  workingRetentionDays: 14,
  lowQualityThreshold: 0.55,
  includeStaleWorking: true,
  includeLowQuality: true,
  includeExactDuplicates: true,
})

const createDefaultWorkspaceContext = (): WorkspaceContext => ({
  activeTab: 'chat',
  modelType: 'live2d',
  modelId: null,
  wallpaperMode: true,
  heroHeight: 460,
  menuOrder: [],
  recentTabs: ['chat'],
  layoutPreset: 'balanced',
  promptVersion: DEFAULT_PROMPT_VERSION,
  promptMode: 'auto',
  promptEngineering: createDefaultPromptEngineering(),
  roleCard: createDefaultRoleCard(),
  worldBook: createDefaultWorldBook(),
  vision: createDefaultVisionSettings(),
  memoryPolicy: createDefaultMemoryPolicy(),
})

const normalizePromptEngineering = (value: Partial<WorkspacePromptEngineering> | undefined): WorkspacePromptEngineering => {
  const keepWork = typeof value?.workPrompt === 'string' && value.workPrompt.trim() && !isBuiltinWorkPrompt(value.workPrompt)
  const keepDaily = typeof value?.dailyPrompt === 'string' && value.dailyPrompt.trim() && !isBuiltinDailyPrompt(value.dailyPrompt)
  return {
    workPrompt: keepWork ? String(value?.workPrompt) : defaultWorkPrompt(),
    dailyPrompt: keepDaily ? String(value?.dailyPrompt) : defaultDailyPrompt(),
  }
}

const normalizeVisionSettings = (value: Partial<WorkspaceVisionSettings> | undefined): WorkspaceVisionSettings => {
  const region = value?.region
  const normalizeRegion = (item: Partial<WorkspaceVisionSettings['region']>): WorkspaceVisionSettings['region'] => ({
    x: Math.max(0, Math.min(100000, Math.round(Number(item.x) || 0))),
    y: Math.max(0, Math.min(100000, Math.round(Number(item.y) || 0))),
    width: Math.max(64, Math.min(100000, Math.round(Number(item.width) || 64))),
    height: Math.max(64, Math.min(100000, Math.round(Number(item.height) || 64))),
  })
  return {
    enabled: value?.enabled === true,
    displayIndex: Math.max(0, Math.min(15, Math.round(Number(value?.displayIndex) || 0))),
    captureMode: value?.captureMode === 'region' ? 'region' : 'display',
    region: {
      x: Math.max(0, Math.min(100000, Math.round(Number(region?.x) || 0))),
      y: Math.max(0, Math.min(100000, Math.round(Number(region?.y) || 0))),
      width: Math.max(64, Math.min(100000, Math.round(Number(region?.width) || 1280))),
      height: Math.max(64, Math.min(100000, Math.round(Number(region?.height) || 720))),
    },
    privacyMasks: Array.isArray(value?.privacyMasks)
      ? value.privacyMasks
          .filter((item): item is WorkspaceVisionSettings['region'] => Boolean(item && typeof item === 'object'))
          .slice(0, 8)
          .map(normalizeRegion)
      : [],
  }
}

const normalizeMemoryPolicy = (value: Partial<WorkspaceMemoryPolicy> | undefined): WorkspaceMemoryPolicy => ({
  workingRetentionDays: Math.max(1, Math.min(365, Math.round(Number(value?.workingRetentionDays) || 14))),
  lowQualityThreshold: Math.max(0, Math.min(1, Number.isFinite(Number(value?.lowQualityThreshold)) ? Number(value?.lowQualityThreshold) : 0.55)),
  includeStaleWorking: value?.includeStaleWorking !== false,
  includeLowQuality: value?.includeLowQuality !== false,
  includeExactDuplicates: value?.includeExactDuplicates !== false,
})

const normalizeRoleCard = (value: Partial<WorkspaceRoleCard> | undefined): WorkspaceRoleCard => ({
  ...createDefaultRoleCard(),
  ...(value ?? {}),
  enabled: value?.enabled !== false,
  name: typeof value?.name === 'string' ? value.name : '',
  personality: typeof value?.personality === 'string' ? value.personality : '',
  scenario: typeof value?.scenario === 'string' ? value.scenario : '',
  instructions: typeof value?.instructions === 'string' ? value.instructions : '',
  firstMessage: typeof value?.firstMessage === 'string' ? value.firstMessage : '',
})

const normalizeWorldBookEntry = (entry: Partial<WorkspaceWorldBookEntry>, index: number): WorkspaceWorldBookEntry => ({
  id: typeof entry.id === 'string' && entry.id.trim() ? entry.id : `world_${Date.now()}_${index}`,
  title: typeof entry.title === 'string' ? entry.title : '',
  keys: Array.isArray(entry.keys) ? entry.keys.map((key) => String(key).trim()).filter(Boolean).slice(0, 24) : [],
  secondaryKeys: Array.isArray(entry.secondaryKeys) ? entry.secondaryKeys.map((key) => String(key).trim()).filter(Boolean).slice(0, 24) : [],
  content: typeof entry.content === 'string' ? entry.content : '',
  enabled: entry.enabled !== false,
  priority: Number.isFinite(Number(entry.priority)) ? Number(entry.priority) : 0,
  insertionOrder: Number.isFinite(Number(entry.insertionOrder)) ? Number(entry.insertionOrder) : index,
  constant: entry.constant === true,
  selective: entry.selective === true,
  caseSensitive: entry.caseSensitive === true,
  matchWholeWords: entry.matchWholeWords === true,
  probability: Math.max(0, Math.min(100, Number.isFinite(Number(entry.probability)) ? Number(entry.probability) : 100)),
})

const normalizeWorldBook = (value: Partial<WorkspaceWorldBook> | undefined): WorkspaceWorldBook => ({
  enabled: value?.enabled === true,
  scanDepth: Math.max(1, Math.min(32, Math.round(Number(value?.scanDepth) || 8))),
  maxEntries: Math.max(1, Math.min(64, Math.round(Number(value?.maxEntries) || 8))),
  budgetTokens: Math.max(128, Math.min(32000, Math.round(Number(value?.budgetTokens) || 1200))),
  entries: Array.isArray(value?.entries)
    ? value.entries
        .filter((entry): entry is Partial<WorkspaceWorldBookEntry> => Boolean(entry && typeof entry === 'object'))
        .map(normalizeWorldBookEntry)
        .slice(0, 80)
    : [],
})

const asContextRecord = (value: unknown): Partial<WorkspaceContext> | undefined => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  return value as Partial<WorkspaceContext>
}

const normalizeWorkspaceContext = (context: Partial<WorkspaceContext> | undefined): WorkspaceContext => {
  const normalized: WorkspaceContext = {
    ...createDefaultWorkspaceContext(),
    ...(context ?? {}),
  }
  if (normalized.activeTab === 'companion') normalized.activeTab = 'chat'
  normalized.recentTabs = Array.isArray(normalized.recentTabs)
    ? normalized.recentTabs
        .map((tab) => tab === 'companion' ? 'chat' : tab)
        .filter((tab, index, tabs) => tabs.indexOf(tab) === index)
    : ['chat']
  if (!['auto', 'work', 'daily'].includes(normalized.promptMode)) {
    normalized.promptMode = 'auto'
  }
  normalized.promptEngineering = normalizePromptEngineering(context?.promptEngineering)
  normalized.promptVersion = DEFAULT_PROMPT_VERSION
  normalized.roleCard = normalizeRoleCard(context?.roleCard)
  normalized.worldBook = normalizeWorldBook(context?.worldBook)
  normalized.vision = normalizeVisionSettings(context?.vision)
  normalized.memoryPolicy = normalizeMemoryPolicy(context?.memoryPolicy)
  return normalized
}

const createDefaultWorkspace = (): WorkspaceRecord => {
  const now = new Date().toISOString()
  return {
    id: 'default',
    name: t('misc.defaultWorkspaceName'),
    createdAt: now,
    updatedAt: now,
    context: createDefaultWorkspaceContext(),
  }
}

const mergeWorkspaceContext = (
  base: WorkspaceContext,
  patch: Partial<WorkspaceContext>,
): WorkspaceContext => {
  const merge = (left: unknown, right: unknown): unknown => {
    if (!right || typeof right !== 'object' || Array.isArray(right)) return right
    if (!left || typeof left !== 'object' || Array.isArray(left)) return right
    const result: Record<string, unknown> = { ...(left as Record<string, unknown>) }
    for (const [key, value] of Object.entries(right as Record<string, unknown>)) {
      result[key] = merge(result[key], value)
    }
    return result
  }
  return merge(base, patch) as WorkspaceContext
}

const isDefaultWorkspaceContext = (context: WorkspaceContext): boolean => (
  JSON.stringify(context) === JSON.stringify(createDefaultWorkspaceContext())
)

interface StoredContextEntry {
  context: WorkspaceContext
  revision: number
}

const readStoredContexts = (): Map<string, StoredContextEntry> => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Map()
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return new Map()
    const entries = parsed
      .filter((item): item is { id: string; context: Partial<WorkspaceContext>; contextRevision?: unknown } => (
        Boolean(item)
        && typeof item === 'object'
        && typeof item.id === 'string'
        && Boolean(item.context)
        && typeof item.context === 'object'
        && !Array.isArray(item.context)
      ))
      .map((item): [string, StoredContextEntry] => [
        item.id,
        {
          context: normalizeWorkspaceContext(item.context),
          revision: typeof item.contextRevision === 'number' ? item.contextRevision : -1,
        },
      ])
    // Normalized defaults are not user-authored context; never let them
    // overwrite a server-side configuration after a rollback or fresh start.
    return new Map(entries.filter(([, entry]) => !isDefaultWorkspaceContext(entry.context)))
  } catch {
    return new Map()
  }
}

const readState = (): WorkspaceStatePayload => {
  const fallback = createDefaultWorkspace()
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    const active = window.localStorage.getItem(ACTIVE_KEY) || fallback.id
    if (!raw) {
      return { activeWorkspaceId: fallback.id, workspaces: [fallback], recentWorkspaceIds: [fallback.id] }
    }
    const parsed = JSON.parse(raw) as WorkspaceRecord[]
    if (!Array.isArray(parsed) || parsed.length === 0) {
      return { activeWorkspaceId: fallback.id, workspaces: [fallback], recentWorkspaceIds: [fallback.id] }
    }
    const normalizedWorkspaces = parsed.map((workspace) => ({
      ...workspace,
      context: normalizeWorkspaceContext(workspace.context),
    }))
    const activeWorkspaceId = normalizedWorkspaces.some((item) => item.id === active) ? active : (normalizedWorkspaces[0]?.id || fallback.id)
    return {
      activeWorkspaceId,
      workspaces: normalizedWorkspaces,
      recentWorkspaceIds: [activeWorkspaceId, ...normalizedWorkspaces.map((item) => item.id).filter((id) => id !== activeWorkspaceId)].slice(0, 8),
    }
  } catch {
    return { activeWorkspaceId: fallback.id, workspaces: [fallback], recentWorkspaceIds: [fallback.id] }
  }
}

export const useWorkspaceStore = defineStore('workspace', () => {
  const state = ref<WorkspaceStatePayload>(readState())
  const companionStore = useCompanionStore()

  const persist = () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state.value.workspaces))
    window.localStorage.setItem(ACTIVE_KEY, state.value.activeWorkspaceId)
  }

  const contextSaveTimers = new Map<string, number>()
  const queueContextSave = (
    workspaceId: string,
    patch?: Partial<WorkspaceContext>,
    retried = false,
  ) => {
    if (typeof window === 'undefined') return
    const pending = contextSaveTimers.get(workspaceId)
    if (pending !== undefined) window.clearTimeout(pending)
    const timer = window.setTimeout(() => {
      contextSaveTimers.delete(workspaceId)
      const workspace = state.value.workspaces.find((item) => item.id === workspaceId)
      if (!workspace) return
      void workspaceClient.update(workspaceId, {
        context: workspace.context as unknown as Record<string, unknown>,
        contextRevision: workspace.contextRevision ?? 0,
      }).then((updated) => {
        const current = state.value.workspaces.find((item) => item.id === workspaceId)
        if (!current || typeof updated.contextRevision !== 'number') return
        current.contextRevision = updated.contextRevision
        persist()
      }).catch((error: unknown) => {
        // A stale revision means another client wrote first. Rebase this edit
        // on the server value instead of discarding it, then retry once.
        const conflict = error as {
          status?: number
          payload?: { context?: unknown; contextRevision?: unknown }
        }
        if (conflict?.status === 409 && conflict.payload) {
          const current = state.value.workspaces.find((item) => item.id === workspaceId)
          const serverContext = asContextRecord(conflict.payload.context)
          if (current) {
            const base = serverContext
              ? normalizeWorkspaceContext(serverContext)
              : createDefaultWorkspaceContext()
            current.context = patch ? mergeWorkspaceContext(base, patch) : base
            if (typeof conflict.payload.contextRevision === 'number') {
              current.contextRevision = conflict.payload.contextRevision
            }
            persist()
            if (patch && !retried) {
              queueContextSave(workspaceId, patch, true)
              return
            }
          }
        }
        console.debug('[WorkspaceStore] failed to persist workspace context:', error)
      })
    }, 600)
    contextSaveTimers.set(workspaceId, timer)
  }

  const activeWorkspace = computed(() => {
    return state.value.workspaces.find((workspace) => workspace.id === state.value.activeWorkspaceId) ?? state.value.workspaces[0] ?? createDefaultWorkspace()
  })

  const activateWorkspaceLocally = (workspaceId: string) => {
    if (!state.value.workspaces.some((workspace) => workspace.id === workspaceId)) {
      return false
    }
    state.value.activeWorkspaceId = workspaceId
    state.value.recentWorkspaceIds = [workspaceId, ...state.value.recentWorkspaceIds.filter((id) => id !== workspaceId)].slice(0, 8)
    persist()
    return true
  }

  const syncActiveWorkspaceToBackend = async (workspaceId: string) => {
    await workspaceClient.setActive(workspaceId)
  }

  const syncActiveWorkspaceInBackground = (workspaceId: string) => {
    void syncActiveWorkspaceToBackend(workspaceId).catch((error) => {
      console.debug('[WorkspaceStore] failed to sync active workspace:', error)
    })
  }

  const setActiveWorkspace = (workspaceId: string) => {
    if (!activateWorkspaceLocally(workspaceId)) return
    syncActiveWorkspaceInBackground(workspaceId)
  }

  const setActiveWorkspaceSynced = async (workspaceId: string) => {
    if (!activateWorkspaceLocally(workspaceId)) {
      throw new Error(`Workspace not found: ${workspaceId}`)
    }
    await syncActiveWorkspaceToBackend(workspaceId)
  }

  const createWorkspace = (name?: string) => {
    const now = new Date().toISOString()
    const workspace: WorkspaceRecord = {
      id: `ws_${Date.now()}`,
      name: name?.trim() || t('misc.sceneFallbackName', { index: state.value.workspaces.length + 1 }),
      createdAt: now,
      updatedAt: now,
      context: { ...activeWorkspace.value.context },
    }
    state.value.workspaces.push(workspace)
    state.value.activeWorkspaceId = workspace.id
    state.value.recentWorkspaceIds = [workspace.id, ...state.value.recentWorkspaceIds.filter((id) => id !== workspace.id)].slice(0, 8)
    persist()
  }

  const syncFromBackend = async () => {
    try {
      const payload = await workspaceClient.list()
      const localContextMap = readStoredContexts()
      const contextsToBackfill: string[] = []
      const backendWorkspaces = payload.workspaces.map((workspace) => {
        const local = localContextMap.get(workspace.id)
        const serverContext = asContextRecord(workspace.context)
        const serverRevision = typeof workspace.contextRevision === 'number' ? workspace.contextRevision : 0
        // Never pair a stale local document with the server's newer revision:
        // that write would be accepted and silently overwrite the server.
        const localIsCurrent = Boolean(local) && local!.revision === serverRevision
        const localIsLegacy = Boolean(local) && local!.revision < 0
        const localIsNewer = Boolean(local) && local!.revision > serverRevision
        const useLocal = Boolean(local) && (
          localIsCurrent
          || (serverContext === undefined && (localIsNewer || localIsLegacy))
        )
        if (useLocal && serverContext === undefined) contextsToBackfill.push(workspace.id)
        return {
          id: workspace.id,
          name: workspace.name,
          description: workspace.description,
          icon: workspace.icon,
          color: workspace.color,
          companion_profile_id: workspace.companion_profile_id,
          default_model: workspace.default_model,
          system_prompt: workspace.system_prompt,
          tool_preset: workspace.tool_preset,
          memory_scope: workspace.memory_scope,
          mcp_preset_id: workspace.mcp_preset_id,
          createdAt: workspace.created_at || new Date().toISOString(),
          updatedAt: workspace.updated_at || new Date().toISOString(),
          context: normalizeWorkspaceContext(useLocal ? local!.context : serverContext),
          contextRevision: serverRevision,
        }
      })

      if (backendWorkspaces.length > 0) {
        state.value.workspaces = backendWorkspaces
        if (!backendWorkspaces.some((item) => item.id === state.value.activeWorkspaceId)) {
          state.value.activeWorkspaceId = backendWorkspaces[0]?.id || 'default'
        }
        persist()
        // Restore from localStorage only when the server has no context yet.
        for (const workspaceId of contextsToBackfill) {
          queueContextSave(workspaceId)
        }
      }
    } catch {
      // fallback to local-only state
    }
    await syncActiveWorkspaceToBackend(state.value.activeWorkspaceId)
  }

  const createWorkspaceRemote = async (name?: string) => {
    const activeCompanionId = activeWorkspace.value.companion_profile_id || companionStore.activeCompanionId || undefined
    const context = { ...activeWorkspace.value.context }
    const created = await workspaceClient.create({
      name: name?.trim() || t('misc.sceneFallbackName', { index: state.value.workspaces.length + 1 }),
      companion_profile_id: activeCompanionId,
      context: context as unknown as Record<string, unknown>,
    })
    const now = new Date().toISOString()
    const workspace: WorkspaceRecord = {
      id: created.id,
      name: created.name,
      description: created.description,
      icon: created.icon,
      color: created.color,
      companion_profile_id: created.companion_profile_id,
      default_model: created.default_model,
      system_prompt: created.system_prompt,
      tool_preset: created.tool_preset,
      memory_scope: created.memory_scope,
      mcp_preset_id: created.mcp_preset_id,
      createdAt: created.created_at || now,
      updatedAt: created.updated_at || now,
      context: { ...activeWorkspace.value.context },
      contextRevision: typeof created.contextRevision === 'number' ? created.contextRevision : 0,
    }
    state.value.workspaces.push(workspace)
    state.value.activeWorkspaceId = workspace.id
    state.value.recentWorkspaceIds = [workspace.id, ...state.value.recentWorkspaceIds.filter((id) => id !== workspace.id)].slice(0, 8)
    persist()
    syncActiveWorkspaceInBackground(workspace.id)
  }

  const renameWorkspaceRemote = async (workspaceId: string, name: string) => {
    const updated = await workspaceClient.update(workspaceId, { name })
    state.value.workspaces = state.value.workspaces.map((workspace) =>
      workspace.id === workspaceId ? { ...workspace, name: updated.name, updatedAt: updated.updated_at || new Date().toISOString() } : workspace
    )
    persist()
  }

  const updateWorkspaceRemote = async (workspaceId: string, patch: WorkspacePatchPayload) => {
    const updated = await workspaceClient.update(workspaceId, patch)
    const responsePatch: Partial<WorkspaceRecord> = {}
    if (updated.name !== undefined) responsePatch.name = updated.name
    if (updated.description !== undefined) responsePatch.description = updated.description
    if (updated.icon !== undefined) responsePatch.icon = updated.icon
    if (updated.color !== undefined) responsePatch.color = updated.color
    if (updated.companion_profile_id !== undefined) responsePatch.companion_profile_id = updated.companion_profile_id
    if (updated.default_model !== undefined) responsePatch.default_model = updated.default_model
    if (updated.system_prompt !== undefined) responsePatch.system_prompt = updated.system_prompt
    if (updated.tool_preset !== undefined) responsePatch.tool_preset = updated.tool_preset
    if (updated.memory_scope !== undefined) responsePatch.memory_scope = updated.memory_scope
    if (updated.mcp_preset_id !== undefined) responsePatch.mcp_preset_id = updated.mcp_preset_id
    if (typeof updated.contextRevision === 'number') responsePatch.contextRevision = updated.contextRevision
    // Only merge context when this request carried one; otherwise the response
    // contains the server's older document and would clobber local edits.
    if ('context' in patch && updated.context && typeof updated.context === 'object' && !Array.isArray(updated.context)) {
      responsePatch.context = normalizeWorkspaceContext(asContextRecord(updated.context))
    }
    state.value.workspaces = state.value.workspaces.map((workspace) =>
      workspace.id === workspaceId
        ? {
            ...workspace,
            ...responsePatch,
            updatedAt: updated.updated_at || new Date().toISOString(),
          }
        : workspace
    )
    persist()
    return updated
  }

  const deleteWorkspaceRemote = async (workspaceId: string) => {
    await workspaceClient.remove(workspaceId)
    const pendingContextSave = contextSaveTimers.get(workspaceId)
    if (pendingContextSave !== undefined) {
      window.clearTimeout(pendingContextSave)
      contextSaveTimers.delete(workspaceId)
    }
    state.value.workspaces = state.value.workspaces.filter((workspace) => workspace.id !== workspaceId)
    if (state.value.activeWorkspaceId === workspaceId) {
      state.value.activeWorkspaceId = state.value.workspaces[0]?.id || 'default'
    }
    state.value.recentWorkspaceIds = state.value.recentWorkspaceIds.filter((id) => id !== workspaceId)
    persist()
    syncActiveWorkspaceInBackground(state.value.activeWorkspaceId)
  }

  // Follow the interface language: workspaces whose prompts are still the
  // built-in default are re-localized, prompts the user edited are untouched.
  watch(currentLocale, () => {
    const changedIds: string[] = []
    for (const workspace of state.value.workspaces) {
      const engineering = workspace.context.promptEngineering
      const workPrompt = isBuiltinWorkPrompt(engineering.workPrompt) ? defaultWorkPrompt() : engineering.workPrompt
      const dailyPrompt = isBuiltinDailyPrompt(engineering.dailyPrompt) ? defaultDailyPrompt() : engineering.dailyPrompt
      if (workPrompt === engineering.workPrompt && dailyPrompt === engineering.dailyPrompt) continue
      workspace.context.promptEngineering = { workPrompt, dailyPrompt }
      changedIds.push(workspace.id)
    }
    if (changedIds.length === 0) return
    persist()
    for (const workspaceId of changedIds) {
      const workspace = state.value.workspaces.find((item) => item.id === workspaceId)
      if (workspace) queueContextSave(workspaceId, { promptEngineering: workspace.context.promptEngineering })
    }
  })

  const updateWorkspaceContext = (workspaceId: string, patch: Partial<WorkspaceContext>) => {
    const workspace = state.value.workspaces.find((w) => w.id === workspaceId)
    if (workspace) {
      workspace.context = { ...workspace.context, ...patch }
      workspace.updatedAt = new Date().toISOString()
      persist()
      queueContextSave(workspaceId, patch)
    }
  }

  return {
    state,
    activeWorkspace,
    activeWorkspaceId: computed(() => state.value.activeWorkspaceId),
    workspaces: computed(() => state.value.workspaces),
    recentWorkspaceIds: computed(() => state.value.recentWorkspaceIds),
    setActiveWorkspace,
    setActiveWorkspaceSynced,
    createWorkspace,
    syncFromBackend,
    createWorkspaceRemote,
    renameWorkspaceRemote,
    updateWorkspaceRemote,
    deleteWorkspaceRemote,
    updateWorkspaceContext,
    persist,
  }
})
