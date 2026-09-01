<template>
  <PanelShell title="对话中心" tone="companion" density="compact" minimal>
    <div
      class="chat-workspace"
      :class="{
        'chat-workspace--rail-hidden': !showSessionRail,
      }"
    >
      <SessionRail
        v-if="showSessionRail"
        class="session-rail-pane"
        :sessions="sessionStore.sessions"
        :active-session-id="sessionStore.activeSessionId"
        :active-workspace-id="workspaceStore.activeWorkspaceId"
        :workspace-names="workspaceNameMap"
        :creating="isCreatingSession"
        :draft-session-ids="draftSessionIds"
        :running-session-ids="chatStore.runningSessionIds"
        :unread-session-ids="chatStore.unreadSessionIds"
        @create-session="handleCreateSession"
        @select-session="handleSelectSession"
        @toggle-pin="handleTogglePin"
        @rename-session="handleRenameSession"
        @archive-session="handleArchiveSession"
        @delete-session="handleDeleteSession"
      />

      <div class="chat-surface flex-1 flex flex-col overflow-hidden">
        <div class="chat-top-corner">
          <div v-if="messageSearch.visible" class="chat-search-strip" @click.stop>
            <el-input
              v-model="messageSearch.query"
              class="chat-search-input"
              size="small"
              clearable
              placeholder="搜索消息"
              @keydown.enter.prevent="jumpSearchResult(1)"
              @keydown.shift.enter.prevent="jumpSearchResult(-1)"
              @keydown.esc.prevent="closeMessageSearch"
            />
            <span class="chat-search-count">{{ searchResultLabel }}</span>
            <button class="search-nav-button" type="button" :disabled="!messageSearchMatches.length" aria-label="上一条" @click="jumpSearchResult(-1)">
              <el-icon><ArrowUp /></el-icon>
            </button>
            <button class="search-nav-button" type="button" :disabled="!messageSearchMatches.length" aria-label="下一条" @click="jumpSearchResult(1)">
              <el-icon><ArrowDown /></el-icon>
            </button>
            <button class="search-nav-button" type="button" aria-label="关闭搜索" @click="closeMessageSearch">
              <el-icon><Close /></el-icon>
            </button>
          </div>
          <el-tooltip content="搜索消息" placement="bottom">
            <button class="top-icon-button" type="button" aria-label="搜索消息" @click="toggleMessageSearch">
              <el-icon><Search /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip :content="showSessionRail ? '隐藏会话列表' : '显示会话列表'" placement="bottom">
            <button class="top-icon-button" type="button" :aria-label="showSessionRail ? '隐藏会话列表' : '显示会话列表'" @click="toggleSessionRail">
              <el-icon>
                <Fold v-if="showSessionRail" />
                <Expand v-else />
              </el-icon>
            </button>
          </el-tooltip>
          <el-tooltip :content="resolvedTheme === 'dark' ? '切换浅色' : '切换深色'" placement="bottom">
            <button class="top-icon-button" type="button" :aria-label="resolvedTheme === 'dark' ? '切换浅色' : '切换深色'" @click="toggleTheme">
              <el-icon>
                <Sunny v-if="resolvedTheme === 'dark'" />
                <Moon v-else />
              </el-icon>
            </button>
          </el-tooltip>
          <el-tooltip content="桌宠设置" placement="bottom">
            <button
              class="top-icon-button"
              type="button"
              aria-label="打开桌宠设置"
              data-testid="chat-pet-settings"
              @click="openPetSettings"
            >
              <el-icon><StarFilled /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip content="设置" placement="bottom">
            <button class="top-icon-button" type="button" aria-label="打开设置" @click="openSettings">
              <el-icon><Setting /></el-icon>
            </button>
          </el-tooltip>
        </div>

        <div v-if="chatState.lastError" class="chat-error-banner">
          <el-icon><WarningFilled /></el-icon>
          <span>{{ chatState.lastError }}</span>
        </div>

        <div
          ref="messagesContainer"
          class="messages-pane flex-1 overflow-y-auto p-3 flex flex-col gap-4 custom-scrollbar bg-slate-50/30 relative"
          @scroll="checkScrollPosition"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="handleDrop"
        >
          <div v-if="dragOver" class="drop-overlay">
            <div class="drop-hint">
              <el-icon><FolderOpened /></el-icon>
              <span>松手上传文件</span>
            </div>
          </div>

          <button v-if="showScrollBtn" class="scroll-bottom-btn" type="button" @click="scrollToBottom">
            <el-icon><Bottom /></el-icon>
          </button>

          <ChatMessageList
            :messages="chatState.messages"
            :context-start-index="chatState.contextStartIndex"
            :current-text="chatState.currentText"
            :is-generating="chatState.isGenerating"
            :pending-assistant-label="pendingAssistantLabel"
            :editing-message="editingMessage"
            :search-matches="messageSearchMatches"
            :active-search-message-index="activeSearchMessageIndex"
            :message-translating-index="messageTranslatingIndex"
            :context-menu="contextMenu"
            :can-regenerate-from-index="canRegenerateFromIndex"
            @copy="handleCopy"
            @quote="quoteMessage"
            @start-edit="startMessageEdit"
            @regenerate="handleRegenerate"
            @create-branch="handleCreateBranch"
            @set-context-start="handleSetContextStart"
            @translate="handleTranslateMessage"
            @delete="handleDeleteMsg"
            @open-context-menu="openContextMenu"
            @close-context-menu="closeContextMenu"
            @update-edit-content="editingMessage.content = $event"
            @save-edit="saveMessageEdit"
            @cancel-edit="cancelMessageEdit"
            @correct-memory="handleCorrectMemory"
            @forget-memory="handleForgetMemory"
          />

          <div v-if="chatState.asrPartialText" class="asr-partial-card animate-fade-in">
            <el-icon><Microphone /></el-icon>
            <span>{{ chatState.asrPartialText }}</span>
          </div>

        </div>

        <div class="composer-panel shrink-0" :class="{ 'composer-panel--tools-open': toolsExpanded }">
          <input ref="fileInput" class="hidden-file-input" type="file" multiple @change="handleFileInputChange" />

          <ChatPlaybackBar
            :playing="chatState.isTTSPlaying"
            :speaking="chatState.isSpeaking"
            :pet-link-enabled="chatOptions.pet_link_enabled !== false"
            :text="playbackText"
            @interrupt="handleInterrupt"
            @toggle-pet-link="togglePetLink"
          />

          <div v-if="attachments.length" class="attachment-strip">
            <div v-for="attachment in attachments" :key="attachment.id" class="attachment-chip" :title="attachment.name">
              <el-icon><FolderOpened /></el-icon>
              <span>{{ attachment.name }}</span>
              <small>{{ formatBytes(attachment.size) }}</small>
              <button type="button" @click="removeAttachment(attachment.id)">×</button>
            </div>
          </div>

          <div class="composer-box" @click.stop>
            <div v-if="quickPanel.visible" class="composer-quick-panel" @mousedown.stop @click.stop>
              <div class="quick-panel-head">
                <span>{{ quickPanelTitle }}</span>
                <kbd>{{ quickPanel.mode === 'slash' ? '/' : '@' }}</kbd>
              </div>
              <div v-if="quickPanelItems.length" class="quick-panel-list">
                <button
                  v-for="(item, index) in quickPanelItems"
                  :key="item.id"
                  class="quick-panel-item"
                  :class="{ selected: quickPanel.selectedIndex === index, current: item.current }"
                  type="button"
                  :disabled="item.disabled"
                  @mouseenter="quickPanel.selectedIndex = index"
                  @click="runQuickPanelItem(item)"
                >
                  <span class="quick-panel-icon">
                    <el-icon><component :is="item.icon" /></el-icon>
                  </span>
                  <span class="quick-panel-copy">
                    <strong>{{ item.label }}</strong>
                    <small v-if="item.description">{{ item.description }}</small>
                  </span>
                </button>
              </div>
              <div v-else class="quick-panel-empty">{{ quickPanelEmptyText }}</div>
            </div>

            <el-input
              v-model="inputText"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 8 }"
              resize="none"
              placeholder="输入消息"
              class="flex-1 chat-input"
              @keydown="handleComposerKeydown"
              @compositionstart="isComposing = true"
              @compositionend="isComposing = false"
            />
            <div class="composer-toolbar">
              <div class="composer-tools-left" aria-label="输入工具栏">
                <span
                  v-for="tool in visibleComposerTools"
                  :key="tool.id"
                  class="composer-tool-slot"
                >
                  <el-tooltip :content="tool.title || tool.label" placement="top">
                    <button
                      class="tool-button"
                      :class="{ active: tool.active }"
                      type="button"
                      :aria-label="tool.label"
                      :disabled="tool.disabled"
                      @click="runComposerTool(tool)"
                    >
                      <el-icon><component :is="tool.icon" /></el-icon>
                    </button>
                  </el-tooltip>
                </span>
              </div>

              <div class="composer-tools-right">
                <ChatRuntimeSettings
                  :model-value="chatOptions"
                  :model-options="modelOptions"
                  :models-loading="modelsLoading"
                  :reasoning-options="reasoningOptions"
                  :response-mode-options="responseModeOptions"
                  :max-output-tokens="maxChatOutputTokens"
                  :model-label="effectiveModelLabel"
                  :mcp-summary="mcpSummaryLabel"
                  :prompt-active="promptProfileActive"
                  :audio-input-devices="audioInputDevices"
                  :audio-devices-loading="audioDevicesLoading"
                  @update-field="updateRuntimeChatOption"
                  @toggle-tts="toggleTtsOutput"
                  @open-prompt="openPromptPanel"
                  @refresh-models="refreshModelOptions"
                  @refresh-audio-devices="refreshAudioInputDevices"
                />
                <el-dropdown trigger="click" @command="handleTopMoreCommand">
                  <button class="tool-button" type="button" aria-label="更多">
                    <el-icon><MoreFilled /></el-icon>
                  </button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="copy-transcript" :disabled="!chatState.messages.length">复制全文</el-dropdown-item>
                      <el-dropdown-item command="copy-last" :disabled="!lastAssistantMessage">复制最后回复</el-dropdown-item>
                      <el-dropdown-item command="open-expanded-composer">展开输入框</el-dropdown-item>
                      <el-dropdown-item command="quick-phrases">快捷短语</el-dropdown-item>
                      <el-dropdown-item command="clear-context" :disabled="!hasConversationContent">清理上下文</el-dropdown-item>
                      <el-dropdown-item command="reset-context" :disabled="chatState.contextStartIndex <= 0">恢复完整上下文</el-dropdown-item>
                      <el-dropdown-item divided command="clear-conversation" :disabled="!hasConversationContent">清空当前会话</el-dropdown-item>
                      <el-dropdown-item command="interrupt" :disabled="!(chatState.isGenerating || chatState.isTTSPlaying)">中断生成与播放</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <button v-if="chatState.isGenerating" class="send-button is-warning" type="button" @click="handleInterrupt">
                  <el-icon><CircleClose /></el-icon>
                </button>
                <button v-else class="send-button" type="button" :disabled="!canSendComposer" @click="handleSendComposer">
                  <el-icon><Promotion /></el-icon>
                </button>
              </div>
            </div>
            <ChatComposerStatusLine
              :connected="socketDomain.isConnected.value"
              :generating="chatState.isGenerating"
              :recording="isRecording"
              :tts-playing="chatState.isTTSPlaying"
              :show-recovery-action="showRealtimeRecovery"
            />

            <ChatVoiceStatus
              v-if="toolsExpanded"
              v-model:mode="voiceMode"
              :status-class="voiceStatusClass"
              :status-text="voiceStatusText"
              :pipeline-text="voicePipelineText"
              :processing-text="voiceProcessingText"
              :latency-summary="voiceLatencySummary"
              :recording="isRecording"
              :meter-bars="voiceMeterBars"
              :level-percent="voiceLevelPercent"
              :mode-options="voiceModeOptions"
              :hold-active="isHoldActive"
              :connected="socketDomain.isConnected.value"
              :shortcut-title="pushToTalkShortcutTitle"
              :tts-playing="chatState.isTTSPlaying"
              :interruptible="voiceInterruptible"
              @hold-pointer-down="handleHoldPointerDown"
              @hold-pointer-up="handleHoldPointerUp"
              @begin-hold="beginHoldToTalk"
              @end-hold="endHoldToTalk"
              @toggle-mic="toggleMic"
              @interrupt="handleInterrupt"
              @retry-realtime="retryRealtimeVoice"
            />
          </div>
        </div>
      </div>
    </div>

    <el-dialog v-model="expandedComposerVisible" title="展开输入" width="min(560px, calc(100vw - 32px))" append-to-body>
      <el-input
        v-model="expandedComposerText"
        type="textarea"
        :autosize="{ minRows: 8, maxRows: 14 }"
        resize="vertical"
        placeholder="输入内容"
      />
      <template #footer>
        <el-button @click="expandedComposerVisible = false">取消</el-button>
        <el-button plain @click="applyExpandedComposer">回填</el-button>
        <el-button type="primary" :disabled="!expandedComposerText.trim()" @click="sendExpandedComposer">发送</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="quickPhraseDialogVisible" title="快捷短语模块" width="min(560px, calc(100vw - 32px))" append-to-body>
      <div class="phrase-manager">
        <article v-for="phrase in quickPhrases" :key="phrase.id" class="phrase-row">
          <el-input v-model="phrase.label" size="small" placeholder="标题" />
          <el-input v-model="phrase.text" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" resize="none" placeholder="短语内容" />
          <el-button type="primary" link @click="insertQuickPhrase(phrase.text)">插入</el-button>
          <el-button type="danger" link @click="removeQuickPhrase(phrase.id)">删除</el-button>
        </article>
        <div class="phrase-create-row">
          <el-input v-model="quickPhraseDraft.label" size="small" placeholder="新短语标题" />
          <el-input v-model="quickPhraseDraft.text" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" resize="none" placeholder="新短语内容" />
          <el-button type="primary" :disabled="!quickPhraseDraft.label.trim() || !quickPhraseDraft.text.trim()" @click="addQuickPhrase">添加</el-button>
        </div>
      </div>
      <template #footer>
        <el-button @click="resetQuickPhrases">恢复默认</el-button>
        <el-button type="primary" @click="quickPhraseDialogVisible = false">完成</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="translationDialogVisible" :title="translationDialogTitle" width="min(520px, calc(100vw - 32px))" append-to-body>
      <div class="translation-result">{{ translationResult }}</div>
      <template #footer>
        <el-button @click="translationDialogVisible = false">关闭</el-button>
        <el-button plain :disabled="!translationResult" @click="handleCopy(translationResult)">复制</el-button>
        <el-button type="primary" :disabled="!translationResult" @click="applyTranslationToInput">回填输入框</el-button>
      </template>
    </el-dialog>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import type { Component } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowUp,
  Bottom,
  CircleClose,
  Close,
  Delete,
  Expand,
  FolderOpened,
  FullScreen,
  Headset,
  Fold,
  MagicStick,
  Microphone,
  MoreFilled,
  Moon,
  Plus,
  Promotion,
  RefreshRight,
  Search,
  Setting,
  StarFilled,
  Sunny,
  WarningFilled,
} from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { useChatDomain } from '../composables/useChatDomain'
import { useMessageSearch } from '../composables/useMessageSearch'
import { useSessionDrafts } from '../composables/useSessionDrafts'
import { useSessionViewState } from '../composables/useSessionViewState'
import ChatMessageList from '../components/ChatMessageList.vue'
import SessionRail from '../components/SessionRail.vue'
import ChatComposerStatusLine from '../components/ChatComposerStatusLine.vue'
import ChatPlaybackBar from '../components/ChatPlaybackBar.vue'
import ChatRuntimeSettings, { type ChatRuntimeSettingsModel } from '../components/ChatRuntimeSettings.vue'
import ChatVoiceStatus from '../components/ChatVoiceStatus.vue'
import { enumerateAudioInputDevices, type AudioInputDevice } from '@/audio/audio-capture'
import { shouldOfferRealtimeInterrupt, shouldOfferRealtimeRecovery } from '@/app/runtime/realtimeRecoveryPolicy'
import { useChatStore } from '@/stores/chatStore'
import { useSessionStore } from '@/stores/sessionStore'
import { DEFAULT_DAILY_PROMPT, DEFAULT_WORK_PROMPT, useWorkspaceStore } from '@/stores/workspaceStore'
import { useSettingsStore } from '@/state/settingsStore'
import { DEFAULT_LLM_MAX_OUTPUT_TOKENS } from '@/../shared/runtime-defaults'
import { useInputBindingsStore } from '@/state/inputBindingsStore'
import { settingsClient, systemClient } from '@/api/client'
import { memoryClient } from '@/api/clients/memory-client'
import type { ChatAttachment, ChatMemorySource, ChatMessage, ChatOptions } from '@/../shared/types'
import type { WorkspacePromptMode } from '@/../shared/workspace'

interface QuickPhrase {
  id: string
  label: string
  text: string
  iconKey?: QuickPhraseIconKey
}

type QuickPhraseIconKey = 'camera' | 'refresh' | 'voice' | 'magic'
type ReasoningOption = NonNullable<ChatOptions['reasoning_effort']>
type ResponseModeOption = NonNullable<ChatOptions['response_mode']>
type PromptModeOption = WorkspacePromptMode
type ComposerToolId =
  | 'attach'
  | 'quickPhrases'
  | 'expandInput'
  | 'voiceInput'
  | 'webSearch'
  | 'translate'
  | 'voiceStatus'
type QuickPanelMode = 'slash' | 'mention'

interface ComposerToolDefinition {
  id: ComposerToolId
  label: string
  icon: Component
  title?: string
  active?: boolean
  disabled?: boolean
  run: () => void | Promise<void>
}

interface QuickPanelItem {
  id: string
  label: string
  description?: string
  icon: Component
  disabled?: boolean
  current?: boolean
  run: () => void | Promise<void>
}

type RequiredChatOptions = ChatOptions & {
  model: string
  temperature: number
  top_p: number
  top_k: number
  min_p: number
  frequency_penalty: number
  presence_penalty: number
  repetition_penalty: number
  max_tokens: number
  reasoning_effort: ReasoningOption
  response_mode: ResponseModeOption
  voice_mode: 'push-to-talk' | 'continuous'
  vad_eagerness: 'low' | 'medium' | 'high' | 'auto'
  audio_input_device_id: string
  mcp_enabled: boolean
  web_search_enabled: boolean
  tts_enabled: boolean
  pet_link_enabled: boolean
  translation_target: string
  prompt_mode: PromptModeOption
}

const {
  socketDomain,
  chatState,
  inputText,
  isRecording,
  audioCaptureState,
  startMic,
  stopMic,
  toggleMic,
  handleInterrupt,
} = useChatDomain()
const chatStore = useChatStore()
const sessionDrafts = useSessionDrafts()
const sessionViewState = useSessionViewState()
const { draftSessionIds } = sessionDrafts
const sessionStore = useSessionStore()
const settingsStore = useSettingsStore()
const inputBindingsStore = useInputBindingsStore()
const pushToTalkShortcutTitle = computed(() => `${inputBindingsStore.pushToTalkLabel.value}说话`)
const workspaceStore = useWorkspaceStore()
const chatOptions = chatStore.chatOptions as RequiredChatOptions
const route = useRoute()
const router = useRouter()

const messagesContainer = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const isComposing = ref(false)
const showScrollBtn = ref(false)
const dragOver = ref(false)
const expandedComposerVisible = ref(false)
const expandedComposerText = ref('')
const quickPhraseDialogVisible = ref(false)
const translationDialogVisible = ref(false)
const translationResult = ref('')
const translationDialogTitle = ref('翻译结果')
const composerTranslating = ref(false)
const messageTranslatingIndex = ref<number | null>(null)
const modelOptions = ref<string[]>([])
const modelsLoading = ref(false)
const audioInputDevices = ref<AudioInputDevice[]>([])
const audioDevicesLoading = ref(false)
const modelOptionsProviderKey = ref('')
let warmupTimer: number | null = null
const mcpSummaryLabel = ref('MCP 状态待刷新')
const attachments = ref<ChatAttachment[]>([])
const isCreatingSession = ref(false)
const voiceMode = ref<'tap' | 'hold'>('tap')
const isHoldActive = ref(false)
const holdStartPending = ref(false)
const quickPhraseDraft = reactive({ label: '', text: '' })
const toolsExpanded = ref(false)
const editingMessage = reactive({
  index: -1,
  content: '',
  saving: false,
})
const CHAT_SESSION_RAIL_STORAGE_KEY = 'yuizaki.chat.sessionRailVisible'
const primaryComposerToolOrder: ComposerToolId[] = [
  'attach',
  'quickPhrases',
  'expandInput',
  'voiceInput',
  'webSearch',
  'translate',
  'voiceStatus',
]

const quickPanel = reactive({
  visible: false,
  mode: 'slash' as QuickPanelMode,
  query: '',
  selectedIndex: 0,
})

const loadSessionRailVisibility = () => {
  if (typeof window === 'undefined') return true
  try {
    const raw = window.localStorage.getItem(CHAT_SESSION_RAIL_STORAGE_KEY)
    if (raw === null) return false
    return raw === 'true'
  } catch {
    return false
  }
}

const showSessionRail = ref(loadSessionRailVisibility())

const voiceModeOptions = [
  { label: '轻点', value: 'tap' },
  { label: '按住', value: 'hold' },
]

const quickPhraseIconKeys = new Set<QuickPhraseIconKey>(['camera', 'refresh', 'voice', 'magic'])

const defaultQuickPhrases: QuickPhrase[] = [
  {
    id: 'summarize-material',
    label: '总结材料',
    text: '请帮我总结当前材料里的重点，并给出下一步建议。',
    iconKey: 'magic',
  },
  {
    id: 'continue-context',
    label: '继续刚才',
    text: '请接着上一轮对话继续，先复述你理解的上下文，再给我下一步。',
    iconKey: 'refresh',
  },
  {
    id: 'voice-brief',
    label: '语音简答',
    text: '请用适合语音播放的方式回答：短句、自然、不要长列表。',
    iconKey: 'voice',
  },
  {
    id: 'break-down',
    label: '帮我拆解',
    text: '请把这件事拆成 3 个可执行步骤，并说明每一步的判断标准。',
    iconKey: 'magic',
  },
]

const QUICK_PHRASES_STORAGE_KEY = 'yuizaki.chat.quickPhrases'
const TEXT_ATTACHMENT_EXTENSIONS = new Set(['txt', 'md', 'markdown', 'json', 'jsonl', 'csv', 'tsv', 'log', 'yaml', 'yml', 'xml', 'html', 'css', 'js', 'ts', 'tsx', 'jsx', 'vue', 'py', 'bat', 'ps1', 'sh'])
const MAX_ATTACHMENT_TEXT_CHARS = 16000

const loadQuickPhrases = (): QuickPhrase[] => {
  if (typeof window === 'undefined') return defaultQuickPhrases.map((item) => ({ ...item }))
  try {
    const raw = window.localStorage.getItem(QUICK_PHRASES_STORAGE_KEY)
    if (!raw) return defaultQuickPhrases.map((item) => ({ ...item }))
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return defaultQuickPhrases.map((item) => ({ ...item }))
    const phrases = parsed
      .filter((item): item is QuickPhrase => Boolean(item && typeof item.label === 'string' && typeof item.text === 'string'))
      .map((item) => {
        const iconKey = typeof item.iconKey === 'string' && quickPhraseIconKeys.has(item.iconKey as QuickPhraseIconKey)
          ? item.iconKey as QuickPhraseIconKey
          : 'magic'
        return {
          id: item.id || `phrase_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          label: item.label,
          text: item.text,
          iconKey,
        }
      })
    return phrases.length ? phrases : defaultQuickPhrases.map((item) => ({ ...item }))
  } catch {
    return defaultQuickPhrases.map((item) => ({ ...item }))
  }
}

const quickPhrases = ref<QuickPhrase[]>(loadQuickPhrases())

const reasoningOptions: Array<{ label: string; value: ReasoningOption }> = [
  { label: '默认思考', value: 'default' },
  { label: '关闭思考', value: 'none' },
  { label: 'Minimal', value: 'minimal' },
  { label: 'Low', value: 'low' },
  { label: 'Medium', value: 'medium' },
  { label: 'High', value: 'high' },
  { label: 'XHigh', value: 'xhigh' },
  { label: 'Auto', value: 'auto' },
]

const responseModeOptions: Array<{ label: string; value: ResponseModeOption }> = [
  { label: '即时', value: 'instant' },
  { label: '均衡', value: 'balanced' },
  { label: '深度', value: 'deep' },
]

const lastAssistantMessage = computed(() => [...chatState.messages].reverse().find((message) => message.role === 'assistant') ?? null)
const playbackText = computed(() => {
  const text = lastAssistantMessage.value?.content?.replace(/\s+/g, ' ').trim() ?? ''
  return text.length > 120 ? `${text.slice(0, 120)}…` : text
})
const pendingAssistantLabel = computed(() => {
  if (chatOptions.reasoning_effort && !['none', 'default'].includes(chatOptions.reasoning_effort)) return '思考中'
  return '等待模型输出'
})
const hasConversationContent = computed(() => Boolean(chatState.messages.length || chatState.currentText || chatState.asrPartialText))
const workspaceNameMap = computed(() => Object.fromEntries(workspaceStore.workspaces.map((workspace) => [workspace.id, workspace.name])))
const effectiveModelLabel = computed(() => chatOptions.model || settingsStore.state.llm.model || '默认模型')
const webSearchLabel = computed(() => chatOptions.web_search_enabled ? '联网搜索开启' : '联网搜索关闭')
const openPromptPanel = () => {
  const workspaceId = String(route.params.workspaceId || workspaceStore.activeWorkspaceId || 'default')
  void router.push(`/w/${encodeURIComponent(workspaceId)}/prompt`)
}
const activePromptProfile = computed(() => ({
  mode: workspaceStore.activeWorkspace.context.promptMode || 'auto',
  promptEngineering: workspaceStore.activeWorkspace.context.promptEngineering,
  roleCard: workspaceStore.activeWorkspace.context.roleCard,
  worldBook: workspaceStore.activeWorkspace.context.worldBook,
}))
const roleCardHasContent = computed(() => {
  const roleCard = workspaceStore.activeWorkspace.context.roleCard
  return roleCard.enabled !== false && [
    roleCard.name,
    roleCard.personality,
    roleCard.scenario,
    roleCard.instructions,
    roleCard.firstMessage,
  ].some((value) => value.trim())
})
const basePromptCustomized = computed(() => {
  const promptEngineering = workspaceStore.activeWorkspace.context.promptEngineering
  return promptEngineering.workPrompt.trim() !== DEFAULT_WORK_PROMPT.trim() ||
    promptEngineering.dailyPrompt.trim() !== DEFAULT_DAILY_PROMPT.trim()
})
const promptProfileActive = computed(() => {
  const context = workspaceStore.activeWorkspace.context
  return basePromptCustomized.value || roleCardHasContent.value || context.worldBook.enabled === true
})
watch(activePromptProfile, (profile) => {
  chatStore.setPromptProfile(profile)
}, { immediate: true, deep: true })
const maxChatOutputTokens = computed(() => {
  const configured = Number(settingsStore.state.llm.default_max_output_tokens || DEFAULT_LLM_MAX_OUTPUT_TOKENS)
  const safeConfigured = Number.isFinite(configured) ? Math.round(configured) : DEFAULT_LLM_MAX_OUTPUT_TOKENS
  return Math.max(256, Math.min(65535, safeConfigured))
})
const updateRuntimeChatOption = (field: keyof ChatRuntimeSettingsModel, value: string | number | boolean) => {
  chatStore.setChatOptions({ [field]: value } as Partial<ChatOptions>)
}
const refreshAudioInputDevices = async () => {
  if (audioDevicesLoading.value) return
  audioDevicesLoading.value = true
  try {
    audioInputDevices.value = await enumerateAudioInputDevices()
  } catch {
    audioInputDevices.value = []
  } finally {
    audioDevicesLoading.value = false
  }
}
const togglePetLink = (enabled: boolean) => {
  chatStore.setChatOptions({ pet_link_enabled: enabled })
}
const canSendComposer = computed(() => Boolean(inputText.value.trim() || attachments.value.length))
const resolvedTheme = computed(() => {
  const preferred = settingsStore.state.system.theme || 'light'
  if (preferred !== 'system') return preferred
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
})
watch(maxChatOutputTokens, (limit) => {
  if (chatOptions.max_tokens > limit) {
    chatStore.setChatOptions({ max_tokens: limit })
  }
}, { immediate: true })
const composerToolRegistry = computed<Record<ComposerToolId, ComposerToolDefinition>>(() => ({
  attach: {
    id: 'attach',
    label: '上传文件',
    icon: FolderOpened,
    run: triggerFilePicker,
  },
  quickPhrases: {
    id: 'quickPhrases',
    label: '快捷短语',
    icon: MagicStick,
    run: () => openQuickPanel('slash'),
  },
  expandInput: {
    id: 'expandInput',
    label: '展开输入框',
    icon: FullScreen,
    run: openExpandedComposer,
  },
  voiceInput: {
    id: 'voiceInput',
    label: isRecording.value ? '结束录音' : '语音输入',
    icon: Microphone,
    active: isRecording.value,
    disabled: !socketDomain.isConnected.value,
    run: toggleMic,
  },
  webSearch: {
    id: 'webSearch',
    label: '网络搜索',
    title: webSearchLabel.value,
    icon: Search,
    active: chatOptions.web_search_enabled,
    run: toggleWebSearch,
  },
  translate: {
    id: 'translate',
    label: '翻译输入',
    icon: RefreshRight,
    disabled: !inputText.value.trim() || composerTranslating.value,
    run: () => { void translateComposerInput() },
  },
  voiceStatus: {
    id: 'voiceStatus',
    label: toolsExpanded.value ? '收起语音状态' : '语音状态',
    icon: Headset,
    active: toolsExpanded.value,
    run: () => { toolsExpanded.value = !toolsExpanded.value },
  },
}))
const visibleComposerTools = computed(() => primaryComposerToolOrder
  .map((id) => composerToolRegistry.value[id])
  .filter((tool): tool is ComposerToolDefinition => Boolean(tool)))
const quickPanelTitle = computed(() => quickPanel.mode === 'mention' ? '选择模型' : '快捷面板')
const quickPanelEmptyText = computed(() => quickPanel.mode === 'mention' ? '没有匹配的模型' : '没有匹配的快捷项')
const slashPanelItems = computed<QuickPanelItem[]>(() => [
  ...quickPhrases.value.map((phrase) => ({
    id: `phrase:${phrase.id}`,
    label: phrase.label,
    description: phrase.text,
    icon: quickPhraseIcon(phrase.iconKey),
    run: () => applyQuickPanelPhrase(phrase.text),
  })),
  {
    id: 'command:newTopic',
    label: '新话题',
    description: isCreatingSession.value ? '正在创建新会话' : '创建一条干净的新会话',
    icon: Plus,
    disabled: isCreatingSession.value,
    run: () => { void handleCreateSession() },
  },
  {
    id: 'command:attach',
    label: '上传文件',
    description: '添加文本、图片或本地文件上下文',
    icon: FolderOpened,
    run: triggerFilePicker,
  },
  {
    id: 'command:managePhrases',
    label: '管理快捷短语',
    description: '编辑、添加或恢复默认短语',
    icon: MagicStick,
    run: () => { quickPhraseDialogVisible.value = true },
  },
  {
    id: 'command:clear',
    label: '清空消息',
    description: '删除当前会话中的所有消息',
    icon: Delete,
    disabled: !hasConversationContent.value,
    run: () => { void handleClearConversation() },
  },
  {
    id: 'command:voice',
    label: '语音输入',
    description: socketDomain.isConnected.value ? '切换麦克风输入' : '实时通道连接后可用',
    icon: Microphone,
    disabled: !socketDomain.isConnected.value,
    run: toggleMic,
  },
])
const modelPanelItems = computed<QuickPanelItem[]>(() => {
  const models = Array.from(new Set(['', settingsStore.state.llm.model, chatOptions.model, ...modelOptions.value].filter((model): model is string => typeof model === 'string')))
  return models.map((model) => ({
    id: `model:${model || 'default'}`,
    label: model || '默认模型',
    description: model ? '设为当前对话模型' : '跟随设置里的默认模型',
    icon: MagicStick,
    current: model === chatOptions.model || (!model && !chatOptions.model),
    run: () => selectQuickPanelModel(model),
  }))
})
const quickPanelItems = computed(() => {
  const source = quickPanel.mode === 'mention' ? modelPanelItems.value : slashPanelItems.value
  const query = quickPanel.query.trim().toLowerCase()
  if (!query) return source
  return source.filter((item) => {
    const label = item.label.toLowerCase()
    const description = item.description?.toLowerCase() || ''
    return label.includes(query) || description.includes(query)
  })
})
const voiceMeterBars = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
const voiceLevelPercent = computed(() => Math.round(Math.min(1, audioCaptureState.level) * 100))
const voiceStatusText = computed(() => {
  if (audioCaptureState.inputHealth === 'disconnected') return '麦克风已断开'
  if (audioCaptureState.phase === 'error') return audioCaptureState.error || '麦克风异常'
  if (isRecording.value && audioCaptureState.inputHealth === 'silent') return '暂未检测到声音'
  if (isRecording.value) return '正在收音'
  if (!socketDomain.isConnected.value) return '实时通道连接中'
  if (chatState.isTTSPlaying) return '正在播放'
  if (chatState.asrPartialText) return '正在识别'
  return '语音就绪'
})
const voicePipelineText = computed(() => {
  if (!socketDomain.isConnected.value) return '实时通道未连接'
  if (isRecording.value) {
    const silenceHint = audioCaptureState.inputHealth === 'silent'
      ? ` · 静音 ${Math.round(audioCaptureState.silenceMs / 1000)} 秒`
      : ''
    return `${formatDuration(audioCaptureState.elapsedMs)} · ${audioCaptureState.chunksSent} 块 · ${formatBytes(audioCaptureState.bytesSent)}${silenceHint}`
  }
  if (chatState.asrPartialText) return 'ASR 已返回部分文本'
  if (chatState.isGenerating) return 'LLM 正在处理当前上下文'
  if (chatState.isTTSPlaying) return 'TTS 音频正在输出'
  return chatOptions.tts_enabled ? 'ASR → Agent → TTS 链路待命' : 'ASR → Agent，TTS 已关闭'
})
const voiceProcessingText = computed(() => {
  const processing = audioCaptureState.audioProcessing
  const formatState = (label: string, value: boolean | null) => (
    value === null ? null : `${label} ${value ? '开' : '关'}`
  )
  return [
    formatState('AEC', processing.echoCancellation),
    formatState('降噪', processing.noiseSuppression),
    formatState('AGC', processing.autoGainControl),
    audioCaptureState.inputSampleRate
      ? `${Math.round(audioCaptureState.inputSampleRate / 1000)}k → 16kHz`
      : null,
  ].filter(Boolean).join(' · ')
})
const voiceLatencySummary = computed(() => {
  const asrStages = chatState.voiceLatency.asr?.stages
  const generationStages = chatState.voiceLatency.generation?.stages
  const endpointMs = asrStages?.endpoint_detected
  const asrFinalMs = asrStages?.asr_final
  const firstTokenMs = generationStages?.llm_first_token
  const firstSentenceMs = generationStages?.llm_first_sentence
  const firstAudioMs = generationStages?.tts_first_audio_ready
  const playbackMs = generationStages?.playback_start
  const parts: string[] = []
  if (endpointMs !== undefined) parts.push(`端点 ${Math.round(endpointMs)} ms`)
  if (firstTokenMs !== undefined) parts.push(`首字 ${Math.round(firstTokenMs)} ms`)
  if (firstSentenceMs !== undefined) parts.push(`成句 ${Math.round(firstSentenceMs)} ms`)
  if (playbackMs !== undefined) {
    parts.push(`首播 ${Math.round((asrFinalMs ?? 0) + playbackMs)} ms`)
  } else if (firstAudioMs !== undefined) {
    parts.push(`首段 ${Math.round((asrFinalMs ?? 0) + firstAudioMs)} ms`)
  }
  return parts.join(' · ')
})
const voiceStatusClass = computed(() => ({
  recording: isRecording.value,
  error: audioCaptureState.phase === 'error',
  silent: isRecording.value && audioCaptureState.inputHealth === 'silent',
  disconnected: audioCaptureState.inputHealth === 'disconnected',
  offline: !socketDomain.isConnected.value,
  speaking: chatState.isTTSPlaying,
}))
const showRealtimeRecovery = computed(() => shouldOfferRealtimeRecovery({
  responseMode: chatOptions.response_mode,
  recording: isRecording.value,
  ttsPlaying: chatState.isTTSPlaying,
  status: chatState.realtimeStatus,
}))
const voiceInterruptible = computed(() => shouldOfferRealtimeInterrupt({
  ttsPlaying: chatState.isTTSPlaying,
  status: chatState.realtimeStatus,
}))
const retryRealtimeVoice = () => {
  window.dispatchEvent(new CustomEvent('pet:realtime-reconnect'))
}
const messageRoleLabel = (role: ChatMessage['role']) => {
  if (role === 'user') return '你'
  if (role === 'assistant') return '結崎'
  return '系统'
}
const {
  state: messageSearch,
  matches: messageSearchMatches,
  activeMessageIndex: activeSearchMessageIndex,
  resultLabel: searchResultLabel,
  open: openMessageSearchState,
  close: closeMessageSearch,
  toggle: toggleMessageSearchState,
  jump: jumpSearchResult,
  handleGlobalKeydown: handleMessageSearchKeydown,
} = useMessageSearch({
  messages: () => chatState.messages,
  roleLabel: messageRoleLabel,
  onMatchSelected: (index) => scrollToMessage(index),
})
const formatDuration = (ms: number) => {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, '0')
  const seconds = (totalSeconds % 60).toString().padStart(2, '0')
  return `${minutes}:${seconds}`
}
const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  return `${Math.round(bytes / 1024)} KB`
}

const quickPhraseIcon = (iconKey?: QuickPhraseIconKey) => {
  if (iconKey === 'camera') return FolderOpened
  if (iconKey === 'refresh') return RefreshRight
  if (iconKey === 'voice') return Microphone
  return MagicStick
}

const closeQuickPanel = () => {
  quickPanel.visible = false
  quickPanel.query = ''
  quickPanel.selectedIndex = 0
}

const stripQuickPanelTrigger = () => {
  inputText.value = inputText.value.replace(/(?:^|\s)[/@][^\s/@]*$/, (match) => match.startsWith(' ') ? ' ' : '')
}

const openQuickPanel = (mode: QuickPanelMode, query = '') => {
  quickPanel.mode = mode
  quickPanel.query = query
  quickPanel.selectedIndex = 0
  quickPanel.visible = true
  if (mode === 'mention') void refreshModelOptions()
}

const syncQuickPanelFromInput = () => {
  const match = inputText.value.match(/(?:^|\s)([/@])([^\s/@]*)$/)
  if (!match) {
    if (quickPanel.visible) closeQuickPanel()
    return
  }
  const mode: QuickPanelMode = match[1] === '@' ? 'mention' : 'slash'
  openQuickPanel(mode, match[2] || '')
}

const applyQuickPanelPhrase = (text: string) => {
  stripQuickPanelTrigger()
  applyQuickPhrase(text)
  closeQuickPanel()
}

const selectQuickPanelModel = (model: string) => {
  stripQuickPanelTrigger()
  chatOptions.model = model
  closeQuickPanel()
  ElMessage.success(model ? `已选择模型 ${model}` : '已切回默认模型')
}

const runQuickPanelItem = (item: QuickPanelItem) => {
  if (item.disabled) return
  stripQuickPanelTrigger()
  closeQuickPanel()
  void item.run()
}

const runSelectedQuickPanelItem = () => {
  const selected = quickPanelItems.value[quickPanel.selectedIndex]
  const item = selected && !selected.disabled
    ? selected
    : quickPanelItems.value.find((entry) => !entry.disabled)
  if (!item) return
  runQuickPanelItem(item)
}

const moveQuickPanelSelection = (delta: number) => {
  const items = quickPanelItems.value
  if (!items.length) return
  let next = quickPanel.selectedIndex
  for (let step = 0; step < items.length; step += 1) {
    next = (next + delta + items.length) % items.length
    if (!items[next]?.disabled) {
      quickPanel.selectedIndex = next
      return
    }
  }
}

const runComposerTool = (tool: ComposerToolDefinition) => {
  if (tool.disabled) return
  closeQuickPanel()
  void tool.run()
}

const handleComposerKeydown = (event: KeyboardEvent) => {
  if (quickPanel.visible) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      moveQuickPanelSelection(1)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      moveQuickPanelSelection(-1)
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      runSelectedQuickPanelItem()
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      closeQuickPanel()
      return
    }
  }
  if (event.key !== 'Enter' || event.shiftKey || isComposing.value) return
  event.preventDefault()
  handleSendComposer()
}

const contextMenu = reactive({ visible: false, x: 0, y: 0, index: -1 })
const openContextMenu = (e: MouseEvent, idx: number, _msg: ChatMessage) => {
  if (editingMessage.index >= 0) return
  contextMenu.visible = true
  contextMenu.x = e.clientX
  contextMenu.y = e.clientY
  contextMenu.index = idx
}
const closeContextMenu = () => { contextMenu.visible = false }
const handleCopy = async (content: string) => { await chatStore.copyMessage(content) }

const scrollToMessage = (index: number) => nextTick(() => {
  const container = messagesContainer.value
  if (!container) return
  const target = container.querySelector<HTMLElement>(`[data-message-index="${index}"]`)
  target?.scrollIntoView({ block: 'center', behavior: 'smooth' })
})

const focusMessageSearchInput = () => nextTick(() => {
  const input = document.querySelector<HTMLInputElement>('.chat-search-input input')
  input?.focus()
  input?.select()
})

const openMessageSearch = () => {
  openMessageSearchState()
  focusMessageSearchInput()
}

const toggleMessageSearch = () => {
  if (!messageSearch.visible) {
    openMessageSearch()
    return
  }
  toggleMessageSearchState()
}

const handleGlobalKeydown = (event: KeyboardEvent) => {
  const wasOpen = messageSearch.visible
  handleMessageSearchKeydown(event)
  if (!wasOpen && messageSearch.visible) focusMessageSearchInput()
}

const excerptMessage = (content: string, maxLength = 180) => {
  const normalized = content.replace(/\s+/g, ' ').trim()
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized
}

const quoteMessage = (msg: ChatMessage) => {
  const selectedText = window.getSelection()?.toString().trim()
  const quoteContent = selectedText || msg.content
  const quote = `> ${messageRoleLabel(msg.role)}：${excerptMessage(quoteContent)}\n\n`
  inputText.value = inputText.value.trim()
    ? `${inputText.value.trim()}\n\n${quote}`
    : quote
  closeContextMenu()
  ElMessage.success('已引用到输入框')
  scrollToBottom()
}

const handleSetContextStart = (idx: number) => {
  if (chatState.isGenerating) {
    ElMessage.info('生成中请先中断再调整上下文')
    return
  }
  chatStore.setContextStartIndex(idx)
  closeContextMenu()
  scrollToMessage(idx)
  ElMessage.success('已从这条消息开始上下文')
}

const handleResetContextStart = () => {
  chatStore.setContextStartIndex(0)
  ElMessage.success('已恢复完整上下文')
}

const messageRegenerationIndex = (idx: number) => {
  const message = chatState.messages[idx]
  if (!message) return -1
  if (message.role === 'user') return idx
  for (let index = idx - 1; index >= 0; index -= 1) {
    if (chatState.messages[index]?.role === 'user') return index
  }
  return -1
}

const canRegenerateFromIndex = (idx: number) => !chatState.isGenerating && messageRegenerationIndex(idx) >= 0

const handleDeleteMsg = async (idx: number) => {
  const message = chatState.messages[idx]
  if (!message) return
  try {
    await ElMessageBox.confirm('这会从本地历史中删除该消息，无法撤销。', '删除消息', {
      confirmButtonText: '删除消息',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
    await chatStore.deleteMessage(idx, chatState.currentWorkspaceId)
    if (message.id !== undefined) {
      sessionStore.noteMessageDeleted(chatState.currentSessionId)
    }
    ElMessage.success(message.id === undefined ? '已删除未同步的本地消息' : '消息已删除')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    console.warn('[ChatPanel] failed to delete message:', error)
    ElMessage.error('删除消息失败')
  }
}

const startMessageEdit = (idx: number, msg: ChatMessage) => {
  if (chatState.isGenerating) {
    ElMessage.info('生成中请先中断再编辑')
    return
  }
  editingMessage.index = idx
  editingMessage.content = msg.content
  editingMessage.saving = false
  closeContextMenu()
}

const cancelMessageEdit = () => {
  editingMessage.index = -1
  editingMessage.content = ''
  editingMessage.saving = false
}

const saveMessageEdit = async (resend: boolean | Event = false) => {
  const index = editingMessage.index
  const message = chatState.messages[index]
  const content = editingMessage.content.trim()
  const shouldResendRequested = resend === true
  if (!message || !content || editingMessage.saving) return
  editingMessage.saving = true
  try {
    await chatStore.updateMessage(index, content, chatState.currentWorkspaceId)
    const shouldResend = shouldResendRequested && message.role === 'user'
    cancelMessageEdit()
    if (shouldResend) {
      const removed = await chatStore.regenerateFromMessage(index, chatState.currentWorkspaceId)
      if (removed > 0) {
        sessionStore.noteMessagesDeleted(chatState.currentSessionId, removed)
      }
      ElMessage.success('已保存并重发')
      return
    }
    ElMessage.success('消息已更新')
  } catch (error) {
    console.warn('[ChatPanel] failed to update message:', error)
    ElMessage.error('保存消息失败')
    editingMessage.saving = false
  }
}

const handleRegenerate = async (idx: number) => {
  const sourceIndex = messageRegenerationIndex(idx)
  if (sourceIndex < 0) {
    ElMessage.info('没有可重发的用户消息')
    return
  }
  try {
    const removed = await chatStore.regenerateFromMessage(sourceIndex, chatState.currentWorkspaceId)
    if (removed > 0) {
      sessionStore.noteMessagesDeleted(chatState.currentSessionId, removed)
    }
  } catch (error) {
    console.warn('[ChatPanel] failed to regenerate message:', error)
    ElMessage.error('重新生成失败')
  }
  closeContextMenu()
}
const handleTopMoreCommand = (command: string) => {
  switch (command) {
    case 'copy-transcript':
      void chatStore.copyTranscript()
      break
    case 'copy-last':
      void chatStore.copyLastAssistantMessage()
      break
    case 'clear-context':
      void handleClearContext()
      break
    case 'reset-context':
      handleResetContextStart()
      break
    case 'clear-conversation':
      void handleClearConversation()
      break
    case 'open-expanded-composer':
      openExpandedComposer()
      break
    case 'quick-phrases':
      quickPhraseDialogVisible.value = true
      break
    case 'interrupt':
      handleInterrupt()
      break
    default:
      break
  }
}

const openSettings = () => {
  const workspaceId = String(route.params.workspaceId || 'default')
  void router.push(`/w/${encodeURIComponent(workspaceId)}/settings`)
}

const openPetSettings = () => {
  const workspaceId = String(route.params.workspaceId || 'default')
  void router.push(`/w/${encodeURIComponent(workspaceId)}/pet`)
}

const handleCorrectMemory = (source: ChatMemorySource) => {
  const workspaceId = String(route.params.workspaceId || chatState.currentWorkspaceId || 'default')
  void router.push({
    path: `/w/${encodeURIComponent(workspaceId)}/memory`,
    query: { edit: source.id },
  })
}

const handleForgetMemory = async (source: ChatMemorySource) => {
  try {
    await ElMessageBox.confirm('这条记忆将从后续检索中隐藏，可在记忆面板中恢复。', '忘记这条记忆', {
      confirmButtonText: '隐藏',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
    await memoryClient.softForgetDoc(source.id, {
      reason: 'chat_memory_feedback',
      turn_id: source.traceId,
      session_id: source.sessionId,
    })
    for (const message of chatState.messages) {
      if (!message.memorySources?.length) continue
      message.memorySources = message.memorySources.filter((item) => item.id !== source.id)
      if (Array.isArray(message.memory_trace)) {
        message.memory_trace = message.memory_trace.filter((item) => {
          if (!item || typeof item !== 'object') return true
          const record = item as Record<string, unknown>
          const doc = record.doc && typeof record.doc === 'object' ? record.doc as Record<string, unknown> : record
          return String(doc.id ?? record.document_id ?? '') !== source.id
        })
      }
    }
    ElMessage.success('已隐藏这条记忆')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    console.warn('[ChatPanel] failed to forget memory:', error)
    ElMessage.error('忘记记忆失败')
  }
}

const chatRouteForSession = (sessionId?: string, workspaceIdOverride?: string) => {
  const workspaceId = workspaceIdOverride || String(route.params.workspaceId || chatState.currentWorkspaceId || 'default')
  return sessionId && sessionId !== 'default'
    ? `/w/${encodeURIComponent(workspaceId)}/chat/${encodeURIComponent(sessionId)}`
    : `/w/${encodeURIComponent(workspaceId)}/chat`
}

const sessionWorkspaceId = (sessionId: string) =>
  sessionStore.sessions.find((session) => session.id === sessionId)?.workspace_id || chatState.currentWorkspaceId || workspaceStore.activeWorkspaceId || 'default'

const syncActiveWorkspaceForSessionView = async (workspaceId: string) => {
  if (workspaceStore.activeWorkspaceId === workspaceId) return
  await workspaceStore.setActiveWorkspaceSynced(workspaceId)
  await sessionStore.loadSessions()
}

const handleClearContext = async () => {
  try {
    await ElMessageBox.confirm('清理后，下一轮请求不会再携带此前消息，但当前视图仍会保留。', '清理上下文', {
      confirmButtonText: '清理',
      cancelButtonText: '取消',
      type: 'warning',
    })
    chatStore.clearContext()
    ElMessage.success('已从当前位置开始新上下文')
  } catch {
    // user cancelled
  }
}
const handleClearConversation = async () => {
  try {
    await ElMessageBox.confirm('这会删除当前会话中的所有消息，但会保留会话本身。此操作无法撤销。', '清空消息', {
      confirmButtonText: '清空消息',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
    const clearedPersistedMessages = await chatStore.clearConversationMessages(chatState.currentWorkspaceId)
    if (clearedPersistedMessages) {
      sessionStore.noteSessionMessagesCleared(chatState.currentSessionId)
    }
    ElMessage.success('已清空当前会话消息')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    console.warn('[ChatPanel] failed to clear conversation messages:', error)
    ElMessage.error('清空消息失败')
  }
}

const handleCreateSession = async () => {
  if (isCreatingSession.value) return
  isCreatingSession.value = true
  try {
    const workspaceId = workspaceStore.activeWorkspaceId || chatState.currentWorkspaceId || 'default'
    const session = await sessionStore.createSession(`新对话 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`)
    sessionStore.setActiveSession(session.id)
    chatStore.clearLocalMessages()
    chatStore.setWorkspaceContext(workspaceId, session.id)
    inputText.value = ''
    attachments.value = []
    closeQuickPanel()
    if (!showSessionRail.value) {
      toggleSessionRail()
    }
    try {
      await chatStore.loadHistory(session.id, workspaceId)
    } catch (historyError) {
      console.debug('[ChatPanel] new session history is not ready yet:', historyError)
      chatStore.clearLocalMessages()
      chatStore.setWorkspaceContext(workspaceId, session.id)
    }
    await router.replace(chatRouteForSession(session.id))
    restoreSessionScroll(session.id)
    ElMessage.success('已创建新会话')
  } catch (error) {
    console.warn('[ChatPanel] failed to create session:', error)
    const message = error instanceof Error && error.message ? error.message : '请确认后端服务已启动'
    ElMessage.error(`新建会话失败：${message}`)
  } finally {
    isCreatingSession.value = false
  }
}

const handleSelectSession = async (sessionId: string) => {
  if (!sessionId || sessionId === sessionStore.activeSessionId) return
  const selectedSession = sessionStore.sessions.find((session) => session.id === sessionId)
  const targetWorkspaceId = selectedSession?.workspace_id || chatState.currentWorkspaceId || 'default'
  sessionStore.setActiveSession(sessionId)
  chatStore.clearLocalMessages()
  chatStore.setWorkspaceContext(targetWorkspaceId, sessionId)
  await syncActiveWorkspaceForSessionView(targetWorkspaceId)
  await router.replace(chatRouteForSession(sessionId, targetWorkspaceId))
  try {
    await chatStore.loadHistory(sessionId, targetWorkspaceId)
  } catch (error) {
    console.warn('[ChatPanel] failed to load session history:', error)
    ElMessage.error('加载会话失败')
  }
  restoreSessionScroll(sessionId)
}

const handleTogglePin = async (sessionId: string, pinned: boolean) => {
  try {
    await sessionStore.updateSession(sessionId, { pinned }, sessionWorkspaceId(sessionId))
  } catch (error) {
    console.warn('[ChatPanel] failed to update session pin:', error)
    ElMessage.error('更新置顶失败')
  }
}

const handleRenameSession = async (sessionId: string, title: string) => {
  try {
    await sessionStore.updateSession(sessionId, { title }, sessionWorkspaceId(sessionId))
  } catch (error) {
    console.warn('[ChatPanel] failed to rename session:', error)
    ElMessage.error('重命名失败')
  }
}

const handleArchiveSession = async (sessionId: string, archived: boolean) => {
  try {
    await sessionStore.updateSession(sessionId, { archived }, sessionWorkspaceId(sessionId))
    if (archived && sessionId === sessionStore.activeSessionId) {
      const nextSession = sessionStore.sessions.find((session) => !session.archived && session.id !== sessionId)
      if (nextSession) {
        await handleSelectSession(nextSession.id)
      } else {
        await handleCreateSession()
      }
    }
  } catch (error) {
    console.warn('[ChatPanel] failed to archive session:', error)
    ElMessage.error(archived ? '归档会话失败' : '恢复会话失败')
  }
}

const handleCreateBranch = async (_index: number, message: ChatMessage) => {
  if (chatState.isGenerating) return
  const messageId = Number(message.id)
  if (!Number.isInteger(messageId)) {
    ElMessage.warning('这条消息尚未保存，无法创建分支')
    return
  }
  const sourceSession = sessionStore.activeSession
  const sourceSessionId = sourceSession?.id || chatState.currentSessionId
  const workspaceId = sourceSession?.workspace_id || chatState.currentWorkspaceId || 'default'
  try {
    const branch = await sessionStore.branchSession(
      sourceSessionId,
      messageId,
      `${sourceSession?.title || '当前会话'} · 分支`,
      workspaceId,
    )
    chatStore.clearLocalMessages()
    chatStore.setWorkspaceContext(workspaceId, branch.id)
    await router.replace(chatRouteForSession(branch.id, workspaceId))
    await chatStore.loadHistory(branch.id, workspaceId)
    restoreSessionScroll(branch.id)
    ElMessage.success('已创建会话分支')
  } catch (error) {
    console.warn('[ChatPanel] failed to create session branch:', error)
    ElMessage.error('创建会话分支失败')
  }
}

const handleDeleteSession = async (sessionId: string) => {
  const wasActive = sessionId === sessionStore.activeSessionId
  try {
    await ElMessageBox.confirm('这会删除该会话和其中的所有消息，无法撤销。', '删除会话', {
      confirmButtonText: '删除会话',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
    await sessionStore.deleteSession(sessionId, sessionWorkspaceId(sessionId))
    sessionDrafts.clearDraft(sessionId)
    sessionViewState.clearSession(sessionId)
    if (wasActive) {
      const nextSession = sessionStore.activeSession
      if (nextSession) {
        const nextWorkspaceId = nextSession.workspace_id || workspaceStore.activeWorkspaceId || 'default'
        await syncActiveWorkspaceForSessionView(nextWorkspaceId)
        chatStore.setWorkspaceContext(nextWorkspaceId, nextSession.id)
        await router.replace(chatRouteForSession(nextSession.id, nextWorkspaceId))
        await chatStore.loadHistory(nextSession.id, nextWorkspaceId)
      } else {
        const workspaceId = workspaceStore.activeWorkspaceId || chatState.currentWorkspaceId || 'default'
        chatStore.clearLocalMessages()
        chatStore.setWorkspaceContext(workspaceId, 'default')
        await router.replace(chatRouteForSession(undefined, workspaceId))
      }
    }
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    console.warn('[ChatPanel] failed to delete session:', error)
    ElMessage.error('删除会话失败')
  }
}

const applyQuickPhrase = (text: string) => {
  inputText.value = inputText.value.trim()
    ? `${inputText.value.trim()}\n${text}`
    : text
  nextTick(() => scrollToBottom())
}

const toggleSessionRail = () => {
  showSessionRail.value = !showSessionRail.value
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(CHAT_SESSION_RAIL_STORAGE_KEY, String(showSessionRail.value))
  }
}

const applyDocumentTheme = () => {
  const theme = resolvedTheme.value
  document.documentElement.setAttribute('data-theme', theme)
  document.documentElement.style.colorScheme = theme
}

const toggleTheme = async () => {
  const nextTheme = resolvedTheme.value === 'dark' ? 'light' : 'dark'
  settingsStore.state.system.theme = nextTheme
  applyDocumentTheme()
  try {
    await settingsStore.saveSettings({ system: { ...settingsStore.state.system, theme: nextTheme } })
  } catch {
    ElMessage.warning('主题已本地切换，后端连接后再保存')
  }
}

const toggleWebSearch = () => {
  chatStore.setChatOptions({ web_search_enabled: !chatOptions.web_search_enabled })
}

const toggleTtsOutput = (value: string | number | boolean) => {
  chatStore.setTtsEnabled(value === true)
}

const insertQuickPhrase = (text: string) => {
  applyQuickPhrase(text)
  quickPhraseDialogVisible.value = false
}

const persistQuickPhrases = () => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(QUICK_PHRASES_STORAGE_KEY, JSON.stringify(quickPhrases.value))
}

const addQuickPhrase = () => {
  const label = quickPhraseDraft.label.trim()
  const text = quickPhraseDraft.text.trim()
  if (!label || !text) return
  quickPhrases.value.push({
    id: `phrase_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    label,
    text,
    iconKey: 'magic',
  })
  quickPhraseDraft.label = ''
  quickPhraseDraft.text = ''
}

const removeQuickPhrase = (id: string) => {
  quickPhrases.value = quickPhrases.value.filter((phrase) => phrase.id !== id)
}

const resetQuickPhrases = () => {
  quickPhrases.value = defaultQuickPhrases.map((item) => ({ ...item }))
}

const openExpandedComposer = () => {
  expandedComposerText.value = inputText.value
  expandedComposerVisible.value = true
}

const applyExpandedComposer = () => {
  inputText.value = expandedComposerText.value
  expandedComposerVisible.value = false
}

const sendExpandedComposer = () => {
  inputText.value = expandedComposerText.value
  expandedComposerVisible.value = false
  handleSendComposer()
}

const triggerFilePicker = () => {
  fileInput.value?.click()
}

const fileExtension = (fileName: string) => fileName.split('.').pop()?.toLowerCase() || ''
const isTextLikeFile = (file: File) => file.type.startsWith('text/') || TEXT_ATTACHMENT_EXTENSIONS.has(fileExtension(file.name))

const readFileText = (file: File) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => resolve(String(reader.result || ''))
  reader.onerror = () => reject(reader.error)
  reader.readAsText(file)
})

const addFiles = async (files: FileList | File[]) => {
  const incoming = Array.from(files)
  for (const file of incoming) {
    if (file.type.startsWith('image/')) {
      attachments.value.push({
        id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        name: file.name,
        type: file.type || 'image',
        size: file.size,
        kind: 'image',
      })
      continue
    }

    if (isTextLikeFile(file)) {
      try {
        const content = await readFileText(file)
        attachments.value.push({
          id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
          name: file.name,
          type: file.type || 'text/plain',
          size: file.size,
          kind: 'text',
          content: content.slice(0, MAX_ATTACHMENT_TEXT_CHARS),
        })
      } catch {
        ElMessage.warning(`${file.name} 读取失败`)
      }
      continue
    }

    attachments.value.push({
      id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      name: file.name,
      type: file.type || 'application/octet-stream',
      size: file.size,
      kind: 'binary',
    })
  }
}

const handleFileInputChange = async (event: Event) => {
  const input = event.target as HTMLInputElement
  if (input.files?.length) {
    await addFiles(input.files)
  }
  input.value = ''
}

const removeAttachment = (id: string) => {
  attachments.value = attachments.value.filter((attachment) => attachment.id !== id)
}

const attachmentPromptBlock = (attachment: ChatAttachment) => {
  const header = `【附件：${attachment.name}｜${attachment.type || 'unknown'}｜${formatBytes(attachment.size)}】`
  if (attachment.kind === 'text') {
    const truncated = attachment.content && attachment.content.length >= MAX_ATTACHMENT_TEXT_CHARS ? '\n\n[内容已截断]' : ''
    return `${header}\n${attachment.content || ''}${truncated}`
  }
  if (attachment.kind === 'image') {
    return `${header}\n图片已作为附件加入；请基于文件名和用户补充说明处理。`
  }
  return `${header}\n该文件为二进制或暂不支持直接读取，请基于文件名和用户补充说明处理。`
}

const buildComposerMessage = () => {
  const text = inputText.value.trim()
  const attachmentText = attachments.value.map(attachmentPromptBlock).join('\n\n')
  if (!attachmentText) return text
  return [text, `以下是本次上传的文件内容或元数据：\n\n${attachmentText}`].filter(Boolean).join('\n\n')
}

const handleSendComposer = () => {
  if (chatState.isGenerating) return
  const text = buildComposerMessage().trim()
  if (!text) return
  if (chatStore.sendChat(text, { chatOptions })) {
    sessionDrafts.clearDraft(sessionStore.activeSessionId)
    sessionViewState.setAttachments(sessionStore.activeSessionId, [])
    inputText.value = ''
    attachments.value = []
  }
}

const translateComposerInput = async () => {
  const text = inputText.value.trim()
  if (!text) return
  composerTranslating.value = true
  try {
    const translated = await chatStore.translateText(text, chatOptions.translation_target)
    if (translated) {
      inputText.value = translated
      ElMessage.success('已翻译到输入框')
    }
  } catch (error) {
    console.warn('[ChatPanel] failed to translate composer:', error)
    ElMessage.error('翻译失败')
  } finally {
    composerTranslating.value = false
  }
}

const handleTranslateMessage = async (msg: ChatMessage, idx: number) => {
  if (!msg.content.trim() || messageTranslatingIndex.value !== null) return
  messageTranslatingIndex.value = idx
  translationDialogTitle.value = `翻译为 ${chatOptions.translation_target || 'zh-CN'}`
  translationResult.value = ''
  try {
    translationResult.value = await chatStore.translateText(msg.content, chatOptions.translation_target)
    translationDialogVisible.value = true
  } catch (error) {
    console.warn('[ChatPanel] failed to translate message:', error)
    ElMessage.error('翻译失败')
  } finally {
    messageTranslatingIndex.value = null
  }
}

const applyTranslationToInput = () => {
  if (!translationResult.value) return
  inputText.value = inputText.value.trim()
    ? `${inputText.value.trim()}\n${translationResult.value}`
    : translationResult.value
  translationDialogVisible.value = false
}

const refreshModelOptions = async (force = false) => {
  if (modelsLoading.value) return
  const providerKey = [
    settingsStore.state.llm.base_url,
    settingsStore.state.llm.api_key,
    settingsStore.state.llm.timeout,
  ].join('\u0000')
  if (!force && modelOptionsProviderKey.value === providerKey && modelOptions.value.length) {
    modelOptions.value = Array.from(new Set([
      ...modelOptions.value,
      settingsStore.state.llm.model,
      chatOptions.model,
    ].filter(Boolean)))
    return
  }
  modelsLoading.value = true
  let loaded = false
  try {
    const baseUrl = settingsStore.state.llm.base_url.trim()
    const isLocalProvider = /^https?:\/\/(localhost|127\.0\.0\.1)(?::\d+)?(?:\/|$)/i.test(baseUrl)
    // Do not probe a remote provider until credentials exist. This keeps first-run
    // startup local and avoids a needless upstream timeout in the chat surface.
    if (!baseUrl || (!settingsStore.state.llm.api_key.trim() && !isLocalProvider)) {
      modelOptions.value = [settingsStore.state.llm.model, chatOptions.model].filter((item): item is string => Boolean(item))
      loaded = true
      return
    }
    const result = await settingsClient.listLlmModels({
      base_url: settingsStore.state.llm.base_url,
      api_key: settingsStore.state.llm.api_key,
      timeout: settingsStore.state.llm.timeout,
    })
    const merged = new Set([settingsStore.state.llm.model, chatOptions.model, ...(result.models || [])].filter(Boolean) as string[])
    modelOptions.value = Array.from(merged)
    loaded = true
  } catch (error) {
    console.warn('[ChatPanel] failed to load LLM models:', error)
    modelOptions.value = [settingsStore.state.llm.model, chatOptions.model].filter((item): item is string => Boolean(item))
  } finally {
    if (loaded) modelOptionsProviderKey.value = providerKey
    modelsLoading.value = false
  }
}

const refreshMcpSummary = async () => {
  try {
    const snapshot = await systemClient.mcp()
    const rows = Object.entries(snapshot.servers || {})
    const connected = rows.filter(([name, server]) => snapshot.status?.[name]?.connected && (snapshot.status?.[name]?.enabled ?? server.enabled)).length
    const enabled = rows.filter(([name, server]) => snapshot.status?.[name]?.enabled ?? server.enabled).length
    mcpSummaryLabel.value = `${connected}/${enabled} 个 MCP 服务可用`
  } catch {
    mcpSummaryLabel.value = 'MCP 状态获取失败'
  }
}

const beginHoldToTalk = async () => {
  if (voiceMode.value !== 'hold' || isHoldActive.value || holdStartPending.value) return
  isHoldActive.value = true
  holdStartPending.value = true
  try {
    await startMic()
  } finally {
    holdStartPending.value = false
  }
}

const endHoldToTalk = () => {
  if (!isHoldActive.value) return
  isHoldActive.value = false
  stopMic()
}

const handleHoldPointerDown = (event: PointerEvent) => {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  void beginHoldToTalk()
}

const handleHoldPointerUp = (event: PointerEvent) => {
  ;(event.currentTarget as HTMLElement | null)?.releasePointerCapture?.(event.pointerId)
  endHoldToTalk()
}

const checkScrollPosition = () => {
  const el = messagesContainer.value
  if (!el) return
  sessionViewState.setScrollPosition(sessionStore.activeSessionId, el.scrollTop)
  showScrollBtn.value = el.scrollHeight - el.scrollTop - el.clientHeight > 200
}

const handleDrop = async (e: DragEvent) => {
  dragOver.value = false
  const files = e.dataTransfer?.files
  if (!files?.length) return
  await addFiles(files)
}

const scrollToBottom = () => nextTick(() => {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    sessionViewState.setScrollPosition(sessionStore.activeSessionId, messagesContainer.value.scrollTop)
    showScrollBtn.value = false
  }
})

const restoreSessionScroll = (sessionId = sessionStore.activeSessionId) => nextTick(() => {
  const container = messagesContainer.value
  if (!container) return
  const savedPosition = sessionViewState.getScrollPosition(sessionId)
  container.scrollTop = savedPosition ?? container.scrollHeight
  showScrollBtn.value = container.scrollHeight - container.scrollTop - container.clientHeight > 200
})

watch(() => chatState.messages.length, scrollToBottom)
watch(() => chatState.currentText, scrollToBottom)
watch(() => chatState.asrPartialText, scrollToBottom)
watch(quickPhrases, persistQuickPhrases, { deep: true })
watch(() => sessionStore.activeSessionId, (sessionId, previousSessionId) => {
  if (previousSessionId) {
    sessionDrafts.setDraft(previousSessionId, inputText.value)
    sessionViewState.setAttachments(previousSessionId, attachments.value)
    if (messagesContainer.value) {
      sessionViewState.setScrollPosition(previousSessionId, messagesContainer.value.scrollTop)
    }
  }
  inputText.value = sessionDrafts.getDraft(sessionId)
  attachments.value = sessionViewState.getAttachments(sessionId)
  restoreSessionScroll(sessionId)
}, { immediate: true, flush: 'sync' })
watch(inputText, () => {
  sessionDrafts.setDraft(sessionStore.activeSessionId, inputText.value)
  if (isComposing.value) return
  syncQuickPanelFromInput()
})
watch(quickPanelItems, (items) => {
  if (!items.length) {
    quickPanel.selectedIndex = 0
    return
  }
  if (quickPanel.selectedIndex >= items.length) {
    quickPanel.selectedIndex = Math.max(0, items.length - 1)
  }
})
watch(voiceMode, (mode) => {
  if (mode === 'tap' && isHoldActive.value) {
    endHoldToTalk()
  }
})

onMounted(() => {
  window.addEventListener('click', closeContextMenu)
  window.addEventListener('click', closeQuickPanel)
  window.addEventListener('keydown', handleGlobalKeydown)
  scrollToBottom()
  void settingsStore.fetchSettings().then(refreshModelOptions)
  const warmupTts = () => {
    void settingsClient.warmupTts().catch(() => undefined)
  }
  warmupTimer = window.setTimeout(warmupTts, 4000)
  void refreshMcpSummary()
})
onUnmounted(() => {
  window.removeEventListener('click', closeContextMenu)
  window.removeEventListener('click', closeQuickPanel)
  window.removeEventListener('keydown', handleGlobalKeydown)
  endHoldToTalk()
  sessionDrafts.flushDrafts()
  if (warmupTimer !== null) {
    window.clearTimeout(warmupTimer)
    warmupTimer = null
  }
})
</script>

<style scoped src="./ChatPanel.css"></style>

<style src="./ChatPanel.global.css"></style>
