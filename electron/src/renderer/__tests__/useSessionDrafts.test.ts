import { beforeEach, describe, expect, it } from 'vitest'
import { useSessionDrafts } from '../domains/chat/composables/useSessionDrafts'

describe('useSessionDrafts', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('restores drafts independently for each session', () => {
    const drafts = useSessionDrafts()

    drafts.setDraft('session-a', 'draft A')
    drafts.setDraft('session-b', 'draft B')

    expect(drafts.getDraft('session-a')).toBe('draft A')
    expect(drafts.getDraft('session-b')).toBe('draft B')
    expect(drafts.draftSessionIds.value).toEqual(['session-a', 'session-b'])
  })

  it('clears only the draft that was sent', () => {
    const drafts = useSessionDrafts()
    drafts.setDraft('session-a', 'send this')
    drafts.setDraft('session-b', 'keep this')

    drafts.clearDraft('session-a')

    expect(drafts.getDraft('session-a')).toBe('')
    expect(drafts.getDraft('session-b')).toBe('keep this')
    expect(drafts.draftSessionIds.value).toEqual(['session-b'])
  })

  it('restores persisted drafts without keeping blank entries', () => {
    window.localStorage.setItem('yuizaki.chat.sessionDrafts.v1', JSON.stringify({
      'session-a': 'persisted',
      'session-b': '   ',
    }))

    const drafts = useSessionDrafts()

    expect(drafts.getDraft('session-a')).toBe('persisted')
    expect(drafts.hasDraft('session-b')).toBe(false)
  })
})
