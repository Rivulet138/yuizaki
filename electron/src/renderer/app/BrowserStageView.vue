<template>
  <div class="browser-stage" :style="stageStyle">
    <header class="stage-toolbar">
      <div class="stage-brand">
        <span class="stage-brand-mark">結</span>
        <span class="stage-brand-name">{{ activeWorkspace.name || '結崎' }}</span>
        <span class="stage-live"><i></i> LIVE</span>
      </div>

      <nav class="stage-actions" aria-label="功能">
        <a
          v-for="item in quickMenus"
          :key="item.id"
          class="stage-icon-button"
          :class="{ active: activeTab === item.id }"
          :data-tab="item.id"
          :href="`#${panelPath(item.id)}`"
          :title="item.title"
          :aria-label="item.title"
          @click="preparePanel(item.id)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
        </a>
        <button class="stage-icon-button" type="button" title="主题" aria-label="主题" @click="$emit('toggle-theme')">
          <el-icon><Moon /></el-icon>
        </button>
        <button class="stage-icon-button" type="button" title="语言" aria-label="语言" @click="showLocale = !showLocale">
          <el-icon><ChatDotRound /></el-icon>
        </button>
      </nav>

      <div v-if="showLocale" class="locale-menu">
        <button v-for="locale in localeOptions" :key="locale.value" type="button" @click="changeLocale(locale.value)">
          {{ locale.label }}
        </button>
      </div>
    </header>

    <main class="stage-main">
      <section class="stage-display" aria-label="Live2D 展示台">
        <div class="stage-backdrop"></div>
        <div class="stage-floor"><span></span></div>
        <BrowserPetStage :key="compactStage ? 'compact' : 'desktop'" />
        <div class="stage-caption">
          <span>{{ companionId || 'yumi' }}</span>
          <small>{{ companionStateLabel }}</small>
        </div>
      </section>

      <aside v-if="activeTab === 'chat' && chatOpen" class="stage-window stage-chat-window">
        <header class="stage-window-header">
          <div>
            <strong>对话</strong>
            <span>{{ realtimeConnected ? '在线' : '连接中' }}</span>
          </div>
          <button class="stage-close" type="button" title="关闭聊天" aria-label="关闭聊天" @click="chatOpen = false">
            <el-icon><Close /></el-icon>
          </button>
        </header>
        <div class="stage-window-body">
          <router-view v-slot="{ Component, route }">
            <component :is="Component" v-if="Component && route.name === 'chat'" class="stage-route-component" />
          </router-view>
        </div>
      </aside>

      <section v-else-if="activeTab !== 'chat' && panelOpen" class="stage-window stage-panel-window">
        <header class="stage-window-header">
          <div>
            <strong>{{ activeTitle }}</strong>
            <span>{{ activeTab }}</span>
          </div>
          <button class="stage-close" type="button" title="关闭窗口" aria-label="关闭窗口" @click="closePanel">
            <el-icon><Close /></el-icon>
          </button>
        </header>
        <div class="stage-window-body stage-panel-body">
          <router-view v-slot="{ Component, route }">
            <component :is="Component" v-if="Component && route.name !== 'chat'" class="stage-route-component" />
          </router-view>
        </div>
      </section>

      <button v-if="activeTab === 'chat' && !chatOpen" class="stage-reopen" type="button" title="打开聊天" @click="chatOpen = true">
        <el-icon><ChatDotRound /></el-icon>
        <span>打开聊天</span>
      </button>
      <button v-if="activeTab !== 'chat' && !panelOpen" class="stage-reopen" type="button" title="返回聊天" @click="closePanel">
        <el-icon><ChatDotRound /></el-icon>
        <span>返回聊天</span>
      </button>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound, Close, Moon } from '@element-plus/icons-vue'
import type { NavigationModuleId } from '@/navigation/modules'
import type { NavigationModule } from '@/navigation/types'
import type { WorkspaceRecord } from '@/../shared/workspace'
import { getSocketClient } from '@/net/socketClient'
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
}>()

const route = useRoute()
const router = useRouter()
const chatOpen = ref(true)
const panelOpen = ref(true)
const showLocale = ref(false)
const compactStage = ref(false)
const realtimeConnected = getSocketClient().connected
let compactMediaQuery: MediaQueryList | null = null

const quickMenus = computed(() => props.menus.filter((item) => ['chat', 'pet', 'settings', 'svc'].includes(item.id)).slice(0, 4))
const activeTitle = computed(() => props.menus.find((item) => item.id === props.activeTab)?.title || props.activeTab)
const localeOptions = [
  { value: 'zh-CN', label: '中文' },
  { value: 'en-US', label: 'EN' },
  { value: 'ja-JP', label: '日本語' },
]
const stageStyle = computed(() => ({
  '--stage-wallpaper': props.currentWallpaper ? `url("${props.currentWallpaper}")` : 'none',
}))

const panelPath = (tab: string): string => {
  const workspaceId = encodeURIComponent(String(route.params.workspaceId || props.activeWorkspace.id || 'default'))
  return `/w/${workspaceId}/${tab}`
}

const preparePanel = (tab: string): void => {
  if (tab === 'chat') chatOpen.value = true
  else panelOpen.value = true
}

const closePanel = (): void => {
  const workspaceId = encodeURIComponent(String(route.params.workspaceId || props.activeWorkspace.id || 'default'))
  panelOpen.value = false
  void router.push(`/w/${workspaceId}/chat`)
}

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
  isolation: isolate;
  width: 100%;
  height: 100%;
  overflow: hidden;
  color: #f8fafc;
  background: #101826;
}

.browser-stage::before {
  position: absolute;
  inset: 0;
  z-index: -2;
  content: '';
  background-image: var(--stage-wallpaper);
  background-position: center;
  background-size: cover;
  filter: saturate(1.12) contrast(1.04);
  opacity: .72;
}

.browser-stage::after {
  position: absolute;
  inset: 0;
  z-index: -1;
  content: '';
  background: linear-gradient(180deg, rgba(10, 16, 29, .28), rgba(10, 16, 29, .08) 44%, rgba(10, 16, 29, .4));
  pointer-events: none;
}

.stage-toolbar {
  position: relative;
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 58px;
  padding: 12px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, .2);
  background: rgba(10, 16, 29, .3);
  backdrop-filter: blur(12px);
}

.stage-brand, .stage-actions { display: flex; align-items: center; gap: 10px; }
.stage-brand-mark { display: grid; width: 30px; height: 30px; place-items: center; border: 1px solid rgba(255,255,255,.5); border-radius: 50%; font-weight: 800; }
.stage-brand-name { font-size: 14px; font-weight: 750; letter-spacing: .02em; }
.stage-live { display: inline-flex; align-items: center; gap: 5px; color: rgba(255,255,255,.72); font-size: 10px; letter-spacing: .14em; }
.stage-live i { width: 6px; height: 6px; border-radius: 50%; background: #fb7185; box-shadow: 0 0 0 4px rgba(251,113,133,.15); }
.stage-icon-button, .stage-close { display: grid; width: 34px; height: 34px; padding: 0; place-items: center; border: 1px solid rgba(255,255,255,.24); border-radius: 8px; color: rgba(255,255,255,.82); background: rgba(10,16,29,.2); cursor: pointer; text-decoration: none; transition: background .16s ease, border-color .16s ease, color .16s ease; }
.stage-icon-button:hover, .stage-icon-button.active, .stage-close:hover { border-color: rgba(255,255,255,.62); color: #fff; background: rgba(255,255,255,.16); }
.locale-menu { position: absolute; top: 52px; right: 18px; display: grid; min-width: 110px; padding: 6px; border: 1px solid rgba(255,255,255,.28); border-radius: 8px; background: rgba(15,23,42,.9); box-shadow: 0 12px 28px rgba(0,0,0,.25); }
.locale-menu button { padding: 8px 10px; border: 0; color: #e2e8f0; background: transparent; text-align: left; cursor: pointer; }
.locale-menu button:hover { background: rgba(255,255,255,.12); }

.stage-main { position: relative; display: flex; width: 100%; height: calc(100% - 58px); min-height: 0; }
.stage-display { position: relative; flex: 1; min-width: 0; min-height: 0; display: grid; place-items: center; overflow: hidden; }
.stage-backdrop { position: absolute; width: min(68vw, 760px); height: min(72vh, 720px); border: 1px solid rgba(255,255,255,.22); border-bottom: 0; border-radius: 50% 50% 0 0; background: linear-gradient(180deg, rgba(255,255,255,.1), rgba(255,255,255,.02)); box-shadow: inset 0 0 80px rgba(255,255,255,.05); }
.stage-floor { position: absolute; bottom: 8%; width: min(72vw, 780px); height: 16%; border-radius: 50%; background: radial-gradient(ellipse, rgba(16,24,39,.48), transparent 68%); }
.stage-floor span { position: absolute; inset: 28% 18% auto; height: 2px; background: linear-gradient(90deg, transparent, rgba(255,255,255,.4), transparent); }
.stage-caption { position: absolute; bottom: 7%; display: grid; gap: 3px; text-align: center; color: rgba(255,255,255,.82); text-shadow: 0 2px 14px rgba(0,0,0,.35); }
.stage-caption span { font-size: 12px; font-weight: 700; }
.stage-caption small { font-size: 10px; color: rgba(255,255,255,.6); }

.stage-window { position: relative; z-index: 3; display: flex; flex-direction: column; width: min(390px, 38vw); min-width: 310px; margin: 16px 16px 16px 0; overflow: hidden; border: 1px solid rgba(255,255,255,.32); border-radius: 12px; background: rgba(15,23,42,.7); box-shadow: 0 18px 45px rgba(2,6,23,.28); backdrop-filter: blur(18px); }
.stage-window-header { display: flex; align-items: center; justify-content: space-between; min-height: 48px; padding: 8px 12px 8px 16px; border-bottom: 1px solid rgba(255,255,255,.18); }
.stage-window-header div { display: flex; align-items: baseline; gap: 8px; }
.stage-window-header strong { font-size: 14px; }
.stage-window-header span { color: rgba(255,255,255,.52); font-size: 10px; }
.stage-window-body { flex: 1; min-height: 0; overflow: hidden; }
.stage-route-component { width: 100%; height: 100%; }
.stage-panel-body { overflow: auto; padding: 10px; }
.stage-panel-body :deep(.panel-shell) { min-height: 100%; }
.stage-reopen { position: absolute; right: 20px; bottom: 20px; z-index: 5; display: inline-flex; align-items: center; gap: 7px; min-height: 36px; padding: 0 12px; border: 1px solid rgba(255,255,255,.38); border-radius: 8px; color: #fff; background: rgba(15,23,42,.72); box-shadow: 0 10px 24px rgba(2,6,23,.25); cursor: pointer; backdrop-filter: blur(10px); }
.stage-reopen:hover { background: rgba(15,23,42,.9); }

@media (max-width: 860px) {
  .stage-main { display: block; overflow: auto; }
  .stage-display { min-height: 610px; height: calc(100vh - 58px); }
  .stage-window { position: absolute; top: 12px; right: 12px; bottom: 12px; width: min(390px, calc(100vw - 24px)); min-width: 0; margin: 0; }
  .stage-panel-window { left: 12px; width: calc(100vw - 24px); }
  .stage-caption { left: 24%; }
  .stage-display :deep(.browser-pet-stage) { transform: translateX(-16%); }
  .stage-actions { gap: 6px; }
  .stage-brand-name, .stage-live { display: none; }
}
</style>
