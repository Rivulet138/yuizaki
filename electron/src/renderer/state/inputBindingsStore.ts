import { computed, reactive } from 'vue'
import {
  DEFAULT_INPUT_BINDINGS,
  mergeInputBindingSettings,
  mouseButtonLabel,
  normalizeInputBindingSettings,
  type InputBindingRegistrationStatus,
  type InputBindingSettings,
  type InputBindingSettingsPatch,
  type InputBindingSnapshot,
} from '@/../shared/input-bindings'

const emptyStatus = (): InputBindingRegistrationStatus => ({
  mouseHookAvailable: false,
  pushToTalkActive: false,
  keyboard: { interact: false, lock: false, openPanel: false, toggleVision: false, emergencyStop: false },
  errors: [],
})

const BROWSER_STORAGE_KEY = 'yuizaki.input-bindings.v1'
const BROWSER_SCOPE_STORAGE_KEY = 'yuizaki.input-bindings.browser-scope.v1'

export type BrowserInputAction = 'interact' | 'lock' | 'openPanel' | 'toggleVision' | 'emergencyStop' | 'startVoice' | 'stopVoice'

const readBrowserShortcutsEnabled = (): boolean => {
  try {
    return window.localStorage.getItem(BROWSER_SCOPE_STORAGE_KEY) !== 'disabled'
  } catch {
    return true
  }
}

const state = reactive({
  settings: structuredClone(DEFAULT_INPUT_BINDINGS) as InputBindingSettings,
  status: emptyStatus(),
  // Browser mode has no native global hook, but keyboard settings are still
  // useful and should survive reloads in the same browser profile.
  available: typeof window !== 'undefined' && !window.petApi?.inputBindings,
  browserFallback: typeof window !== 'undefined' && !window.petApi?.inputBindings,
  browserShortcutsEnabled: typeof window !== 'undefined' ? readBrowserShortcutsEnabled() : true,
  lastBrowserAction: null as BrowserInputAction | null,
  lastBrowserActionAt: 0,
  loading: false,
  error: '',
})

const browserSnapshot = (): InputBindingSnapshot => {
  let settings = structuredClone(DEFAULT_INPUT_BINDINGS) as InputBindingSettings
  try {
    const raw = window.localStorage.getItem(BROWSER_STORAGE_KEY)
    if (raw) settings = normalizeInputBindingSettings(JSON.parse(raw))
  } catch {
    // Use defaults when browser storage is unavailable or corrupt.
  }
  return {
    settings,
    status: {
      mouseHookAvailable: false,
      pushToTalkActive: false,
      keyboard: {
        interact: Boolean(settings.keyboard.interact),
        lock: Boolean(settings.keyboard.lock),
        openPanel: Boolean(settings.keyboard.openPanel),
        toggleVision: Boolean(settings.keyboard.toggleVision),
        emergencyStop: Boolean(settings.keyboard.emergencyStop),
      },
      errors: [],
    },
  }
}

const saveBrowserSettings = (settings: InputBindingSettings): void => {
  try {
    window.localStorage.setItem(BROWSER_STORAGE_KEY, JSON.stringify(settings))
  } catch {
    state.error = '浏览器无法保存快捷键设置'
  }
}

const saveBrowserShortcutsEnabled = (enabled: boolean): void => {
  try {
    window.localStorage.setItem(BROWSER_SCOPE_STORAGE_KEY, enabled ? 'enabled' : 'disabled')
  } catch {
    state.error = '浏览器无法保存本页输入开关'
  }
}

const applySnapshot = (snapshot: InputBindingSnapshot): void => {
  state.settings = structuredClone(snapshot.settings)
  state.status = structuredClone(snapshot.status)
  state.available = true
  state.error = ''
}

const load = async (): Promise<InputBindingSnapshot | null> => {
  const api = window.petApi?.inputBindings
  if (!api) {
    const snapshot = browserSnapshot()
    applySnapshot(snapshot)
    state.browserFallback = true
    state.browserShortcutsEnabled = readBrowserShortcutsEnabled()
    return snapshot
  }
  state.loading = true
  try {
    const snapshot = await api.get()
    applySnapshot(snapshot)
    return snapshot
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
    return null
  } finally {
    state.loading = false
  }
}

const update = async (patch: InputBindingSettingsPatch): Promise<InputBindingSnapshot | null> => {
  const api = window.petApi?.inputBindings
  if (!api) {
    const settings = mergeInputBindingSettings(state.settings, patch)
    saveBrowserSettings(settings)
    const snapshot = browserSnapshot()
    applySnapshot(snapshot)
    state.browserFallback = true
    state.browserShortcutsEnabled = readBrowserShortcutsEnabled()
    return snapshot
  }
  state.loading = true
  try {
    const snapshot = await api.update(patch)
    applySnapshot(snapshot)
    return snapshot
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
    throw error
  } finally {
    state.loading = false
  }
}

const reset = async (): Promise<InputBindingSnapshot | null> => {
  const api = window.petApi?.inputBindings
  if (!api) {
    saveBrowserSettings(structuredClone(DEFAULT_INPUT_BINDINGS))
    const snapshot = browserSnapshot()
    applySnapshot(snapshot)
    state.browserFallback = true
    state.browserShortcutsEnabled = readBrowserShortcutsEnabled()
    return snapshot
  }
  state.loading = true
  try {
    const snapshot = await api.reset()
    applySnapshot(snapshot)
    return snapshot
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
    throw error
  } finally {
    state.loading = false
  }
}

const setBrowserShortcutsEnabled = (enabled: boolean): void => {
  state.browserShortcutsEnabled = Boolean(enabled)
  saveBrowserShortcutsEnabled(state.browserShortcutsEnabled)
}

const markBrowserAction = (action: BrowserInputAction): void => {
  state.lastBrowserAction = action
  state.lastBrowserActionAt = Date.now()
}

export const useInputBindingsStore = () => ({
  state,
  load,
  update,
  reset,
  setBrowserShortcutsEnabled,
  markBrowserAction,
  pushToTalkLabel: computed(() => `按住${mouseButtonLabel(state.settings.pushToTalk.mouseButton)}`),
})
