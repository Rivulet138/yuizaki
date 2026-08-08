<template>
  <div v-for="({ message, answer }, index) in presentedMessages" :key="message.id ?? index">
    <div v-if="contextStartIndex === index && index > 0" class="context-start-divider">
      <span>从这里开始上下文</span>
    </div>
    <div
      class="message-row"
      :class="[
        messageRowClass(message.role),
        {
          'is-search-match': searchMatchSet.has(index),
          'is-search-active': activeSearchMessageIndex === index,
          'is-context-anchor': contextStartIndex === index && index > 0,
        },
      ]"
      :data-role="message.role"
      :data-message-index="index"
    >
      <div class="message-stack" :class="message.role === 'user' ? 'items-end' : 'items-start'">
        <div
          class="message-bubble group"
          :class="messageBubbleClass(message.role)"
          @contextmenu.prevent="emit('open-context-menu', $event, index, message)"
        >
          <template v-if="editingMessage.index === index">
            <el-input
              :model-value="editingMessage.content"
              class="message-edit-input"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 10 }"
              resize="none"
              @update:model-value="emit('update-edit-content', String($event))"
              @keydown.ctrl.enter.prevent="emit('save-edit', false)"
              @keydown.meta.enter.prevent="emit('save-edit', false)"
              @keydown.esc.prevent="emit('cancel-edit')"
            />
            <div class="message-edit-actions">
              <el-button size="small" text @click.stop="emit('cancel-edit')">取消</el-button>
              <el-button
                size="small"
                type="primary"
                :disabled="!editingMessage.content.trim()"
                :loading="editingMessage.saving"
                @click.stop="emit('save-edit', false)"
              >保存</el-button>
              <el-button
                v-if="message.role === 'user'"
                size="small"
                plain
                :disabled="!editingMessage.content.trim()"
                :loading="editingMessage.saving"
                @click.stop="emit('save-edit', true)"
              >保存并重发</el-button>
            </div>
          </template>
          <template v-else>
            <span v-if="message.role === 'user'">{{ message.content }}</span>
            <template v-else>
              <span
                v-if="answer"
                class="md-content"
                v-html="renderMarkdown(answer)"
              ></span>
              <div
                v-if="message.agentSteps?.length || message.memorySources?.length"
                class="message-provenance"
              >
                <details v-if="message.agentSteps?.length" class="message-disclosure">
                  <summary>
                    <span>Agent 步骤 {{ message.agentSteps.length }}</span>
                  </summary>
                  <ol class="agent-step-list">
                    <li v-for="step in message.agentSteps" :key="step.id" class="agent-step-row">
                      <span class="agent-step-status" :data-status="step.status">{{ agentStepStatusLabel(step.status) }}</span>
                      <span class="agent-step-copy">
                        <strong>{{ step.title }}</strong>
                        <small v-if="step.tool">{{ step.tool }}</small>
                        <small v-if="step.error" class="agent-step-error">{{ step.error }}</small>
                      </span>
                    </li>
                  </ol>
                </details>
                <details v-if="message.memorySources?.length" class="message-disclosure">
                  <summary>
                    <span>使用记忆 {{ message.memorySources.length }}</span>
                  </summary>
                  <ul class="memory-source-list">
                    <li v-for="source in message.memorySources" :key="source.id" class="memory-source-row">
                      <p>{{ source.text }}</p>
                      <div class="memory-source-meta">
                        <span v-if="source.layer">{{ source.layer }}</span>
                        <span v-if="source.source">{{ source.source }}</span>
                      </div>
                      <div class="memory-source-actions">
                        <button type="button" data-memory-action="correct" @click.stop="emit('correct-memory', source)">纠正</button>
                        <button type="button" data-memory-action="forget" @click.stop="emit('forget-memory', source)">忘记</button>
                      </div>
                    </li>
                  </ul>
                </details>
              </div>
            </template>
          </template>

          <template v-if="editingMessage.index !== index">
            <div class="message-footline" :class="message.role === 'user' ? 'justify-end' : 'justify-start'">
              <span>{{ messageRoleLabel(message.role) }}</span>
              <span v-if="formatMessageTime(message.timestamp)">{{ formatMessageTime(message.timestamp) }}</span>
            </div>
            <div class="message-actions" :class="message.role === 'user' ? 'justify-end' : 'justify-start'">
              <el-tooltip content="复制" placement="top" :show-after="250">
                <button class="message-action-button" type="button" aria-label="复制消息" @click.stop="emit('copy', message.content)">
                  <el-icon><CopyDocument /></el-icon>
                </button>
              </el-tooltip>
              <el-tooltip content="引用" placement="top" :show-after="250">
                <button class="message-action-button" type="button" aria-label="引用消息" @click.stop="emit('quote', message)">
                  <el-icon><ChatLineRound /></el-icon>
                </button>
              </el-tooltip>
              <el-tooltip content="编辑" placement="top" :show-after="250">
                <button class="message-action-button" type="button" aria-label="编辑消息" @click.stop="emit('start-edit', index, message)">
                  <el-icon><EditPen /></el-icon>
                </button>
              </el-tooltip>
              <el-tooltip :content="message.role === 'assistant' ? '重新生成' : '从这里重发'" placement="top" :show-after="250">
                <button
                  class="message-action-button"
                  type="button"
                  :aria-label="message.role === 'assistant' ? '重新生成回复' : '从这条消息重发'"
                  :disabled="!canRegenerateFromIndex(index)"
                  @click.stop="emit('regenerate', index)"
                >
                  <el-icon><Refresh /></el-icon>
                </button>
              </el-tooltip>
              <el-tooltip content="创建分支" placement="top" :show-after="250">
                <button
                  class="message-action-button"
                  type="button"
                  aria-label="从此处创建分支"
                  :disabled="isGenerating || !hasPersistedMessageId(message)"
                  @click.stop="emit('create-branch', index, message)"
                >
                  <el-icon><Share /></el-icon>
                </button>
              </el-tooltip>
              <el-tooltip content="设为上下文起点" placement="top" :show-after="250">
                <button
                  class="message-action-button"
                  type="button"
                  aria-label="设为上下文起点"
                  :disabled="isGenerating"
                  @click.stop="emit('set-context-start', index)"
                >
                  <el-icon><Aim /></el-icon>
                </button>
              </el-tooltip>
              <el-tooltip content="翻译" placement="top" :show-after="250">
                <button
                  class="message-action-button"
                  type="button"
                  aria-label="翻译消息"
                  :disabled="messageTranslatingIndex !== null"
                  @click.stop="emit('translate', message, index)"
                >
                  <el-icon><Connection /></el-icon>
                </button>
              </el-tooltip>
              <el-tooltip content="删除" placement="top" :show-after="250">
                <button class="message-action-button danger" type="button" aria-label="删除消息" @click.stop="emit('delete', index)">
                  <el-icon><Delete /></el-icon>
                </button>
              </el-tooltip>
            </div>
          </template>

          <div
            v-if="contextMenu.visible && contextMenu.index === index"
            class="context-menu"
            :style="{ top: `${contextMenu.y}px`, left: `${contextMenu.x}px` }"
          >
            <button type="button" @click="emit('copy', message.content); emit('close-context-menu')">复制</button>
            <button type="button" @click="emit('quote', message); emit('close-context-menu')">引用</button>
            <button type="button" @click="emit('start-edit', index, message); emit('close-context-menu')">编辑</button>
            <button type="button" @click="emit('translate', message, index); emit('close-context-menu')">翻译</button>
            <button type="button" :disabled="isGenerating" @click="emit('set-context-start', index); emit('close-context-menu')">从这里开始上下文</button>
            <button type="button" :disabled="!canRegenerateFromIndex(index)" @click="emit('regenerate', index); emit('close-context-menu')">
              {{ message.role === 'assistant' ? '重新生成' : '从这里重发' }}
            </button>
            <button type="button" :disabled="isGenerating || !hasPersistedMessageId(message)" @click="emit('create-branch', index, message); emit('close-context-menu')">创建分支</button>
            <button type="button" class="danger" title="从本地历史删除这条消息" @click="emit('delete', index); emit('close-context-menu')">删除</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div v-if="currentText" class="message-row items-start animate-fade-in" data-role="assistant">
    <div class="message-stack items-start">
      <div class="message-bubble message-bubble-streaming">
        <span v-if="currentAssistantAnswer" class="md-content" v-html="renderMarkdown(currentAssistantAnswer)"></span>
        <span class="stream-caret"></span>
      </div>
    </div>
  </div>
  <div v-else-if="isGenerating" class="message-row items-start animate-fade-in" data-role="assistant">
    <div class="message-stack items-start">
      <div class="message-bubble message-bubble-streaming message-pending">
        <span class="pending-dot"></span>
        <span>{{ pendingAssistantLabel }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Aim, ChatLineRound, Connection, CopyDocument, Delete, EditPen, Refresh, Share } from '@element-plus/icons-vue'
import type { ChatMemorySource, ChatMessage } from '@/../shared/types'
import { renderMarkdown } from '@/utils/markdown'

interface EditingMessageState {
  index: number
  content: string
  saving: boolean
}

interface MessageContextMenuState {
  visible: boolean
  x: number
  y: number
  index: number
}

const props = defineProps<{
  messages: ChatMessage[]
  contextStartIndex: number
  currentText: string
  isGenerating: boolean
  pendingAssistantLabel: string
  editingMessage: EditingMessageState
  searchMatches: number[]
  activeSearchMessageIndex: number | null
  messageTranslatingIndex: number | null
  contextMenu: MessageContextMenuState
  canRegenerateFromIndex: (index: number) => boolean
}>()

const emit = defineEmits<{
  copy: [content: string]
  quote: [message: ChatMessage]
  'start-edit': [index: number, message: ChatMessage]
  regenerate: [index: number]
  'create-branch': [index: number, message: ChatMessage]
  'set-context-start': [index: number]
  translate: [message: ChatMessage, index: number]
  delete: [index: number]
  'open-context-menu': [event: MouseEvent, index: number, message: ChatMessage]
  'close-context-menu': []
  'update-edit-content': [content: string]
  'save-edit': [resend: boolean]
  'cancel-edit': []
  'correct-memory': [source: ChatMemorySource]
  'forget-memory': [source: ChatMemorySource]
}>()

const hasPersistedMessageId = (message: ChatMessage) => Number.isInteger(Number(message.id))

const extractVisibleAnswer = (content: string) => {
  const withoutTaggedReasoning = content
    .replace(/<(think|thinking|reasoning|analysis)[^>]*>[\s\S]*?(?:<\/\1>|$)/gi, '\n')
    .trim()
  const match = content.match(/^\s*(?:思考过程|思考|推理|Reasoning|Thoughts)\s*[:：]\s*([\s\S]*?)(?:\n{1,3}\s*(?:最终回答|答复|回答|Answer|Final Answer)\s*[:：]\s*([\s\S]*))\s*$/i)
  return match?.[2]?.trim() || withoutTaggedReasoning
}

const presentedMessages = computed(() => props.messages.map((message) => ({
  message,
  answer: message.role === 'user' ? message.content : extractVisibleAnswer(message.content),
})))
const searchMatchSet = computed(() => new Set(props.searchMatches))
const currentAssistantAnswer = computed(() => extractVisibleAnswer(props.currentText))
const messageRowClass = (role: ChatMessage['role']) => role === 'user' ? 'items-end' : 'items-start'
const messageRoleLabel = (role: ChatMessage['role']) => role === 'user' ? '你' : role === 'assistant' ? '結崎' : '系统'
const messageBubbleClass = (role: ChatMessage['role']) => role === 'user'
  ? 'message-bubble-user'
  : role === 'system'
    ? 'message-bubble-system'
    : 'message-bubble-assistant'

const agentStepStatusLabel = (status: string) => {
  if (status === 'completed' || status === 'success') return '完成'
  if (status === 'failed' || status === 'error') return '失败'
  if (status === 'running' || status === 'started') return '运行中'
  return '记录'
}

const formatMessageTime = (timestamp?: string | null) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  const sameDay = date.toDateString() === new Date().toDateString()
  return date.toLocaleString('zh-CN', {
    month: sameDay ? undefined : '2-digit',
    day: sameDay ? undefined : '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
</script>

<style scoped src="./ChatMessageList.css"></style>
