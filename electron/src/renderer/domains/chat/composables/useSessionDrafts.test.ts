import { effectScope, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionDrafts } from './useSessionDrafts'

const STORAGE_KEY = 'yuizaki.chat.sessionDrafts.v1'

describe('shared session draft persistence', () => {
  let storage: Map<string, string>
  const persisted = () => JSON.parse(storage.get(STORAGE_KEY) || '{}') as Record<string, string>
  beforeEach(() => {
    vi.useFakeTimers()
    storage = new Map()
    vi.stubGlobal('window', {
      localStorage: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) },
      setTimeout, clearTimeout,
    })
  })
  afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals() })

  it('keeps both instances live through A/B/A edits and either flush order', async () => {
    const a = useSessionDrafts()
    const b = useSessionDrafts()
    a.setDraft('a', 'A draft')
    b.setDraft('b', 'B draft')
    a.setDraft('a', 'A revised')
    expect(a.getDraft('b')).toBe('B draft')
    expect(b.getDraft('a')).toBe('A revised')
    b.flushDrafts()
    a.flushDrafts()
    await vi.runAllTimersAsync()
    expect(persisted()).toEqual({ a: 'A revised', b: 'B draft' })
    expect(useSessionDrafts().getDraft('b')).toBe('B draft')
  })

  it('never resurrects a cleared draft through a pending timer or stale instance flush/unmount', async () => {
    storage.set(STORAGE_KEY, JSON.stringify({ a: 'old draft' }))
    const scope = effectScope()
    const old = scope.run(() => useSessionDrafts())!
    const current = useSessionDrafts()
    old.setDraft('a', 'old pending draft')
    current.clearDraft('a')
    current.flushDrafts()
    old.flushDrafts()
    scope.stop()
    await vi.runAllTimersAsync()
    expect(old.getDraft('a')).toBe('')
    expect(persisted()).toEqual({})
    expect(useSessionDrafts().getDraft('a')).toBe('')
  })
  it('isolates default drafts and exposes the default badge only in its workspace', () => {
    const workspace = ref('A')
    const a = useSessionDrafts(() => workspace.value)
    const b = useSessionDrafts(() => 'B')
    a.setDraft('default', 'A default')
    a.setDraft('named-session', 'named')
    expect(b.getDraft('default')).toBe('')
    expect(b.draftSessionIds.value).toEqual(['named-session'])
    b.setDraft('default', 'B default')
    workspace.value = 'B'
    expect(a.getDraft('default')).toBe('B default')
    workspace.value = 'A'
    expect(a.getDraft('default')).toBe('A default')
    expect(a.draftSessionIds.value).toContain('default')
    b.clearDraft('default')
    b.flushDrafts()
    expect(a.getDraft('default')).toBe('A default')
    expect(b.hasDraft('default')).toBe(false)
  })

  it('migrates the legacy default exactly once, preserving named drafts and reload compatibility', () => {
    storage.set(STORAGE_KEY, JSON.stringify({ default: 'legacy default', named: 'named draft' }))
    const a = useSessionDrafts(() => 'workspace A')
    const b = useSessionDrafts(() => 'workspace B')
    expect(a.getDraft('default')).toBe('legacy default')
    expect(b.getDraft('default')).toBe('')
    expect(b.getDraft('named')).toBe('named draft')
    a.flushDrafts()
    expect(persisted()).toEqual({ [JSON.stringify(['default', 'workspace A'])]: 'legacy default', named: 'named draft' })
    const saved = persisted()
    vi.stubGlobal('window', { localStorage: {
      getItem: (key: string) => key === STORAGE_KEY ? JSON.stringify(saved) : null,
      setItem: (key: string, value: string) => storage.set(key, value),
    }, setTimeout, clearTimeout })
    expect(useSessionDrafts(() => 'workspace A').getDraft('default')).toBe('legacy default')
    expect(useSessionDrafts(() => 'workspace B').getDraft('default')).toBe('')
  })

  it('migrates a full legacy map without evicting a named draft', () => {
    const named = Object.fromEntries(Array.from({ length: 99 }, (_, index) => ['named-' + index, 'draft']))
    storage.set(STORAGE_KEY, JSON.stringify({ ...named, default: 'legacy' }))
    const drafts = useSessionDrafts(() => 'A')
    drafts.flushDrafts()
    expect(persisted()).toEqual({ ...named, [JSON.stringify(['default', 'A'])]: 'legacy' })
  })

  it('keeps an existing scoped default when legacy data is also present', () => {
    storage.set(STORAGE_KEY, JSON.stringify({ default: 'legacy', [JSON.stringify(['default', 'A'])]: 'newer' }))
    const a = useSessionDrafts(() => 'A')
    const b = useSessionDrafts(() => 'B')
    expect(a.getDraft('default')).toBe('newer')
    expect(b.getDraft('default')).toBe('')
    b.flushDrafts()
    expect(persisted()).not.toHaveProperty('default')
  })

  it('preserves the existing length and count limits across shared instances', () => {
    const a = useSessionDrafts()
    const b = useSessionDrafts()
    for (let index = 0; index < 101; index += 1) a.setDraft('session-' + index, 'draft')
    b.setDraft('long', 'x'.repeat(50_001))
    expect(Object.keys(a.drafts.value)).toHaveLength(100)
    expect(a.getDraft('session-0')).toBe('')
    expect(a.getDraft('long')).toHaveLength(50_000)
  })
})
