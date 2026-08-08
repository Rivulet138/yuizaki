import { describe, expect, it } from 'vitest'
import { useSessionViewState } from '../domains/chat/composables/useSessionViewState'

describe('useSessionViewState', () => {
  it('keeps attachments and scroll positions isolated by session', () => {
    const state = useSessionViewState()
    const firstAttachment = {
      id: 'att-a',
      name: 'notes.txt',
      type: 'text/plain',
      size: 12,
      kind: 'text' as const,
      content: 'session A',
    }

    state.setAttachments('session-a', [firstAttachment])
    state.setScrollPosition('session-a', 320)
    state.setScrollPosition('session-b', 48)

    expect(state.getAttachments('session-a')).toEqual([firstAttachment])
    expect(state.getAttachments('session-b')).toEqual([])
    expect(state.getScrollPosition('session-a')).toBe(320)
    expect(state.getScrollPosition('session-b')).toBe(48)
  })

  it('returns attachment snapshots and clears only the requested session', () => {
    const state = useSessionViewState()
    state.setAttachments('session-a', [{
      id: 'att-a',
      name: 'a.png',
      type: 'image/png',
      size: 42,
      kind: 'image',
    }])
    state.setAttachments('session-b', [{
      id: 'att-b',
      name: 'b.txt',
      type: 'text/plain',
      size: 10,
      kind: 'text',
      content: 'keep',
    }])
    state.getAttachments('session-a').push({
      id: 'external',
      name: 'external.bin',
      type: 'application/octet-stream',
      size: 1,
      kind: 'binary',
    })

    expect(state.getAttachments('session-a')).toHaveLength(1)

    state.clearSession('session-a')
    expect(state.getAttachments('session-a')).toEqual([])
    expect(state.getAttachments('session-b')).toHaveLength(1)
    expect(state.getScrollPosition('session-a')).toBeNull()
  })
})
