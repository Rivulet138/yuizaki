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
          <span class="stage-brand-mark">結</span>
          <div>
            <strong>{{ activeWorkspace.name || '結崎' }}</strong>
            <span class="stage-subtitle">对话空间</span>
          </div>
          <span class="stage-live"><i></i>在线</span>
        </div>

        <div class="stage-actions">
        <button class="stage-icon-button" type="button" title="主题" aria-label="主题" @click="$emit('toggle-theme')">
          <el-icon><Moon /></el-icon>
        </button>
        <button class="stage-icon-button" type="button" title="语言" aria-label="语言" @click="showLocale = !showLocale">
          <el-icon><ChatDotRound /></el-icon>
        </button>
        </div>

        <div v-if="showLocale" class="locale-menu">
          <button v-for="locale in localeOptions" :key="locale.value" type="button" @click="changeLocale(locale.value)">
            {{ locale.label }}
          </button>
        </div>
      </header>

      <main class="stage-main">
        <section class="stage-display" aria-label="对话中的 Live2D 或 VRM 模型">
          <div class="stage-floor"><span></span></div>
          <BrowserPetStage :key="compactStage ? 'compact' : 'desktop'" />
          <div class="stage-caption">
            <span>{{ companionId || 'yumi' }}</span>
            <small>{{ companionStateLabel }}</small>
          </div>
        </section>

        <aside v-if="chatOpen" class="stage-window stage-chat-window">
          <header class="stage-window-header">
            <div>
              <strong>对话</strong>
              <span>{{ realtimeConnected ? '在线' : '连接中' }}</span>
            </div>
            <button class="stage-close" type="button" title="关闭聊天" aria-label="关闭聊天" @click="chatOpen = false">
              <el-icon><Close /></el-icon>
            </button>
          </header>
          <div class="stage-window-body chat-mode">
            <router-view v-slot="{ Component, route }">
              <component :is="Component" v-if="Component && route.name === 'chat'" class="stage-route-component" />
            </router-view>
          </div>
        </aside>

        <button v-else class="stage-reopen" type="button" title="打开聊天" @click="chatOpen = true">
          <el-icon><ChatDotRound /></el-icon>
          <span>打开聊天</span>
        </button>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ChatDotRound, Close, Moon } from '@element-plus/icons-vue'
import type { NavigationModuleId } from '@/navigation/modules'
import type { NavigationModule } from '@/navigation/types'
import type { WorkspaceRecord } from '@/../shared/workspace'
import { getSocketClient } from '@/net/socketClient'
import AppSidebar from './AppSidebar.vue'
import BrowserPetStage from './BrowserPetStage.vue'

const props = defineProps<{
  currentWallpaper: string
  activeTab: NavigationModuleId
  menus: NavigationModule[]
  activeWorkspace: WorkspaceRecord
  companionId: string
  companionStateLabel: string
}>()

const emit = defineEmits<{
  toggleTheme: []
  changeLocale: [locale: string]
  'open-workspace-settings': []
}>()

const chatOpen = ref(true)
const showLocale = ref(false)
const compactStage = ref(false)
const realtimeConnected = getSocketClient().connected
let compactMediaQuery: MediaQueryList | null = null

const localeOptions = [
  { value: 'zh-CN', label: '中文' },
  { value: 'en-US', label: 'EN' },
  { value: 'ja-JP', label: '日本語' },
]
const stageStyle = computed(() => ({
  '--stage-wallpaper': 'url("/assets/chat-depth-bg.jpg")',
  '--stage-user-wallpaper': props.currentWallpaper ? `url("${props.currentWallpaper}")` : 'none',
}))

const changeLocale = (locale: string): void => {
  showLocale.value = false
  // Parent owns persistence and backend synchronization.
  emit('changeLocale', locale)
}

const syncCompactStage = (): void => {
  compactStage.value = compactMediaQuery?.matches ?? false
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
  background: var(--yui-browser-bg);
}

.stage-sidebar { flex: 0 0 202px; height: 100%; }
.stage-content { position: relative; display: flex; flex: 1; min-width: 0; min-height: 0; flex-direction: column; }
.stage-toolbar {
  position: relative;
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 58px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--yui-browser-border);
  color: var(--yui-browser-text);
  background: var(--yui-browser-surface);
}

.stage-brand, .stage-actions { display: flex; align-items: center; gap: 10px; }
.stage-brand-mark { display: grid; width: 30px; height: 30px; place-items: center; border: 1px solid var(--yui-border-strong); border-radius: 50%; font-weight: 800; }
.stage-brand strong { display: block; font-size: 14px; font-weight: 750; letter-spacing: .02em; }
.stage-subtitle { display: block; margin-top: 2px; color: var(--yui-muted); font-size: 10px; }
.stage-live { display: inline-flex; align-items: center; gap: 5px; color: var(--yui-muted); font-size: 10px; letter-spacing: .14em; }
.stage-live i { width: 6px; height: 6px; border-radius: 50%; background: #fb7185; box-shadow: 0 0 0 4px rgba(251,113,133,.15); }
.stage-icon-button, .stage-close { display: grid; width: 34px; height: 34px; padding: 0; place-items: center; border: 1px solid var(--yui-border); border-radius: 8px; color: var(--yui-muted); background: var(--yui-panel-surface); cursor: pointer; text-decoration: none; transition: background .16s ease, border-color .16s ease, color .16s ease; }
.stage-icon-button:hover, .stage-icon-button.active, .stage-close:hover { border-color: var(--yui-border-strong); color: var(--yui-text); background: var(--yui-panel-surface-strong); }
.locale-menu { position: absolute; top: 52px; right: 18px; z-index: 6; display: grid; min-width: 110px; padding: 6px; border: 1px solid var(--yui-border); border-radius: 8px; background: var(--yui-surface-raised); box-shadow: var(--yui-shadow-card); }
.locale-menu button { padding: 8px 10px; border: 0; color: var(--yui-text); background: transparent; text-align: left; cursor: pointer; }
.locale-menu button:hover { background: var(--yui-chat-hover); }

.stage-main {
  position: relative;
  display: flex;
  flex: 1;
  width: auto;
  min-height: 0;
  margin: 14px 18px 18px;
  overflow: hidden;
  isolation: isolate;
  border: 1px solid var(--yui-browser-border);
  border-radius: var(--yui-radius-panel);
  background: var(--yui-panel-surface);
  box-shadow: var(--yui-panel-shadow);
}

.stage-main::before {
  position: absolute;
  inset: 0;
  z-index: -2;
  content: '';
  background-image: var(--stage-wallpaper);
  background-position: center;
  background-size: cover;
  filter: blur(10px) saturate(1.06) contrast(1.02);
  opacity: .62;
  transform: scale(1.04);
}

.stage-main::after {
  position: absolute;
  inset: 0;
  z-index: -1;
  content: '';
  background: linear-gradient(180deg, rgba(8, 13, 24, .24), rgba(8, 13, 24, .08) 46%, rgba(8, 13, 24, .36));
  pointer-events: none;
}

.stage-display { position: relative; flex: 1; min-width: 0; min-height: 0; display: grid; place-items: center; overflow: hidden; padding: 18px 26px; }
.stage-floor { position: absolute; bottom: 8%; width: min(72vw, 780px); height: 16%; border-radius: 50%; background: radial-gradient(ellipse, rgba(16,24,39,.48), transparent 68%); }
.stage-floor span { position: absolute; inset: 28% 18% auto; height: 2px; background: linear-gradient(90deg, transparent, rgba(255,255,255,.4), transparent); }
.stage-caption { position: absolute; bottom: 7%; display: grid; gap: 3px; text-align: center; color: var(--yui-text); text-shadow: 0 2px 14px rgba(0,0,0,.35); }
.stage-caption span { font-size: 12px; font-weight: 700; }
.stage-caption small { font-size: 10px; color: var(--yui-muted); }
.stage-window { position: relative; z-index: 3; display: flex; flex-direction: column; width: min(430px, 42vw); min-width: 340px; margin: 16px 16px 16px 0; overflow: hidden; border: 1px solid var(--yui-panel-outline); border-radius: var(--yui-radius-card); color: var(--yui-text); background: var(--yui-surface-raised); box-shadow: var(--yui-panel-shadow); }
.stage-window-header { display: flex; align-items: center; justify-content: space-between; min-height: 48px; padding: 8px 12px 8px 16px; border-bottom: 1px solid var(--yui-border); background: var(--yui-surface-muted); }
.stage-window-header div { display: flex; align-items: baseline; gap: 8px; }
.stage-window-header strong { font-size: 14px; }
.stage-window-header span { color: var(--yui-muted); font-size: 10px; }
.stage-window-body { flex: 1; min-height: 0; overflow: hidden; }
.stage-route-component { width: 100%; height: 100%; }
.stage-reopen { position: absolute; right: 20px; bottom: 20px; z-index: 5; display: inline-flex; align-items: center; gap: 7px; min-height: 36px; padding: 0 12px; border: 1px solid var(--yui-border); border-radius: 8px; color: var(--yui-text); background: var(--yui-panel-surface-strong); box-shadow: var(--yui-shadow-card); cursor: pointer; }
.stage-reopen:hover { border-color: var(--yui-border-strong); background: var(--yui-surface-raised); }

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
  .stage-window { position: absolute; top: 12px; right: 12px; bottom: 12px; width: min(430px, calc(100% - 24px)); min-width: 0; margin: 0; }
  .stage-caption { left: 24%; }
  .stage-display :deep(.browser-pet-stage) { transform: translateX(-16%); }
  .stage-actions { gap: 6px; }
  .stage-brand strong, .stage-subtitle, .stage-live { display: none; }
}
</style>
