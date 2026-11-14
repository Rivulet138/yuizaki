import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, onMounted, onActivated, onDeactivated, onBeforeUnmount, onUnmounted, type EffectScope } from 'vue'
import SettingsPanel from './SettingsPanel.vue'
import { settingsClient } from '@/api/clients/settings-client'
import { resourceClient } from '@/api/clients/resource-client'
import { memoryClient } from '@/api/clients/memory-client'
import { ElMessage } from 'element-plus'
import { t } from '@/i18n'
import { settingsSaveState } from '../settingsSaveState'

vi.mock('element-plus/es/components/alert/style/css', () => ({}))
vi.mock('element-plus/es/components/icon/style/css', () => ({}))
vi.mock('element-plus/es/components/button/style/css', () => ({}))
vi.mock('element-plus/es/components/slider/style/css', () => ({}))
vi.mock('element-plus/es/components/input/style/css', () => ({}))
vi.mock('element-plus/es/components/input-number/style/css', () => ({}))
vi.mock('element-plus/es/components/card/style/css', () => ({}))
vi.mock('element-plus/es/components/tag/style/css', () => ({}))
vi.mock('element-plus/es/components/table/style/css', () => ({}))
vi.mock('element-plus/es/components/table-column/style/css', () => ({}))
vi.mock('element-plus/es/components/collapse/style/css', () => ({}))
vi.mock('element-plus/es/components/collapse-item/style/css', () => ({}))
vi.mock('element-plus/es/components/tabs/style/css', () => ({}))
vi.mock('element-plus/es/components/form/style/css', () => ({}))
vi.mock('element-plus/es/components/form-item/style/css', () => ({}))
vi.mock('element-plus/es/components/tab-pane/style/css', () => ({}))
vi.mock('element-plus/es/components/select/style/css', () => ({}))
vi.mock('element-plus/es/components/option/style/css', () => ({}))
vi.mock('@/shared/components/panel/PanelShell.vue', () => ({ default: {} }))
vi.mock('@/shared/components/feedback/AsyncState.vue', () => ({ default: {} }))
vi.mock('../components/SettingsAsrSection.vue', () => ({ default: {} }))
vi.mock('../components/SettingsAccessSection.vue', () => ({ default: {} }))
vi.mock('../components/SettingsLlmVisionSection.vue', () => ({ default: {} }))
vi.mock('../components/SettingsMemorySection.vue', () => ({ default: {} }))
vi.mock('../components/SettingsSummarySection.vue', () => ({ default: {} }))
vi.mock('../components/SettingsDesktopInputSection.vue', () => ({ default: {} }))
vi.mock('../components/SettingsInterfaceSection.vue', () => ({ default: {} }))
vi.mock('../components/SettingsResourcesSection.vue', () => ({ default: {} }))

vi.mock('vue', async (original) => ({ ...await original<typeof import('vue')>(), useSSRContext: () => ({ modules: new Set() }), onActivated: vi.fn(), onDeactivated: vi.fn(), onMounted: vi.fn(), onBeforeUnmount: vi.fn(), onUnmounted: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))
vi.mock('element-plus', async (original) => ({
  ...await original<typeof import('element-plus')>(),
  ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') },
}))
vi.mock('../components/SettingsSvcSection.vue', () => ({ default: {} }))
vi.mock('@/api/clients/settings-client', () => ({ settingsClient: {
  runtimeStatus: vi.fn(), retryRuntime: vi.fn(), load: vi.fn(), save: vi.fn(), listLlmModels: vi.fn(), discoverLocal: vi.fn(),
  backendTokenStatus: vi.fn(), ttsCharacters: vi.fn(), warmupTts: vi.fn(), testLlm: vi.fn(), testTts: vi.fn(), testSvc: vi.fn(),
  llmStatus: vi.fn(), ttsStatus: vi.fn(), deleteSetting: vi.fn(), setSetting: vi.fn(), metadata: vi.fn(), history: vi.fn(),
} }))
vi.mock('@/api/client', async () => ({ settingsClient: (await import('@/api/clients/settings-client')).settingsClient }))
vi.mock('@/api/clients/resource-client', () => ({ resourceClient: {
  storageStatus: vi.fn(), status: vi.fn(), progress: vi.fn(), prepare: vi.fn(), cancel: vi.fn(), remove: vi.fn(),
} }))
vi.mock('@/state/inputBindingsStore', () => ({ useInputBindingsStore: () => ({ state: {}, load: vi.fn() }) }))
vi.mock('@/api/clients/memory-client', () => ({ memoryClient: { getIndexStatus: vi.fn(), rebuildIndex: vi.fn(), getIndexRebuildJob: vi.fn(), cancelIndexRebuild: vi.fn() } }))

const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
let scope: EffectScope
let logging: ReturnType<typeof vi.spyOn>
let state: any
let saved: any
const emptyResources = () => ({ activeDownloads: [], resumableDownloads: [] })

beforeEach(() => {
  settingsSaveState.pending.value = null
  settingsSaveState.failed.value = null
  settingsSaveState.pendingFields = new Map()
  settingsSaveState.failedFields = new Map()
  settingsSaveState.activeFields = new Map()
  settingsSaveState.failureScopes.value = new Map()
  settingsSaveState.active.value = null
  settingsSaveState.inFlight.value = false
  settingsSaveState.readbackFailed.value = false
  settingsSaveState.deletingKeys.value = new Set()
  settingsSaveState.completion.value = null
  settingsSaveState.queuedAt = null
  settingsSaveState.timeout = null
  settingsSaveState.failures = 0
  settingsSaveState.idleResolvers = []
  settingsSaveState.adminInFlight = false
  settingsSaveState.adminResolvers = []
  vi.clearAllMocks()
  vi.useFakeTimers()
  logging = vi.spyOn(console, 'error').mockImplementation(() => undefined)
  vi.stubGlobal('window', { localStorage: { getItem: () => 'gpt-6.1-sol-v1' }, setInterval, clearInterval, setTimeout, clearTimeout })
  vi.stubGlobal('document', { hidden: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })
  scope = effectScope()
  state = scope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
  saved = structuredClone(JSON.parse(JSON.stringify(state.form)))
  state.settings.value = structuredClone(saved)
  vi.mocked(settingsClient.load).mockImplementation(async () => structuredClone(saved))
  vi.mocked(settingsClient.save).mockResolvedValue({ status: 'ok' })
  vi.mocked(settingsClient.backendTokenStatus).mockResolvedValue(null as any)
  vi.mocked(settingsClient.ttsCharacters).mockResolvedValue({ characters: [] } as any)
  vi.mocked(settingsClient.ttsStatus).mockResolvedValue(null as any)
  vi.mocked(resourceClient.status).mockResolvedValue(emptyResources() as any)
  vi.mocked(resourceClient.progress).mockResolvedValue({ activeDownloads: [] })
})
afterEach(() => {
  scope.stop()
  logging.mockRestore()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('settings shared save recovery regressions', () => {
  it('clears the original save failure and normalizes its draft after another panel retries successfully', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    state.form.summary.trigger_messages = 999
    vi.mocked(settingsClient.save).mockRejectedValueOnce(new Error('synthetic save failure'))
    state.debouncedSave({ summary: { trigger_messages: 999 } })
    expect(await state.flushPendingSave()).toBe(false)
    const secondScope = effectScope()
    try {
      const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
      second.settings.value = structuredClone(saved)
      second.hydratePreservingDraft(second.captureFormDraft(), saved)
      expect(second.form.summary.trigger_messages).toBe(999)
      const normalized = { ...saved, summary: { ...saved.summary, trigger_messages: 100 } }
      vi.mocked(settingsClient.save).mockResolvedValueOnce({ status: 'ok', normalized_settings: normalized })
      second.retryFailedSave()
      await second.waitForSaveIdle()
      await nextTick()
      expect(second.form.summary.trigger_messages).toBe(100)
      expect(state.failedSavePatch.value).toBeNull()
      expect(state.settings.value.summary.trigger_messages).toBe(100)
      expect(state.updateRequest.error).toBeNull()
      expect(state.saveStatusLabel.value).toBe(t('settings.status.saved'))
      expect(state.form.summary.trigger_messages).toBe(100)
    } finally { secondScope.stop() }
  })
  it('normalizes the submitting panel when another panel drains its queued edit', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    const first = deferred<any>()
    const normalizedFirst = { ...saved, summary: { ...saved.summary, trigger_messages: 30 } }
    const normalizedSecond = { ...saved, summary: { ...saved.summary, trigger_messages: 100 } }
    vi.mocked(settingsClient.save).mockReturnValueOnce(first.promise).mockResolvedValueOnce({ status: 'ok', normalized_settings: normalizedSecond })
    state.form.summary.trigger_messages = 30
    state.debouncedSave({ summary: { trigger_messages: 30 } })
    const flushing = state.flushPendingSave()
    const secondScope = effectScope()
    try {
      const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
      second.settings.value = structuredClone(saved)
      second.hydratePreservingDraft(second.captureFormDraft(), saved)
      second.form.summary.trigger_messages = 999
      second.debouncedSave({ summary: { trigger_messages: 999 } })
      first.resolve({ status: 'ok', normalized_settings: normalizedFirst })
      await flushing
      await nextTick()
      expect(settingsClient.save).toHaveBeenCalledTimes(2)
      expect(second.pendingSavePatch.value).toBeNull()
      expect(second.settings.value.summary.trigger_messages).toBe(100)
      expect(second.form.summary.trigger_messages).toBe(100)
    } finally { secondScope.stop() }
  })

  it('preserves an unrelated same-value draft when another panel saves that field', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    const response = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(response.promise)
    state.form.summary.trigger_messages = 999
    state.debouncedSave({ summary: { trigger_messages: 999 } })
    const flushing = state.flushPendingSave()
    const secondScope = effectScope()
    try {
      const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
      second.settings.value = structuredClone(saved)
      second.hydratePreservingDraft(second.captureFormDraft(), saved)
      second.form.summary.trigger_messages = 998
      second.form.summary.trigger_messages = 999
      response.resolve({ status: 'ok', normalized_settings: { ...saved, summary: { ...saved.summary, trigger_messages: 100 } } })
      await flushing
      await nextTick()
      expect(second.settings.value.summary.trigger_messages).toBe(100)
      expect(second.form.summary.trigger_messages).toBe(999)
    } finally { secondScope.stop() }
  })

  it('preserves edits away and back after this panel submitted a field', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    const response = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(response.promise)
    state.form.summary.trigger_messages = 999
    state.debouncedSave({ summary: { trigger_messages: 999 } })
    const flushing = state.flushPendingSave()
    state.form.summary.trigger_messages = 998
    state.form.summary.trigger_messages = 999
    response.resolve({ status: 'ok', normalized_settings: { ...saved, summary: { ...saved.summary, trigger_messages: 100 } } })
    await flushing
    expect(state.settings.value.summary.trigger_messages).toBe(100)
    expect(state.form.summary.trigger_messages).toBe(999)
  })

  it('does not clear a failed save error when an unrelated completion arrives', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    state.form.summary.trigger_messages = 999
    vi.mocked(settingsClient.save).mockRejectedValueOnce(new Error('synthetic save failure'))
    state.debouncedSave({ summary: { trigger_messages: 999 } })
    expect(await state.flushPendingSave()).toBe(false)
    const originalError = state.updateRequest.error
    settingsSaveState.completion.value = { status: 'ok', normalizedSettings: saved, submitted: {}, owner: Symbol('unrelated-admin-write') }
    await nextTick()
    expect(state.updateRequest.error).toBe(originalError)
    expect(state.saveStatusLabel.value).toBe(t('settings.status.saveFailed'))
  })

  it('normalizes nested profiles queued by another panel without losing its later profile draft', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    const first = deferred<any>()
    const secondResponse = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(first.promise).mockReturnValueOnce(secondResponse.promise)
    state.form.summary.trigger_messages = 30
    state.debouncedSave({ summary: { trigger_messages: 30 } })
    const flushing = state.flushPendingSave()
    const secondScope = effectScope()
    try {
      const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
      second.settings.value = structuredClone(saved)
      second.hydratePreservingDraft(second.captureFormDraft(), saved)
      second.form.llm.timeout = 999
      second.llmProfiles.custom.timeout = 999
      second.llmProfiles.custom.model = 'submitted-model'
      second.debouncedSave({ llm: { timeout: 999, profiles: { custom: { timeout: 999, model: 'submitted-model' } } } })
      second.llmProfiles.custom.model = 'later-model'
      first.resolve({ status: 'ok', normalized_settings: { ...saved, summary: { ...saved.summary, trigger_messages: 30 } } })
      for (let i = 0; i < 12; i += 1) await Promise.resolve()
      secondResponse.resolve({ status: 'ok', normalized_settings: { ...saved, llm: { ...saved.llm, timeout: 120, profiles: { custom: { ...saved.llm, timeout: 120, model: 'submitted-model' } } } } })
      await flushing
      expect(second.form.llm.timeout).toBe(120)
      expect(second.llmProfiles.custom.timeout).toBe(120)
      expect(second.llmProfiles.custom.model).toBe('later-model')
    } finally {
      first.resolve({ status: 'ok', normalized_settings: saved })
      secondResponse.resolve({ status: 'ok', normalized_settings: saved })
      secondScope.stop()
    }
  })

  it('keeps a failure linked across another failed retry and clears it after recovery', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    state.form.summary.trigger_messages = 999
    vi.mocked(settingsClient.save).mockRejectedValueOnce(new Error('first failure'))
    state.debouncedSave({ summary: { trigger_messages: 999 } })
    await state.flushPendingSave()
    const secondScope = effectScope()
    try {
      const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
      second.settings.value = structuredClone(saved)
      second.hydratePreservingDraft(second.captureFormDraft(), saved)
      vi.mocked(settingsClient.save).mockRejectedValueOnce(new Error('retry failure'))
      second.retryFailedSave()
      await second.waitForSaveIdle()
      expect(state.updateRequest.error).toBeTruthy()
      expect(second.updateRequest.error).toBeTruthy()
      vi.mocked(settingsClient.save).mockResolvedValueOnce({ status: 'ok', normalized_settings: { ...saved, summary: { ...saved.summary, trigger_messages: 100 } } })
      second.retryFailedSave()
      await second.waitForSaveIdle()
      expect(state.updateRequest.error).toBeNull()
      expect(second.updateRequest.error).toBeNull()
      expect(state.form.summary.trigger_messages).toBe(100)
    } finally { secondScope.stop() }
  })

  it.each([false, true])('acknowledges a failed credential save only after deletion succeeds (other panel: %s)', async otherPanel => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    state.form.asr.api_key = 'failed-fixture-key'
    vi.mocked(settingsClient.save).mockRejectedValueOnce(new Error('credential save failed'))
    state.debouncedSave({ asr: { api_key: 'failed-fixture-key' } })
    await state.flushPendingSave()
    const secondScope = effectScope()
    try {
      const second: any = otherPanel ? secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() })) : state
      if (otherPanel) {
        second.settings.value = structuredClone(saved)
        second.hydratePreservingDraft(second.captureFormDraft(), saved)
      }
      const removal = deferred<any>()
      vi.mocked(settingsClient.deleteSetting).mockReturnValueOnce(removal.promise)
      const clearing = second.clearAsrApiKey()
      for (let i = 0; i < 12; i += 1) await Promise.resolve()
      expect(state.updateRequest.error).toContain('credential save failed')
      removal.resolve({ status: 'ok' })
      await clearing
      expect(state.updateRequest.error).toBeNull()
      expect(state.form.asr.api_key).toBe('')
      expect(settingsSaveState.failureScopes.value.size).toBe(0)
      expect(state.failedSavePatch.value).toBeNull()
      expect(state.saveStatusLabel.value).not.toBe(t('settings.status.saveFailed'))
    } finally { secondScope.stop() }
  })

  it('retains a credential save failure when DELETE fails, then clears it on successful deletion', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    state.form.asr.api_key = 'failed-fixture-key'
    vi.mocked(settingsClient.save).mockRejectedValueOnce(new Error('credential save failed'))
    state.debouncedSave({ asr: { api_key: 'failed-fixture-key' } })
    await state.flushPendingSave()
    vi.mocked(settingsClient.deleteSetting).mockRejectedValueOnce(new Error('DELETE failed'))
    await state.clearAsrApiKey()
    expect(state.updateRequest.error).toContain('credential save failed')
    vi.mocked(settingsClient.deleteSetting).mockResolvedValueOnce({ status: 'ok' })
    await state.clearAsrApiKey()
    expect(state.updateRequest.error).toBeNull()
  })

  it('does not acknowledge a removed credential when only the remaining failed fields were saved', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    state.form.asr.api_key = 'failed-fixture-key'
    state.form.summary.trigger_messages = 999
    vi.mocked(settingsClient.save).mockRejectedValueOnce(new Error('mixed save failed'))
    state.debouncedSave({ asr: { api_key: 'failed-fixture-key' }, summary: { trigger_messages: 999 } })
    await state.flushPendingSave()
    const removal = deferred<any>()
    vi.mocked(settingsClient.deleteSetting).mockReturnValueOnce(removal.promise)
    vi.mocked(settingsClient.save).mockResolvedValueOnce({ status: 'ok', normalized_settings: { ...saved, summary: { ...saved.summary, trigger_messages: 100 } } })
    const clearing = state.clearAsrApiKey()
    for (let i = 0; i < 18; i += 1) await Promise.resolve()
    expect(settingsClient.save).toHaveBeenLastCalledWith({ summary: { trigger_messages: 999 } })
    expect(state.saveError.value).toContain('mixed save failed')
    removal.resolve({ status: 'ok' })
    await clearing
    expect(state.updateRequest.error).toBeNull()
  })

  it('rechecks shared saves before acquiring an admin mutation slot', async () => {
    const saving = deferred<any>()
    const writing = deferred<any>()
    let activeWrites = 0
    let maxConcurrentWrites = 0
    vi.mocked(settingsClient.save).mockImplementationOnce(async () => {
      maxConcurrentWrites = Math.max(maxConcurrentWrites, ++activeWrites)
      try { return await saving.promise } finally { activeWrites -= 1 }
    })
    vi.mocked(settingsClient.setSetting).mockImplementationOnce(async () => {
      maxConcurrentWrites = Math.max(maxConcurrentWrites, ++activeWrites)
      try { return await writing.promise } finally { activeWrites -= 1 }
    })
    vi.mocked(settingsClient.history).mockResolvedValue({ history: [] } as any)
    state.setKey.value = 'summary.trigger_messages'
    state.setValueJson.value = '41'
    const adminWrite = state.writeSettingKey()
    // Let the empty flush finish, then start another panel's save before lock acquisition.
    await Promise.resolve()
    const secondScope = effectScope()
    try {
      const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
      second.debouncedSave({ summary: { trigger_messages: 50 } })
      const flushing = second.flushPendingSave()
      for (let i = 0; i < 12; i += 1) await Promise.resolve()
      saving.resolve({ status: 'ok', normalized_settings: saved })
      writing.resolve({ status: 'ok' })
      await Promise.all([adminWrite, flushing])
      expect(settingsClient.save).toHaveBeenCalledOnce()
      expect(settingsClient.setSetting).toHaveBeenCalledOnce()
      expect(maxConcurrentWrites).toBe(1)
    } finally {
      saving.resolve({ status: 'ok', normalized_settings: saved })
      writing.resolve({ status: 'ok' })
      secondScope.stop()
    }
  })

  it('preserves a later unsubmitted draft over an older queued patch during normalized readback', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    const first = deferred<any>()
    const second = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    state.form.asr.base_url = 'submitted-first'
    state.debouncedSave({ asr: { base_url: 'submitted-first' } })
    const flushing = state.flushPendingSave()
    state.form.asr.base_url = 'queued-second'
    state.debouncedSave({ asr: { base_url: 'queued-second' } })
    state.form.asr.base_url = 'typed-later'
    first.resolve({ status: 'ok', normalized_settings: { ...saved, asr: { ...saved.asr, base_url: 'normalized-first' } } })
    for (let i = 0; i < 12; i += 1) await Promise.resolve()
    const draftAfterFirstReadback = state.form.asr.base_url
    second.resolve({ status: 'ok', normalized_settings: { ...saved, asr: { ...saved.asr, base_url: 'queued-second' } } })
    await flushing
    expect(settingsClient.save).toHaveBeenLastCalledWith({ asr: { base_url: 'queued-second' } })
    expect.soft(draftAfterFirstReadback).toBe('typed-later')
    expect(state.form.asr.base_url).toBe('typed-later')
  })

  it('preserves another panel\'s local same-field draft when a shared save completes', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    const response = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(response.promise)
    state.form.asr.base_url = 'owner-write'
    state.debouncedSave({ asr: { base_url: 'owner-write' } })
    const flushing = state.flushPendingSave()
    const secondScope = effectScope()
    try {
      const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
      second.settings.value = structuredClone(saved)
      second.hydratePreservingDraft(second.captureFormDraft(), saved)
      second.form.asr.base_url = 'later-local-draft'
      response.resolve({ status: 'ok', normalized_settings: { ...saved, asr: { ...saved.asr, base_url: 'owner-write' } } })
      await flushing
      await nextTick()
      expect(second.settings.value.asr.base_url).toBe('owner-write')
      expect(second.form.asr.base_url).toBe('later-local-draft')
    } finally {
      response.resolve({ status: 'ok', normalized_settings: saved })
      secondScope.stop()
    }
  })

  it('keeps a completed admin write when an older mount read arrives late', async () => {
    const oldSnapshot = structuredClone(saved)
    const read = deferred<any>()
    const secondScope = effectScope()
    try {
      const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
      vi.mocked(settingsClient.load).mockReturnValueOnce(read.promise)
      const mounting = vi.mocked(onMounted).mock.calls.at(-1)![0]!()
      state.setKey.value = 'summary.trigger_messages'
      state.setValueJson.value = '41'
      vi.mocked(settingsClient.setSetting).mockImplementationOnce(async () => {
        saved.summary.trigger_messages = 41
        return { status: 'ok' }
      })
      vi.mocked(settingsClient.history).mockResolvedValue({ history: [] } as any)
      await state.writeSettingKey()
      const writerValue = state.form.summary.trigger_messages
      read.resolve(oldSnapshot)
      await mounting
      expect(writerValue).toBe(41)
      expect.soft(second.settings.value.summary.trigger_messages).toBe(41)
      expect(second.form.summary.trigger_messages).toBe(41)
    } finally {
      read.resolve(oldSnapshot)
      secondScope.stop()
    }
  })

  it('does not revive deleted credentials in an existing panel when later drafts are saved', async () => {
    saved.asr.api_key = '********'
    state.settings.value = structuredClone(saved)
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    const secondScope = effectScope()
    try {
      const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
      second.settings.value = structuredClone(saved)
      second.hydratePreservingDraft(second.captureFormDraft(), saved)
      expect(second.asrApiKeyStored.value).toBe(true)
      second.form.asr.api_key = 'stale-local-credential'
      second.form.asr.base_url = 'unrelated-local-draft'
      vi.mocked(settingsClient.deleteSetting).mockImplementationOnce(async () => {
        saved.asr.api_key = ''
        return { status: 'ok' }
      })
      await state.clearAsrApiKey()
      await nextTick()
      const afterDelete = { draft: second.form.asr.api_key, stored: second.asrApiKeyStored.value }
      vi.mocked(settingsClient.save).mockImplementationOnce(async (patch) => {
        Object.assign(saved.asr, patch.asr)
        return { status: 'ok', normalized_settings: structuredClone(saved) }
      })
      second.debouncedSave({ asr: { base_url: second.form.asr.base_url } })
      await second.flushPendingSave()
      await nextTick()
      expect(settingsClient.deleteSetting).toHaveBeenCalledWith('asr.api_key')
      expect.soft(afterDelete).toEqual({ draft: '', stored: false })
      expect.soft(second.form.asr.api_key).toBe('')
      expect.soft(second.asrApiKeyStored.value).toBe(false)
      expect(second.settings.value.asr.api_key).toBe('')
      expect(second.form.asr.base_url).toBe('unrelated-local-draft')
      expect(vi.mocked(settingsClient.save).mock.calls.every(([patch]) => !patch.asr?.api_key)).toBe(true)
    } finally { secondScope.stop() }
  })

  it('does not revive deleted credentials in a new panel when an older mount read arrives late', async () => {
    saved.asr.api_key = '********'
    state.settings.value = structuredClone(saved)
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    const oldSnapshot = structuredClone(saved)
    const removal = deferred<any>()
    const read = deferred<any>()
    vi.mocked(settingsClient.deleteSetting).mockImplementationOnce(async () => {
      const result = await removal.promise
      saved.asr.api_key = ''
      return result
    })
    const clearing = state.clearAsrApiKey()
    for (let i = 0; i < 12; i += 1) await Promise.resolve()
    const secondScope = effectScope()
    try {
      const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
      vi.mocked(settingsClient.load).mockReturnValueOnce(read.promise)
      const mounting = vi.mocked(onMounted).mock.calls.at(-1)![0]!()
      second.form.asr.base_url = 'new-panel-draft'
      removal.resolve({ status: 'ok' })
      await clearing
      read.resolve(oldSnapshot)
      await mounting
      expect.soft(second.settings.value.asr.api_key).toBe('')
      expect.soft(second.form.asr.api_key).toBe('')
      expect.soft(second.asrApiKeyStored.value).toBe(false)
      expect.soft(second.form.asr.base_url).toBe('new-panel-draft')
      vi.mocked(settingsClient.save).mockImplementationOnce(async (patch) => {
        Object.assign(saved.asr, patch.asr)
        return { status: 'ok', normalized_settings: structuredClone(saved) }
      })
      second.debouncedSave({ asr: { base_url: second.form.asr.base_url } })
      await second.flushPendingSave()
      await nextTick()
      expect.soft(second.form.asr.api_key).toBe('')
      expect(second.asrApiKeyStored.value).toBe(false)
      expect(vi.mocked(settingsClient.save).mock.calls.every(([patch]) => !patch.asr?.api_key)).toBe(true)
    } finally {
      removal.resolve({ status: 'ok' })
      read.resolve(oldSnapshot)
      secondScope.stop()
    }
  })
})

describe('settings panel operation boundaries', () => {
  it('retains a failed save after unmount and exposes it to a new panel for retry', async () => {
    const response = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(response.promise)
    state.form.summary.trigger_messages = 37
    state.debouncedSave({ summary: { trigger_messages: 37 } })
    const flushing = state.flushPendingSave()
    await Promise.resolve()
    vi.mocked(onBeforeUnmount).mock.calls[0]![0]!()
    vi.mocked(onUnmounted).mock.calls[0]![0]!()
    scope.stop()
    scope = effectScope()
    const replacement: any = scope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
    response.resolve(undefined)
    expect(await flushing).toBe(false)
    expect(replacement.failedSavePatch.value).toEqual({ summary: { trigger_messages: 37 } })
    expect(ElMessage.error).toHaveBeenCalled()
    await vi.mocked(onMounted).mock.calls.at(-1)![0]!()
    expect(replacement.form.summary.trigger_messages).toBe(37)
    vi.mocked(settingsClient.save).mockResolvedValue({ status: 'ok', normalized_settings: { ...saved, summary: { ...saved.summary, trigger_messages: 37 } } })
    replacement.retryFailedSave()
    await replacement.waitForSaveIdle()
    expect(replacement.failedSavePatch.value).toBeNull()
    expect(settingsClient.save).toHaveBeenCalledTimes(2)
    expect(settingsClient.save).toHaveBeenLastCalledWith({ summary: { trigger_messages: 37 } })
  })

  it('serializes saves from two panel instances and keeps the latest queued edit', async () => {
    const response = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(response.promise)
    state.debouncedSave({ summary: { trigger_messages: 30 } })
    const flushing = state.flushPendingSave()
    await Promise.resolve()
    const secondScope = effectScope()
    const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
    second.debouncedSave({ summary: { trigger_messages: 40 } })
    await vi.advanceTimersByTimeAsync(1000)
    expect(settingsClient.save).toHaveBeenCalledTimes(1)
    response.resolve({ status: 'ok', normalized_settings: saved })
    expect(await flushing).toBe(true)
    expect(settingsClient.save).toHaveBeenCalledTimes(2)
    expect(settingsClient.save).toHaveBeenLastCalledWith({ summary: { trigger_messages: 40 } })
    secondScope.stop()
  })

  it('keeps a completed shared save when an older mount read arrives late', async () => {
    const response = deferred<any>()
    const read = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(response.promise)
    state.debouncedSave({ summary: { trigger_messages: 41 } })
    const flushing = state.flushPendingSave()
    const secondScope = effectScope()
    const second: any = secondScope.run(() => (SettingsPanel as any).setup({}, { expose: vi.fn() }))
    vi.mocked(settingsClient.load).mockReturnValueOnce(read.promise)
    const mounting = vi.mocked(onMounted).mock.calls.at(-1)![0]!()
    const normalized = { ...saved, summary: { ...saved.summary, trigger_messages: 41 } }
    response.resolve({ status: 'ok', normalized_settings: normalized })
    await flushing
    read.resolve(saved)
    await mounting
    expect(second.form.summary.trigger_messages).toBe(41)
    expect(second.settings.value.summary.trigger_messages).toBe(41)
    secondScope.stop()
  })

  it('loads global runtime failures on the summary page and retries the frozen target without saving', async () => {
    state.route.query.section = 'summary'
    vi.mocked(settingsClient.runtimeStatus).mockResolvedValue({ sections: { svc: { state: 'failed', target_revision: 7, applied_revision: null } } })
    await vi.mocked(onMounted).mock.calls[0]![0]!()
    await nextTick()
    expect(state.runtimeReload.value.sections.svc.state).toBe('failed')
    vi.mocked(settingsClient.retryRuntime).mockResolvedValue({ sections: { svc: { state: 'applied', target_revision: 7, applied_revision: 7 } } })
    await state.retryRuntimeApplication({ svc: 7 })
    expect(settingsClient.retryRuntime).toHaveBeenCalledExactlyOnceWith({ svc: 7 })
    expect(settingsClient.save).not.toHaveBeenCalled()
    expect(state.runtimeReload.value.sections.svc.state).toBe('applied')
  })

  it('retains only unfinished resources for a partial retry', async () => {
    const status = { ...emptyResources(), tts: { ready: true }, sherpa: { ready: false, state: 'partial' } }
    await state.runResourceCommand('test', async () => ({ success: false, errorCode: 'network_timeout', message: 'partial failure', status }), ['tts', 'sherpa'])
    expect(state.selectedResourceIds.value).toEqual(['sherpa'])
    expect(state.resourceMessageType.value).toBe('warning')
    expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('waits for the memory job terminal state and handles cancellation without success', async () => {
    const job = { job_id: 'job-1', state: 'queued', phase: 'prepare', processed_count: 0, total_count: 2 }
    vi.mocked(memoryClient.getIndexStatus).mockResolvedValue({ backend: 'sqlite', count: 0, status: 'ok' })
    vi.mocked(memoryClient.rebuildIndex).mockResolvedValue({ status: 'ok', index_status: 'queued', job } as any)
    await state.handleRebuildMemoryIndex()
    expect(state.memoryIndexWorking.value).toBe(true)
    expect(ElMessage.success).not.toHaveBeenCalled()
    vi.mocked(memoryClient.cancelIndexRebuild).mockResolvedValue({ status: 'ok', job: { ...job, state: 'cancelling' } } as any)
    await state.cancelMemoryRebuild()
    expect(state.memoryRebuildJob.value.state).toBe('cancelling')
    vi.mocked(memoryClient.getIndexRebuildJob).mockResolvedValue({ status: 'ok', job: { ...job, state: 'cancelled' } } as any)
    await state.refreshMemoryRebuild()
    expect(state.memoryIndexWorking.value).toBe(false)
    expect(ElMessage.success).not.toHaveBeenCalled()
    state.applyMemoryRebuildJob({ ...job, job_id: 'job-2', state: 'completed', processed_count: 2 })
    expect(ElMessage.success).toHaveBeenCalledOnce()
  })

  it('shows a backend wait failure and never starts a rebuild', async () => {
    vi.mocked(memoryClient.getIndexStatus).mockRejectedValue(new Error('backend unavailable'))
    await state.handleRebuildMemoryIndex()
    expect(state.memoryRebuildError.value).toBe(t('settings.messages.memoryRebuildFailed'))
    expect(state.memoryIndexWorking.value).toBe(false)
    expect(memoryClient.rebuildIndex).not.toHaveBeenCalled()
  })

  it('blocks every probe after a failed flush', async () => {
    vi.mocked(settingsClient.save).mockRejectedValue(new Error('save failed'))
    state.form.llm.base_url = 'http://localhost:1234/v1'
    state.form.llm.model = 'model'
    state.form.tts.genie_character = 'voice'
    state.debouncedSave({ summary: { trigger_messages: 30 } })
    await state.handleTestLlm()
    await state.handleTestTts()
    await state.handleTestSvc()
    await state.discoverLlmModels({ manual: true })
    await state.applyLocalAsrDiscovery()
    await state.queueTtsWarmup()
    expect(settingsClient.testLlm).not.toHaveBeenCalled()
    expect(settingsClient.testTts).not.toHaveBeenCalled()
    expect(settingsClient.testSvc).not.toHaveBeenCalled()
    expect(settingsClient.listLlmModels).not.toHaveBeenCalled()
    expect(settingsClient.discoverLocal).not.toHaveBeenCalled()
    expect(settingsClient.warmupTts).not.toHaveBeenCalled()
  })

  it('preserves drafts dirty before and during a normalized save', async () => {
    state.hydratePreservingDraft(state.captureFormDraft())
    state.form.asr.base_url = 'draft before save'
    state.form.summary.trigger_messages = 999
    const readback = deferred<any>()
    vi.mocked(settingsClient.load).mockReturnValueOnce(readback.promise)
    state.debouncedSave({ summary: { trigger_messages: 999 } })
    const saving = state.flushPendingSave()
    await Promise.resolve()
    state.form.memory.qdrant_url = 'draft during save'
    readback.resolve({ ...saved, summary: { ...saved.summary, trigger_messages: 100 } })
    expect(await saving).toBe(true)
    expect(state.form.summary.trigger_messages).toBe(100)
    expect(state.form.asr.base_url).toBe('draft before save')
    expect(state.form.memory.qdrant_url).toBe('draft during save')
  })

  it('normalizes the explicitly written key while preserving unrelated drafts', async () => {
    state.hydratePreservingDraft(state.captureFormDraft())
    state.form.summary.trigger_messages = 999
    state.form.memory.qdrant_url = 'unsent draft'
    state.setKey.value = 'summary.trigger_messages'
    state.setValueJson.value = '999'
    saved.summary.trigger_messages = 100
    vi.mocked(settingsClient.setSetting).mockResolvedValue({ status: 'ok' })
    vi.mocked(settingsClient.history).mockResolvedValue({ history: [] } as any)
    await state.writeSettingKey()
    expect(settingsClient.setSetting).toHaveBeenCalledWith('summary.trigger_messages', 999)
    expect(state.form.summary.trigger_messages).toBe(100)
    expect(state.form.memory.qdrant_url).toBe('unsent draft')
    expect(state.keyError.value).toBe('')
  })

  it('keeps credential removal serialized after an older save and strips queued copies', async () => {
    const olderSave = deferred<any>()
    const removal = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(olderSave.promise)
    vi.mocked(settingsClient.deleteSetting).mockReturnValueOnce(removal.promise)
    state.form.asr.api_key = 'old secret'
    state.debouncedSave({ asr: { api_key: 'old secret' } })
    const saving = state.flushPendingSave()
    await Promise.resolve()
    const clearing = state.clearAsrApiKey()
    expect(settingsClient.deleteSetting).not.toHaveBeenCalled()
    olderSave.resolve({ status: 'ok' })
    await saving
    for (let i = 0; i < 12; i += 1) await Promise.resolve()
    expect(settingsClient.deleteSetting).toHaveBeenCalledWith('asr.api_key')
    state.debouncedSave({ asr: { api_key: 'old secret', model: 'new model' } })
    expect(state.pendingSavePatch.value.asr).not.toHaveProperty('api_key')
    removal.resolve({ status: 'ok' })
    await clearing
    expect(state.form.asr.api_key).toBe('')
    await state.flushPendingSave()
    expect(vi.mocked(settingsClient.save).mock.calls.slice(1).every(([patch]) => !patch.asr || !('api_key' in patch.asr))).toBe(true)
  })

  it('does not apply discovery over later edits or resubmit hidden credentials', async () => {
    const discovery = deferred<any>()
    vi.mocked(settingsClient.discoverLocal).mockReturnValueOnce(discovery.promise)
    const detecting = state.applyLocalAsrDiscovery()
    for (let i = 0; i < 8; i += 1) await Promise.resolve()
    state.form.asr.base_url = 'new draft'
    discovery.resolve({ asr: [{ ok: true, base_url: 'http://discovered', provider: 'funasr-service' }] })
    await detecting
    expect(state.form.asr.base_url).toBe('new draft')
    state.form.tts.api_key = 'old cloud secret'
    state.form.tts.provider = 'genie-tts'
    state.saveActiveTtsPatch({ lang: 'en' })
    expect(state.pendingSavePatch.value.tts).not.toHaveProperty('api_key')
  })

  it('does not turn an unconfirmed cancellation into a finished state', async () => {
    state.activeResourceIds.value = ['tts']
    vi.mocked(resourceClient.cancel).mockResolvedValue({ success: true, cancelled: ['tts'], status: emptyResources() } as any)
    vi.mocked(resourceClient.status).mockRejectedValue(new Error('status unavailable'))
    await state.cancelActiveResourceDownloads()
    state.activeResourceIds.value = []
    state.settleResourceCancellation()
    expect(state.cancellingResourceIds.value).toEqual(['tts'])
    expect(state.resourceMessageType.value).toBe('error')
  })

  it('confirms current status after a late cancellation ACK instead of restoring old progress', async () => {
    const cancellation = deferred<any>()
    state.activeResourceIds.value = ['tts']
    vi.mocked(resourceClient.cancel).mockReturnValueOnce(cancellation.promise)
    const cancelling = state.cancelActiveResourceDownloads()
    state.activeResourceIds.value = []
    cancellation.resolve({ success: true, cancelled: ['tts'], status: { ...emptyResources(), activeDownloads: [{ resourceId: 'tts', phase: 'cancelling' }] } })
    await cancelling
    expect(resourceClient.status).toHaveBeenCalledOnce()
    expect(state.activeDownloadProgress.value).toEqual([])
    expect(state.cancellingResourceIds.value).toEqual([])
  })
})


describe('settings cached draft and runtime application', () => {
  it('saves one LLM field without serializing stale profiles', async () => {
    state.llmProfiles.openai = { ...state.snapshotLlmProfile(), provider: 'openai', model: 'stale-other' }
    state.saveLlmField('temperature', 0.4)
    await state.flushPendingSave()
    expect(settingsClient.save).toHaveBeenCalledWith({ llm: { temperature: 0.4, profiles: { custom: { temperature: 0.4 } } } })
  })

  it('refreshes cached settings and keeps dirty fields and later edits', async () => {
    state.hydratePreservingDraft(state.captureFormDraft(), saved)
    state.form.llm.model = 'unsaved-local'
    const response = deferred<any>()
    vi.mocked(settingsClient.load).mockReturnValueOnce(response.promise)
    const refresh = state.refreshActivatedSettings()
    state.form.llm.timeout = 88
    response.resolve({ ...saved, llm: { ...saved.llm, model: 'external', temperature: 0.25, timeout: 50 } })
    await refresh
    expect(state.form.llm.model).toBe('unsaved-local')
    expect(state.form.llm.timeout).toBe(88)
    expect(state.form.llm.temperature).toBe(0.25)
  })

  it('does not report config acknowledgement as service application', () => {
    state.recordSettingsSaved({ runtime_applied: ['llm'], runtime_changed: ['llm'], runtime_reload: { sections: { llm: { state: 'pending', target_revision: 1, applied_revision: null } } } })
    expect(state.saveStatusDetail.value).toContain('llm')
    expect(state.lastApplied.value).toEqual([])
  })
})


it('waits for an in-flight save before refreshing a cached settings page', async () => {
  const saving = deferred<any>()
  vi.mocked(settingsClient.save).mockReturnValueOnce(saving.promise)
  state.debouncedSave({ llm: { temperature: 0.4 } })
  const flush = state.flushPendingSave()
  const refreshing = state.refreshActivatedSettings()
  expect(settingsClient.load).not.toHaveBeenCalled()
  saved.llm.temperature = 0.4
  saving.resolve({ status: 'ok' })
  await flush
  await refreshing
  expect(state.failedSavePatch.value).toBeNull()
  expect(state.form.llm.temperature).toBe(0.4)
})


it('keeps old service readiness separate from a pending or failed target', () => {
  state.llmStatus.value = { available: true, last_preconnect_ok: true }
  state.ttsStatus.value = { available: true, warmup_done: true }
  state.acceptRuntimeStatus({ sections: {
    llm: { state: 'pending', target_revision: 7, applied_revision: 6 },
    tts: { state: 'failed', target_revision: 8, applied_revision: 6 },
  } })
  expect(state.llmRuntimeTagType.value).toBe('warning')
  expect(state.ttsRuntimeTagType.value).toBe('danger')
  expect(state.llmRuntimeLabel.value).not.toBe(t('settings.llm.runtime.ready'))
  expect(state.ttsRuntimeLabel.value).not.toBe(t('settings.tts.status.ready'))
})


describe('LLM generation capabilities', () => {
  it('displays provider bounds without overwriting a saved profile value', () => {
    state.llmProviderPreset.value = 'claude'
    state.form.llm.model = 'claude-3-5-sonnet'
    state.form.llm.temperature = 1.8
    expect(state.llmParameterValue('temperature')).toBe(1)
    expect(state.form.llm.temperature).toBe(1.8)
    state.updateLlmParameter('temperature', 0.6)
    expect(state.llmParameterValue('temperature')).toBe(0.6)
    state.updateLlmParameter('temperature', null)
    expect(state.form.llm.temperature).toBe(0.6)
  })

  it('preserves hidden parameter values when applying model recommendations', () => {
    state.llmProviderPreset.value = 'chatgpt'
    state.form.llm.model = 'gpt-5.2'
    state.form.llm.temperature = 0.7
    state.form.llm.min_p = 0.2
    expect(state.llmGenerationCapabilities.value.parameters).toEqual({})
    state.applyRecommendedLlmSettings()
    expect(state.form.llm.temperature).toBe(0.7)
    expect(state.form.llm.min_p).toBe(0.2)
    state.form.llm.model = 'gpt-4o'
    expect(state.llmGenerationCapabilities.value.parameters.temperature).toBeDefined()
    expect(state.llmParameterValue('temperature')).toBe(0.7)
  })

  it('keeps zero as the default top-k rather than enabling a one-token candidate pool', () => {
    state.llmProviderPreset.value = 'gemini'
    state.form.llm.model = 'gemini-2.5-flash'
    state.form.llm.top_k = 0
    expect(state.llmParameterValue('top_k')).toBe(0)
    state.applyRecommendedLlmSettings()
    expect(state.form.llm.top_k).toBe(0)
  })
})


it.each(['failed', 'applying', 'applied'])('tracks the actual %s runtime target independently of save status', (phase) => {
  state.runtimeReload.value = { sections: { svc: { state: phase, target_revision: 7, applied_revision: phase === 'applied' ? 7 : null } } }
  state.syncRuntimeReloadDisplay()
  expect(state.runtimeFailedSections.value).toEqual(phase === 'failed' ? ['svc'] : [])
  expect(state.lastRuntimePending.value).toEqual(phase === 'applying' ? ['svc'] : [])
  expect(state.lastApplied.value).toEqual(phase === 'applied' ? ['svc'] : [])
})


describe('settings loading and save latency', () => {
  it('loads core settings immediately on access without waiting for token or bindings', async () => {
    const token = deferred<any>()
    const bindings = deferred<any>()
    vi.mocked(settingsClient.backendTokenStatus).mockReturnValue(token.promise)
    state.inputBindingsStore.load.mockReturnValue(bindings.promise)
    state.route.query.section = 'access'
    state.settings.value = null
    const mounting = vi.mocked(onMounted).mock.calls[0][0]()
    expect(settingsClient.load).toHaveBeenCalledOnce()
    await mounting
    expect(state.settings.value).toEqual(saved)
    expect(state.form.llm.model).toBe(saved.llm.model)
    expect(state.inputBindingsStore.load).not.toHaveBeenCalled()
    expect(settingsClient.metadata).not.toHaveBeenCalled()
    expect(resourceClient.status).not.toHaveBeenCalled()
    expect(resourceClient.storageStatus).not.toHaveBeenCalled()
    expect(settingsClient.llmStatus).not.toHaveBeenCalled()
    expect(settingsClient.ttsStatus).not.toHaveBeenCalled()
    expect(settingsClient.ttsCharacters).not.toHaveBeenCalled()
    expect(settingsClient.warmupTts).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(2000)
    expect(settingsClient.listLlmModels).not.toHaveBeenCalled()
    token.resolve(null)
    bindings.resolve(null)
  })

  it('distinguishes pending edits, sends at 350ms, and merges fields', async () => {
    const saving = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(saving.promise)
    state.debouncedSave({ summary: { trigger_messages: 20 } })
    expect(state.saveStatusLabel.value).toBe(t('settings.status.pending'))
    await vi.advanceTimersByTimeAsync(100)
    state.debouncedSave({ summary: { max_tokens: 100 } })
    await vi.advanceTimersByTimeAsync(349)
    expect(settingsClient.save).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(settingsClient.save).toHaveBeenCalledExactlyOnceWith({ summary: { trigger_messages: 20, max_tokens: 100 } })
    expect(state.saveStatusLabel.value).toBe(t('settings.status.saving'))
    saving.resolve({ status: 'ok', normalized_settings: saved })
    await vi.advanceTimersByTimeAsync(0)
    expect(state.saveStatusLabel.value).toBe(t('settings.status.saved'))
    expect(settingsClient.load).not.toHaveBeenCalled()
  })

  it('sends within 1000ms even while edits continue every 200ms', async () => {
    state.debouncedSave({ summary: { trigger_messages: 1 } })
    for (let i = 2; i <= 5; i++) {
      await vi.advanceTimersByTimeAsync(200)
      state.debouncedSave({ summary: { trigger_messages: i } })
    }
    await vi.advanceTimersByTimeAsync(199)
    expect(settingsClient.save).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(settingsClient.save).toHaveBeenCalledExactlyOnceWith({ summary: { trigger_messages: 5 } })
  })

  it('starts the next merged save immediately after the in-flight request settles', async () => {
    const first = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(first.promise)
    state.debouncedSave({ summary: { trigger_messages: 20 } })
    const flush = state.flushPendingSave()
    state.debouncedSave({ summary: { trigger_messages: 30 } })
    state.debouncedSave({ summary: { max_tokens: 100 } })
    expect(settingsClient.save).toHaveBeenCalledOnce()
    first.resolve({ status: 'ok', normalized_settings: saved })
    expect(await flush).toBe(true)
    expect(settingsClient.save).toHaveBeenCalledTimes(2)
    expect(settingsClient.save).toHaveBeenLastCalledWith({ summary: { trigger_messages: 30, max_tokens: 100 } })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('parks a failed save with later edits and retries the merged patch', async () => {
    const first = deferred<any>()
    vi.mocked(settingsClient.save).mockReturnValueOnce(first.promise)
    state.debouncedSave({ summary: { trigger_messages: 20 } })
    const flush = state.flushPendingSave()
    state.debouncedSave({ summary: { trigger_messages: 30 } })
    first.resolve(undefined)
    expect(await flush).toBe(false)
    expect(state.failedSavePatch.value).toEqual({ summary: { trigger_messages: 30 } })
    await vi.advanceTimersByTimeAsync(1000)
    expect(settingsClient.save).toHaveBeenCalledOnce()
    state.retryFailedSave()
    expect(await state.flushPendingSave()).toBe(true)
    expect(settingsClient.save).toHaveBeenLastCalledWith({ summary: { trigger_messages: 30 } })
  })

  it('loads system bindings on demand and admin data only when expanded', async () => {
    state.activeSection.value = 'system'
    await nextTick()
    expect(state.inputBindingsStore.load).toHaveBeenCalledOnce()
    expect(settingsClient.metadata).not.toHaveBeenCalled()
    vi.mocked(settingsClient.metadata).mockResolvedValue({})
    vi.mocked(settingsClient.history).mockResolvedValue({ history: [], count: 0 })
    state.adminCollapseNames.value = ['metadata']
    await nextTick()
    expect(settingsClient.metadata).toHaveBeenCalledOnce()
  })

  it('cancels automatic model discovery when switching away from LLM', async () => {
    state.form.llm.base_url = 'http://localhost:1234/v1'
    state.scheduleLlmModelDiscovery({ manual: false })
    state.activeSection.value = 'access'
    await nextTick()
    await vi.advanceTimersByTimeAsync(1000)
    expect(settingsClient.listLlmModels).not.toHaveBeenCalled()
    expect(settingsClient.ttsStatus).not.toHaveBeenCalled()
    expect(resourceClient.status).not.toHaveBeenCalled()
  })

  it('never warms a voice page that became hidden while status was loading', async () => {
    const status = deferred<any>()
    state.form.tts.genie_character = 'voice'
    vi.mocked(settingsClient.ttsStatus).mockReturnValueOnce(status.promise)
    vi.mocked(settingsClient.ttsCharacters).mockResolvedValue({ characters: [] } as any)
    state.activeSection.value = 'voice'
    await nextTick()
    expect(settingsClient.ttsStatus).toHaveBeenCalledOnce()
    state.activeSection.value = 'access'
    await nextTick()
    status.resolve({ available: true })
    await vi.advanceTimersByTimeAsync(2000)
    expect(settingsClient.warmupTts).not.toHaveBeenCalled()
  })

  it('does not start TTS probes from a runtime ACK while another page is visible', () => {
    state.recordSettingsSaved({ runtime_applied: ['tts'], runtime_reload: { sections: { tts: { state: 'applied', target_revision: 1, applied_revision: 1 } } } })
    expect(settingsClient.ttsStatus).not.toHaveBeenCalled()
  })

  it('keeps activation work scoped to access and suppresses hidden page work', async () => {
    state.route.query.section = 'access'
    vi.mocked(onActivated).mock.calls[0][0]()
    vi.mocked(onDeactivated).mock.calls[0][0]()
    document.hidden = true
    vi.mocked(onActivated).mock.calls[0][0]()
    await vi.advanceTimersByTimeAsync(1000)
    expect(settingsClient.load).not.toHaveBeenCalled()
    document.hidden = false
    state.handleResourceProgressVisibility()
    await vi.advanceTimersByTimeAsync(0)
    expect(settingsClient.load).toHaveBeenCalledOnce()
    expect(settingsClient.backendTokenStatus).toHaveBeenCalledOnce()
    expect(settingsClient.metadata).not.toHaveBeenCalled()
    expect(settingsClient.ttsStatus).not.toHaveBeenCalled()
    expect(resourceClient.status).not.toHaveBeenCalled()
  })
})


it('does not run a status scan after resource progress completes on a hidden page', async () => {
  const progress = deferred<any>()
  state.activeSection.value = 'resources'
  vi.mocked(resourceClient.storageStatus).mockResolvedValue({ categories: [] } as any)
  await state.refreshActiveSection()
  await nextTick()
  vi.mocked(resourceClient.status).mockClear()
  state.resourceStatus.value = { ...emptyResources(), activeDownloads: [{ resourceId: 'tts', phase: 'downloading' }] }
  vi.mocked(resourceClient.progress).mockReturnValueOnce(progress.promise)
  const polling = state.pollResourceStatus()
  state.activeSection.value = 'access'
  await nextTick()
  progress.resolve({ activeDownloads: [] })
  await polling
  expect(resourceClient.status).not.toHaveBeenCalled()
})

it('does not start discovery after deactivation during a pending save flush', async () => {
  const saving = deferred<any>()
  vi.mocked(settingsClient.save).mockReturnValueOnce(saving.promise)
  state.form.llm.base_url = 'http://localhost:1234/v1'
  state.debouncedSave({ summary: { trigger_messages: 20 } })
  const discovering = state.discoverLlmModels({ manual: false })
  vi.mocked(onDeactivated).mock.calls[0][0]()
  saving.resolve({ status: 'ok', normalized_settings: saved })
  await discovering
  expect(settingsClient.listLlmModels).not.toHaveBeenCalled()
})

it('renders core system settings while native bindings are still pending', async () => {
  const bindings = deferred<any>()
  state.inputBindingsStore.load.mockReturnValueOnce(bindings.promise)
  state.route.query.section = 'system'
  state.settings.value = null
  await vi.mocked(onMounted).mock.calls[0][0]()
  expect(settingsClient.load).toHaveBeenCalledOnce()
  expect(state.inputBindingsStore.load).toHaveBeenCalledOnce()
  expect(state.settings.value).toEqual(saved)
  expect(settingsClient.backendTokenStatus).not.toHaveBeenCalled()
  expect(settingsClient.metadata).not.toHaveBeenCalled()
  bindings.resolve(null)
})

it('shows queued edits separately while a save is in flight', async () => {
  const saving = deferred<any>()
  vi.mocked(settingsClient.save).mockReturnValueOnce(saving.promise)
  state.debouncedSave({ summary: { trigger_messages: 20 } })
  const flush = state.flushPendingSave()
  state.debouncedSave({ summary: { trigger_messages: 30 } })
  expect(state.saveStatusLabel.value).toBe(t('settings.status.saving'))
  expect(state.saveStatusDetail.value).toBe(t('settings.status.savingQueued'))
  saving.resolve({ status: 'ok', normalized_settings: saved })
  await flush
})


it('reuses discovered models when returning to the same unchanged LLM configuration', async () => {
  state.form.llm.base_url = 'http://localhost:1234/v1'
  state.form.llm.model = 'local-model'
  vi.mocked(settingsClient.listLlmModels).mockResolvedValue({ ok: true, models: ['local-model'] })
  await state.discoverLlmModels({ manual: false })
  expect(settingsClient.listLlmModels).toHaveBeenCalledOnce()
  state.activeSection.value = 'access'
  await nextTick()
  state.activeSection.value = 'llm'
  await nextTick()
  await vi.advanceTimersByTimeAsync(1000)
  expect(settingsClient.listLlmModels).toHaveBeenCalledOnce()
  expect(state.llmModels.value).toEqual(['local-model'])
})


describe('connection feedback independent of runtime status', () => {
  it.each(['llm', 'tts'] as const)('reports %s test failure while its status GET is still pending', async (service) => {
    const pending = deferred<any>()
    const test = service === 'llm' ? settingsClient.testLlm : settingsClient.testTts
    const status = service === 'llm' ? settingsClient.llmStatus : settingsClient.ttsStatus
    vi.mocked(test).mockResolvedValue({ ok: false, message: 'provider rejected connection' })
    vi.mocked(status).mockReturnValue(pending.promise)
    const action = service === 'llm' ? state.handleTestLlm() : state.handleTestTts()
    await vi.advanceTimersByTimeAsync(0)
    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('provider rejected connection'))
    pending.resolve(null)
    await action
  })

  it('reports warmup failure while runtime status is still pending', async () => {
    const pending = deferred<any>()
    state.form.tts.provider = 'genie-tts'
    state.form.tts.genie_character = 'synthetic-ready-voice'
    vi.mocked(settingsClient.warmupTts).mockResolvedValue({ ok: false, queued: false, message: 'warmup refused' })
    vi.mocked(settingsClient.ttsStatus).mockReturnValue(pending.promise)
    const action = state.handleWarmupTts()
    await vi.advanceTimersByTimeAsync(0)
    expect(ElMessage.error).toHaveBeenCalledWith('warmup refused')
    pending.resolve(null)
    await action
  })
})


describe('TTS warmup concurrent status feedback', () => {
  beforeEach(() => {
    vi.mocked(settingsClient.warmupTts).mockReset()
    vi.mocked(settingsClient.ttsStatus).mockReset().mockResolvedValue(null as any)
  })

  it('shows the actual handleWarmupTts success after a newer GET supersedes its runtime', async () => {
    const warmup = deferred<any>()
    state.form.tts.provider = 'genie-tts'
    state.form.tts.genie_character = 'synthetic-ready-voice'
    vi.mocked(settingsClient.warmupTts).mockReturnValueOnce(warmup.promise)
    const newer = { available: false, provider: 'openai-compatible' }
    vi.mocked(settingsClient.ttsStatus).mockResolvedValue(newer)
    const action = state.handleWarmupTts()
    await vi.advanceTimersByTimeAsync(0)
    expect(settingsClient.warmupTts).toHaveBeenCalledOnce()
    await state.refreshTtsStatus()
    warmup.resolve({ ok: true, queued: true, runtime: { available: true, provider: 'genie-tts' } })
    await action
    expect(ElMessage.success).toHaveBeenCalledWith(t('settings.messages.ttsWarmupQueued'))
    expect(ElMessage.error).not.toHaveBeenCalled()
    expect(state.ttsStatus.value).toEqual(newer)
  })

  it.each(['before', 'after'] as const)('keeps a stale GET failure %s warmup ACK out of actual handleWarmupTts feedback', async order => {
    const status = deferred<any>()
    const refresh = deferred<any>()
    const warmup = deferred<any>()
    state.form.tts.provider = 'genie-tts'
    state.form.tts.genie_character = 'synthetic-ready-voice'
    vi.mocked(settingsClient.ttsStatus).mockReturnValueOnce(status.promise).mockReturnValueOnce(refresh.promise)
    vi.mocked(settingsClient.warmupTts).mockReturnValueOnce(warmup.promise)
    const loading = state.refreshTtsStatus()
    const action = state.handleWarmupTts()
    await vi.advanceTimersByTimeAsync(0)
    expect(settingsClient.warmupTts).toHaveBeenCalledOnce()
    const failOldGet = async () => {
      status.reject(new Error('stale TTS status failure'))
      await loading
      expect(state.ttsStatusRequest.error).toBeNull()
    }
    if (order === 'before') await failOldGet()
    const ready = { available: true, provider: 'genie-tts', warmup_done: true }
    warmup.resolve({ ok: true, queued: true, runtime: ready })
    await action
    if (order === 'after') await failOldGet()
    expect(ElMessage.success).toHaveBeenCalledWith(t('settings.messages.ttsWarmupQueued'))
    expect(ElMessage.error).not.toHaveBeenCalled()
    expect(state.ttsStatus.value).toEqual(ready)
    expect(state.ttsStatusRequest.error).toBeNull()
    expect(state.ttsStatusRequest.loading).toBe(true)
    refresh.resolve(ready)
    await vi.advanceTimersByTimeAsync(0)
    expect(state.ttsStatusRequest.loading).toBe(false)
  })
})
