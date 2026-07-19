import { computed, reactive } from 'vue'
import {
  DEFAULT_INPUT_BINDINGS,
  mouseButtonLabel,
  type InputBindingRegistrationStatus,
  type InputBindingSettings,
  type InputBindingSettingsPatch,
  type InputBindingSnapshot,
} from '@/../shared/input-bindings'

const emptyStatus = (): InputBindingRegistrationStatus => ({
  mouseHookAvailable: false,
  pushToTalkActive: false,
  keyboard: { interact: false, lock: false, openPanel: false, toggleVision: false },
  errors: [],
})

const state = reactive({
  settings: structuredClone(DEFAULT_INPUT_BINDINGS) as InputBindingSettings,
  status: emptyStatus(),
  available: false,
  loading: false,
  error: '',
})

const applySnapshot = (snapshot: InputBindingSnapshot): void => {
  state.settings = structuredClone(snapshot.settings)
  state.status = structuredClone(snapshot.status)
  state.available = true
  state.error = ''
}

const load = async (): Promise<InputBindingSnapshot | null> => {
  const api = window.petApi?.inputBindings
  if (!api) {
    state.available = false
    return null
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
  if (!api) return null
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
  if (!api) return null
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

export const useInputBindingsStore = () => ({
  state,
  load,
  update,
  reset,
  pushToTalkLabel: computed(() => `按住${mouseButtonLabel(state.settings.pushToTalk.mouseButton)}`),
})
