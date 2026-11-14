import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'

/** Page-owned refreshes and timers pause while a KeepAlive view is hidden. */
export const usePanelLifecycle = (refresh: () => Promise<unknown>, pause: () => void = () => {}) => {
  const active = ref(true)
  const lastUpdated = ref('')
  const refreshError = ref('')
  let pending: Promise<void> | null = null
  let generation = 0
  let wasDeactivated = false
  const reload = (): Promise<void> => {
    if (!active.value) return Promise.resolve()
    if (pending) return pending
    const request = generation
    refreshError.value = ''
    pending = Promise.resolve().then(() => {
      if (request === generation && active.value) return refresh()
    }).then(() => {
      if (request === generation && active.value) lastUpdated.value = new Date().toLocaleString()
    }).catch((error: unknown) => {
      if (request === generation && active.value) refreshError.value = error instanceof Error ? error.message : String(error)
    }).finally(() => { if (request === generation) pending = null })
    return pending
  }
  const deactivate = () => {
    active.value = false
    wasDeactivated = true
    generation += 1
    pending = null
    pause()
  }
  onMounted(() => { void reload() })
  onActivated(() => {
    active.value = true
    if (wasDeactivated) { wasDeactivated = false; void reload() }
  })
  onDeactivated(deactivate)
  onBeforeUnmount(deactivate)
  return { active, lastUpdated, refreshError, reload }
}
