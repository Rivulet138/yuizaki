<template>
  <div class="browser-stage" :style="stageStyle">
    <AppSidebar
      class="stage-sidebar"
      :active-workspace-id="activeWorkspace.id"
      :menus="menus"
      @open-workspace-settings="$emit('open-workspace-settings')"
    />

    <div class="stage-content">
      <header class="stage-toolbar">
        <div class="stage-brand">
          <div>
            <strong>{{ activeWorkspace.name || t('chat.stage.workspaceFallback') }}</strong>
            <span class="stage-subtitle">{{ t('chat.stage.subtitle') }}</span>
          </div>
          <span class="stage-live">{{ realtimeConnected ? t('chat.stage.online') : t('chat.stage.connecting') }}</span>
        </div>

        <div class="stage-actions">
          <button class="stage-text-button" type="button" :title="t('chat.stage.language')" @click="showLocale = !showLocale">
            {{ t('chat.stage.language') }}
          </button>
        </div>

        <div v-if="showLocale" class="locale-menu">
          <button v-for="locale in localeOptions" :key="locale.value" type="button" @click="changeLocale(locale.value)">
            {{ locale.label }}
          </button>
        </div>
      </header>

      <main class="stage-main">
        <section class="stage-display" :aria-label="t('chat.stage.modelLabel')">
          <BrowserPetStage
            ref="petStageRef"
            :key="compactStage ? 'compact' : 'desktop'"
            @zoom-change="modelZoom = $event"
          />
        </section>

        <aside v-if="chatOpen" class="stage-window stage-chat-window">
          <div class="stage-window-zoom-controls" role="group" :aria-label="t('chat.stage.modelZoom')">
            <button
              class="stage-window-zoom-button"
              type="button"
              :title="t('chat.stage.zoomOut')"
              :aria-label="t('chat.stage.zoomOut')"
              :disabled="modelZoom <= MODEL_ZOOM_MIN"
              @click.stop="changeModelZoom(-ZOOM_STEP)"
            >
              <el-icon><ZoomOut /></el-icon>
            </button>
            <button
              class="stage-window-zoom-button"
              type="button"
              :title="t('chat.stage.zoomReset')"
              :aria-label="t('chat.stage.zoomReset')"
              @click.stop="resetModelZoom"
            >
              <el-icon><Refresh /></el-icon>
            </button>
            <button
              class="stage-window-zoom-button"
              type="button"
              :title="t('chat.stage.zoomIn')"
              :aria-label="t('chat.stage.zoomIn')"
              :disabled="modelZoom >= MODEL_ZOOM_MAX"
              @click.stop="changeModelZoom(ZOOM_STEP)"
            >
              <el-icon><ZoomIn /></el-icon>
            </button>
          </div>
          <header class="stage-window-header">
            <div>
              <strong>{{ t('chat.title') }}</strong>
            </div>
            <button class="stage-close" type="button" :title="t('chat.stage.close')" :aria-label="t('chat.stage.close')" @click="chatOpen = false">
              <el-icon><Close /></el-icon>
            </button>
          </header>
          <div class="stage-window-body chat-mode">
            <router-view v-slot="{ Component, route }">
              <component :is="Component" v-if="Component && route.name === 'chat'" class="stage-route-component" />
            </router-view>
          </div>
        </aside>

        <button v-else class="stage-reopen" type="button" :title="t('chat.stage.open')" @click="chatOpen = true">
          <el-icon><ChatDotRound /></el-icon>
          <span>{{ t('chat.stage.open') }}</span>
        </button>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ChatDotRound, Close, Refresh, ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import type { NavigationModule } from '@/navigation/types'
import type { WorkspaceRecord } from '@/../shared/workspace'
import { getSocketClient } from '@/net/socketClient'
import { useI18n } from '@/i18n'
import AppSidebar from './AppSidebar.vue'
import BrowserPetStage from './BrowserPetStage.vue'

const props = defineProps<{
  currentWallpaper: string
  menus: NavigationModule[]
  activeWorkspace: WorkspaceRecord
}>()

const emit = defineEmits<{
  changeLocale: [locale: string]
  'open-workspace-settings': []
}>()
const { t } = useI18n()

const chatOpen = ref(true)
const showLocale = ref(false)
const compactStage = ref(false)
const petStageRef = ref<{ adjustZoom: (delta: number) => void; resetZoom: () => void } | null>(null)
const MODEL_ZOOM_MIN = 1.2
const MODEL_ZOOM_MAX = 3
const ZOOM_STEP = 0.1
const modelZoom = ref(1.7)
const realtimeConnected = getSocketClient().connected
let compactMediaQuery: MediaQueryList | null = null

const localeOptions = [
  { value: 'zh-CN', label: '中文' },
  { value: 'en-US', label: 'EN' },
  { value: 'ja-JP', label: '日本語' },
]
const stageStyle = computed(() => ({
  '--stage-wallpaper': props.currentWallpaper
    ? `url("${props.currentWallpaper}")`
    : 'url("/assets/chat-home-bg.jpg")',
}))

const changeLocale = (locale: string): void => {
  showLocale.value = false
  // Parent owns persistence and backend synchronization.
  emit('changeLocale', locale)
}

const syncCompactStage = (): void => {
  compactStage.value = compactMediaQuery?.matches ?? false
}

const changeModelZoom = (delta: number): void => {
  petStageRef.value?.adjustZoom(delta)
}

const resetModelZoom = (): void => {
  petStageRef.value?.resetZoom()
}

onMounted(() => {
  compactMediaQuery = window.matchMedia('(max-width: 860px)')
  syncCompactStage()
  compactMediaQuery.addEventListener('change', syncCompactStage)
})

onBeforeUnmount(() => {
  compactMediaQuery?.removeEventListener('change', syncCompactStage)
})
</script>

<style scoped>
.browser-stage {
  position: relative;
  display: flex;
  isolation: isolate;
  width: 100%;
  height: 100%;
  overflow: hidden;
  color: var(--yui-text);
  background: transparent;
  --stage-border: rgba(255, 255, 255, .58);
  --stage-chrome-surface: rgba(255, 255, 255, .18);
  --stage-frame: rgba(255, 255, 255, .68);
  --stage-window-surface: rgba(255, 255, 255, .86);
}

:global(:root[data-theme='dark']) .browser-stage {
  --stage-border: rgba(173, 207, 233, .42);
  --stage-chrome-surface: rgba(15, 23, 42, .58);
  --stage-frame: rgba(30, 41, 59, .9);
  --stage-window-surface: rgba(15, 23, 42, .78);
}

.browser-stage::before {
  position: absolute;
  inset: 0;
  z-index: 0;
  content: '';
  background-color: #edf2f7;
  background-image: var(--stage-wallpaper);
  background-position: center;
  background-size: cover;
  background-repeat: no-repeat;
}

:global(.yuizaki-bg.browser-mode .stage-sidebar.sidebar) {
  flex: 0 0 202px;
  height: 100%;
  background: var(--stage-chrome-surface);
  background-image: none;
  border-color: var(--stage-border);
  backdrop-filter: blur(4px) saturate(1.06);
}
.stage-content { position: relative; z-index: 1; display: flex; flex: 1; min-width: 0; min-height: 0; flex-direction: column; }
.stage-toolbar {
  position: relative;
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 58px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--stage-border);
  color: var(--yui-browser-text);
  background: var(--stage-chrome-surface);
  backdrop-filter: blur(4px) saturate(1.06);
}

.stage-brand, .stage-actions { display: flex; align-items: center; gap: 10px; }
.stage-brand strong { display: block; font-size: 14px; font-weight: 750; letter-spacing: .02em; }
.stage-subtitle { display: block; margin-top: 2px; color: var(--yui-muted); font-size: 10px; }
.stage-live { color: var(--yui-muted); font-size: 10px; }
.stage-text-button, .stage-close { min-height: 30px; padding: 0 9px; border: 1px solid var(--stage-border); border-radius: 7px; color: var(--yui-muted); background: rgba(255, 255, 255, .18); cursor: pointer; text-decoration: none; transition: background .16s ease, border-color .16s ease, color .16s ease; }
.stage-text-button:hover, .stage-text-button.active, .stage-close:hover { border-color: rgba(255, 255, 255, .96); color: var(--yui-text); background: rgba(255, 255, 255, .42); }
.locale-menu { position: absolute; top: 52px; right: 18px; z-index: 6; display: grid; min-width: 110px; padding: 6px; border: 1px solid var(--yui-border); border-radius: 8px; background: var(--yui-surface-raised); box-shadow: var(--yui-shadow-card); }
.locale-menu button { padding: 8px 10px; border: 0; color: var(--yui-text); background: transparent; text-align: left; cursor: pointer; }
.locale-menu button:hover { background: var(--yui-chat-hover); }

.stage-main {
  position: relative;
  display: flex;
  flex: 1;
  width: auto;
  min-height: 0;
  gap: 14px;
  margin: 14px 18px 18px;
  overflow: hidden;
}

.stage-display {
  position: relative;
  display: grid;
  flex: 1;
  min-width: 0;
  min-height: 0;
  place-items: center;
  overflow: hidden;
  isolation: isolate;
  border: 6px solid var(--stage-frame);
  border-radius: 26px;
  background-color: #edf2f7;
  background-image: url('/assets/echobot-reference-bg.jpg');
  background-position: center;
  background-size: cover;
  background-repeat: no-repeat;
  backdrop-filter: none;
  box-shadow: 0 0 0 1px rgba(15, 23, 42, .18), 0 18px 46px rgba(15, 23, 42, .18), inset 0 0 0 1px rgba(255, 255, 255, .58);
  padding: 18px 26px;
}

.stage-window { position: relative; z-index: 3; display: flex; flex-direction: column; width: clamp(360px, 31vw, 480px); min-width: 340px; margin: 0; overflow: hidden; border: 7px solid var(--stage-frame); border-radius: 28px; color: var(--yui-text); background: var(--stage-window-surface); box-shadow: 0 0 0 1px rgba(15, 23, 42, .18), 0 20px 52px rgba(15, 23, 42, .2), inset 0 0 0 1px rgba(255, 255, 255, .68); }
.stage-window-header { position: relative; z-index: 2; display: flex; align-items: center; justify-content: space-between; min-height: 48px; padding: 8px 12px 8px 16px; border-bottom: 1px solid rgba(255, 255, 255, .42); background: rgba(255, 255, 255, .28); }
.stage-window-header div { display: flex; align-items: baseline; }
.stage-window-header strong { font-size: 14px; }
.stage-window-header span { color: var(--yui-muted); font-size: 10px; }
.stage-window-body { position: relative; z-index: 1; flex: 1; min-height: 0; overflow: hidden; background: rgba(255, 255, 255, .08); }
.stage-route-component { width: 100%; height: 100%; }
.stage-window-zoom-controls { position: absolute; top: 78px; left: 14px; z-index: 4; display: inline-flex; align-items: center; gap: 6px; padding: 5px; border: 1px solid rgba(255, 255, 255, .72); border-radius: 10px; background: rgba(255, 255, 255, .62); box-shadow: 0 8px 18px rgba(15, 23, 42, .14); backdrop-filter: blur(5px); }
.stage-window-zoom-button { display: inline-grid; width: 30px; height: 30px; padding: 0; place-items: center; border: 1px solid rgba(148, 163, 184, .42); border-radius: 7px; color: #334155; background: rgba(255, 255, 255, .72); cursor: pointer; transition: background .16s ease, border-color .16s ease, color .16s ease, opacity .16s ease; }
.stage-window-zoom-button:hover:not(:disabled) { border-color: rgba(71, 85, 105, .58); color: #0f172a; background: #fff; }
.stage-window-zoom-button:focus-visible { outline: 2px solid rgba(59, 130, 246, .72); outline-offset: 2px; }
.stage-window-zoom-button:disabled { cursor: not-allowed; opacity: .4; }
.stage-reopen { position: absolute; right: 20px; bottom: 20px; z-index: 5; display: inline-flex; align-items: center; gap: 7px; min-height: 36px; padding: 0 12px; border: 1px solid var(--yui-border); border-radius: 8px; color: var(--yui-text); background: var(--yui-panel-surface-strong); box-shadow: var(--yui-shadow-card); cursor: pointer; }
.stage-reopen:hover { border-color: var(--yui-border-strong); background: var(--yui-surface-raised); }

.stage-window-body :deep(.chat-workspace) {
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.stage-window-body :deep(.session-rail-pane) {
  background: rgba(255, 255, 255, .2);
}

:global(:root[data-theme='dark']) .stage-window-header,
:global(:root[data-theme='dark']) .stage-window-body :deep(.session-rail-pane) {
  background: rgba(15, 23, 42, .76);
}

:global(:root[data-theme='dark']) .stage-window {
  background: var(--stage-window-surface);
}

:global(:root[data-theme='dark']) .stage-window-zoom-controls {
  border-color: rgba(148, 163, 184, .42);
  background: rgba(15, 23, 42, .72);
}

:global(:root[data-theme='dark']) .stage-window-zoom-button {
  border-color: rgba(148, 163, 184, .44);
  color: #dbeafe;
  background: rgba(30, 41, 59, .82);
}

:global(:root[data-theme='dark']) .stage-window-body {
  background: rgba(15, 23, 42, .2);
}

@media (max-width: 860px) {
  .stage-sidebar { flex-basis: 68px; width: 68px; }
  .stage-sidebar :deep(.sidebar) { width: 68px; min-width: 68px; padding: 14px 8px; }
  .stage-sidebar :deep(.brand-wordmark), .stage-sidebar :deep(.menu-label), .stage-sidebar :deep(.admin-toggle-label), .stage-sidebar :deep(.admin-toggle-icon), .stage-sidebar :deep(.menu-group-label), .stage-sidebar :deep(.settings-action) { display: none; }
  .stage-sidebar :deep(.brand) { justify-content: center; padding: 0 0 14px; }
  .stage-sidebar :deep(.brand-name) { display: block; font-size: 16px; }
  .stage-sidebar :deep(.menu-item) { justify-content: center; padding: 0; }
  .stage-main { display: block; overflow: auto; }
  .stage-display { min-height: 520px; height: calc(100vh - 58px); }
  .stage-main { margin: 10px 10px 12px; }
  .stage-display { padding: 12px 14px; }
  .stage-window { position: absolute; top: 12px; right: 12px; bottom: 12px; width: min(360px, calc(100% - 24px)); min-width: 0; border-width: 5px; border-radius: 24px; }
  .stage-display :deep(.browser-pet-stage) { transform: translateX(-28%); }
  .stage-actions { gap: 6px; }
  .stage-brand strong, .stage-subtitle, .stage-live { display: none; }
}
</style>
