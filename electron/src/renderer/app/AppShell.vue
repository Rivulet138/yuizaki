<template>
  <div class="yuizaki-bg">
    <div class="shell cherry-shell">
      <AppSidebar
        :active-workspace-id="activeWorkspace.id"
        :menus="menus"
        :admin-menus="adminMenus"
        @open-workspace-settings="dialogStore.openWorkspaceDrawer"
      />

      <section class="main" :class="{ 'wallpaper-on': wallpaperMode, 'main--chat': activeTab === 'chat' }">
        <div class="wallpaper-layer" :style="{ backgroundImage: `url(${currentWallpaper})` }"></div>
        <div class="wallpaper-blur" :style="{ backgroundImage: `url(${currentWallpaper})` }"></div>
        <div class="wallpaper-mask"></div>
        <div class="content-frame">
          <AppTopbar
            v-if="activeTab !== 'chat'"
            :active-workspace="activeWorkspace"
            :companion-id="activeWorkspace.companion_profile_id || companionStore.activeCompanionId"
            :companions="companionOptions"
            :title="activeModuleTitle"
            :companion-state="companionRuntime.presentationState.value"
            :companion-state-label="companionStateLabel"
            :admin-mode="adminMode"
            :is-electron-panel="isElectronPanel"
            :notification-count="notifications.length"
            :theme="resolvedTheme"
            @toggle-admin-mode="toggleAdminMode"
            @toggle-theme="toggleTheme"
            @change-locale="handleLocaleChange"
            @toggle-notifications="showNotifPanel = !showNotifPanel"
            @minimize="minimize"
            @maximize="maximize"
            @close="close"
            @change-companion="handleCompanionChange"
          />

          <RuntimeEnvironmentStrip
            v-if="runtimeEnvironmentNotice"
            v-bind="runtimeEnvironmentNotice"
            @open-checks="openRuntimeChecks"
            @retry="retryConnection"
          />

          <main class="app-main" :class="activeTab === 'chat' ? 'chat-mode' : 'panel-mode'">
            <div
              class="view-host"
              data-testid="route-view"
              :data-route-name="activeTab"
            >
              <router-view v-slot="{ Component, route }">
                <keep-alive>
                  <component :is="Component" v-if="Component" :key="route.name" class="view-component" />
                </keep-alive>
              </router-view>
            </div>
          </main>
        </div>
      </section>
    </div>

    <GlobalDialogs />

    <Teleport to="body">
      <div v-if="showShortcuts" class="shortcuts-overlay" @click="showShortcuts = false">
        <div class="shortcuts-modal" @click.stop>
          <h3>{{ t('shell.shortcuts.title') }}</h3>
          <div v-for="shortcut in shortcuts" :key="shortcut.key" class="shortcut-item">
            <kbd>{{ shortcut.key }}</kbd>
            <span>{{ shortcut.desc }}</span>
          </div>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="showNotifPanel" class="shortcuts-overlay" @click="showNotifPanel = false">
        <div class="shortcuts-modal" @click.stop>
          <h3>{{ t('shell.notifications.title') }}</h3>
          <div v-if="!notifications.length" class="empty-notice">{{ t('shell.notifications.empty') }}</div>
          <div v-for="notification in notifications" :key="notification.id" class="shortcut-item">
            <span>{{ notification.text }}</span>
            <span class="notice-time">{{ notification.time }}</span>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { yuizakiConfig } from '@/config/yuizaki'
import { hasControlAuthToken } from '@/api/clients/http-client'
import { getSocketClient, SocketEvents } from '@/net/socketClient'
import { useChatStore } from '@/stores/chatStore'
import { useCompanionStore } from '@/stores/companionStore'
import { useDialogStore, type PermissionRequestPayload } from '@/stores/dialogStore'
import { useSystemStore } from '@/stores/systemStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useSettingsStore } from '@/state/settingsStore'
import { useInputBindingsStore } from '@/state/inputBindingsStore'
import { setLocale, syncLocaleFromSettings, t } from '@/i18n'
import { logger } from '@/logger'
import { adminNavigationModules, isPanelKey, primaryNavigationModules, type NavigationModuleId } from '@/navigation/modules'
import AppSidebar from './AppSidebar.vue'
import AppTopbar from './AppTopbar.vue'
import GlobalDialogs from './components/dialogs/GlobalDialogs.vue'
import RuntimeEnvironmentStrip from './components/RuntimeEnvironmentStrip.vue'
import { useAppOrchestrator } from './orchestrators/useAppOrchestrator'
import { useVoiceConversationBridge } from './composables/useVoiceConversationBridge'
import { advanceCompanionCooldownForE2E, useCompanionRuntimeBridge } from './composables/useCompanionRuntimeBridge'
import { publishCompanionRuntimeEvent } from './runtime/companionRuntime'
import { createAppRuntimeTeardown } from './runtime/appRuntimeTeardown'
import { createVisualCaptureRuntime } from './runtime/visualCaptureRuntime'

const systemStore = useSystemStore()
const workspaceStore = useWorkspaceStore()
const companionStore = useCompanionStore()
const dialogStore = useDialogStore()
const settingsStore = useSettingsStore()
const inputBindingsStore = useInputBindingsStore()
const chatStore = useChatStore()
const orchestrator = useAppOrchestrator()
const companionRuntime = useCompanionRuntimeBridge()
useVoiceConversationBridge()
const route = useRoute()
const router = useRouter()
const petApi = window.petApi
const e2eApi = petApi?.e2e
const e2eMode = Boolean(e2eApi)

const activeTab = computed<NavigationModuleId>(() => {
  const segments = route.path.replace(/^\//, '').split('/')
  return (segments[2] || 'chat') as NavigationModuleId
})

const activeWorkspace = computed(() => workspaceStore.activeWorkspace)
const wallpaperMode = ref(true)
const currentWallpaper = ref(yuizakiConfig.slides[0] || '')
const localMenus = computed(() => primaryNavigationModules())
const localAdminMenus = computed(() => adminNavigationModules())
const ADMIN_MODE_STORAGE_KEY = 'yuizaki.adminMode'
const activeVisionSettings = computed(() => workspaceStore.activeWorkspace.context.vision ?? {
  enabled: false,
  displayIndex: 0,
  captureMode: 'display' as const,
  region: { x: 0, y: 0, width: 1280, height: 720 },
  privacyMasks: [],
})
const adminMode = ref(
  typeof window !== 'undefined' && window.localStorage.getItem(ADMIN_MODE_STORAGE_KEY) === 'true',
)
const chatState = computed(() => chatStore.state)
const showShortcuts = ref(false)
const showNotifPanel = ref(false)
const notifications = computed(() => chatStore.notifications || [])
const companionOptions = computed(() => {
  const companions = Array.isArray(companionStore.companions) ? companionStore.companions : []
  return companions
    .filter((item) => item && item.id && item.name)
    .map((item) => ({ id: item.id, name: item.name }))
})
const isElectronPanel = computed(() => Boolean(petApi?.window))
const handleCompanionChange = orchestrator.handleCompanionChange
const runtimeEnvironmentNotice = computed(() => {
  const browserHost = !isElectronPanel.value
  const browserAuthorized = browserHost && (hasControlAuthToken() || systemStore.controlRunning)
  if (systemStore.statusChecked && (!systemStore.controlRunning || !systemStore.pythonRunning)) {
    const unavailable = [
      !systemStore.controlRunning ? '控制服务' : '',
      !systemStore.pythonRunning ? 'Python 后端' : '',
    ].filter(Boolean).join('、')
    return {
      kind: 'offline' as const,
      tone: 'danger' as const,
      title: `${unavailable}未连接`,
      detail: '对话、语音、记忆或桌宠控制暂不可用。',
      retryable: true,
    }
  }
  if (systemStore.statusChecked && !systemStore.sioConnected) {
    return {
      kind: 'degraded' as const,
      tone: 'warning' as const,
      title: '实时通道未连接',
      detail: '设置仍可读取，但流式对话、语音回传和桌宠联动会中断。',
      retryable: true,
    }
  }
  if (browserHost) {
    return {
      kind: 'browser' as const,
      tone: 'info' as const,
      title: browserAuthorized ? '浏览器控制台' : '浏览器预览模式',
      detail: browserAuthorized
        ? '服务功能可用；桌宠宿主窗口、全局输入和 Electron 进程资源不可用。'
        : '仅用于界面预览；请从 Yuizaki 桌面应用或本地控制页打开完整功能。',
      retryable: false,
    }
  }
  if (!systemStore.statusChecked) return null
  return null
})

let themeMediaQuery: MediaQueryList | null = null
let healthScheduleEnabled = !e2eMode
let companionScheduleEnabled = !e2eMode
let disposeE2EControls: (() => void) | null = null
let e2eInitialHealthChecked = false
let visualContextEnabled = activeVisionSettings.value.enabled
const visualCaptureRuntime = createVisualCaptureRuntime({
  getSettings: () => activeVisionSettings.value,
  getHealth: () => ({
    controlRunning: systemStore.controlRunning,
    pythonRunning: systemStore.pythonRunning,
  }),
  isDocumentHidden: () => document.hidden,
  getScreenApi: () => petApi?.screen,
  getSocket: getSocketClient,
  state: {
    markVisualPerceptionCapturing: systemStore.markVisualPerceptionCapturing,
    markVisualPerceptionReady: systemStore.markVisualPerceptionReady,
    markVisualPerceptionError: systemStore.markVisualPerceptionError,
  },
  logger,
})
const resolveTheme = () => {
  const preferred = settingsStore.state.system.theme || 'light'
  if (preferred !== 'system') return preferred
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const applyTheme = () => {
  const theme = resolveTheme()
  document.documentElement.setAttribute('data-theme', theme)
  document.documentElement.style.colorScheme = theme
}

const resolvedTheme = computed(() => resolveTheme())

const toggleTheme = async () => {
  const nextTheme = resolveTheme() === 'dark' ? 'light' : 'dark'
  settingsStore.state.system.theme = nextTheme
  applyTheme()
  try {
    await settingsStore.saveSettings({ system: { ...settingsStore.state.system, theme: nextTheme } })
  } catch {
    ElMessage.warning(t('common.localOnly'))
  }
}

const shortcuts = computed(() => [
  { key: '?', desc: t('shell.shortcuts.toggle') },
  { key: inputBindingsStore.state.settings.keyboard.interact || t('common.disabled'), desc: t('shell.shortcuts.dragMode') },
  { key: inputBindingsStore.state.settings.keyboard.lock || t('common.disabled'), desc: t('shell.shortcuts.lockMode') },
  { key: inputBindingsStore.state.settings.keyboard.openPanel || t('common.disabled'), desc: t('shell.shortcuts.openPanel') },
  { key: inputBindingsStore.state.settings.keyboard.toggleVision || t('common.disabled'), desc: t('shell.shortcuts.toggleVision') },
  { key: inputBindingsStore.pushToTalkLabel.value, desc: t('shell.shortcuts.voice') },
])

const menus = computed(() => {
  const orderMap = new Map((activeWorkspace.value.context?.menuOrder || []).map((id, index) => [id, index]))
  return [...localMenus.value]
    .filter((module) => module.enabled !== false)
    .sort((left, right) => {
      const leftOrder = orderMap.get(left.id) ?? Number.MAX_SAFE_INTEGER
      const rightOrder = orderMap.get(right.id) ?? Number.MAX_SAFE_INTEGER
      return leftOrder - rightOrder || (left.order ?? 0) - (right.order ?? 0)
    })
})

const adminMenus = computed(() => (adminMode.value ? localAdminMenus.value : []))
const activeModuleTitle = computed(() => {
  const module = [...localMenus.value, ...localAdminMenus.value].find((item) => item.id === activeTab.value)
  return module?.title || yuizakiConfig.heroTitle
})
const companionStateLabel = computed(() => t(`companion.home.state.${companionRuntime.presentationState.value}`))

const retryConnection = () => {
  const socketClient = getSocketClient()
  socketClient.connect()
  systemStore.refreshStatus(
    () => socketClient.isConnected(),
    () => socketClient.isConnected(),
  )
}

const openRuntimeChecks = () => handlePanelOpenTab('deploy')

const handleGlobalKeydown = (event: KeyboardEvent) => {
  if (event.key === '?' && !event.ctrlKey && !event.metaKey && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
    showShortcuts.value = !showShortcuts.value
  }
  if (event.key === 'Escape') showShortcuts.value = false
}

const handlePanelOpenTab = (tab: string) => {
  const normalizedTab = String(tab || '').trim().toLowerCase()
  if (!isPanelKey(normalizedTab)) return
  const workspaceId = encodeURIComponent(activeWorkspace.value.id || 'default')
  const sessionId = route.params.sessionId ? encodeURIComponent(String(route.params.sessionId)) : ''
  const suffix = normalizedTab === 'chat' && sessionId ? `/${sessionId}` : ''
  void router.push(`/w/${workspaceId}/${normalizedTab}${suffix}`)
}

const handleToggleVisionShortcut = () => {
  const vision = activeVisionSettings.value
  const enabled = !vision.enabled
  workspaceStore.updateWorkspaceContext(activeWorkspace.value.id, {
    vision: { ...vision, enabled },
  })
  ElMessage({
    message: enabled ? '桌宠视觉已恢复' : '桌宠视觉已暂停',
    type: enabled ? 'success' : 'warning',
    duration: 1800,
  })
}

const callWindowAction = (action: 'minimize' | 'maximize' | 'close') => {
  const winApi = petApi?.window
  if (!winApi) {
    ElMessage.info(t('window.electronOnly'))
    return
  }
  winApi[action]?.()
}

const minimize = () => callWindowAction('minimize')
const maximize = () => callWindowAction('maximize')
const close = () => callWindowAction('close')
const toggleAdminMode = () => {
  adminMode.value = !adminMode.value
  window.localStorage.setItem(ADMIN_MODE_STORAGE_KEY, String(adminMode.value))
}

const handleLocaleChange = async (locale: string) => {
  try {
    await setLocale(locale)
    ElMessage.success(t('language.changed'))
  } catch {
    ElMessage.warning(t('common.localOnly'))
  }
}

const handlePermissionRequest = (data: PermissionRequestPayload) => {
  void publishCompanionRuntimeEvent({ source: 'permission', permission: 'waiting', requestId: data.request_id })
  dialogStore.openPermissionRequest(data)
}

const stopAppRuntime = () => {
  visualCaptureRuntime.stop()
  window.removeEventListener('keydown', handleGlobalKeydown)
  petApi?.off?.('panel:open-tab', handlePanelOpenTab)
  petApi?.off?.('shortcut:toggle-vision', handleToggleVisionShortcut)
  themeMediaQuery?.removeEventListener('change', applyTheme)
  systemStore.stopHealthCheck()
  companionRuntime.stopCompanionRuntime()
  const socketClient = getSocketClient()
  socketClient.off(SocketEvents.PERMISSION_REQUEST, handlePermissionRequest)
  socketClient.off(SocketEvents.SCREENSHOT_RESULT, visualCaptureRuntime.handleResult)
  socketClient.off(SocketEvents.SCREENSHOT_CAPTURE_REQUEST, visualCaptureRuntime.handleCaptureRequest)
  disposeE2EControls?.()
  disposeE2EControls = null
}

const appRuntimeTeardown = createAppRuntimeTeardown({
  stop: stopAppRuntime,
  disconnect: () => getSocketClient().disconnect(),
})
const teardownAppRuntime = () => appRuntimeTeardown.run()
defineExpose({ teardownAppRuntime })

if (e2eApi) {
  disposeE2EControls = e2eApi.onControl(async ({ control }) => {
    const socketClient = getSocketClient()
    switch (control) {
      case 'pauseHealthPolling':
        healthScheduleEnabled = false
        systemStore.stopHealthCheck()
        return { paused: true }
      case 'pollHealthOnce':
        if (!e2eInitialHealthChecked) {
          const socketDeadline = Date.now() + 5_000
          while (!socketClient.isConnected()) {
            if (Date.now() >= socketDeadline) throw new Error('Initial E2E Socket connection timed out')
            await new Promise(resolve => window.setTimeout(resolve, 25))
          }
          e2eInitialHealthChecked = true
        }
        await systemStore.refreshStatus(() => false, () => socketClient.isConnected())
        return {
          checked: systemStore.statusChecked,
          controlRunning: systemStore.controlRunning,
          pythonRunning: systemStore.pythonRunning,
          sioConnected: systemStore.sioConnected,
        }
      case 'resumeHealthPolling':
        healthScheduleEnabled = true
        systemStore.startHealthCheck(() => false, () => socketClient.isConnected())
        while (!systemStore.statusChecked) await new Promise(resolve => window.setTimeout(resolve, 25))
        return { resumed: true, checked: true }
      case 'sampleVisualOnce':
        {
          const socketDeadline = Date.now() + 5_000
          while (!socketClient.isConnected()) {
            if (Date.now() >= socketDeadline) throw new Error('Visual sample Socket connection timed out')
            await new Promise(resolve => window.setTimeout(resolve, 25))
          }
          const frameId = `renderer-e2e-${Date.now()}`
          const result = await visualCaptureRuntime.captureAndWait(frameId, true)
          return { sampled: true, frameId, status: result['status'] }
        }
      case 'pauseCompanionPolling':
        companionScheduleEnabled = false
        companionRuntime.stopCompanionRuntime()
        return { paused: true }
      case 'pollCompanionOnce':
        return companionRuntime.pollCompanionOnce()
      case 'resumeCompanionPolling':
        {
          companionScheduleEnabled = true
          const previous = companionRuntime.runtimeSnapshot.value
          const nextSnapshot = new Promise<void>((resolve, reject) => {
            const timeout = window.setTimeout(() => {
              stopWatching()
              reject(new Error('Scheduled companion poll timed out'))
            }, 4_000)
            const stopWatching = watch(companionRuntime.runtimeSnapshot, (snapshot) => {
              if (!snapshot || snapshot === previous) return
              window.clearTimeout(timeout)
              stopWatching()
              resolve()
            })
          })
          companionRuntime.startCompanionRuntime(() => systemStore.controlRunning && systemStore.pythonRunning)
          await nextSnapshot
          return { resumed: true, polled: true }
        }
      case 'advanceCompanionCooldown':
        return { advancedMs: advanceCompanionCooldownForE2E() }
      case 'pauseHeartbeat':
        socketClient.pauseHeartbeat()
        return { paused: true }
      case 'emitHeartbeatOnce':
        return socketClient.emitHeartbeatOnceAndWaitForEcho()
      case 'teardownRuntime':
        await teardownAppRuntime()
        return { tornDown: true }
    }
  })
}

watch(() => chatState.value.isGenerating, (generating) => {
  document.title = generating ? t('shell.status.thinking') : yuizakiConfig.heroTitle
})

onMounted(() => {
  applyTheme()
  themeMediaQuery = window.matchMedia?.('(prefers-color-scheme: dark)') ?? null
  themeMediaQuery?.addEventListener('change', applyTheme)
  syncLocaleFromSettings()
  void settingsStore.fetchSettings().then(() => {
    applyTheme()
    syncLocaleFromSettings(settingsStore.state.error ? undefined : settingsStore.state.system.language)
  })
  void inputBindingsStore.load()
  wallpaperMode.value = activeWorkspace.value.context?.wallpaperMode ?? true
  window.addEventListener('keydown', handleGlobalKeydown)
  petApi?.on?.('panel:open-tab', handlePanelOpenTab)
  petApi?.on?.('shortcut:toggle-vision', handleToggleVisionShortcut)

  const socketClient = getSocketClient()
  if (e2eMode) socketClient.pauseHeartbeat()
  socketClient.connect()
  // E2E drives health checks explicitly so startup ordering remains deterministic.
  if (healthScheduleEnabled && !e2eMode) {
    systemStore.startHealthCheck(
      () => false,
      () => socketClient.isConnected(),
    )
  }
  socketClient.on(SocketEvents.PERMISSION_REQUEST, handlePermissionRequest)
  socketClient.on(SocketEvents.SCREENSHOT_RESULT, visualCaptureRuntime.handleResult)
  socketClient.on(SocketEvents.SCREENSHOT_CAPTURE_REQUEST, visualCaptureRuntime.handleCaptureRequest)
  systemStore.setVisualPerceptionEnabled(activeVisionSettings.value.enabled)

  if (companionScheduleEnabled) {
    companionRuntime.startCompanionRuntime(() => systemStore.controlRunning && systemStore.pythonRunning)
  }
  const restoredTab = activeWorkspace.value.context.activeTab
  if (activeTab.value === 'companion' && restoredTab && isPanelKey(restoredTab) && restoredTab !== 'companion') {
    void router.replace(`/w/${encodeURIComponent(activeWorkspace.value.id)}/${restoredTab}`)
  }
})

onUnmounted(() => {
  void teardownAppRuntime()
})

watch(() => settingsStore.state.system.theme, applyTheme)
watch(() => settingsStore.state.system.language, (language) => syncLocaleFromSettings(language))
watch(activeTab, (tab) => {
  const context = activeWorkspace.value.context
  const recentTabs = [tab, ...(context.recentTabs ?? []).filter((item) => item !== tab)].slice(0, 8)
  workspaceStore.updateWorkspaceContext(activeWorkspace.value.id, { activeTab: tab, recentTabs })
})
watch(activeVisionSettings, () => {
  const wasEnabled = visualContextEnabled
  visualContextEnabled = activeVisionSettings.value.enabled
  visualCaptureRuntime.invalidate()
  systemStore.setVisualPerceptionEnabled(visualContextEnabled)
  if (wasEnabled && !visualContextEnabled) getSocketClient().clearVisualContext()
}, { deep: true })
watch(
  () => [systemStore.statusChecked, systemStore.controlRunning, systemStore.pythonRunning] as const,
  ([checked, controlRunning, pythonRunning]) => {
    const availability = !checked ? 'degraded' : controlRunning && pythonRunning ? 'online' : 'offline'
    void publishCompanionRuntimeEvent({ source: 'health', availability })
  },
  { immediate: true },
)
</script>

<style scoped>
.yuizaki-bg {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--yui-app-bg);
  color: var(--yui-text);
}

.shell {
  position: relative;
  display: flex;
  width: 100%;
  height: 100%;
  padding: 0;
  box-sizing: border-box;
  gap: 0;
}

.main {
  position: relative;
  flex: 1;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  background: var(--yui-main-bg);
  padding: 14px 16px 16px;
  box-sizing: border-box;
}

.wallpaper-layer,
.wallpaper-blur,
.wallpaper-mask {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.wallpaper-layer {
  z-index: 0;
  background-position: center;
  background-size: cover;
  filter: saturate(1.22) contrast(1.08);
  opacity: 1;
  transition: opacity 0.3s ease;
}

.wallpaper-blur {
  display: none;
  z-index: 0;
  background-position: center;
  background-size: cover;
  filter: blur(24px) saturate(1.18);
  opacity: 0;
}

.wallpaper-mask {
  z-index: 1;
  background: var(--yui-panel-wallpaper-mask);
}

.wallpaper-on .wallpaper-layer {
  opacity: var(--yui-panel-wallpaper-opacity);
}

.content-frame {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
}

.app-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  border: 1px solid var(--yui-panel-border);
  border-radius: 8px;
  background: var(--yui-app-main-panel-bg);
  box-shadow: none;
}

.app-main.panel-mode {
  padding: 18px 24px 22px;
  border-color: var(--yui-panel-outline);
  background: var(--yui-panel-surface);
  background-clip: padding-box;
  box-shadow: var(--yui-panel-shadow);
}

.app-main.chat-mode {
  padding: 0;
  border-color: transparent;
  background: var(--yui-chat-page-bg);
  box-shadow: none;
}

.main--chat .wallpaper-layer {
  opacity: var(--yui-chat-wallpaper-opacity);
  filter: saturate(0.92) contrast(0.98);
}

.main--chat .wallpaper-mask {
  background: var(--yui-chat-wallpaper-mask);
}

.main--chat .wallpaper-blur {
  display: none;
}

.view-host {
  position: relative;
  flex: 1;
  min-height: 0;
}

.view-component {
  position: absolute;
  inset: 0;
}

.shortcuts-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(31, 34, 65, 0.28);
}

.shortcuts-modal {
  min-width: 320px;
  padding: 24px 28px;
  border-radius: var(--yui-radius-panel);
  border: 1px solid var(--yui-border);
  background: var(--yui-surface-raised);
  box-shadow: 0 26px 80px rgba(42, 45, 86, 0.24);
}

.shortcuts-modal h3 {
  margin: 0 0 16px;
  font-size: 17px;
}

.shortcut-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 0;
  border-bottom: 1px solid #f1f5f9;
  font-size: 14px;
}

.shortcut-item kbd {
  border: 1px solid #e2e8f0;
  border-radius: 5px;
  color: #334155;
  background: #f1f5f9;
  padding: 3px 8px;
  font-family: monospace;
  font-size: 13px;
}

.empty-notice,
.notice-time {
  color: #94a3b8;
  font-size: 13px;
}

.empty-notice {
  padding: 16px 0;
}

.animate-fade-in {
  animation: fadeIn 0.3s ease-out;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.3); }
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 980px) {
  .shell {
    padding: 0;
  }

  .main {
    min-width: 0;
    padding: 10px 12px 12px;
  }

  .app-main.panel-mode {
    padding: 14px;
  }

  .wallpaper-layer,
  .wallpaper-blur {
    left: 0;
    right: 0;
    width: auto;
    transform: none;
  }
}

@media (max-width: 760px) {
  .shell {
    padding: 0;
  }

  .main {
    padding: 8px;
  }

  .app-main.panel-mode {
    padding: 10px;
  }

}
</style>

<style>
:root,
:root[data-theme='light'] {
  --yui-app-bg: radial-gradient(circle at 18% 12%, rgba(255, 214, 236, 0.68), transparent 28%),
    radial-gradient(circle at 82% 8%, rgba(177, 232, 255, 0.68), transparent 30%),
    linear-gradient(135deg, #fff7fb 0%, #eef8ff 48%, #fff5e8 100%);
  --yui-main-bg: linear-gradient(135deg, rgba(255, 247, 251, 0.2), rgba(236, 248, 255, 0.16));
  --yui-panel-bg: rgba(255, 255, 255, 0.035);
  --yui-panel-border: rgba(255, 255, 255, 0.54);
  --yui-panel-shine: rgba(255, 255, 255, 0.16);
  --yui-surface: rgba(255, 255, 255, 0.94);
  --yui-surface-raised: #ffffff;
  --yui-surface-muted: rgba(246, 248, 251, 0.62);
  --yui-surface-subtle: rgba(238, 244, 251, 0.56);
  --yui-panel-surface: rgba(255, 255, 255, 0.58);
  --yui-panel-surface-strong: rgba(255, 255, 255, 0.76);
  --yui-panel-outline: rgba(255, 255, 255, 0.78);
  --yui-panel-outline-strong: rgba(255, 255, 255, 0.94);
  --yui-panel-shadow: 0 12px 28px rgba(15, 23, 42, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.5);
  --yui-border: rgba(203, 213, 225, 0.9);
  --yui-border-strong: rgba(148, 163, 184, 0.72);
  --yui-shadow-card: 0 10px 24px rgba(15, 23, 42, 0.055);
  --yui-shadow-hover: 0 16px 32px rgba(15, 23, 42, 0.09);
  --yui-radius-card: 12px;
  --yui-radius-panel: 18px;
  --yui-accent: #2563eb;
  --yui-accent-soft: #eff6ff;
  --yui-success-soft: #ecfdf5;
  --yui-warning-soft: #fffbeb;
  --yui-danger-soft: #fff1f2;
  --yui-app-main-panel-bg: transparent;
  --yui-panel-wallpaper-opacity: 1;
  --yui-panel-wallpaper-mask: transparent;
  --yui-chat-page-bg: transparent;
  --yui-chat-wallpaper-opacity: 1;
  --yui-chat-wallpaper-mask: transparent;
  --yui-chat-surface: rgba(255, 255, 255, 0.74);
  --yui-chat-surface-muted: rgba(241, 245, 249, 0.66);
  --yui-chat-sidebar-bg: rgba(244, 247, 251, 0.62);
  --yui-chat-border: rgba(203, 213, 225, 0.82);
  --yui-chat-text: #172033;
  --yui-chat-muted: #64748b;
  --yui-chat-hover: #e9eff6;
  --yui-chat-user-bg: #e8eef5;
  --yui-chat-assistant-bg: #ffffff;
  --yui-chat-focus: rgba(37, 99, 235, 0.3);
  --yui-text: #172033;
  --yui-muted: #64748b;
}

:root[data-theme='dark'] {
  --yui-app-bg: radial-gradient(circle at 18% 12%, rgba(47, 60, 103, 0.42), transparent 28%),
    radial-gradient(circle at 82% 8%, rgba(21, 94, 117, 0.36), transparent 30%),
    linear-gradient(135deg, #0b1020 0%, #111827 52%, #151827 100%);
  --yui-main-bg: linear-gradient(135deg, rgba(15, 23, 42, 0.5), rgba(17, 24, 39, 0.38));
  --yui-panel-bg: rgba(15, 23, 42, 0.24);
  --yui-panel-border: rgba(51, 65, 85, 0.72);
  --yui-panel-shine: rgba(255, 255, 255, 0.055);
  --yui-surface: rgba(15, 23, 42, 0.96);
  --yui-surface-raised: #111827;
  --yui-surface-muted: rgba(30, 41, 59, 0.64);
  --yui-surface-subtle: rgba(36, 48, 68, 0.58);
  --yui-panel-surface: rgba(15, 23, 42, 0.64);
  --yui-panel-surface-strong: rgba(15, 23, 42, 0.8);
  --yui-panel-outline: rgba(148, 163, 184, 0.46);
  --yui-panel-outline-strong: rgba(203, 213, 225, 0.66);
  --yui-panel-shadow: 0 14px 32px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.06);
  --yui-border: rgba(71, 85, 105, 0.82);
  --yui-border-strong: rgba(100, 116, 139, 0.82);
  --yui-shadow-card: 0 12px 28px rgba(0, 0, 0, 0.22);
  --yui-shadow-hover: 0 18px 40px rgba(0, 0, 0, 0.28);
  --yui-radius-card: 12px;
  --yui-radius-panel: 18px;
  --yui-accent: #60a5fa;
  --yui-accent-soft: rgba(37, 99, 235, 0.16);
  --yui-success-soft: rgba(16, 185, 129, 0.14);
  --yui-warning-soft: rgba(245, 158, 11, 0.14);
  --yui-danger-soft: rgba(244, 63, 94, 0.14);
  --yui-app-main-panel-bg: transparent;
  --yui-panel-wallpaper-opacity: 1;
  --yui-panel-wallpaper-mask: transparent;
  --yui-chat-page-bg: transparent;
  --yui-chat-wallpaper-opacity: 1;
  --yui-chat-wallpaper-mask: transparent;
  --yui-chat-surface: rgba(17, 24, 39, 0.76);
  --yui-chat-surface-muted: rgba(30, 41, 59, 0.68);
  --yui-chat-sidebar-bg: rgba(11, 18, 32, 0.68);
  --yui-chat-border: rgba(71, 85, 105, 0.82);
  --yui-chat-text: #e5e7eb;
  --yui-chat-muted: #94a3b8;
  --yui-chat-hover: #243044;
  --yui-chat-user-bg: #263449;
  --yui-chat-assistant-bg: #111827;
  --yui-chat-focus: rgba(96, 165, 250, 0.42);
  --yui-text: #e5e7eb;
  --yui-muted: #94a3b8;
}

.yuizaki-bg .el-card,
.yuizaki-bg .el-tabs--border-card,
.yuizaki-bg .el-table,
.yuizaki-bg .el-descriptions,
.yuizaki-bg .el-alert {
  border: 1px solid var(--yui-panel-outline);
  border-color: var(--yui-panel-outline);
  border-radius: var(--yui-radius-card);
  background: var(--yui-panel-surface);
  background-clip: padding-box;
  box-shadow: var(--yui-panel-shadow);
  color: var(--yui-text);
}

.yuizaki-bg .el-card__header,
.yuizaki-bg .el-tabs--border-card > .el-tabs__header,
.yuizaki-bg .el-table th.el-table__cell {
  border-color: var(--yui-border);
  background: var(--yui-surface-muted);
}

.yuizaki-bg .el-tabs--border-card > .el-tabs__content,
.yuizaki-bg .el-table tr,
.yuizaki-bg .el-table__body,
.yuizaki-bg .el-table__inner-wrapper::before {
  background: transparent;
}

.yuizaki-bg .el-input__wrapper,
.yuizaki-bg .el-select__wrapper,
.yuizaki-bg .el-textarea__inner,
.yuizaki-bg .el-input-number,
.yuizaki-bg .el-radio-button__inner {
  border-color: var(--yui-border);
  background: var(--yui-surface-raised);
  box-shadow: 0 0 0 1px var(--yui-border) inset;
  font-family: var(--yui-font-sans);
}

.yuizaki-bg .el-button,
.yuizaki-bg .el-tag {
  font-family: var(--yui-font-sans);
}

.yuizaki-bg .el-button {
  min-height: 32px;
  border-radius: 9px;
  font-weight: 650;
}

.yuizaki-bg .el-button--small {
  min-height: 28px;
  border-radius: 8px;
}

.yuizaki-bg .el-button + .el-button {
  margin-left: 0;
}

.yuizaki-bg .el-tag {
  border-radius: 999px;
  font-weight: 650;
}

.yuizaki-bg .el-button:not(.is-text) {
  border-color: var(--yui-border);
  background: var(--yui-surface-raised);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.yuizaki-bg .el-button:not(.is-text):hover,
.yuizaki-bg .el-button:not(.is-text):focus-visible {
  border-color: var(--yui-border-strong);
  color: var(--yui-accent);
  background: var(--yui-accent-soft);
}

.yuizaki-bg .el-button--primary:not(.is-text),
.yuizaki-bg .el-radio-button__original-radio:checked + .el-radio-button__inner {
  border-color: var(--yui-accent);
  color: #fff;
  background: var(--yui-accent);
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
}

.yuizaki-bg .el-button--primary:not(.is-text):hover,
.yuizaki-bg .el-button--primary:not(.is-text):focus-visible {
  border-color: var(--yui-accent);
  color: #fff;
  background: var(--yui-accent);
  filter: brightness(1.03);
}

.yuizaki-bg.yuizaki-bg .el-card,
.yuizaki-bg.yuizaki-bg .el-tabs--border-card,
.yuizaki-bg.yuizaki-bg .el-descriptions,
.yuizaki-bg.yuizaki-bg .el-alert,
.yuizaki-bg.yuizaki-bg .el-table,
.yuizaki-bg.yuizaki-bg .el-drawer,
.yuizaki-bg.yuizaki-bg .panel-card,
.yuizaki-bg.yuizaki-bg .metric-card,
.yuizaki-bg.yuizaki-bg .ops-card,
.yuizaki-bg.yuizaki-bg .ops-status-card,
.yuizaki-bg.yuizaki-bg .control-card,
.yuizaki-bg.yuizaki-bg .status-card,
.yuizaki-bg.yuizaki-bg .mode-card,
.yuizaki-bg.yuizaki-bg .server-card,
.yuizaki-bg.yuizaki-bg .host-card,
.yuizaki-bg.yuizaki-bg .plugin-card,
.yuizaki-bg.yuizaki-bg .preset-card,
.yuizaki-bg.yuizaki-bg .launch-card,
.yuizaki-bg.yuizaki-bg .schedule-card,
.yuizaki-bg.yuizaki-bg .schedule-item,
.yuizaki-bg.yuizaki-bg .run-card,
.yuizaki-bg.yuizaki-bg .loop-log-card,
.yuizaki-bg.yuizaki-bg .observability-card,
.yuizaki-bg.yuizaki-bg .voice-card,
.yuizaki-bg.yuizaki-bg .service-item,
.yuizaki-bg.yuizaki-bg .runway-step,
.yuizaki-bg.yuizaki-bg .command-item,
.yuizaki-bg.yuizaki-bg .permission-item,
.yuizaki-bg.yuizaki-bg .audit-item,
.yuizaki-bg.yuizaki-bg .detail-block,
.yuizaki-bg.yuizaki-bg .contribution-item,
.yuizaki-bg.yuizaki-bg .object-item,
.yuizaki-bg.yuizaki-bg .summary-detail-card,
.yuizaki-bg.yuizaki-bg .session-card,
.yuizaki-bg.yuizaki-bg .context-menu,
.yuizaki-bg.yuizaki-bg .toolbar,
.yuizaki-bg.yuizaki-bg .plugin-toolbar,
.yuizaki-bg.yuizaki-bg .governance-toolbar,
.yuizaki-bg.yuizaki-bg .voice-toolbar,
  .yuizaki-bg.yuizaki-bg .panel-toolbar {
  border-color: var(--yui-panel-outline);
  border-radius: var(--yui-radius-card);
  background: var(--yui-panel-surface);
  background-clip: padding-box;
  box-shadow: var(--yui-panel-shadow);
}

.yuizaki-bg.yuizaki-bg .panel-mode .el-card,
.yuizaki-bg.yuizaki-bg .panel-mode .el-tabs--border-card,
.yuizaki-bg.yuizaki-bg .panel-mode .el-descriptions,
.yuizaki-bg.yuizaki-bg .panel-mode .el-alert,
.yuizaki-bg.yuizaki-bg .panel-mode .el-table,
.yuizaki-bg.yuizaki-bg .panel-mode .panel-card,
.yuizaki-bg.yuizaki-bg .panel-mode .metric-card,
.yuizaki-bg.yuizaki-bg .panel-mode .ops-card,
.yuizaki-bg.yuizaki-bg .panel-mode .ops-status-card,
.yuizaki-bg.yuizaki-bg .panel-mode .control-card,
.yuizaki-bg.yuizaki-bg .panel-mode .status-card,
.yuizaki-bg.yuizaki-bg .panel-mode .mode-card,
.yuizaki-bg.yuizaki-bg .panel-mode .server-card,
.yuizaki-bg.yuizaki-bg .panel-mode .host-card,
.yuizaki-bg.yuizaki-bg .panel-mode .plugin-card,
.yuizaki-bg.yuizaki-bg .panel-mode .preset-card,
.yuizaki-bg.yuizaki-bg .panel-mode .launch-card,
.yuizaki-bg.yuizaki-bg .panel-mode .schedule-card,
.yuizaki-bg.yuizaki-bg .panel-mode .schedule-item,
.yuizaki-bg.yuizaki-bg .panel-mode .run-card,
.yuizaki-bg.yuizaki-bg .panel-mode .loop-log-card,
.yuizaki-bg.yuizaki-bg .panel-mode .observability-card,
.yuizaki-bg.yuizaki-bg .panel-mode .voice-card,
.yuizaki-bg.yuizaki-bg .panel-mode .service-item,
.yuizaki-bg.yuizaki-bg .panel-mode .runway-step,
.yuizaki-bg.yuizaki-bg .panel-mode .command-item,
.yuizaki-bg.yuizaki-bg .panel-mode .permission-item,
.yuizaki-bg.yuizaki-bg .panel-mode .audit-item,
.yuizaki-bg.yuizaki-bg .panel-mode .detail-block,
.yuizaki-bg.yuizaki-bg .panel-mode .contribution-item,
.yuizaki-bg.yuizaki-bg .panel-mode .object-item,
.yuizaki-bg.yuizaki-bg .panel-mode .summary-detail-card,
.yuizaki-bg.yuizaki-bg .panel-mode .session-card {
  box-shadow: none;
}

.yuizaki-bg.yuizaki-bg .metric-card.green,
.yuizaki-bg.yuizaki-bg .metric-card.blue,
.yuizaki-bg.yuizaki-bg .metric-card.violet,
.yuizaki-bg.yuizaki-bg .metric-card.amber,
.yuizaki-bg.yuizaki-bg .metric-card.red,
.yuizaki-bg.yuizaki-bg .metric-card.slate,
.yuizaki-bg.yuizaki-bg .host-card.green,
.yuizaki-bg.yuizaki-bg .host-card.blue,
.yuizaki-bg.yuizaki-bg .host-card.violet,
.yuizaki-bg.yuizaki-bg .ops-status-card.online,
.yuizaki-bg.yuizaki-bg .ops-status-card.warning,
.yuizaki-bg.yuizaki-bg .ops-status-card.offline,
.yuizaki-bg.yuizaki-bg .model-card,
.yuizaki-bg.yuizaki-bg .safety-card,
.yuizaki-bg.yuizaki-bg .appearance-card,
.yuizaki-bg.yuizaki-bg .recovery-card,
.yuizaki-bg.yuizaki-bg .pet-ops-card {
  background: var(--yui-surface-muted);
}

.yuizaki-bg.yuizaki-bg .metric-card.green,
.yuizaki-bg.yuizaki-bg .metric-card.tone-emerald,
.yuizaki-bg.yuizaki-bg .host-card.green,
.yuizaki-bg.yuizaki-bg .ops-status-card.online {
  background: var(--yui-success-soft);
}

.yuizaki-bg.yuizaki-bg .metric-card.amber,
.yuizaki-bg.yuizaki-bg .metric-card.tone-amber,
.yuizaki-bg.yuizaki-bg .ops-status-card.warning {
  background: var(--yui-warning-soft);
}

.yuizaki-bg.yuizaki-bg .metric-card.red,
.yuizaki-bg.yuizaki-bg .metric-card.tone-rose,
.yuizaki-bg.yuizaki-bg .ops-status-card.offline {
  background: var(--yui-danger-soft);
}

.yuizaki-bg.yuizaki-bg .metric-card.blue,
.yuizaki-bg.yuizaki-bg .metric-card.tone-blue,
.yuizaki-bg.yuizaki-bg .metric-card.violet,
.yuizaki-bg.yuizaki-bg .host-card.blue,
.yuizaki-bg.yuizaki-bg .host-card.violet {
  background: var(--yui-accent-soft);
}

.yuizaki-bg.yuizaki-bg .el-card__header,
.yuizaki-bg.yuizaki-bg .el-card__body,
.yuizaki-bg.yuizaki-bg .el-tabs--border-card > .el-tabs__header,
.yuizaki-bg.yuizaki-bg .el-tabs--border-card > .el-tabs__content,
.yuizaki-bg.yuizaki-bg .el-table th.el-table__cell,
.yuizaki-bg.yuizaki-bg .el-table tr,
.yuizaki-bg.yuizaki-bg .el-table td.el-table__cell,
.yuizaki-bg.yuizaki-bg .el-table__body,
.yuizaki-bg.yuizaki-bg .el-table__header,
.yuizaki-bg.yuizaki-bg .el-table__inner-wrapper,
.yuizaki-bg.yuizaki-bg .el-table__empty-block {
  background: transparent;
}

.yuizaki-bg.yuizaki-bg .el-input__wrapper,
.yuizaki-bg.yuizaki-bg .el-select__wrapper,
.yuizaki-bg.yuizaki-bg .el-textarea__inner,
.yuizaki-bg.yuizaki-bg .el-input-number,
.yuizaki-bg.yuizaki-bg .el-radio-button__inner,
.yuizaki-bg.yuizaki-bg .search-input,
.yuizaki-bg.yuizaki-bg .composer-box,
.yuizaki-bg.yuizaki-bg .message-bubble,
.yuizaki-bg.yuizaki-bg .md-content pre,
.yuizaki-bg.yuizaki-bg .md-content code {
  border-color: var(--yui-border);
  background: var(--yui-surface-raised);
  box-shadow: 0 0 0 1px var(--yui-border) inset;
}

.yuizaki-bg .el-input__wrapper,
.yuizaki-bg .el-select__wrapper,
.yuizaki-bg .el-input-number {
  border-radius: 10px;
}

.yuizaki-bg .el-textarea__inner {
  border-radius: 10px;
}

.yuizaki-bg .el-card__header {
  font-weight: 750;
}

.yuizaki-bg .panel-mode .el-alert__content,
.yuizaki-bg .panel-mode .el-alert__title,
.yuizaki-bg .panel-mode .el-alert__description {
  min-width: 0;
  max-width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
}

.yuizaki-bg .panel-mode .el-slider {
  max-width: 100%;
  min-width: 0;
}

.yuizaki-bg .panel-mode .el-card__body,
.yuizaki-bg .panel-mode .el-card__header,
.yuizaki-bg .panel-mode .toolbar-actions,
.yuizaki-bg .panel-mode .hero-actions,
.yuizaki-bg .panel-mode .card-head,
.yuizaki-bg .panel-mode .card-header,
.yuizaki-bg .panel-mode .section-header {
  min-width: 0;
}

.yuizaki-bg .panel-mode .toolbar-actions,
.yuizaki-bg .panel-mode .hero-actions {
  flex-wrap: wrap;
}

.yuizaki-bg .panel-mode .metric-card,
.yuizaki-bg .panel-mode .summary-card,
.yuizaki-bg .panel-mode .status-card,
.yuizaki-bg .panel-mode .panel-card {
  min-width: 0;
  box-sizing: border-box;
}

.yuizaki-bg .app-main.panel-mode > .view-host > .view-component > .panel-shell {
  background: var(--yui-panel-surface-strong, var(--yui-panel-surface));
}

.yuizaki-bg .el-table,
.yuizaki-bg .el-descriptions {
  max-width: 100%;
  overflow-x: auto;
}

body .el-dialog,
body .el-message-box,
body .el-drawer,
body .el-popper,
body .el-select__popper,
body .el-picker-panel,
body .el-dropdown__popper {
  border-color: var(--yui-border);
  border-radius: var(--yui-radius-panel);
  background: var(--yui-surface-raised);
  box-shadow: 0 24px 72px rgba(15, 23, 42, 0.18);
}

body .el-dialog__header,
body .el-dialog__body,
body .el-message-box__header,
body .el-message-box__content,
body .el-drawer__header,
body .el-drawer__body,
body .el-popper .el-select-dropdown,
body .el-popper .el-dropdown-menu {
  background: transparent;
}

[data-theme='dark'] .yuizaki-bg .el-card,
[data-theme='dark'] .yuizaki-bg .el-tabs--border-card,
[data-theme='dark'] .yuizaki-bg .el-table,
[data-theme='dark'] .yuizaki-bg .el-descriptions,
[data-theme='dark'] .yuizaki-bg .el-alert {
  border-color: rgba(51, 65, 85, 0.72);
  background: rgba(15, 23, 42, 0.36);
  color: #e5e7eb;
}

[data-theme='dark'] body .el-dialog,
[data-theme='dark'] body .el-message-box,
[data-theme='dark'] body .el-drawer,
[data-theme='dark'] body .el-popper,
[data-theme='dark'] body .el-select__popper,
[data-theme='dark'] body .el-picker-panel,
[data-theme='dark'] body .el-dropdown__popper {
  border-color: rgba(51, 65, 85, 0.72);
  background: rgba(15, 23, 42, 0.94);
  color: #e5e7eb;
}

[data-theme='dark'] body .el-select-dropdown__item,
[data-theme='dark'] body .el-dropdown-menu__item,
[data-theme='dark'] body .el-message-box__title,
[data-theme='dark'] body .el-dialog__title {
  color: #e5e7eb;
}

[data-theme='dark'] .yuizaki-bg .sidebar {
  border-color: rgba(148, 163, 184, 0.42);
  background:
    linear-gradient(155deg, rgba(30, 41, 59, 0.76), rgba(15, 23, 42, 0.88)),
    rgba(15, 23, 42, 0.92);
}

[data-theme='dark'] .yuizaki-bg .brand-name,
[data-theme='dark'] .yuizaki-bg .menu-item,
[data-theme='dark'] .yuizaki-bg .menu-item.admin {
  color: #dbeafe;
}

[data-theme='dark'] .yuizaki-bg .menu-section-label,
[data-theme='dark'] .yuizaki-bg .admin-label {
  color: #93a4bd;
}

[data-theme='dark'] .yuizaki-bg .menu-item:hover,
[data-theme='dark'] .yuizaki-bg .menu-item.active {
  border-color: rgba(226, 232, 240, 0.42);
  background: rgba(226, 232, 240, 0.1);
  color: #f8fafc;
}
</style>
