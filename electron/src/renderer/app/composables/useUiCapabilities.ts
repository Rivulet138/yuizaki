import { computed, ref } from 'vue'
import { systemClient, type UiCapabilitiesSnapshot, type UiClientCapabilities } from '@/api/clients/system-client'
import { t } from '@/i18n'

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

export type UiTransport = 'browserLocal' | 'hostHttp' | 'electronIpc'
export interface UiCapability { available: boolean; transport: UiTransport; reason: string }

// A single snapshot is shared by the shell and its cached panels.
const snapshot = ref<UiCapabilitiesSnapshot | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
let refreshGeneration = 0
let pendingRefresh: Promise<void> | null = null

export const useUiCapabilities = () => {
  const isElectron = computed(() => Boolean(typeof window !== 'undefined' && window.petApi?.window))
  const mode = computed<'browser' | 'electron'>(() => (isElectron.value ? 'electron' : 'browser'))
  const client = computed(() => snapshot.value?.clients[mode.value] ?? emptyClient(mode.value))
  const connected = computed(() => snapshot.value?.protocol.http === true)

  const load = async (): Promise<void> => {
    const generation = ++refreshGeneration
    loading.value = true
    error.value = null
    try {
      const next = normalizeSnapshot(await systemClient.uiCapabilities())
      if (generation !== refreshGeneration) return
      if (!next) throw new Error(t('misc.browserCapabilitiesInvalidFormat'))
      snapshot.value = next
    } catch (cause) {
      if (generation !== refreshGeneration) return
      error.value = cause instanceof Error ? cause.message : t('misc.browserCapabilitiesReadFailed')
    } finally {
      if (generation === refreshGeneration) loading.value = false
    }
  }

  const refresh = (): Promise<void> => {
    if (!pendingRefresh) pendingRefresh = load().finally(() => { pendingRefresh = null })
    return pendingRefresh
  }
  const capability = (transport: UiTransport, key?: keyof UiClientCapabilities['hostCapabilities'], ipcPresent = false): UiCapability => {
    if (transport === 'browserLocal') return { available: true, transport, reason: '在当前浏览器处理所选文件。' }
    if (transport === 'hostHttp') {
      const available = snapshot.value?.protocol.http !== false
      return { available, transport, reason: available
        ? '通过 HTTP 操作服务所在的宿主；文件路径属于宿主。'
        : '宿主未提供 HTTP 能力；请连接宿主服务或使用桌面端。' }
    }
    const available = isElectron.value && ipcPresent && (!key || client.value.hostCapabilities[key])
    return { available, transport, reason: available ? '通过 Electron IPC 操作本机。' : '当前环境没有此 Electron IPC 能力；请在桌面端操作，或使用宿主 HTTP 入口。' }
  }
  return { snapshot, loading, error, isElectron, mode, client, connected, capability, refresh }
}
