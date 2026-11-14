<template>
  <div class="browser-stage" :style="stageStyle">
    <AppSidebar
      class="stage-sidebar"
      :active-workspace-id="activeWorkspace.id"
      :menus="menus"
      @open-workspace-settings="$emit('open-workspace-settings')"
    />
    <div class="stage-content">
      <main
        ref="mainEl"
        class="stage-main"
        :class="{ 'is-immersive': immersive }"
        :style="layoutStyle"
      >
        <aside
          id="stage-chat"
          v-show="chatOpen"
          class="stage-window stage-chat-window"
          :aria-label="immersive ? t('chat.stage.history') : t('chat.title')"
        >
          <header class="stage-window-header">
            <strong>{{
              immersive ? t("chat.stage.history") : t("chat.title")
            }}</strong>
            <div class="stage-header-actions">
              <button
                ref="modeButton"
                class="stage-text-button"
                type="button"
                @click="setImmersive(!immersive)"
              >
                <el-icon
                  ><component
                    :is="immersive ? ChatDotRound : Headset" /></el-icon
                >{{
                  immersive
                    ? t("chat.stage.textMode")
                    : t("chat.stage.voiceMode")
                }}
              </button>
              <button
                v-if="immersive"
                class="stage-icon-button"
                type="button"
                :title="t('chat.stage.close')"
                :aria-label="t('chat.stage.close')"
                @click="chatOpen = false"
              >
                <el-icon><Close /></el-icon>
              </button>
            </div>
          </header>
          <slot name="status" />
          <div class="stage-window-body chat-mode">
            <router-view v-slot="{ Component, route }"
              ><component
                :is="Component"
                v-if="Component && route.name === 'chat'"
                class="stage-route-component"
            /></router-view>
          </div>
        </aside>
        <div
          v-if="!immersive"
          class="stage-splitter"
          role="separator"
          tabindex="0"
          aria-orientation="vertical"
          :aria-label="t('chat.stage.resize')"
          :aria-valuemin="MIN_AVATAR_WIDTH"
          :aria-valuemax="maxAvatarWidth"
          :aria-valuenow="Math.round(avatarWidth)"
          @pointerdown="startResize"
          @pointermove="resizeAvatar"
          @pointerup="finishResize"
          @pointercancel="finishResize"
          @lostpointercapture="finishResize"
          @keydown.left.prevent="setAvatarWidth(avatarWidth + 20)"
          @keydown.right.prevent="setAvatarWidth(avatarWidth - 20)"
          @keydown.home.prevent="setAvatarWidth(MIN_AVATAR_WIDTH)"
          @keydown.end.prevent="setAvatarWidth(maxAvatarWidth)"
        >
          <span></span>
        </div>
        <section class="stage-display" :aria-label="t('chat.stage.modelLabel')">
          <BrowserPetStage
            ref="petStageRef"
            @zoom-change="modelZoom = $event"
          />
          <div class="stage-scene-actions">
            <details class="stage-model-menu">
              <summary
                :title="t('chat.stage.modelZoom')"
                :aria-label="t('chat.stage.modelZoom')"
              >
                <el-icon><MoreFilled /></el-icon>
              </summary>
              <div
                class="stage-display-zoom-controls"
                role="group"
                :aria-label="t('chat.stage.modelZoom')"
              >
                <button
                  class="stage-icon-button"
                  type="button"
                  :title="t('chat.stage.zoomOut')"
                  :aria-label="t('chat.stage.zoomOut')"
                  :disabled="modelZoom <= MODEL_ZOOM_MIN"
                  @click="petStageRef?.adjustZoom(-0.1)"
                >
                  <el-icon><ZoomOut /></el-icon>
                </button>
                <button
                  class="stage-icon-button"
                  type="button"
                  :title="t('chat.stage.zoomReset')"
                  :aria-label="t('chat.stage.zoomReset')"
                  @click="petStageRef?.resetZoom()"
                >
                  <el-icon><Refresh /></el-icon>
                </button>
                <button
                  class="stage-icon-button"
                  type="button"
                  :title="t('chat.stage.zoomIn')"
                  :aria-label="t('chat.stage.zoomIn')"
                  :disabled="modelZoom >= MODEL_ZOOM_MAX"
                  @click="petStageRef?.adjustZoom(0.1)"
                >
                  <el-icon><ZoomIn /></el-icon>
                </button>
              </div>
            </details>
            <button
              v-if="immersive"
              ref="textModeButton"
              class="stage-text-button"
              type="button"
              @click="setImmersive(false)"
            >
              <el-icon><ChatDotRound /></el-icon>{{ t("chat.stage.textMode") }}
            </button>
          </div>
          <div v-if="!immersive" class="stage-presence" role="status">
            <span
              class="stage-presence-dot"
              :class="{ active: busy || chatStore.state.isRecording }"
            ></span
            ><span>{{ statusLabel }}</span>
          </div>
          <div v-else class="stage-voice-dock">
            <p v-if="subtitleText" class="stage-subtitles" aria-live="polite">
              {{ subtitleText }}
            </p>
            <div class="stage-voice-controls">
              <span class="stage-voice-status" role="status">{{
                statusLabel
              }}</span>
              <button
                class="stage-text-button stage-mic-button"
                :class="{ active: chatStore.state.isRecording }"
                type="button"
                :aria-pressed="chatStore.state.isRecording"
                :disabled="!realtimeConnected && !chatStore.state.isRecording"
                @click="toggleVoice"
              >
                <el-icon><Microphone /></el-icon
                >{{
                  chatStore.state.isRecording
                    ? t("chatPanel.voice.stopRecording")
                    : t("chatPanel.voice.voiceInput")
                }}
              </button>
              <button
                class="stage-icon-button"
                type="button"
                :disabled="!busy"
                :title="t('chatPanel.voice.stopResponse')"
                :aria-label="t('chatPanel.voice.stopResponse')"
                @click="chatStore.interrupt()"
              >
                <el-icon><Mute /></el-icon>
              </button>
              <button
                class="stage-text-button"
                type="button"
                :aria-expanded="chatOpen"
                aria-controls="stage-chat"
                @click="chatOpen = !chatOpen"
              >
                <el-icon><ChatDotRound /></el-icon>{{ t("chat.stage.history") }}
              </button>
            </div>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ElIcon } from "element-plus";
import "element-plus/es/components/icon/style/css";
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from "vue";
import {
  ChatDotRound,
  Close,
  Headset,
  Microphone,
  MoreFilled,
  Mute,
  Refresh,
  ZoomIn,
  ZoomOut,
} from "@element-plus/icons-vue";
import type { NavigationModule } from "@/navigation/types";
import type { WorkspaceRecord } from "@/../shared/workspace";
import { useI18n } from "@/i18n";
import { useChatStore } from "@/stores/chatStore";
import { getSocketClient } from "@/net/socketClient";
import AppSidebar from "./AppSidebar.vue";
import BrowserPetStage from "./BrowserPetStage.vue";

const props = defineProps<{
  currentWallpaper: string;
  menus: NavigationModule[];
  activeWorkspace: WorkspaceRecord;
}>();
defineEmits<{ "open-workspace-settings": [] }>();
const { t } = useI18n();
const chatStore = useChatStore();
const realtimeConnected = getSocketClient().connected;
const modeButton = ref<HTMLButtonElement | null>(null);
const textModeButton = ref<HTMLButtonElement | null>(null);
const chatOpen = ref(true);
const immersive = ref(false);
const mainEl = ref<HTMLElement | null>(null);
const mainWidth = ref(1000);
const preferredAvatarWidth = ref<number | null>(null);
const MIN_AVATAR_WIDTH = 220;
const WIDTH_STORAGE_KEY = "yuizaki.chat.avatar-width";
const MODEL_ZOOM_MIN = 0.7;
const MODEL_ZOOM_MAX = 1.8;
const modelZoom = ref(1);
const petStageRef = ref<{
  adjustZoom: (delta: number) => void;
  resetZoom: () => void;
} | null>(null);
const maxAvatarWidth = computed(() =>
  Math.max(MIN_AVATAR_WIDTH, Math.min(440, mainWidth.value * 0.45)),
);
const avatarWidth = computed(() =>
  Math.max(
    MIN_AVATAR_WIDTH,
    Math.min(
      maxAvatarWidth.value,
      preferredAvatarWidth.value ?? mainWidth.value * 0.3,
    ),
  ),
);
const layoutStyle = computed(() => ({
  "--stage-avatar-width": `${avatarWidth.value}px`,
}));
const stageStyle = computed(() => ({
  "--stage-wallpaper": props.currentWallpaper
    ? `url("${props.currentWallpaper}")`
    : 'url("/assets/chat-home-bg.jpg")',
}));
const busy = computed(
  () =>
    chatStore.state.isGenerating ||
    chatStore.state.isTTSPlaying ||
    chatStore.state.isSpeaking,
);
const statusLabel = computed(() => {
  if (!realtimeConnected.value)
    return t("chat.status.channelOffline");
  if (chatStore.state.isRecording) return t("chat.status.listening");
  if (chatStore.state.isTTSPlaying || chatStore.state.isSpeaking)
    return t("chat.status.playing");
  if (chatStore.state.isGenerating) return t("chat.status.thinking");
  return t("chat.stage.idle");
});
const subtitleText = computed(() => {
  const state = chatStore.state;
  return (
    state.asrPartialText ||
    state.ttsPlaybackText ||
    state.currentText ||
    [...state.messages]
      .reverse()
      .find((message) => message.role === "assistant")?.content ||
    ""
  );
});
let resizeObserver: ResizeObserver | null = null;
let dragging = false;
let active = false;
const setAvatarWidth = (width: number): void => {
  preferredAvatarWidth.value = Math.max(
    MIN_AVATAR_WIDTH,
    Math.min(maxAvatarWidth.value, width),
  );
  try {
    localStorage.setItem(WIDTH_STORAGE_KEY, String(preferredAvatarWidth.value));
  } catch {
    /* Resizing remains available when browser storage is disabled. */
  }
};
const startResize = (event: PointerEvent): void => {
  if (event.button !== 0) return;
  dragging = true;
  const target = event.currentTarget as HTMLElement;
  target.setPointerCapture(event.pointerId);
  event.preventDefault();
};
const resizeAvatar = (event: PointerEvent): void => {
  if (!dragging || !mainEl.value) return;
  preferredAvatarWidth.value = Math.max(
    MIN_AVATAR_WIDTH,
    Math.min(
      maxAvatarWidth.value,
      mainEl.value.getBoundingClientRect().right - event.clientX,
    ),
  );
};
const finishResize = (): void => {
  if (!dragging) return;
  dragging = false;
  setAvatarWidth(avatarWidth.value);
};
const setImmersive = (value: boolean): void => {
  immersive.value = value;
  chatOpen.value = !value;
  void nextTick(() =>
    (value ? textModeButton.value : modeButton.value)?.focus(),
  );
};
const toggleVoice = (): void => {
  window.dispatchEvent(
    new CustomEvent("yuizaki:input-action", {
      detail: {
        action: chatStore.state.isRecording ? "stopVoice" : "startVoice",
      },
    }),
  );
};
const handleInputAction = (event: Event): void => {
  if (!active) return;
  if (
    (event as CustomEvent<{ action?: string }>).detail?.action === "openPanel"
  )
    chatOpen.value = true;
};
const handleEscape = (event: KeyboardEvent): void => {
  if (!active) return;
  if (!event.defaultPrevented && event.key === "Escape" && immersive.value) {
    if (chatOpen.value) chatOpen.value = false;
    else setImmersive(false);
  }
};
onMounted(() => {
  try {
    const stored = Number(localStorage.getItem(WIDTH_STORAGE_KEY));
    if (Number.isFinite(stored) && stored >= MIN_AVATAR_WIDTH)
      preferredAvatarWidth.value = stored;
  } catch {
    /* Use the default split when storage is unavailable. */
  }
  resizeObserver = new ResizeObserver(([entry]) => {
    if (active && entry && entry.contentRect.width > 0)
      mainWidth.value = entry.contentRect.width;
  });
  activateStage();
});
const activateStage = (): void => {
  if (active) return;
  active = true;
  window.addEventListener("yuizaki:input-action", handleInputAction);
  window.addEventListener("keydown", handleEscape);
  void nextTick(() => {
    if (!active || !mainEl.value) return;
    const width = mainEl.value.clientWidth;
    if (width > 0) mainWidth.value = width;
    resizeObserver?.observe(mainEl.value);
  });
};
const deactivateStage = (): void => {
  active = false;
  dragging = false;
  resizeObserver?.disconnect();
  window.removeEventListener("yuizaki:input-action", handleInputAction);
  window.removeEventListener("keydown", handleEscape);
};
onActivated(activateStage);
onDeactivated(deactivateStage);
onBeforeUnmount(deactivateStage);
</script>

<style scoped>
.stage-display,
.stage-window,
.stage-window-header,
.stage-text-button,
.stage-icon-button,
.stage-voice-dock {
  box-sizing: border-box;
}
.browser-stage {
  position: relative;
  display: flex;
  isolation: isolate;
  width: 100%;
  height: 100%;
  overflow: hidden;
  color: var(--yui-text);
  --stage-border: var(--yui-border);
  --stage-chrome-surface: rgba(255, 255, 255, 0.74);
  --stage-window-surface: var(--yui-chat-surface, #fff);
}
:global(:root[data-theme="dark"] .browser-stage) {
  --stage-chrome-surface: rgba(15, 23, 42, 0.86);
}
.browser-stage::before {
  position: absolute;
  inset: 0;
  z-index: 0;
  content: "";
  background: #edf2f7 var(--stage-wallpaper) center / cover no-repeat;
}
:global(.yuizaki-bg.browser-mode .stage-sidebar.sidebar) {
  position: relative;
  flex: 0 0 202px;
  height: 100%;
  z-index: 5;
  background: var(--stage-chrome-surface);
  background-image: none;
  border-color: var(--stage-border);
  backdrop-filter: blur(4px);
}
.stage-content {
  position: relative;
  z-index: 1;
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
}
.stage-main {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 16px var(--stage-avatar-width);
  grid-template-areas: "chat splitter model";
  flex: 1;
  min-width: 0;
  min-height: 0;
  margin: 16px;
}
.stage-display {
  grid-area: model;
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  isolation: isolate;
  border: 1px solid var(--stage-border);
  border-radius: 16px;
  background: #edf2f7 url("/assets/echobot-reference-bg.jpg") center / cover
    no-repeat;
}
.stage-scene-actions {
  position: absolute;
  top: 12px;
  left: 12px;
  right: 12px;
  z-index: 4;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  pointer-events: none;
}
.stage-scene-actions > * {
  pointer-events: auto;
}
.stage-model-menu {
  position: relative;
}
.stage-model-menu summary {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  list-style: none;
  cursor: pointer;
  border: 1px solid var(--stage-border);
  border-radius: 8px;
  background: var(--stage-chrome-surface);
  color: var(--yui-text);
}
.stage-model-menu summary::-webkit-details-marker {
  display: none;
}
.stage-display-zoom-controls {
  position: absolute;
  top: 40px;
  left: 0;
  display: flex;
  gap: 4px;
  padding: 6px;
  border: 1px solid var(--stage-border);
  border-radius: 10px;
  background: var(--stage-window-surface);
  box-shadow: var(--yui-shadow-card);
}
.stage-icon-button,
.stage-text-button {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  padding: 5px 10px;
  border: 1px solid var(--stage-border);
  border-radius: 8px;
  color: var(--yui-text);
  background: var(--stage-chrome-surface);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.stage-icon-button {
  width: 32px;
  padding: 0;
}
.stage-icon-button:hover:not(:disabled),
.stage-text-button:hover {
  background: var(--yui-surface-raised);
  border-color: var(--yui-border-strong);
}
.stage-text-button:disabled,
.stage-icon-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.stage-icon-button:focus-visible,
.stage-text-button:focus-visible,
summary:focus-visible,
.stage-splitter:focus-visible {
  outline: 2px solid var(--yui-accent, #477aab);
  outline-offset: 3px;
}
.stage-presence {
  position: absolute;
  bottom: 16px;
  left: 50%;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 12px;
  transform: translateX(-50%);
  white-space: nowrap;
  border: 1px solid var(--stage-border);
  border-radius: 20px;
  color: var(--yui-text);
  background: var(--stage-chrome-surface);
  font-size: 12px;
}
.stage-presence-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--yui-muted);
}
.stage-presence-dot.active {
  background: var(--yui-accent, #477aab);
}
.stage-splitter {
  grid-area: splitter;
  display: grid;
  place-items: center;
  cursor: col-resize;
  touch-action: none;
  border-radius: 6px;
}
.stage-splitter span {
  width: 3px;
  height: 36px;
  border-radius: 3px;
  background: var(--yui-border-strong);
}
.stage-splitter:hover span,
.stage-splitter:focus-visible span {
  background: var(--yui-accent, #477aab);
}
.stage-window {
  grid-area: chat;
  position: relative;
  z-index: 3;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--stage-border);
  border-radius: 16px;
  color: var(--yui-text);
  background: var(--stage-window-surface);
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.06);
}
.stage-window-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 52px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--stage-border);
  background: transparent;
}
.stage-window-header strong {
  font-size: 14px;
  font-weight: 600;
}
.stage-header-actions {
  display: flex;
  gap: 8px;
}
.stage-window-body {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: transparent;
}
.stage-route-component {
  width: 100%;
  height: 100%;
}
.stage-window-body :deep(.chat-workspace) {
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.stage-window-body :deep(.session-rail-pane) {
  background: var(--yui-surface);
}
.stage-main.is-immersive {
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas: "model";
}
.is-immersive .stage-display {
  grid-area: 1 / 1;
}
.is-immersive .stage-window {
  grid-area: model;
  position: absolute;
  top: 12px;
  left: 12px;
  bottom: 12px;
  width: min(460px, calc(100% - 24px));
  box-shadow: var(--yui-shadow-card);
}
.stage-voice-dock {
  position: absolute;
  z-index: 3;
  bottom: 20px;
  left: 50%;
  width: min(720px, calc(100% - 40px));
  padding: 16px;
  transform: translateX(-50%);
  border: 1px solid var(--stage-border);
  border-radius: 16px;
  background: var(--stage-chrome-surface);
  backdrop-filter: blur(12px);
}
.stage-subtitles {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  margin: 0 0 14px;
  color: var(--yui-text);
  font-size: 16px;
  line-height: 1.6;
  text-align: center;
  overflow-wrap: anywhere;
}
.stage-voice-controls {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
}
.stage-voice-status {
  margin-right: 8px;
  color: var(--yui-text);
  font-size: 12px;
}
.stage-mic-button.active {
  border-color: var(--yui-accent);
  background: var(--yui-surface-raised);
}
@media (max-width: 980px) {
  :global(.yuizaki-bg.browser-mode .stage-sidebar.sidebar) {
    flex-basis: 76px;
  }
}
@media (max-width: 860px) {
  .stage-main {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: 170px minmax(0, 1fr);
    grid-template-areas: "model" "chat";
    gap: 10px;
    margin: 10px;
  }
  .stage-splitter {
    display: none;
  }
  .stage-display,
  .stage-window {
    border-radius: 12px;
  }
  .stage-presence {
    left: auto;
    right: 12px;
    bottom: 12px;
    transform: none;
  }
  .stage-main.is-immersive {
    grid-template-rows: minmax(0, 1fr);
  }
  .stage-window-header {
    padding: 8px 12px;
  }
  .stage-voice-dock {
    bottom: 12px;
    width: calc(100% - 24px);
    padding: 12px;
  }
  .stage-voice-status {
    flex-basis: 100%;
    text-align: center;
    margin: 0;
  }
}
@media (max-width: 760px) {
  :global(.yuizaki-bg.browser-mode .stage-sidebar.sidebar) {
    flex-basis: 64px;
  }
}
@media (max-width: 860px) and (max-height: 640px) {
  .stage-main:not(.is-immersive) {
    grid-template-rows: 110px minmax(0, 1fr);
  }
}
</style>
