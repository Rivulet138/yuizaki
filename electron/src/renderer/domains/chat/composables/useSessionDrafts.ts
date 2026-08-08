import { computed, ref } from 'vue'

const SESSION_DRAFTS_STORAGE_KEY = 'yuizaki.chat.sessionDrafts.v1'
const MAX_SESSION_DRAFTS = 100
const MAX_DRAFT_LENGTH = 50_000

type SessionDraftMap = Record<string, string>

const normalizeSessionId = (sessionId?: string | null) => sessionId?.trim() || 'default'

const loadDrafts = (): SessionDraftMap => {
  if (typeof window === 'undefined') return {}
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SESSION_DRAFTS_STORAGE_KEY) || '{}')
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

export const useSessionDrafts = () => {
  const drafts = ref<SessionDraftMap>(loadDrafts())
  let persistTimer: number | null = null

  const flushDrafts = () => {
    if (typeof window === 'undefined') return
    if (persistTimer !== null) window.clearTimeout(persistTimer)
    persistTimer = null
    window.localStorage.setItem(SESSION_DRAFTS_STORAGE_KEY, JSON.stringify(drafts.value))
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

  const clearDraft = (sessionId?: string | null) => setDraft(sessionId, '')
  const hasDraft = (sessionId?: string | null) => Boolean(getDraft(sessionId).trim())
  const draftSessionIds = computed(() => Object.keys(drafts.value).filter((sessionId) => hasDraft(sessionId)))

  return {
    drafts,
    draftSessionIds,
    getDraft,
    setDraft,
    clearDraft,
    hasDraft,
    flushDrafts,
  }
}
