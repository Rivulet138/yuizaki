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
        <div v-if="showOfflineBanner" class="offline-banner">
          <span>{{ t('shell.offline') }}</span>
          <button type="button" @click="retryConnection">{{ t('shell.retry') }}</button>
        </div>

        <div class="content-frame" :class="{ 'has-offline-banner': showOfflineBanner }">
          <AppTopbar
            v-if="activeTab !== 'chat'"
            :active-workspace="activeWorkspace"
            :companion-id="activeWorkspace.companion_profile_id || companionStore.activeCompanionId"
            :companions="companionOptions"
            :title="yuizakiConfig.heroTitle"
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

          <main class="app-main" :class="activeTab === 'chat' ? 'chat-mode' : 'panel-mode'">
            <div v-if="activeTab !== 'chat'" class="chat-bar">
              <div v-if="chatState.isGenerating || chatState.currentText" class="chat-status">
                <span class="status-dot" :class="{ active: chatState.isGenerating }"></span>
                <span class="status-text">
                  {{ chatState.isGenerating ? t('shell.status.thinking') : chatState.isSpeaking ? t('shell.status.speaking') : t('shell.status.idle') }}
                </span>
                <button v-if="chatState.isGenerating" class="interrupt-btn" type="button" @click="chatStore.interrupt()">{{ t('shell.status.interrupt') }}</button>
              </div>

              <div v-if="chatState.currentText" class="streaming-bubble animate-fade-in">
                <div class="streaming-avatar">結</div>
                <div class="streaming-content">
                  {{ chatState.currentText }}
                  <span v-if="chatState.isGenerating" class="cursor-blink">▍</span>
                </div>
              </div>

            </div>

            <div class="view-host">
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
import { getSocketClient, SocketEvents } from '@/net/socketClient'
import { useChatStore } from '@/stores/chatStore'
import { useCompanionStore } from '@/stores/companionStore'
import { useDialogStore, type PermissionRequestPayload } from '@/stores/dialogStore'
import { useSystemStore, type VisualAnalysisStatus } from '@/stores/systemStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useSettingsStore } from '@/state/settingsStore'
import { useInputBindingsStore } from '@/state/inputBindingsStore'
import { isTerminalVisualFrameResult, VisualCaptureEpoch } from '@/visual-capture-epoch'
import { setLocale, syncLocaleFromSettings, t } from '@/i18n'
import { adminNavigationModules, isPanelKey, primaryNavigationModules, type NavigationModuleId } from '@/navigation/modules'
import { logger } from '@/logger'
import { calculateFrameDifference, computeFrameSignature } from '@/vision/frame-signature'
import {
  normalizeVisualCaptureInterval,
  resolveVisualCaptureBlockReason,
  resolveVisualCapturePolicy,
} from '@/vision/capture-policy'
import { audioCapture } from '@/audio/audio-capture'
import AppSidebar from './AppSidebar.vue'
import AppTopbar from './AppTopbar.vue'
import GlobalDialogs from './components/dialogs/GlobalDialogs.vue'
import { useAppOrchestrator } from './orchestrators/useAppOrchestrator'
import { useVoiceConversationBridge } from './composables/useVoiceConversationBridge'
import { advanceCompanionCooldownForE2E, useCompanionRuntimeBridge } from './composables/useCompanionRuntimeBridge'
import { publishCompanionRuntimeEvent } from './runtime/companionRuntime'
import { createAppRuntimeTeardown } from './runtime/appRuntimeTeardown'

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
  return (segments[2] || 'companion') as NavigationModuleId
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
  intervalMs: 30_000,
  pauseWhenAppHidden: true,
  captureMode: 'display' as const,
  region: { x: 0, y: 0, width: 1280, height: 720 },
  privacyMasks: [],
})
const adminMode = ref(
  typeof window !== 'undefined' && window.localStorage.getItem(ADMIN_MODE_STORAGE_KEY) === 'true',
)
const chatState = computed(() => chatStore.state)
const audioCaptureState = audioCapture.getStatus()
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
const showOfflineBanner = computed(() => (
  systemStore.statusChecked &&
  !systemStore.pythonRunning &&
  !systemStore.sioConnected
))

let visualFrameTimer: number | null = null
let visualFrameInFlight = false
let visualFrameSeq = 0
let lastVisualFrameSignature: Uint8Array | null = null
let lastVisualFrameSentAt = 0
const pendingVisualResults = new Map<string, {
  resolve: (payload: Record<string, unknown>) => void
  reject: (error: Error) => void
  timeout: number
}>()
const visualCaptureEpoch = new VisualCaptureEpoch()
let themeMediaQuery: MediaQueryList | null = null
let healthScheduleEnabled = !e2eMode
let visualScheduleEnabled = !e2eMode
let companionScheduleEnabled = !e2eMode
let disposeE2EControls: (() => void) | null = null
let e2eInitialHealthChecked = false

const VISUAL_CHANGE_THRESHOLD = 0.035
const VISUAL_CAPTURE_ENCODING = {
  maxWidth: 1280,
  maxHeight: 720,
  format: 'jpeg' as const,
  quality: 72,
}
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
      if (left.id === 'companion' && right.id !== 'companion') return -1
      if (right.id === 'companion' && left.id !== 'companion') return 1
      const leftOrder = orderMap.get(left.id) ?? Number.MAX_SAFE_INTEGER
      const rightOrder = orderMap.get(right.id) ?? Number.MAX_SAFE_INTEGER
      return leftOrder - rightOrder || (left.order ?? 0) - (right.order ?? 0)
    })
})

const adminMenus = computed(() => (adminMode.value ? localAdminMenus.value : []))

const retryConnection = () => {
  const socketClient = getSocketClient()
  socketClient.connect()
  systemStore.refreshStatus(
    () => socketClient.isConnected(),
    () => socketClient.isConnected(),
  )
}

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

const captureRealtimeVisualFrame = async (
  requestedFrameId?: string,
  forceEnabled = false,
): Promise<string> => {
  const vision = activeVisionSettings.value
  const socketClient = getSocketClient()
  const blockReason = resolveVisualCaptureBlockReason({
    enabled: forceEnabled || vision.enabled,
    pauseWhenAppHidden: vision.pauseWhenAppHidden,
    documentHidden: document.hidden,
    servicesHealthy: systemStore.controlRunning && systemStore.pythonRunning,
    socketConnected: socketClient.isConnected(),
  })
  if (blockReason === 'health-unavailable') {
    return `skipped:health:${systemStore.controlRunning}:${systemStore.pythonRunning}`
  }
  if (blockReason) return `skipped:${blockReason}`
  const screenApi = petApi?.screen
  if (!screenApi?.capture) {
    systemStore.markVisualPerceptionError('当前环境不支持屏幕采集')
    return 'skipped:capture-api-unavailable'
  }
  if (visualFrameInFlight) return 'skipped:capture-in-flight'
  const capturePolicy = resolveVisualCapturePolicy({
    configuredIntervalMs: vision.intervalMs,
    microphoneRecording: audioCaptureState.isRecording,
    microphoneLevel: audioCaptureState.level,
    hasPartialTranscript: Boolean(chatState.value.asrPartialText),
    assistantSpeaking: chatState.value.isTTSPlaying || chatState.value.isSpeaking,
  })
  if (!capturePolicy.shouldCapture) return 'skipped:capture-policy'

  const captureEpoch = visualCaptureEpoch.current()
  visualFrameInFlight = true
  try {
    const captureOptions = {
      ...VISUAL_CAPTURE_ENCODING,
      privacyMasks: vision.privacyMasks.map((mask) => ({ ...mask })),
    }
    const image = vision.captureMode === 'region' && screenApi.captureRegion
      ? await screenApi.captureRegion(
          vision.region.x,
          vision.region.y,
          vision.region.width,
          vision.region.height,
          vision.displayIndex,
          captureOptions,
        )
      : await screenApi.capture(vision.displayIndex, captureOptions)
    if (!visualCaptureEpoch.isCurrent(captureEpoch)) return 'skipped:capture-invalidated'
    if (typeof image !== 'string' || !image.startsWith('data:image/')) {
      systemStore.markVisualPerceptionError('没有捕获到可用画面')
      return 'skipped:invalid-image'
    }
    const signature = await computeFrameSignature(image)
    if (!visualCaptureEpoch.isCurrent(captureEpoch)) return 'skipped:signature-invalidated'
    const now = Date.now()
    const initialFrame = lastVisualFrameSignature === null
    const changeScore = initialFrame
      ? 1
      : calculateFrameDifference(lastVisualFrameSignature, signature)
    const intervalElapsed = now - lastVisualFrameSentAt >= capturePolicy.minUploadIntervalMs
    const changed = initialFrame || changeScore >= VISUAL_CHANGE_THRESHOLD
    const forceFrame = Number.isFinite(capturePolicy.forceUploadIntervalMs)
      && now - lastVisualFrameSentAt >= capturePolicy.forceUploadIntervalMs
    if ((!changed || !intervalElapsed) && !forceFrame) return 'skipped:unchanged'

    const captureReason = initialFrame
      ? 'initial'
      : audioCaptureState.isRecording
        ? 'voice_change'
        : changed
          ? 'change'
          : 'heartbeat'

    systemStore.markVisualPerceptionCapturing()
    visualFrameSeq += 1
    const frameId = requestedFrameId ?? `renderer-${Date.now()}-${visualFrameSeq}`
    visualCaptureEpoch.trackFrame(frameId, captureEpoch, forceEnabled)
    socketClient.requestScreenshot(image, {
      displayIndex: vision.displayIndex,
      region: vision.captureMode === 'region' ? { ...vision.region } : undefined,
      mode: 'observe',
      source: vision.captureMode === 'region' ? 'desktop_region' : 'desktop',
      timestamp: Date.now(),
      frameId,
      changeScore,
      captureReason,
    })
    lastVisualFrameSignature = signature
    lastVisualFrameSentAt = now
    return frameId
  } catch (error) {
    if (!visualCaptureEpoch.isCurrent(captureEpoch)) return 'skipped:capture-error-invalidated'
    logger.warn('Failed to capture realtime visual frame:', error)
    systemStore.markVisualPerceptionError(error instanceof Error ? error.message : '实时视觉采集失败')
    return `skipped:capture-error:${error instanceof Error ? error.message : String(error)}`
  } finally {
    visualFrameInFlight = false
  }
}

const handleVisualFrameResult = (value: unknown) => {
  if (!value || typeof value !== 'object') return
  const payload = value as Record<string, unknown>
  const frameId = typeof payload.frame_id === 'string' ? payload.frame_id : null
  const pending = frameId ? pendingVisualResults.get(frameId) : undefined
  const terminalResult = isTerminalVisualFrameResult(payload)
  const accepted = frameId
    ? visualCaptureEpoch.acceptResult(frameId, activeVisionSettings.value.enabled, terminalResult)
    : false
  if (!accepted) {
    if (frameId && pending) {
      window.clearTimeout(pending.timeout)
      pendingVisualResults.delete(frameId)
      pending.reject(new Error(`Visual frame result was invalidated: ${frameId}`))
    }
    return
  }
  if (typeof payload.error === 'string' && payload.error) {
    if (frameId && pending) {
      window.clearTimeout(pending.timeout)
      pendingVisualResults.delete(frameId)
      pending.reject(new Error(payload.error))
    }
    systemStore.markVisualPerceptionError(
      typeof payload.message === 'string' && payload.message ? payload.message : payload.error,
    )
    return
  }
  if (payload.status !== 'ok' || payload.mode !== 'observe') return
  if (frameId && pending) {
    window.clearTimeout(pending.timeout)
    pendingVisualResults.delete(frameId)
    pending.resolve(payload)
  }
  systemStore.markVisualPerceptionReady(
    typeof payload.frame_id === 'string' ? payload.frame_id : null,
    typeof payload.received_at === 'number' ? payload.received_at : null,
    {
      analysisStatus: typeof payload.analysis_status === 'string'
        ? payload.analysis_status as VisualAnalysisStatus
        : null,
      analysisReason: typeof payload.analysis_reason === 'string' ? payload.analysis_reason : null,
      analysisAttempts: typeof payload.analysis_attempts === 'number' ? payload.analysis_attempts : null,
      analysisSkipped: typeof payload.analysis_skipped === 'number' ? payload.analysis_skipped : null,
      changeScore: typeof payload.change_score === 'number' ? payload.change_score : null,
      captureReason: typeof payload.capture_reason === 'string' ? payload.capture_reason : null,
      analysisLatencyMs: typeof payload.analysis_latency_ms === 'number' ? payload.analysis_latency_ms : null,
    },
  )
}

const waitForVisualFrameResult = (frameId: string): Promise<Record<string, unknown>> => (
  new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      pendingVisualResults.delete(frameId)
      visualCaptureEpoch.forgetFrame(frameId)
      reject(new Error(`Visual frame result timed out: ${frameId}`))
    }, 20_000)
    pendingVisualResults.set(frameId, { resolve, reject, timeout })
  })
)

const cancelVisualFrameResultWait = (frameId: string) => {
  const pending = pendingVisualResults.get(frameId)
  if (!pending) return
  window.clearTimeout(pending.timeout)
  pendingVisualResults.delete(frameId)
  visualCaptureEpoch.forgetFrame(frameId)
}

const restartVisualFrameTimer = () => {
  visualCaptureEpoch.invalidate()
  const hadUploadedVisualContext = lastVisualFrameSentAt > 0
  if (visualFrameTimer) {
    window.clearInterval(visualFrameTimer)
    visualFrameTimer = null
  }
  const vision = activeVisionSettings.value
  systemStore.setVisualPerceptionEnabled(vision.enabled)
  lastVisualFrameSignature = null
  lastVisualFrameSentAt = 0
  if (!vision.enabled) {
    if (hadUploadedVisualContext) getSocketClient().clearVisualContext()
    return
  }
  if (!visualScheduleEnabled) return
  if (vision.pauseWhenAppHidden && document.hidden) return
  const samplingIntervalMs = normalizeVisualCaptureInterval(vision.intervalMs)
  visualFrameTimer = window.setInterval(() => {
    void captureRealtimeVisualFrame()
  }, samplingIntervalMs)
}

const handleVisibilityChange = () => {
  if (visualScheduleEnabled && activeVisionSettings.value.pauseWhenAppHidden) {
    restartVisualFrameTimer()
  }
}

const handlePermissionRequest = (data: PermissionRequestPayload) => {
  void publishCompanionRuntimeEvent({ source: 'permission', permission: 'waiting', requestId: data.request_id })
  dialogStore.openPermissionRequest(data)
}

const stopAppRuntime = () => {
  visualCaptureEpoch.invalidate()
  window.removeEventListener('keydown', handleGlobalKeydown)
  petApi?.off?.('panel:open-tab', handlePanelOpenTab)
  petApi?.off?.('shortcut:toggle-vision', handleToggleVisionShortcut)
  themeMediaQuery?.removeEventListener('change', applyTheme)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  systemStore.stopHealthCheck()
  companionRuntime.stopCompanionRuntime()
  if (visualFrameTimer) window.clearInterval(visualFrameTimer)
  visualFrameTimer = null
  for (const [frameId, pending] of pendingVisualResults) {
    window.clearTimeout(pending.timeout)
    pending.reject(new Error(`Visual frame result wait cancelled: ${frameId}`))
  }
  pendingVisualResults.clear()
  const socketClient = getSocketClient()
  socketClient.off(SocketEvents.PERMISSION_REQUEST, handlePermissionRequest)
  socketClient.off(SocketEvents.SCREENSHOT_RESULT, handleVisualFrameResult)
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
      case 'pauseVisualSampling':
        visualScheduleEnabled = false
        restartVisualFrameTimer()
        return { paused: true }
      case 'sampleVisualOnce':
        {
          const socketDeadline = Date.now() + 5_000
          while (!socketClient.isConnected()) {
            if (Date.now() >= socketDeadline) throw new Error('Visual sample Socket connection timed out')
            await new Promise(resolve => window.setTimeout(resolve, 25))
          }
          const frameId = `renderer-e2e-${Date.now()}-${visualFrameSeq + 1}`
          const resultPromise = waitForVisualFrameResult(frameId)
          const sentFrameId = await captureRealtimeVisualFrame(frameId, true)
          if (sentFrameId !== frameId) {
            cancelVisualFrameResultWait(frameId)
            throw new Error(`Visual frame was not captured: ${sentFrameId}`)
          }
          const result = await resultPromise
          return { sampled: true, frameId, status: result['status'] }
        }
      case 'resumeVisualSampling':
        visualScheduleEnabled = true
        restartVisualFrameTimer()
        return { resumed: true }
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
  document.addEventListener('visibilitychange', handleVisibilityChange)

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
  socketClient.on(SocketEvents.SCREENSHOT_RESULT, handleVisualFrameResult)

  if (companionScheduleEnabled) {
    companionRuntime.startCompanionRuntime(() => systemStore.controlRunning && systemStore.pythonRunning)
  }
  if (visualScheduleEnabled) restartVisualFrameTimer()

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
  if (visualScheduleEnabled) restartVisualFrameTimer()
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
  padding: 18px 20px 20px;
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
  opacity: 0.98;
  transition: opacity 0.3s ease;
}

.wallpaper-blur {
  z-index: 0;
  background-position: center;
  background-size: cover;
  filter: blur(24px) saturate(1.18);
  opacity: 0;
}

.wallpaper-mask {
  z-index: 1;
  background: transparent;
}

.wallpaper-on .wallpaper-layer {
  opacity: 1;
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
  border-radius: var(--yui-radius-panel);
  background: var(--yui-surface);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.12);
}

.app-main.panel-mode {
  padding: 18px 24px 22px;
}

.app-main.chat-mode {
  padding: 0;
  border-color: transparent;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
}

.main--chat .wallpaper-layer {
  opacity: var(--yui-chat-wallpaper-opacity);
  filter: saturate(0.92) contrast(0.98);
}

.main--chat .wallpaper-mask {
  background: var(--yui-chat-wallpaper-mask);
}

.main--chat .wallpaper-blur {
  opacity: 0;
}

.chat-bar {
  flex-shrink: 0;
  margin-bottom: 16px;
}

.chat-status {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: min(2020px, calc(100vw - 590px));
  margin-bottom: 8px;
  padding: 8px 12px;
  border: 1px solid rgba(255, 255, 255, 0.58);
  border-radius: 999px;
  color: #4d5274;
  background: rgba(255, 255, 255, 0.14);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(18px) saturate(1.25);
  font-size: 14px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
}

.status-dot.active {
  background: #f59e0b;
  animation: pulse-dot 1.5s infinite;
}

.status-text {
  flex: 1;
}

.interrupt-btn {
  border: none;
  border-radius: 10px;
  padding: 4px 12px;
  color: #dc2626;
  background: rgba(255, 242, 242, 0.48);
  backdrop-filter: blur(16px);
  font-size: 13px;
  cursor: pointer;
}

.streaming-bubble {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  width: 100%;
  max-width: 780px;
  margin-bottom: 10px;
  padding: 14px 18px;
  border: 1px solid rgba(255, 255, 255, 0.62);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.14);
  box-shadow: 0 16px 38px rgba(82, 82, 130, 0.13), inset 0 1px 0 rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(18px) saturate(1.16);
}

.streaming-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  color: transparent;
  background: #fff url('../assets/yuizaki/icons/yuizaki-icon.png') center / cover no-repeat;
  box-shadow: 0 8px 24px rgba(169, 102, 255, 0.32);
  font-size: 0;
  font-weight: 700;
}

.streaming-content {
  flex: 1;
  color: #1e293b;
  font-size: 15px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.cursor-blink {
  display: inline-block;
  color: #6366f1;
  font-weight: 700;
  animation: blink 1s step-end infinite;
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

.offline-banner {
  position: absolute;
  top: 6px;
  left: 50%;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 10px;
  transform: translateX(-50%);
  padding: 6px 16px;
  border: 1px solid #fecaca;
  border-radius: 10px;
  color: #dc2626;
  background: #fef2f2;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  font-size: 14px;
}

.offline-banner button {
  border: none;
  border-radius: 6px;
  color: #fff;
  background: #dc2626;
  padding: 4px 12px;
  font-size: 13px;
  cursor: pointer;
}

.shortcuts-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(31, 34, 65, 0.28);
  backdrop-filter: blur(12px);
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
    padding: 12px;
  }

  .main {
    min-width: 0;
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
    padding: 8px;
  }

  .app-main.panel-mode {
    padding: 10px;
  }

  .offline-banner {
    top: 10px;
    max-width: calc(100vw - 32px);
    white-space: nowrap;
  }

  .content-frame.has-offline-banner {
    box-sizing: border-box;
    padding-top: 54px;
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
  --yui-surface-muted: #f6f8fb;
  --yui-surface-subtle: #eef4fb;
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
  --yui-chat-page-bg: #f8fafc;
  --yui-chat-wallpaper-opacity: 0.82;
  --yui-chat-wallpaper-mask: rgba(248, 250, 252, 0.34);
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
  --yui-surface-muted: #1e293b;
  --yui-surface-subtle: #243044;
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
  --yui-chat-page-bg: #0f172a;
  --yui-chat-wallpaper-opacity: 0.56;
  --yui-chat-wallpaper-mask: rgba(15, 23, 42, 0.48);
  --yui-text: #e5e7eb;
  --yui-muted: #94a3b8;
}

.yuizaki-bg .el-card,
.yuizaki-bg .el-tabs--border-card,
.yuizaki-bg .el-table,
.yuizaki-bg .el-descriptions,
.yuizaki-bg .el-alert {
  border-color: var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
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
  border-color: var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
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
