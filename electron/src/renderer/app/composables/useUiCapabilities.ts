import { computed, ref } from 'vue'
import { systemClient, type UiCapabilitiesSnapshot, type UiClientCapabilities } from '@/api/clients/system-client'

const emptyClient = (mode: 'browser' | 'electron'): UiClientCapabilities => ({
  mode,
  coreRoutes: ['chat', 'memory', 'settings'],
  hostCapabilities: {
    windowControls: mode === 'electron',
    desktopActions: mode === 'electron',
    screenCapture: mode === 'electron',
    localFilePicker: mode === 'electron',
  },
  limitations: [],
})

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
)

const normalizeClient = (value: unknown, mode: 'browser' | 'electron'): UiClientCapabilities => {
  if (!isRecord(value)) return emptyClient(mode)
  const capabilities = isRecord(value.hostCapabilities) ? value.hostCapabilities : {}
  const routes = Array.isArray(value.coreRoutes)
    ? value.coreRoutes.filter((item): item is string => typeof item === 'string').slice(0, 20)
    : emptyClient(mode).coreRoutes
  return {
    mode,
    coreRoutes: routes,
    hostCapabilities: {
      windowControls: capabilities.windowControls === true,
      desktopActions: capabilities.desktopActions === true,
      screenCapture: capabilities.screenCapture === true,
      localFilePicker: capabilities.localFilePicker === true,
    },
    limitations: Array.isArray(value.limitations)
      ? value.limitations.filter((item): item is string => typeof item === 'string').slice(0, 20)
      : [],
  }
}

const normalizeSnapshot = (value: unknown): UiCapabilitiesSnapshot | null => {
  if (!isRecord(value)) return null
  const protocol = isRecord(value.protocol) ? value.protocol : {}
  const clients = isRecord(value.clients) ? value.clients : {}
  return {
    schemaVersion: typeof value.schemaVersion === 'string' ? value.schemaVersion : 'yuizaki.ui-capabilities.v1',
    protocol: {
      http: protocol.http === true,
      socketIo: protocol.socketIo === true,
      openapi: typeof protocol.openapi === 'string' ? protocol.openapi.slice(0, 120) : '/docs',
    },
    clients: {
      browser: normalizeClient(clients.browser, 'browser'),
      electron: normalizeClient(clients.electron, 'electron'),
    },
    browserPlatform: isRecord(value.browserPlatform) ? value.browserPlatform : {},
  }
}

export const useUiCapabilities = () => {
  const snapshot = ref<UiCapabilitiesSnapshot | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let refreshGeneration = 0

  const isElectron = computed(() => Boolean(typeof window !== 'undefined' && window.petApi?.window))
  const mode = computed<'browser' | 'electron'>(() => (isElectron.value ? 'electron' : 'browser'))
  const client = computed(() => snapshot.value?.clients[mode.value] ?? emptyClient(mode.value))
  const connected = computed(() => snapshot.value?.protocol.http === true)

  const refresh = async (): Promise<void> => {
    const generation = ++refreshGeneration
    loading.value = true
    error.value = null
    try {
      const next = normalizeSnapshot(await systemClient.uiCapabilities())
      if (generation !== refreshGeneration) return
      if (!next) throw new Error('浏览器能力响应格式无效')
      snapshot.value = next
    } catch (cause) {
      if (generation !== refreshGeneration) return
      error.value = cause instanceof Error ? cause.message : '浏览器能力读取失败'
    } finally {
      if (generation === refreshGeneration) loading.value = false
    }
  }

  return { snapshot, loading, error, isElectron, mode, client, connected, refresh }
}
