import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
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
import { useCompanionStore } from './companionStore'

const STORAGE_KEY = 'deskpet-workspaces'
const ACTIVE_KEY = 'deskpet-active-workspace'
const LEGACY_DEFAULT_MODEL_ID = 'hiyori'
export const DEFAULT_PROMPT_VERSION = 2

const LEGACY_DEFAULT_WORK_PROMPT = `当前处于任务模式。你是 Yuizaki 本地 AI 桌宠 agent 的任务协助人格。
- 先判断用户要完成的具体结果、约束、风险和可验证标准。
- 对代码、配置、文件、工具和项目内任务，优先基于当前上下文与可验证证据行动。
- 可以直接完成的事不要反复确认；缺少关键信息或存在破坏性操作时再提问。
- 输出要清晰、可执行、可复查；涉及修改时说明关键变更和验证结果，但不要把普通对话写成控制台报告。
- 不编造文件、日志、命令输出、依赖能力或外部事实。
- 保持中文为主，必要的代码标识、命令和专有名词保留原文。`

const LEGACY_DEFAULT_DAILY_PROMPT = `当前处于日常陪伴模式。你是轻松、温暖、自然的桌宠 agent。
- 语气亲近、明朗、不过度正式，优先让对话顺畅舒服。
- 用户只是闲聊、吐槽、陪伴或轻量咨询时，不要套用工程化流程。
- 可以给出简短建议、轻松回应和自然追问，但不要显得黏人或施压。
- 如果用户切到严肃任务，再自然进入结构化协助。
- 保持中文为主，回应适合后续 TTS 播放，避免过长段落。`

export const DEFAULT_WORK_PROMPT = `当前处于工作模式。你处于任务协助模式。
- 先用一句话确认用户真正要得到的结果；仅在结果、权限或破坏性风险无法判断时提问。
- 把事实、推断和未知分开。涉及文件、屏幕、工具结果或系统状态时，只使用本轮可验证证据。
- 对可安全执行的本地任务，先完成最小必要操作，再核验结果；没有执行成功时不得声称已经完成。
- 涉及写入、删除、发送、安装、授权或隐私数据时，说明影响范围并遵守既有权限策略。
- 回答先给结论，再给必要依据和下一步。普通问题保持简洁，复杂任务才使用分段结构。
- 使用自然中文；代码、命令、路径、字段名和专有名词保持原样。`

export const DEFAULT_DAILY_PROMPT = `当前处于日常模式。你处于日常陪伴模式。
- 先回应用户当下的情绪和意图，再决定是否提供建议；不要把闲聊改写成任务清单。
- 语气温暖、自然、有分寸。可以表达关心和好奇，但不占有、不施压、不连续追问。
- 不假装拥有未提供的记忆、感官或现实经历。只有收到实时画面、工具结果或明确上下文时，才据此描述。
- 用户需要严肃协助时，自然切换为清晰、可执行的表达，并保持陪伴感。
- 默认短句和短段落，适合 TTS；只有用户要求或问题复杂时再展开。
- 使用自然中文，避免模板化客服语气和过度卖萌。`

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
  workPrompt: DEFAULT_WORK_PROMPT,
  dailyPrompt: DEFAULT_DAILY_PROMPT,
})

const createDefaultVisionSettings = (): WorkspaceVisionSettings => ({
  enabled: true,
  displayIndex: 0,
  intervalMs: 2000,
  pauseWhenAppHidden: true,
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
  activeTab: 'companion',
  modelType: 'live2d',
  modelId: null,
  wallpaperMode: true,
  heroHeight: 460,
  menuOrder: [],
  recentTabs: ['companion'],
  layoutPreset: 'balanced',
  promptVersion: DEFAULT_PROMPT_VERSION,
  promptMode: 'auto',
  promptEngineering: createDefaultPromptEngineering(),
  roleCard: createDefaultRoleCard(),
  worldBook: createDefaultWorldBook(),
  vision: createDefaultVisionSettings(),
  memoryPolicy: createDefaultMemoryPolicy(),
})

const normalizePromptEngineering = (
  value: Partial<WorkspacePromptEngineering> | undefined,
  promptVersion: number,
): WorkspacePromptEngineering => {
  const workPrompt = typeof value?.workPrompt === 'string' && value.workPrompt.trim() ? value.workPrompt : DEFAULT_WORK_PROMPT
  const dailyPrompt = typeof value?.dailyPrompt === 'string' && value.dailyPrompt.trim() ? value.dailyPrompt : DEFAULT_DAILY_PROMPT
  return {
    workPrompt: promptVersion < DEFAULT_PROMPT_VERSION && workPrompt.trim() === LEGACY_DEFAULT_WORK_PROMPT.trim()
      ? DEFAULT_WORK_PROMPT
      : workPrompt,
    dailyPrompt: promptVersion < DEFAULT_PROMPT_VERSION && dailyPrompt.trim() === LEGACY_DEFAULT_DAILY_PROMPT.trim()
      ? DEFAULT_DAILY_PROMPT
      : dailyPrompt,
  }
}

const normalizeVisionSettings = (value: Partial<WorkspaceVisionSettings> | undefined): WorkspaceVisionSettings => {
  const intervalMs = Number(value?.intervalMs)
  const region = value?.region
  const normalizeRegion = (item: Partial<WorkspaceVisionSettings['region']>): WorkspaceVisionSettings['region'] => ({
    x: Math.max(0, Math.min(100000, Math.round(Number(item.x) || 0))),
    y: Math.max(0, Math.min(100000, Math.round(Number(item.y) || 0))),
    width: Math.max(64, Math.min(100000, Math.round(Number(item.width) || 64))),
    height: Math.max(64, Math.min(100000, Math.round(Number(item.height) || 64))),
  })
  return {
    enabled: value?.enabled !== false,
    displayIndex: Math.max(0, Math.min(15, Math.round(Number(value?.displayIndex) || 0))),
    intervalMs: [1000, 2000, 5000, 10000].includes(intervalMs) ? intervalMs : 2000,
    pauseWhenAppHidden: value?.pauseWhenAppHidden !== false,
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

const normalizeWorkspaceContext = (context: Partial<WorkspaceContext> | undefined): WorkspaceContext => {
  const promptVersion = Number.isFinite(Number(context?.promptVersion))
    ? Math.max(0, Math.round(Number(context?.promptVersion)))
    : 0
  const normalized: WorkspaceContext = {
    ...createDefaultWorkspaceContext(),
    ...(context ?? {}),
  }
  if (!['auto', 'work', 'daily'].includes(normalized.promptMode)) {
    normalized.promptMode = 'auto'
  }
  normalized.promptEngineering = normalizePromptEngineering(context?.promptEngineering, promptVersion)
  normalized.promptVersion = DEFAULT_PROMPT_VERSION
  normalized.roleCard = normalizeRoleCard(context?.roleCard)
  normalized.worldBook = normalizeWorldBook(context?.worldBook)
  normalized.vision = normalizeVisionSettings(context?.vision)
  normalized.memoryPolicy = normalizeMemoryPolicy(context?.memoryPolicy)
  if (normalized.modelType === 'live2d' && normalized.modelId === LEGACY_DEFAULT_MODEL_ID) {
    normalized.modelId = null
  }
  return normalized
}

const normalizeWorkspaceName = (id: string, name: string): string =>
  id === 'default' && name === '默认工作区' ? '默认场景' : name

const createDefaultWorkspace = (): WorkspaceRecord => {
  const now = new Date().toISOString()
  return {
    id: 'default',
    name: '默认场景',
    createdAt: now,
    updatedAt: now,
    context: createDefaultWorkspaceContext(),
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
      name: normalizeWorkspaceName(workspace.id, workspace.name),
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
      name: name?.trim() || `场景 ${state.value.workspaces.length + 1}`,
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
      const localContextMap = new Map(state.value.workspaces.map((item) => [item.id, item.context]))
      const backendWorkspaces = payload.workspaces.map((workspace) => ({
        id: workspace.id,
        name: normalizeWorkspaceName(workspace.id, workspace.name),
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
        context: localContextMap.get(workspace.id) ?? createDefaultWorkspace().context,
      }))

      if (backendWorkspaces.length > 0) {
        state.value.workspaces = backendWorkspaces
        if (!backendWorkspaces.some((item) => item.id === state.value.activeWorkspaceId)) {
          state.value.activeWorkspaceId = backendWorkspaces[0]?.id || 'default'
        }
        persist()
      }
    } catch {
      // fallback to local-only state
    }
    await syncActiveWorkspaceToBackend(state.value.activeWorkspaceId)
  }

  const createWorkspaceRemote = async (name?: string) => {
    const activeCompanionId = activeWorkspace.value.companion_profile_id || companionStore.activeCompanionId || undefined
    const created = await workspaceClient.create({ name: name?.trim() || `场景 ${state.value.workspaces.length + 1}`, companion_profile_id: activeCompanionId })
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
    state.value.workspaces = state.value.workspaces.filter((workspace) => workspace.id !== workspaceId)
    if (state.value.activeWorkspaceId === workspaceId) {
      state.value.activeWorkspaceId = state.value.workspaces[0]?.id || 'default'
    }
    state.value.recentWorkspaceIds = state.value.recentWorkspaceIds.filter((id) => id !== workspaceId)
    persist()
    syncActiveWorkspaceInBackground(state.value.activeWorkspaceId)
  }

  const updateWorkspaceContext = (workspaceId: string, patch: Partial<WorkspaceContext>) => {
    const workspace = state.value.workspaces.find((w) => w.id === workspaceId)
    if (workspace) {
      workspace.context = { ...workspace.context, ...patch }
      workspace.updatedAt = new Date().toISOString()
      persist()
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
