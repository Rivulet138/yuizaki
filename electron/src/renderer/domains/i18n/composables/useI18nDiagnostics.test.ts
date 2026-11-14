import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref, type EffectScope } from 'vue'
import { i18nClient } from '@/api/client'
import { useI18nDiagnostics } from './useI18nDiagnostics'

vi.mock('vue', async (original) => ({ ...await original<typeof import('vue')>(), onMounted: vi.fn() }))
vi.mock('element-plus', () => ({ ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn() } }))
vi.mock('@/i18n', () => ({
  setLocale: vi.fn().mockResolvedValue('en-US'),
  useI18n: () => ({ locale: ref('zh-CN'), localeLabel: (value: string) => value, supportedLocales: [], t: (key: string) => key }),
}))
vi.mock('@/shared/errors/describe-error', () => ({ describeFailure: (error: Error) => error.message }))
vi.mock('@/api/client', () => ({ i18nClient: { locales: vi.fn(), messages: vi.fn(), setLocale: vi.fn(), message: vi.fn(), errorMessage: vi.fn() } }))
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
let scope: EffectScope
const setup = () => {
  scope = effectScope()
  return scope.run(() => useI18nDiagnostics())!
}
beforeEach(() => vi.clearAllMocks())
afterEach(() => scope?.stop())

describe('i18n request ordering', () => {
  it('keeps the acknowledged backend locale when dictionary readback fails', async () => {
    vi.mocked(i18nClient.setLocale).mockResolvedValue({ status: 'ok', locale: 'ja-JP' })
    vi.mocked(i18nClient.messages).mockRejectedValueOnce(new Error('dictionary unavailable'))
    const state = setup()
    state.currentLocale.value = 'zh-CN'
    state.messages.value = { old: true }
    state.selectedLocale.value = 'ja-JP'
    await state.applyBackendLocale()
    expect(state.currentLocale.value).toBe('ja-JP')
    expect(state.messages.value).toEqual({})
    expect(state.loadError.value).toBe('dictionary unavailable')
    expect(state.localeBusy.value).toBe(false)
  })

  it('discards a late lookup error after the selected locale changes', async () => {
    let fail!: (error: Error) => void
    vi.mocked(i18nClient.message).mockReturnValueOnce(new Promise((_resolve, reject) => { fail = reject }))
    const state = setup()
    state.messageKey.value = 'key'
    state.selectedLocale.value = 'zh-CN'
    const pending = state.lookupMessage()
    state.selectedLocale.value = 'en-US'
    fail(new Error('stale failure'))
    await pending
    expect(state.lastLookup.value).toBe('')
    expect(state.lookupFailed.value).toBe(false)
    expect(state.lookupKind.value).toBe('')
  })

  it('rejects an older refresh after a language mutation', async () => {
    const oldMessages = deferred<Awaited<ReturnType<typeof i18nClient.messages>>>()
    vi.mocked(i18nClient.locales).mockResolvedValue({ current: 'zh-CN', available: ['zh-CN', 'en-US'], localeNames: {} })
    vi.mocked(i18nClient.messages).mockReturnValueOnce(oldMessages.promise).mockResolvedValueOnce({ messages: { newest: true } })
    vi.mocked(i18nClient.setLocale).mockResolvedValue({ status: 'ok', locale: 'en-US' })
    const state = setup()
    const refreshing = state.loadAll()
    await Promise.resolve()
    state.selectedLocale.value = 'en-US'
    await state.applyBackendLocale()
    oldMessages.resolve({ messages: { old: true } })
    await refreshing
    expect(state.currentLocale.value).toBe('en-US')
    expect(state.messages.value).toEqual({ newest: true })
    expect(state.loading.value).toBe(false)
  })

  it('releases a superseded refresh and keeps a newer refresh busy when the old one finishes', async () => {
    const oldMessages = deferred<Awaited<ReturnType<typeof i18nClient.messages>>>()
    const newMessages = deferred<Awaited<ReturnType<typeof i18nClient.messages>>>()
    vi.mocked(i18nClient.locales).mockResolvedValue({ current: 'en-US', available: ['en-US'], localeNames: {} })
    vi.mocked(i18nClient.messages).mockReturnValueOnce(oldMessages.promise)
      .mockResolvedValueOnce({ messages: { applied: true } }).mockReturnValueOnce(newMessages.promise)
    vi.mocked(i18nClient.setLocale).mockResolvedValue({ status: 'success', locale: 'en-US' })
    const state = setup()
    const old = state.loadAll()
    await Promise.resolve()
    state.selectedLocale.value = 'en-US'
    await state.applyBackendLocale()
    expect(state.loading.value).toBe(false)
    const latest = state.loadAll()
    await Promise.resolve()
    oldMessages.resolve({ messages: { stale: true } })
    await old
    expect(state.loading.value).toBe(true)
    newMessages.resolve({ messages: { latest: true } })
    await latest
    expect(state.messages.value).toEqual({ latest: true })
    expect(state.loading.value).toBe(false)
  })

  it('serializes the two language mutation entry points', async () => {
    const applying = deferred<Awaited<ReturnType<typeof i18nClient.setLocale>>>()
    vi.mocked(i18nClient.setLocale).mockReturnValueOnce(applying.promise)
    vi.mocked(i18nClient.messages).mockResolvedValue({ messages: {} })
    const state = setup()
    state.selectedLocale.value = 'ja-JP'
    const first = state.applyBackendLocale()
    state.selectedFrontendLocale.value = 'en-US'
    await state.applyAppLocale()
    expect(i18nClient.setLocale).toHaveBeenCalledTimes(1)
    applying.resolve({ status: 'ok', locale: 'ja-JP' })
    await first
    expect(state.currentLocale.value).toBe('ja-JP')
    expect(state.localeBusy.value).toBe(false)
  })

  it('binds lookups to kind, key, locale and request order', async () => {
    const old = deferred<{ message: string }>()
    vi.mocked(i18nClient.message).mockReturnValueOnce(old.promise)
    vi.mocked(i18nClient.errorMessage).mockResolvedValue({ message: 'new result' })
    const state = setup()
    state.messageKey.value = 'old'
    state.selectedLocale.value = 'zh-CN'
    const first = state.lookupMessage()
    state.messageKey.value = 'new'
    state.selectedLocale.value = 'en-US'
    await state.lookupError()
    old.resolve({ message: 'stale result' })
    await first
    expect(state.lastLookup.value).toBe('new result')
    expect(i18nClient.errorMessage).toHaveBeenCalledWith('new', 'en-US')
    state.selectedLocale.value = 'ja-JP'
    expect(state.lastLookup.value).toBe('')
  })
})
