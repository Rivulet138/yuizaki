import type { ChatAttachment } from '@/../shared/types'

const normalizeSessionId = (sessionId?: string | null) => sessionId?.trim() || 'default'

export function useSessionViewState() {
  const attachmentsBySession = new Map<string, ChatAttachment[]>()
  const scrollPositionBySession = new Map<string, number>()

  const getAttachments = (sessionId?: string | null) => (
    attachmentsBySession.get(normalizeSessionId(sessionId))?.map((attachment) => ({ ...attachment })) ?? []
  )

  const setAttachments = (sessionId: string | null | undefined, attachments: ChatAttachment[]) => {
    const id = normalizeSessionId(sessionId)
    if (!attachments.length) {
      attachmentsBySession.delete(id)
      return
    }
    attachmentsBySession.set(id, attachments.map((attachment) => ({ ...attachment })))
  }

  const getScrollPosition = (sessionId?: string | null) => (
    scrollPositionBySession.get(normalizeSessionId(sessionId)) ?? null
  )

  const setScrollPosition = (sessionId: string | null | undefined, position: number) => {
    if (!Number.isFinite(position)) return
    scrollPositionBySession.set(normalizeSessionId(sessionId), Math.max(0, position))
  }

  const clearSession = (sessionId?: string | null) => {
    const id = normalizeSessionId(sessionId)
    attachmentsBySession.delete(id)
    scrollPositionBySession.delete(id)
  }

  return {
    getAttachments,
    setAttachments,
    getScrollPosition,
    setScrollPosition,
    clearSession,
  }
}
