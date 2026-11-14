import { computed, ref } from 'vue'

const SESSION_DRAFTS_STORAGE_KEY = 'yuizaki.chat.sessionDrafts.v1'
const MAX_SESSION_DRAFTS = 100
const MAX_DRAFT_LENGTH = 50_000

type SessionDraftMap = Record<string, string>

const normalizeSessionId = (sessionId?: string | null) => sessionId?.trim() || 'default'

const loadDrafts = (storage?: Storage): SessionDraftMap => {
  if (!storage) return {}
  try {
    const parsed = JSON.parse(storage.getItem(SESSION_DRAFTS_STORAGE_KEY) || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    return Object.fromEntries(
      Object.entries(parsed)
        .filter(([sessionId, value]) => sessionId.trim() && typeof value === 'string' && value.trim())
        .slice(-MAX_SESSION_DRAFTS)
        .map(([sessionId, value]) => [sessionId, (value as string).slice(0, MAX_DRAFT_LENGTH)]),
    )
  } catch {
    return {}
  }
}

const createDraftState = (storage?: Storage) => {
  const drafts = ref<SessionDraftMap>(loadDrafts(storage))
  let persistTimer: number | null = null

  const flushDrafts = () => {
    if (!storage) return
    if (persistTimer !== null) window.clearTimeout(persistTimer)
    persistTimer = null
    storage.setItem(SESSION_DRAFTS_STORAGE_KEY, JSON.stringify(drafts.value))
  }

  const schedulePersist = () => {
    if (typeof window === 'undefined') return
    if (persistTimer !== null) window.clearTimeout(persistTimer)
    persistTimer = window.setTimeout(flushDrafts, 180)
  }

  const getDraft = (sessionId?: string | null) => drafts.value[normalizeSessionId(sessionId)] || ''

  const setDraft = (sessionId: string | null | undefined, value: string) => {
    const id = normalizeSessionId(sessionId)
    if (!value.trim()) {
      if (id in drafts.value) {
        const next = { ...drafts.value }
        delete next[id]
        drafts.value = next
        schedulePersist()
      }
      return
    }
    const next = {
      ...drafts.value,
      [id]: value.slice(0, MAX_DRAFT_LENGTH),
    }
    const entries = Object.entries(next).slice(-MAX_SESSION_DRAFTS)
    drafts.value = Object.fromEntries(entries)
    schedulePersist()
  }

  return { drafts, getDraft, setDraft, flushDrafts }
}

// All cached panels writing to the same storage share one map and debounce queue.
const draftStates = new WeakMap<Storage, ReturnType<typeof createDraftState>>()

export const useSessionDrafts = (workspaceId: () => string = () => 'default') => {
  const storage = typeof window === 'undefined' ? undefined : window.localStorage
  let state = storage ? draftStates.get(storage) : undefined
  if (!state) {
    state = createDraftState(storage)
    if (storage) draftStates.set(storage, state)
  }
  const { drafts, flushDrafts } = state
  const shared = state
  const defaultKey = (workspace: string) => JSON.stringify(['default', workspace.trim() || 'default'])
  const draftKey = (sessionId: string | null | undefined, workspace: string) => {
    const id = normalizeSessionId(sessionId)
    return id === 'default' ? defaultKey(workspace) : id
  }

  // The legacy default draft had no workspace. Claim it once for the first workspace opened.
  const legacyDefault = shared.getDraft('default')
  if (legacyDefault) {
    const key = defaultKey(workspaceId())
    shared.setDraft('default', '')
    if (!shared.getDraft(key)) shared.setDraft(key, legacyDefault)
  }

  const getDraft = (sessionId?: string | null, workspace = workspaceId()) => shared.getDraft(draftKey(sessionId, workspace))
  const setDraft = (sessionId: string | null | undefined, value: string, workspace = workspaceId()) => shared.setDraft(draftKey(sessionId, workspace), value)
  const clearDraft = (sessionId?: string | null, workspace = workspaceId()) => setDraft(sessionId, '', workspace)
  const hasDraft = (sessionId?: string | null) => Boolean(getDraft(sessionId).trim())
  const draftSessionIds = computed(() => Object.keys(drafts.value)
    .filter((key) => !key.startsWith('["default",') || key === defaultKey(workspaceId()))
    .map((key) => key === defaultKey(workspaceId()) ? 'default' : key))

  return { drafts, draftSessionIds, getDraft, setDraft, clearDraft, hasDraft, flushDrafts }
}
