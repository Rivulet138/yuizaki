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
        @create-session="handleCreateSession"
          @select-session="handleSelectSession"
          @toggle-pin="handleTogglePin"
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

          <div
            v-for="(msg, idx) in chatState.messages"
            :key="idx"
          >
            <div v-if="chatState.contextStartIndex === idx && idx > 0" class="context-start-divider">
              <span>从这里开始上下文</span>
            </div>
            <div
              class="message-row"
              :class="[
                messageRowClass(msg.role),
                {
                  'is-search-match': isSearchMatch(idx),
                  'is-search-active': activeSearchMessageIndex === idx,
                  'is-context-anchor': chatState.contextStartIndex === idx && idx > 0,
                },
              ]"
              :data-role="msg.role"
              :data-message-index="idx"
            >
              <div class="message-stack" :class="msg.role === 'user' ? 'items-end' : 'items-start'">
                <div
                  class="message-bubble group"
                  :class="messageBubbleClass(msg.role)"
                  @contextmenu.prevent="openContextMenu($event, idx, msg)"
                >
                  <template v-if="editingMessage.index === idx">
                    <el-input
                      v-model="editingMessage.content"
                      class="message-edit-input"
                      type="textarea"
                      :autosize="{ minRows: 2, maxRows: 10 }"
                      resize="none"
                      @keydown.ctrl.enter.prevent="saveMessageEdit"
                      @keydown.meta.enter.prevent="saveMessageEdit"
                      @keydown.esc.prevent="cancelMessageEdit"
                    />
                    <div class="message-edit-actions">
                      <el-button size="small" text @click.stop="cancelMessageEdit">取消</el-button>
                      <el-button size="small" type="primary" :disabled="!editingMessage.content.trim()" :loading="editingMessage.saving" @click.stop="saveMessageEdit">保存</el-button>
                      <el-button
                        v-if="msg.role === 'user'"
                        size="small"
                        plain
                        :disabled="!editingMessage.content.trim()"
                        :loading="editingMessage.saving"
                        @click.stop="saveMessageEdit(true)"
                      >
                        保存并重发
                      </el-button>
                    </div>
                  </template>
                  <template v-else>
                    <span v-if="msg.role === 'user'">{{ msg.content }}</span>
                    <template v-else>
                      <details v-if="parsedAssistantContent(msg).reasoning && showReasoningPanel" class="message-reasoning" :open="reasoningPanelExpanded">
                        <summary>
                          <span>思考过程</span>
                          <small>{{ reasoningLengthLabel(parsedAssistantContent(msg).reasoning) }}</small>
                        </summary>
                        <div class="md-content reasoning-content" v-html="renderMessageMarkdown(parsedAssistantContent(msg).reasoning)"></div>
                      </details>
                      <button
                        v-else-if="parsedAssistantContent(msg).reasoning"
                        class="message-reasoning-hidden"
                        type="button"
                        @click.stop="setReasoningPanelVisible(true)"
                      >
                        思考过程已隐藏 · {{ reasoningLengthLabel(parsedAssistantContent(msg).reasoning) }}
                      </button>
                      <span v-if="parsedAssistantContent(msg).answer" class="md-content" v-html="renderMessageMarkdown(parsedAssistantContent(msg).answer)"></span>
                    </template>
                  </template>
                  <div v-if="editingMessage.index !== idx" class="message-footline" :class="msg.role === 'user' ? 'justify-end' : 'justify-start'">
                    <span>{{ messageRoleLabel(msg.role) }}</span>
                    <span v-if="formatMessageTime(msg.timestamp)">{{ formatMessageTime(msg.timestamp) }}</span>
                  </div>
                  <div v-if="editingMessage.index !== idx" class="message-actions" :class="msg.role === 'user' ? 'justify-end' : 'justify-start'">
                    <el-tooltip content="复制" placement="top" :show-after="250">
                      <button class="message-action-button" type="button" aria-label="复制消息" @click.stop="handleCopy(msg.content)">
                        <el-icon><CopyDocument /></el-icon>
                      </button>
                    </el-tooltip>
                    <el-tooltip content="引用" placement="top" :show-after="250">
                      <button class="message-action-button" type="button" aria-label="引用消息" @click.stop="quoteMessage(msg)">
                        <el-icon><ChatLineRound /></el-icon>
                      </button>
                    </el-tooltip>
                    <el-tooltip content="编辑" placement="top" :show-after="250">
                      <button class="message-action-button" type="button" aria-label="编辑消息" @click.stop="startMessageEdit(idx, msg)">
                        <el-icon><EditPen /></el-icon>
                      </button>
                    </el-tooltip>
                    <el-tooltip :content="msg.role === 'assistant' ? '重新生成' : '从这里重发'" placement="top" :show-after="250">
                      <button
                        class="message-action-button"
                        type="button"
                        :aria-label="msg.role === 'assistant' ? '重新生成回复' : '从这条消息重发'"
                        :disabled="!canRegenerateFromIndex(idx)"
                        @click.stop="handleRegenerate(idx)"
                      >
                        <el-icon><Refresh /></el-icon>
                      </button>
                    </el-tooltip>
                    <el-tooltip content="设为上下文起点" placement="top" :show-after="250">
                      <button class="message-action-button" type="button" aria-label="设为上下文起点" :disabled="chatState.isGenerating" @click.stop="handleSetContextStart(idx)">
                        <el-icon><Aim /></el-icon>
                      </button>
                    </el-tooltip>
                    <el-tooltip content="翻译" placement="top" :show-after="250">
                      <button class="message-action-button" type="button" aria-label="翻译消息" :disabled="messageTranslatingIndex !== null" @click.stop="handleTranslateMessage(msg, idx)">
                        <el-icon><Connection /></el-icon>
                      </button>
                    </el-tooltip>
                    <el-tooltip content="删除" placement="top" :show-after="250">
                      <button class="message-action-button danger" type="button" aria-label="删除消息" @click.stop="handleDeleteMsg(idx)">
                        <el-icon><Delete /></el-icon>
                      </button>
                    </el-tooltip>
                  </div>
                  <div
                    v-if="contextMenu.visible && contextMenu.index === idx"
                    class="context-menu"
                    :style="{ top: contextMenu.y + 'px', left: contextMenu.x + 'px' }"
                  >
                    <button type="button" @click="handleCopy(msg.content); closeContextMenu()">复制</button>
                    <button type="button" @click="quoteMessage(msg); closeContextMenu()">引用</button>
                    <button type="button" @click="startMessageEdit(idx, msg); closeContextMenu()">编辑</button>
                    <button type="button" @click="handleTranslateMessage(msg, idx); closeContextMenu()">翻译</button>
                    <button type="button" :disabled="chatState.isGenerating" @click="handleSetContextStart(idx); closeContextMenu()">从这里开始上下文</button>
                    <button :disabled="!canRegenerateFromIndex(idx)" type="button" @click="handleRegenerate(idx); closeContextMenu()">{{ msg.role === 'assistant' ? '重新生成' : '从这里重发' }}</button>
                    <button type="button" class="danger" title="从本地历史删除这条消息" @click="handleDeleteMsg(idx); closeContextMenu()">删除</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="chatState.currentText" class="message-row items-start animate-fade-in" data-role="assistant">
            <div class="message-stack items-start">
              <div class="message-bubble message-bubble-streaming">
                <details v-if="currentAssistantContent.reasoning && showReasoningPanel" class="message-reasoning is-streaming" :open="reasoningPanelExpanded">
                  <summary>
                    <span>思考过程</span>
                    <small>{{ reasoningLengthLabel(currentAssistantContent.reasoning) }}</small>
                  </summary>
                  <div class="md-content reasoning-content" v-html="renderMessageMarkdown(currentAssistantContent.reasoning)"></div>
                </details>
                <button
                  v-else-if="currentAssistantContent.reasoning"
                  class="message-reasoning-hidden"
                  type="button"
                  @click.stop="setReasoningPanelVisible(true)"
                >
                  思考过程已隐藏 · {{ reasoningLengthLabel(currentAssistantContent.reasoning) }}
                </button>
                <span v-if="currentAssistantContent.answer" class="md-content" v-html="renderMessageMarkdown(currentAssistantContent.answer)"></span><span class="stream-caret"></span>
              </div>
            </div>
          </div>
          <div v-else-if="chatState.isGenerating" class="message-row items-start animate-fade-in" data-role="assistant">
            <div class="message-stack items-start">
              <div class="message-bubble message-bubble-streaming message-pending">
                <span class="pending-dot"></span>
                <span>{{ pendingAssistantLabel }}</span>
              </div>
            </div>
          </div>

          <div v-if="chatState.asrPartialText" class="asr-partial-card animate-fade-in">
            <el-icon><Microphone /></el-icon>
            <span>{{ chatState.asrPartialText }}</span>
          </div>

          <div v-if="dialogStore.permissionDialogVisible" class="permission-card animate-fade-in sticky top-2 z-10">
            <div class="permission-card__header">
              <el-icon><WarningFilled /></el-icon>
              <span>权限确认</span>
            </div>
            <p>
              工具 <code>{{ dialogStore.permissionRequest?.tool_name || dialogStore.permissionRequest?.capability_id }}</code>
              需要你的确认才能执行
            </p>
            <small>{{ dialogStore.permissionRequest?.reason }}</small>
            <div class="permission-card__actions">
              <el-button size="small" type="success" @click="resolvePermission(true)">允许</el-button>
              <el-button size="small" type="danger" @click="resolvePermission(false)">拒绝</el-button>
              <el-button size="small" plain @click="resolvePermission(true, true)">允许并记住</el-button>
            </div>
          </div>
        </div>

        <div class="composer-panel shrink-0" :class="{ 'composer-panel--tools-open': toolsExpanded }">
          <input ref="fileInput" class="hidden-file-input" type="file" multiple @change="handleFileInputChange" />

          <div v-if="chatState.isTTSPlaying" class="tts-indicator">
            <div class="waveform">
              <span v-for="n in 5" :key="n" class="wave-bar" :style="{ animationDelay: `${n * 0.12}s` }"></span>
            </div>
            <span>播放中</span>
          </div>

          <div v-if="attachments.length" class="attachment-strip">
            <div v-for="attachment in attachments" :key="attachment.id" class="attachment-chip" :title="attachment.name">
              <el-icon><FolderOpened /></el-icon>
              <span>{{ attachment.name }}</span>
              <small>{{ formatBytes(attachment.size) }}</small>
              <button type="button" @click="removeAttachment(attachment.id)">×</button>
            </div>
          </div>

          <div v-if="chatState.adviceFeed.length" class="advice-strip" @click.stop>
            <div class="advice-strip__head">
              <span>行为建议</span>
              <button type="button" @click="handleClearAdvice">清空</button>
            </div>
            <div class="advice-list">
              <div v-for="item in visibleAdviceItems" :key="item.id" class="advice-item">
                <div class="advice-copy">
                  <small>{{ adviceSourceLabel(item.source) }}</small>
                  <span>{{ item.content }}</span>
                </div>
                <div class="advice-actions">
                  <button type="button" @click="applyAdviceToInput(item.id)">填入</button>
                  <button type="button" @click="showAdviceInConversation(item.id)">显示</button>
                  <button type="button" @click="chatStore.dismissAdvice(item.id)">忽略</button>
                </div>
              </div>
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
              :disabled="chatState.isGenerating"
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
                  :class="{ 'is-dragging': draggingToolId === tool.id, 'is-drop-target': dragOverToolId === tool.id }"
                  draggable="true"
                  @dragstart="handleToolDragStart($event, tool.id)"
                  @dragover.prevent="handleToolDragOver(tool.id)"
                  @drop.prevent="handleToolDrop(tool.id)"
                  @dragend="handleToolDragEnd"
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
                <el-segmented
                  v-model="chatOptions.response_mode"
                  :options="responseModeOptions"
                  size="small"
                  class="response-mode-control"
                  aria-label="响应速度"
                />
                <el-select
                  v-model="chatOptions.model"
                  size="small"
                  class="model-select"
                  clearable
                  filterable
                  placeholder="模型"
                  :loading="modelsLoading"
                  @visible-change="(visible) => visible && refreshModelOptions()"
                >
                  <el-option label="默认模型" value="" />
                  <el-option v-for="model in modelOptions" :key="model" :label="model" :value="model" />
                </el-select>
                <el-select v-model="chatOptions.reasoning_effort" size="small" class="reasoning-select" placeholder="思考">
                  <el-option v-for="item in reasoningOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-switch
                  v-model="chatOptions.mcp_enabled"
                  size="small"
                  inline-prompt
                  active-text="MCP"
                  inactive-text="MCP"
                  :title="mcpSummaryLabel"
                />
                <el-switch
                  v-model="chatOptions.pet_link_enabled"
                  size="small"
                  inline-prompt
                  active-text="联动"
                  inactive-text="独立"
                  :title="petLinkLabel"
                />
                <el-switch
                  v-model="chatOptions.tts_enabled"
                  size="small"
                  inline-prompt
                  active-text="TTS"
                  inactive-text="静音"
                  :title="ttsLabel"
                  @change="toggleTtsOutput"
                />
                <el-tooltip content="提示词" placement="top">
                  <button class="tool-button" :class="{ active: promptProfileActive }" type="button" aria-label="提示词" title="提示词" @click="openPromptPanel">
                    <el-icon><Tickets /></el-icon>
                  </button>
                </el-tooltip>
                <el-popover placement="top" width="320" trigger="click">
                  <template #reference>
                    <button class="tool-button" type="button" aria-label="参数">
                      <el-icon><Timer /></el-icon>
                    </button>
                  </template>
                  <div class="advanced-options">
                    <label>
                      <span>温度 {{ chatOptions.temperature?.toFixed(2) }}</span>
                      <el-slider v-model="chatOptions.temperature" :min="0" :max="2" :step="0.05" />
                    </label>
                    <label>
                      <span>Top P {{ chatOptions.top_p?.toFixed(2) }}</span>
                      <el-slider v-model="chatOptions.top_p" :min="0" :max="1" :step="0.05" />
                    </label>
                    <div class="advanced-options-grid">
                      <label>
                        <span>Top K</span>
                        <el-input-number v-model="chatOptions.top_k" :min="0" :max="2000" :step="50" size="small" />
                      </label>
                      <label>
                        <span>Min P {{ chatOptions.min_p?.toFixed(2) }}</span>
                        <el-slider v-model="chatOptions.min_p" :min="0" :max="1" :step="0.01" />
                      </label>
                    </div>
                    <div class="advanced-options-grid">
                      <label>
                        <span>频率惩罚 {{ chatOptions.frequency_penalty?.toFixed(2) }}</span>
                        <el-slider v-model="chatOptions.frequency_penalty" :min="-2" :max="2" :step="0.05" />
                      </label>
                      <label>
                        <span>存在惩罚 {{ chatOptions.presence_penalty?.toFixed(2) }}</span>
                        <el-slider v-model="chatOptions.presence_penalty" :min="-2" :max="2" :step="0.05" />
                      </label>
                    </div>
                    <label>
                      <span>重复惩罚 {{ chatOptions.repetition_penalty?.toFixed(2) }}</span>
                      <el-slider v-model="chatOptions.repetition_penalty" :min="0" :max="2" :step="0.05" />
                    </label>
                    <label>
                      <span>最大回复 tokens</span>
                      <el-input-number v-model="chatOptions.max_tokens" :min="128" :max="maxChatOutputTokens" :step="128" size="small" />
                    </label>
                    <label>
                      <span>翻译目标</span>
                      <el-select v-model="chatOptions.translation_target" size="small" filterable>
                        <el-option label="简体中文" value="zh-CN" />
                        <el-option label="English" value="en" />
                        <el-option label="日本語" value="ja" />
                        <el-option label="한국어" value="ko" />
                        <el-option label="Français" value="fr" />
                        <el-option label="Deutsch" value="de" />
                      </el-select>
                    </label>
                  </div>
                </el-popover>
                <el-dropdown trigger="click" @command="handleTopMoreCommand">
                  <button class="tool-button" type="button" aria-label="更多">
                    <el-icon><MoreFilled /></el-icon>
                  </button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="copy-transcript" :disabled="!chatState.messages.length">复制全文</el-dropdown-item>
                      <el-dropdown-item command="copy-last" :disabled="!lastAssistantMessage">复制最后回复</el-dropdown-item>
                      <el-dropdown-item command="toggle-reasoning">{{ showReasoningPanel ? '隐藏思考过程' : '显示思考过程' }}</el-dropdown-item>
                      <el-dropdown-item command="toggle-reasoning-expanded" :disabled="!showReasoningPanel">{{ reasoningPanelExpanded ? '默认折叠思考' : '默认展开思考' }}</el-dropdown-item>
                      <el-dropdown-item command="clear-context" :disabled="!hasConversationContent">清理上下文</el-dropdown-item>
                      <el-dropdown-item command="reset-context" :disabled="chatState.contextStartIndex <= 0">恢复完整上下文</el-dropdown-item>
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
            <div class="composer-meta-line">
              <span class="composer-meta-chip" :class="{ ready: socketDomain.isConnected.value }">
                {{ socketDomain.isConnected.value ? '实时通道已连接' : '实时通道连接中' }}
              </span>
              <span v-if="chatOptions.web_search_enabled" class="composer-meta-chip is-active">联网搜索</span>
              <span v-if="chatOptions.mcp_enabled" class="composer-meta-chip is-active">MCP</span>
              <span class="composer-meta-value">{{ effectiveModelLabel }}</span>
              <span>{{ chatOptions.pet_link_enabled ? '桌宠联动' : '独立对话' }}</span>
              <span class="composer-meta-chip" :class="{ 'is-active': chatOptions.tts_enabled }">{{ chatOptions.tts_enabled ? 'TTS' : '静音' }}</span>
              <span>{{ voicePermissionText }}</span>
              <span>{{ estimatedInputTokens }} tokens</span>
            </div>

            <div v-if="toolsExpanded" class="voice-console">
              <div class="voice-console__main">
                <div class="voice-status-badge" :class="voiceStatusClass">
                  <el-icon><Headset /></el-icon>
                </div>
                <div class="voice-status-stack">
                  <div class="voice-status-line">
                    <strong>{{ voiceStatusText }}</strong>
                    <small>{{ voicePipelineText }}</small>
                    <small v-if="isRecording && voiceProcessingText">{{ voiceProcessingText }}</small>
                    <small v-if="voiceLatencySummary" class="voice-latency-summary">{{ voiceLatencySummary }}</small>
                  </div>
                  <div class="voice-meter" aria-label="麦克风电平">
                    <span
                      v-for="level in voiceMeterBars"
                      :key="level"
                      :class="{ active: voiceLevelPercent >= level }"
                    ></span>
                  </div>
                </div>
              </div>

              <div class="voice-console__controls">
                <el-segmented v-model="voiceMode" :options="voiceModeOptions" size="small" />
                <button
                  v-if="voiceMode === 'hold'"
                  type="button"
                  class="hold-to-talk"
                  :class="{ active: isHoldActive || isRecording }"
                  :disabled="!socketDomain.isConnected.value"
                  :title="pushToTalkShortcutTitle"
                  @pointerdown.prevent="handleHoldPointerDown"
                  @pointerup.prevent="handleHoldPointerUp"
                  @pointercancel.prevent="handleHoldPointerUp"
                  @keydown.space.prevent="beginHoldToTalk"
                  @keyup.space.prevent="endHoldToTalk"
                >
                  <el-icon><Microphone /></el-icon>
                  <span>{{ isRecording ? '松开发送' : '按住说话' }}</span>
                </button>
                <button v-else type="button" class="hold-to-talk" :class="{ active: isRecording }" :disabled="!socketDomain.isConnected.value" :title="pushToTalkShortcutTitle" @click="toggleMic">
                  <el-icon><Microphone /></el-icon>
                  <span>{{ isRecording ? '结束录音' : '语音输入' }}</span>
                </button>
                <button class="tool-button" type="button" :disabled="!chatState.isTTSPlaying" @click="handleInterrupt">
                  <el-icon><Mute /></el-icon>
                </button>
              </div>
            </div>
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
  Aim,
  ArrowDown,
  ArrowUp,
  Bottom,
  ChatLineRound,
  CircleClose,
  Close,
  Connection,
  CopyDocument,
  Delete,
  EditPen,
  Expand,
  FolderOpened,
  FullScreen,
  Headset,
  Fold,
  MagicStick,
  Microphone,
  Mute,
  MoreFilled,
  Moon,
  Plus,
  Promotion,
  Refresh,
  RefreshRight,
  Search,
  Setting,
  Sunny,
  Tickets,
  Timer,
  WarningFilled,
} from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { getSocketClient } from '@/net/socketClient'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { useChatDomain } from '../composables/useChatDomain'
import SessionRail from '../components/SessionRail.vue'
import { useChatStore } from '@/stores/chatStore'
import { useSessionStore } from '@/stores/sessionStore'
import { DEFAULT_DAILY_PROMPT, DEFAULT_WORK_PROMPT, useWorkspaceStore } from '@/stores/workspaceStore'
import { useDialogStore } from '@/stores/dialogStore'
import { useSettingsStore } from '@/state/settingsStore'
import { DEFAULT_LLM_MAX_OUTPUT_TOKENS } from '@/../shared/runtime-defaults'
import { useInputBindingsStore } from '@/state/inputBindingsStore'
import { settingsClient, systemClient } from '@/api/client'
import { renderMarkdown } from '@/utils/markdown'
import type { ChatAttachment, ChatMessage, ChatOptions } from '@/../shared/types'
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
  | 'sessionRail'
  | 'newTopic'
  | 'attach'
  | 'quickPhrases'
  | 'expandInput'
  | 'clearMessages'
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

interface ParsedAssistantContent {
  reasoning: string
  answer: string
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
const sessionStore = useSessionStore()
const dialogStore = useDialogStore()
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
const messageSearch = reactive({
  visible: false,
  query: '',
  activeMatchIndex: -1,
})
const CHAT_SESSION_RAIL_STORAGE_KEY = 'yuizaki.chat.sessionRailVisible'
const COMPOSER_TOOL_ORDER_STORAGE_KEY = 'yuizaki.chat.toolOrder'
const REASONING_PANEL_VISIBLE_STORAGE_KEY = 'yuizaki.chat.reasoningPanelVisible'
const REASONING_PANEL_EXPANDED_STORAGE_KEY = 'yuizaki.chat.reasoningPanelExpanded'
const defaultComposerToolOrder: ComposerToolId[] = [
  'sessionRail',
  'newTopic',
  'attach',
  'quickPhrases',
  'expandInput',
  'clearMessages',
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
const draggingToolId = ref<ComposerToolId | null>(null)
const dragOverToolId = ref<ComposerToolId | null>(null)

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

const loadComposerToolOrder = (): ComposerToolId[] => {
  if (typeof window === 'undefined') return [...defaultComposerToolOrder]
  try {
    const raw = window.localStorage.getItem(COMPOSER_TOOL_ORDER_STORAGE_KEY)
    if (!raw) return [...defaultComposerToolOrder]
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return [...defaultComposerToolOrder]
    const valid = new Set(defaultComposerToolOrder)
    const restored = parsed.filter((id): id is ComposerToolId => valid.has(id as ComposerToolId))
    return [
      ...restored,
      ...defaultComposerToolOrder.filter((id) => !restored.includes(id)),
    ]
  } catch {
    return [...defaultComposerToolOrder]
  }
}

const loadBooleanPreference = (key: string, fallback: boolean) => {
  if (typeof window === 'undefined') return fallback
  try {
    const raw = window.localStorage.getItem(key)
    if (raw === null) return fallback
    return raw === 'true'
  } catch {
    return fallback
  }
}

const showSessionRail = ref(loadSessionRailVisibility())
const composerToolOrder = ref<ComposerToolId[]>(loadComposerToolOrder())
const showReasoningPanel = ref(loadBooleanPreference(REASONING_PANEL_VISIBLE_STORAGE_KEY, true))
const reasoningPanelExpanded = ref(loadBooleanPreference(REASONING_PANEL_EXPANDED_STORAGE_KEY, true))

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
const currentAssistantContent = computed(() => parseAssistantContent(chatState.currentText))
const pendingAssistantLabel = computed(() => {
  if (chatOptions.reasoning_effort && !['none', 'default'].includes(chatOptions.reasoning_effort)) return '思考中'
  return '等待模型输出'
})
const hasConversationContent = computed(() => Boolean(chatState.messages.length || chatState.currentText || chatState.asrPartialText))
const visibleAdviceItems = computed(() => chatState.adviceFeed.slice(0, 3))
const workspaceNameMap = computed(() => Object.fromEntries(workspaceStore.workspaces.map((workspace) => [workspace.id, workspace.name])))
const effectiveModelLabel = computed(() => chatOptions.model || settingsStore.state.llm.model || '默认模型')
const petLinkLabel = computed(() => chatOptions.pet_link_enabled ? 'Live2D/VRM 联动开启' : '桌宠联动已禁用')
const webSearchLabel = computed(() => chatOptions.web_search_enabled ? '联网搜索开启' : '联网搜索关闭')
const ttsLabel = computed(() => chatOptions.tts_enabled ? 'TTS 输出开启' : 'TTS 输出关闭')
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
const canSendComposer = computed(() => Boolean(inputText.value.trim() || attachments.value.length))
const estimatedInputTokens = computed(() => estimateTokens(inputText.value))
const normalizedSearchQuery = computed(() => messageSearch.query.trim().toLowerCase())
const messageSearchMatches = computed(() => {
  const query = normalizedSearchQuery.value
  if (!query) return []
  return chatState.messages
    .map((message, index) => ({ message, index }))
    .filter(({ message }) => `${messageRoleLabel(message.role)} ${message.content}`.toLowerCase().includes(query))
    .map(({ index }) => index)
})
const activeSearchMessageIndex = computed(() => {
  if (!messageSearchMatches.value.length) return -1
  const activeIndex = Math.max(0, Math.min(messageSearch.activeMatchIndex, messageSearchMatches.value.length - 1))
  return messageSearchMatches.value[activeIndex] ?? -1
})
const searchResultLabel = computed(() => {
  if (!normalizedSearchQuery.value) return '0/0'
  if (!messageSearchMatches.value.length) return '0/0'
  return `${Math.max(0, messageSearch.activeMatchIndex) + 1}/${messageSearchMatches.value.length}`
})
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
  sessionRail: {
    id: 'sessionRail',
    label: showSessionRail.value ? '隐藏会话' : '显示会话',
    title: showSessionRail.value ? '隐藏会话' : '显示会话',
    icon: showSessionRail.value ? Fold : Expand,
    active: showSessionRail.value,
    run: toggleSessionRail,
  },
  newTopic: {
    id: 'newTopic',
    label: isCreatingSession.value ? '创建中' : '新话题',
    title: isCreatingSession.value ? '正在创建新会话' : '新话题',
    icon: Plus,
    disabled: isCreatingSession.value,
    run: () => { void handleCreateSession() },
  },
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
  clearMessages: {
    id: 'clearMessages',
    label: '清空消息',
    title: '删除当前会话中的所有消息',
    icon: Delete,
    disabled: !hasConversationContent.value,
    run: () => { void handleClearConversation() },
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
const visibleComposerTools = computed(() => composerToolOrder.value
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
  if (audioCaptureState.phase === 'error') return audioCaptureState.error || '麦克风异常'
  if (isRecording.value) return '正在收音'
  if (!socketDomain.isConnected.value) return '实时通道连接中'
  if (chatState.isTTSPlaying) return '正在播放'
  if (chatState.asrPartialText) return '正在识别'
  return '语音就绪'
})
const voicePipelineText = computed(() => {
  if (!socketDomain.isConnected.value) return '实时通道未连接'
  if (isRecording.value) return `${formatDuration(audioCaptureState.elapsedMs)} · ${audioCaptureState.chunksSent} 块 · ${formatBytes(audioCaptureState.bytesSent)}`
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
  offline: !socketDomain.isConnected.value,
  speaking: chatState.isTTSPlaying,
}))
const voicePermissionText = computed(() => {
  if (audioCaptureState.permission === 'denied') return '麦克风被拒绝'
  if (audioCaptureState.permission === 'granted') return '麦克风已授权'
  if (audioCaptureState.permission === 'prompt') return '麦克风待授权'
  return '麦克风未检测'
})

const resolvePermission = (allowed: boolean, remember = false) => {
  const req = dialogStore.permissionRequest
  if (!req?.request_id) return
  const sio = getSocketClient()
  sio.sendPermissionResponse(req.request_id, allowed, remember)
  dialogStore.permissionDialogVisible = false
  dialogStore.permissionRequest = null
}

const estimateTokens = (text: string) => Math.max(0, Math.ceil(text.trim().length / 1.7))
const renderMessageMarkdown = (content: string) => renderMarkdown(content)
const normalizeReasoningText = (value?: string | null) => typeof value === 'string' ? value.trim() : ''
const extractTaggedReasoning = (content: string) => {
  const reasoningParts: string[] = []
  const answer = content.replace(/<(think|thinking|reasoning|analysis)[^>]*>([\s\S]*?)(?:<\/\1>|$)/gi, (_match, _tag, body) => {
    const reasoning = String(body || '').trim()
    if (reasoning) reasoningParts.push(reasoning)
    return '\n'
  }).trim()
  return {
    reasoning: reasoningParts.join('\n\n'),
    answer,
  }
}
const extractLabeledReasoning = (content: string): ParsedAssistantContent | null => {
  const match = content.match(/^\s*(?:思考过程|思考|推理|Reasoning|Thoughts)\s*[:：]\s*([\s\S]*?)(?:\n{1,3}\s*(?:最终回答|答复|回答|Answer|Final Answer)\s*[:：]\s*([\s\S]*))\s*$/i)
  if (!match?.[1] || !match[2]) return null
  return {
    reasoning: match[1].trim(),
    answer: match[2].trim(),
  }
}
const parseAssistantContent = (message: ChatMessage | string): ParsedAssistantContent => {
  const content = typeof message === 'string' ? message : message.content
  const explicitReasoning = typeof message === 'string' ? '' : normalizeReasoningText(message.reasoning)
  const tagged = extractTaggedReasoning(content)
  if (explicitReasoning || tagged.reasoning) {
    return {
      reasoning: [explicitReasoning, tagged.reasoning].filter(Boolean).join('\n\n'),
      answer: tagged.answer,
    }
  }
  return extractLabeledReasoning(content) || { reasoning: '', answer: content }
}
const parsedAssistantContent = (msg: ChatMessage) => parseAssistantContent(msg)
const reasoningLengthLabel = (content: string) => `${estimateTokens(content)} tokens`
const messageRowClass = (role: ChatMessage['role']) => role === 'user' ? 'items-end' : 'items-start'
const messageRoleLabel = (role: ChatMessage['role']) => {
  if (role === 'user') return '你'
  if (role === 'assistant') return '結崎'
  return '系统'
}
const messageBubbleClass = (role: ChatMessage['role']) => {
  if (role === 'user') return 'message-bubble-user'
  if (role === 'system') return 'message-bubble-system'
  return 'message-bubble-assistant'
}
const formatMessageTime = (timestamp?: string | null) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  return date.toLocaleString('zh-CN', {
    month: sameDay ? undefined : '2-digit',
    day: sameDay ? undefined : '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
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

const persistComposerToolOrder = () => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(COMPOSER_TOOL_ORDER_STORAGE_KEY, JSON.stringify(composerToolOrder.value))
}

const persistBooleanPreference = (key: string, value: boolean) => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(key, String(value))
}

const setReasoningPanelVisible = (visible: boolean) => {
  showReasoningPanel.value = visible
  persistBooleanPreference(REASONING_PANEL_VISIBLE_STORAGE_KEY, visible)
}

const setReasoningPanelExpanded = (expanded: boolean) => {
  reasoningPanelExpanded.value = expanded
  persistBooleanPreference(REASONING_PANEL_EXPANDED_STORAGE_KEY, expanded)
}

const runComposerTool = (tool: ComposerToolDefinition) => {
  if (tool.disabled) return
  closeQuickPanel()
  void tool.run()
}

const handleToolDragStart = (event: DragEvent, toolId: ComposerToolId) => {
  draggingToolId.value = toolId
  event.dataTransfer?.setData('text/plain', toolId)
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
  }
}

const handleToolDragOver = (toolId: ComposerToolId) => {
  if (!draggingToolId.value || draggingToolId.value === toolId) return
  dragOverToolId.value = toolId
}

const handleToolDrop = (targetId: ComposerToolId) => {
  const sourceId = draggingToolId.value
  if (!sourceId || sourceId === targetId) return
  const nextOrder = [...composerToolOrder.value]
  const sourceIndex = nextOrder.indexOf(sourceId)
  const targetIndex = nextOrder.indexOf(targetId)
  if (sourceIndex < 0 || targetIndex < 0) return
  nextOrder.splice(sourceIndex, 1)
  nextOrder.splice(targetIndex, 0, sourceId)
  composerToolOrder.value = nextOrder
  persistComposerToolOrder()
  handleToolDragEnd()
}

const handleToolDragEnd = () => {
  draggingToolId.value = null
  dragOverToolId.value = null
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

const isSearchMatch = (idx: number) => messageSearchMatches.value.includes(idx)

const openMessageSearch = () => {
  messageSearch.visible = true
  nextTick(() => {
    const input = document.querySelector<HTMLInputElement>('.chat-search-input input')
    input?.focus()
    input?.select()
  })
}

const closeMessageSearch = () => {
  messageSearch.visible = false
  messageSearch.query = ''
  messageSearch.activeMatchIndex = -1
}

const toggleMessageSearch = () => {
  if (messageSearch.visible) {
    closeMessageSearch()
    return
  }
  openMessageSearch()
}

const jumpSearchResult = (direction: 1 | -1) => {
  const matches = messageSearchMatches.value
  if (!matches.length) return
  if (messageSearch.activeMatchIndex < 0) {
    messageSearch.activeMatchIndex = direction > 0 ? 0 : matches.length - 1
  } else {
    messageSearch.activeMatchIndex = (messageSearch.activeMatchIndex + direction + matches.length) % matches.length
  }
  scrollToMessage(matches[messageSearch.activeMatchIndex])
}

const handleGlobalKeydown = (event: KeyboardEvent) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
    event.preventDefault()
    openMessageSearch()
  }
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
    case 'toggle-reasoning':
      setReasoningPanelVisible(!showReasoningPanel.value)
      break
    case 'toggle-reasoning-expanded':
      setReasoningPanelExpanded(!reasoningPanelExpanded.value)
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

const adviceSourceLabel = (source: string) => {
  if (source === 'heartbeat') return '心跳'
  if (source === 'persona-debug') return '调试'
  return '行为'
}

const applyAdviceToInput = (adviceId: string) => {
  const item = chatState.adviceFeed.find((advice) => advice.id === adviceId)
  if (!item) return
  inputText.value = inputText.value.trim()
    ? `${inputText.value.trim()}\n${item.content}`
    : item.content
  chatStore.dismissAdvice(adviceId)
  ElMessage.success('已填入输入框')
}

const showAdviceInConversation = (adviceId: string) => {
  if (chatStore.promoteAdviceToMessage(adviceId)) {
    ElMessage.success('已显示到当前对话视图')
  }
}

const handleClearAdvice = () => {
  chatStore.clearAdviceFeed()
  ElMessage.info('已清空本地建议')
}

const openSettings = () => {
  const workspaceId = String(route.params.workspaceId || 'default')
  void router.push(`/w/${encodeURIComponent(workspaceId)}/settings`)
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
}

const handleTogglePin = async (sessionId: string, pinned: boolean) => {
  try {
    await sessionStore.updateSession(sessionId, { pinned }, sessionWorkspaceId(sessionId))
  } catch (error) {
    console.warn('[ChatPanel] failed to update session pin:', error)
    ElMessage.error('更新置顶失败')
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
  const text = buildComposerMessage().trim()
  if (!text) return
  chatStore.sendChat(text, { chatOptions })
  inputText.value = ''
  attachments.value = []
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

const refreshModelOptions = async () => {
  if (modelsLoading.value) return
  modelsLoading.value = true
  try {
    if (!settingsStore.state.llm.base_url) {
      modelOptions.value = [settingsStore.state.llm.model, chatOptions.model].filter((item): item is string => Boolean(item))
      return
    }
    const result = await settingsClient.listLlmModels({
      base_url: settingsStore.state.llm.base_url,
      api_key: settingsStore.state.llm.api_key,
      timeout: settingsStore.state.llm.timeout,
    })
    const merged = new Set([settingsStore.state.llm.model, chatOptions.model, ...(result.models || [])].filter(Boolean) as string[])
    modelOptions.value = Array.from(merged)
  } catch (error) {
    console.warn('[ChatPanel] failed to load LLM models:', error)
    modelOptions.value = [settingsStore.state.llm.model, chatOptions.model].filter((item): item is string => Boolean(item))
  } finally {
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
    showScrollBtn.value = false
  }
})

watch(() => chatState.messages.length, scrollToBottom)
watch(() => chatState.currentText, scrollToBottom)
watch(() => chatState.asrPartialText, scrollToBottom)
watch(quickPhrases, persistQuickPhrases, { deep: true })
watch(inputText, () => {
  if (isComposing.value) return
  syncQuickPanelFromInput()
})
watch(messageSearchMatches, (matches) => {
  if (!messageSearch.visible || !normalizedSearchQuery.value) {
    messageSearch.activeMatchIndex = -1
    return
  }
  messageSearch.activeMatchIndex = matches.length ? 0 : -1
  if (matches.length) {
    scrollToMessage(matches[0])
  }
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
  messagesContainer.value?.addEventListener('scroll', checkScrollPosition)
  window.addEventListener('click', closeContextMenu)
  window.addEventListener('click', closeQuickPanel)
  window.addEventListener('keydown', handleGlobalKeydown)
  scrollToBottom()
  void settingsStore.fetchSettings().then(refreshModelOptions)
  void settingsClient.warmupTts().catch(() => undefined)
  void refreshMcpSummary()
})
onUnmounted(() => {
  messagesContainer.value?.removeEventListener('scroll', checkScrollPosition)
  window.removeEventListener('click', closeContextMenu)
  window.removeEventListener('click', closeQuickPanel)
  window.removeEventListener('keydown', handleGlobalKeydown)
  endHoldToTalk()
})
</script>

<style scoped>
.chat-workspace {
  display: flex;
  flex: 1;
  gap: 12px;
  min-height: 0;
  overflow: hidden;
}

.chat-workspace--rail-hidden {
  gap: 0;
}

.session-rail-pane {
  flex: 0 0 248px;
  width: 248px;
  border-right: 1px solid rgba(255, 255, 255, 0.36);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.16);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.52);
  backdrop-filter: blur(12px) saturate(1.12);
}

.chat-surface {
  position: relative;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
}

.chat-workspace--rail-hidden .chat-surface {
  width: 100%;
}

.chat-command-bar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.72);
  padding: 10px 16px 12px;
  background: transparent;
}

.chat-command-main {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.chat-command-icon {
  display: none;
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(241, 245, 249, 0.82);
  color: #475569;
}

.chat-command-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.chat-command-copy strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-command-copy span {
  color: #94a3b8;
  font-size: 11px;
}

.chat-command-actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 6px;
}

.runtime-strip {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 7px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.22);
  min-height: 34px;
  padding: 7px 14px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.045);
  font-size: 11px;
  overflow-x: auto;
  white-space: nowrap;
}

.runtime-strip--expanded {
  color: #94a3b8;
}

.runtime-strip::-webkit-scrollbar {
  height: 0;
}

.runtime-strip span {
  flex: 0 0 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-strip span + span::before {
  content: '·';
  margin-right: 7px;
  color: #cbd5e1;
}

.runtime-strip .runtime-pill {
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.68);
  color: #64748b;
  font-weight: 800;
  padding: 2px 8px;
}

.runtime-strip .runtime-pill::before,
.runtime-strip .runtime-pill + span::before {
  display: none;
}

.runtime-strip .runtime-pill.active {
  background: rgba(220, 252, 231, 0.78);
  color: #047857;
}

.chat-error-banner {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid rgba(254, 202, 202, 0.65);
  background: rgba(255, 247, 247, 0.92);
  color: #b91c1c;
  font-size: 12px;
  padding: 8px 16px;
}

.messages-pane {
  padding: 20px clamp(16px, 4vw, 72px) 16px;
  background: transparent !important;
}

.empty-chat-home {
  display: flex;
  width: min(520px, 100%);
  align-self: center;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: #64748b;
  text-align: center;
}

.empty-chat-mark {
  display: inline-flex;
  width: 46px;
  height: 46px;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: rgba(219, 234, 254, 0.7);
  color: #2563eb;
  font-size: 22px;
}

.empty-chat-home h3 {
  margin: 4px 0 0;
  color: #334155;
  font-size: 17px;
}

.empty-chat-home p {
  margin: 0;
  font-size: 13px;
}

.empty-chat-hints {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px;
  margin-top: 2px;
}

.empty-chat-hints span {
  border: 1px solid rgba(203, 213, 225, 0.54);
  border-radius: 999px;
  background: rgba(248, 250, 252, 0.5);
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
}

.empty-chat-hints span.ready {
  border-color: rgba(34, 197, 94, 0.28);
  background: rgba(220, 252, 231, 0.56);
  color: #047857;
}

.starter-prompt-grid {
  display: grid;
  width: min(560px, 100%);
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 8px;
}

.starter-prompt {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  column-gap: 9px;
  row-gap: 2px;
  min-height: 70px;
  border: 1px solid rgba(255, 255, 255, 0.48);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.14);
  color: #334155;
  cursor: pointer;
  padding: 12px;
  text-align: left;
  transition: border-color 0.16s ease, background 0.16s ease, transform 0.16s ease;
}

.starter-prompt:hover,
.starter-prompt:focus-visible {
  border-color: rgba(124, 58, 237, 0.28);
  background: rgba(255, 255, 255, 0.22);
  transform: translateY(-1px);
}

.starter-prompt .el-icon {
  grid-row: 1 / span 2;
  color: #7c3aed;
  font-size: 18px;
}

.starter-prompt span,
.starter-prompt small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.starter-prompt span {
  font-size: 13px;
  font-weight: 800;
}

.starter-prompt small {
  color: #64748b;
  font-size: 11px;
}

.message-row {
  display: flex;
  flex-direction: row;
  gap: 10px;
  width: 100%;
}

.message-row[data-role='user'] {
  flex-direction: row-reverse;
}

.message-stack {
  display: flex;
  max-width: min(82%, 800px);
  flex-direction: column;
  gap: 6px;
}

.message-avatar {
  display: flex;
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  box-shadow: none;
  font-size: 13px;
  font-weight: 700;
}

.message-avatar-user {
  background: #2563eb;
  color: white;
}

.message-avatar-assistant {
  border: 1px solid rgba(244, 114, 182, 0.28);
  background: rgba(255, 247, 237, 0.48);
  color: #be185d;
}

.message-avatar-system {
  border: 1px dashed rgba(148, 163, 184, 0.6);
  background: rgba(248, 250, 252, 0.42);
  color: #64748b;
}

.message-meta {
  display: none;
}

.context-start-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 2px 0 4px;
  color: #64748b;
  font-size: 11px;
}

.context-start-divider::before,
.context-start-divider::after {
  content: '';
  height: 1px;
  flex: 1;
  background: rgba(148, 163, 184, 0.28);
}

.context-start-divider span {
  flex: 0 0 auto;
  border: 1px solid rgba(16, 185, 129, 0.22);
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.08);
  color: #047857;
  line-height: 1;
  padding: 4px 8px;
}

.message-bubble {
  position: relative;
  max-width: 100%;
  border-radius: 14px;
  padding: 12px 14px;
  box-shadow: none;
  backdrop-filter: none;
  color: #334155;
  font-size: 14px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  transition: none;
}

.message-row.is-search-match .message-bubble {
  border-color: rgba(245, 158, 11, 0.46);
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.1);
}

.message-row.is-search-active .message-bubble {
  border-color: rgba(245, 158, 11, 0.82);
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.18);
}

.message-row.is-context-anchor .message-bubble {
  border-color: rgba(16, 185, 129, 0.38);
}

.message-footline {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.2;
  opacity: 0;
  transition: opacity 0.16s ease;
}

.message-bubble:hover .message-footline,
.message-bubble:focus-within .message-footline {
  opacity: 1;
}

.message-avatar {
  display: none;
}

.message-bubble-user {
  border-top-right-radius: 4px;
  background: #2563eb;
  color: #fff;
}

.message-bubble-assistant {
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-top-left-radius: 4px;
  background: rgba(255, 255, 255, 0.96);
}

.message-bubble-streaming {
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-top-left-radius: 4px;
  background: rgba(255, 255, 255, 0.96);
  color: #1d4ed8;
}

.message-bubble-system {
  border: 1px dashed rgba(148, 163, 184, 0.7);
  background: rgba(248, 250, 252, 0.84);
  color: #475569;
}

.stream-caret {
  display: inline-block;
  width: 6px;
  height: 16px;
  margin-left: 4px;
  background: #6366f1;
  vertical-align: middle;
  animation: caret-pulse 1s ease-in-out infinite;
}

@keyframes caret-pulse {
  0%, 100% { opacity: 0.25; }
  50% { opacity: 1; }
}

.message-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  opacity: 0;
  transform: translateY(4px);
  transition: all 0.18s ease;
}

.message-bubble:hover .message-actions,
.message-bubble:focus-within .message-actions {
  opacity: 1;
  transform: translateY(0);
}

.message-action-button {
  display: inline-flex;
  width: 26px;
  height: 26px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  font-size: 15px;
  line-height: 1;
  padding: 0;
  transition: background 0.16s ease, color 0.16s ease, opacity 0.16s ease;
}

.message-action-button:hover,
.message-action-button:focus-visible {
  background: #f8fafc;
  color: #1e293b;
  outline: none;
}

.message-action-button:disabled {
  cursor: not-allowed;
  opacity: 0.34;
}

.message-bubble-user .message-action-button {
  color: #64748b;
}

.message-bubble-user .message-action-button:hover,
.message-bubble-user .message-action-button:focus-visible {
  background: rgba(255, 255, 255, 0.76);
  color: #111827;
}

.message-action-button.danger:hover,
.message-action-button.danger:focus-visible {
  background: #fef2f2;
  color: #b91c1c;
}

.message-edit-input {
  min-width: min(520px, 62vw);
}

.message-edit-input :deep(.el-textarea__inner) {
  border-radius: 8px;
  background: #fff;
  color: #111827;
  font-size: 13px;
  line-height: 1.55;
}

.message-edit-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

.asr-partial-card {
  display: flex;
  max-width: min(86%, 720px);
  align-items: flex-start;
  gap: 8px;
  border: 1px dashed rgba(245, 158, 11, 0.4);
  border-radius: 12px;
  background: rgba(255, 251, 235, 0.88);
  color: #92400e;
  font-size: 13px;
  line-height: 1.6;
  padding: 10px 12px;
}

.permission-card {
  display: flex;
  width: min(90%, 620px);
  flex-direction: column;
  gap: 8px;
  border: 1px solid rgba(245, 158, 11, 0.42);
  border-radius: 14px;
  background: rgba(255, 251, 235, 0.96);
  box-shadow: 0 10px 24px rgba(146, 64, 14, 0.08);
  color: #92400e;
  padding: 14px;
}

.permission-card__header,
.permission-card__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.permission-card__header {
  font-weight: 700;
}

.permission-card p,
.permission-card small {
  margin: 0;
}

.permission-card code {
  border-radius: 6px;
  background: rgba(254, 243, 199, 0.9);
  padding: 1px 5px;
}

.composer-panel {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  gap: 8px;
  border-top: 1px solid rgba(226, 232, 240, 0.72);
  background: transparent;
  padding: 10px 16px 12px;
  backdrop-filter: none;
}

.composer-panel--tools-open {
  gap: 10px;
}

.composer-tools {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 1px solid rgba(226, 232, 240, 0.72);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  padding: 10px;
  order: 0;
}

.chat-tool-strip {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 1px;
}

.chat-tool-strip::-webkit-scrollbar {
  height: 0;
}

.tool-select {
  flex: 0 0 auto;
}

.model-select {
  width: 190px;
}

.reasoning-select {
  width: 118px;
}

.response-mode-control {
  flex: 0 0 auto;
}

.advanced-options {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.advanced-options label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #475569;
  font-size: 12px;
}

.advanced-options-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 12px;
}

.advanced-options-grid :deep(.el-input-number) {
  width: 100%;
}

.hidden-file-input {
  display: none;
}

.voice-console {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid rgba(226, 232, 240, 0.72);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.68);
  padding: 10px 12px;
  color: #475569;
  backdrop-filter: none;
}

.voice-console__main {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: 10px;
}

.voice-status-badge {
  display: inline-flex;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: rgba(220, 252, 231, 0.78);
  color: #16a34a;
}

.voice-status-badge.recording {
  background: rgba(254, 226, 226, 0.8);
  color: #dc2626;
}

.voice-status-badge.speaking {
  background: rgba(237, 233, 254, 0.82);
  color: #7c3aed;
}

.voice-status-badge.offline,
.voice-status-badge.error {
  background: rgba(241, 245, 249, 0.8);
  color: #64748b;
}

.voice-status-stack {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 6px;
}

.voice-status-line {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.voice-status-line strong {
  color: #334155;
  font-size: 13px;
}

.voice-status-line small {
  color: #64748b;
  font-size: 11px;
}

.voice-meter {
  display: grid;
  width: min(260px, 100%);
  grid-template-columns: repeat(10, minmax(0, 1fr));
  gap: 3px;
}

.voice-meter span {
  height: 5px;
  border-radius: 999px;
  background: rgba(203, 213, 225, 0.72);
}

.voice-meter span.active {
  background: linear-gradient(90deg, #38bdf8, #22c55e);
}

.voice-console__controls {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
}

.hold-to-talk {
  display: inline-flex;
  min-width: 112px;
  height: 32px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid rgba(37, 99, 235, 0.3);
  border-radius: 8px;
  background: rgba(219, 234, 254, 0.72);
  color: #1d4ed8;
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  user-select: none;
}

.hold-to-talk.active {
  border-color: rgba(220, 38, 38, 0.36);
  background: rgba(254, 226, 226, 0.82);
  color: #dc2626;
}

.hold-to-talk:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.tts-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid rgba(226, 232, 240, 0.72);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.68);
  padding: 10px 12px;
  color: #475569;
  backdrop-filter: none;
}

.tts-indicator {
  color: #6d28d9;
}

.attachment-strip {
  display: flex;
  gap: 8px;
  overflow-x: auto;
}

.attachment-strip::-webkit-scrollbar {
  height: 0;
}

.attachment-chip {
  display: inline-flex;
  max-width: 260px;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 8px;
  background: rgba(248, 250, 252, 0.82);
  color: #475569;
  font-size: 12px;
  padding: 6px 8px;
}

.attachment-chip span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-chip small {
  flex: 0 0 auto;
  color: #94a3b8;
}

.attachment-chip button {
  flex: 0 0 auto;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}

.advice-strip {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 10px;
  background: #fff;
  padding: 8px;
}

.advice-strip__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
}

.advice-strip__head button,
.advice-actions button {
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  font-size: 12px;
  padding: 4px 6px;
}

.advice-strip__head button:hover,
.advice-actions button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.advice-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.advice-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  border-radius: 8px;
  background: #f8fafc;
  padding: 7px 8px;
}

.advice-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.advice-copy small {
  color: #64748b;
  font-size: 10.5px;
  font-weight: 700;
}

.advice-copy span {
  overflow: hidden;
  color: #334155;
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.advice-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 2px;
}

.composer-box {
  position: relative;
  display: flex;
  min-height: 104px;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  border: 1px solid rgba(226, 232, 240, 0.82);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: none;
  padding: 14px;
  backdrop-filter: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.composer-box:focus-within {
  border-color: rgba(117, 217, 255, 0.7);
  box-shadow: 0 0 0 2px rgba(117, 217, 255, 0.12);
}

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.composer-left-actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 7px;
}

.composer-stats {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  color: #94a3b8;
  font-size: 11px;
}

.composer-stats span + span::before {
  content: '·';
  margin-right: 8px;
  color: #cbd5e1;
}

.composer-actions {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
}

.composer-inline-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  order: 3;
}

.composer-meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  color: #64748b;
  font-size: 11px;
  order: 4;
}

.composer-meta-line span + span::before {
  content: '·';
  margin-right: 6px;
  color: #cbd5e1;
}

.composer-meta-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.92);
  color: #475569;
  font-weight: 600;
}

.composer-meta-chip.ready {
  background: rgba(220, 252, 231, 0.92);
  color: #047857;
}

.composer-meta-line--tools {
  color: #94a3b8;
  order: 5;
}

.chat-input {
  width: 100%;
}

.chat-input :deep(.el-textarea__inner) {
  min-height: 42px !important;
  border: none;
  background: transparent;
  box-shadow: none;
  color: #0f172a;
  font-size: 15px;
  line-height: 1.65;
  padding: 0;
}

.chat-input :deep(.el-textarea__inner::placeholder) {
  color: rgba(71, 85, 105, 0.62);
}

.chat-input :deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.composer-quick-panel {
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: calc(100% + 10px);
  z-index: 30;
  overflow: hidden;
  border: 1px solid rgba(226, 232, 240, 0.96);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 18px 44px rgba(15, 23, 42, 0.14);
}

.quick-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.78);
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  padding: 8px 10px;
}

.quick-panel-head kbd {
  display: inline-flex;
  min-width: 22px;
  height: 22px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(203, 213, 225, 0.88);
  border-radius: 7px;
  background: #f8fafc;
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.quick-panel-list {
  display: flex;
  max-height: 286px;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  padding: 6px;
}

.quick-panel-item {
  display: grid;
  width: 100%;
  grid-template-columns: 30px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: #0f172a;
  cursor: pointer;
  padding: 7px 8px;
  text-align: left;
}

.quick-panel-item:hover,
.quick-panel-item.selected {
  border-color: rgba(203, 213, 225, 0.82);
  background: #f8fafc;
}

.quick-panel-item.current {
  border-color: rgba(16, 185, 129, 0.34);
  background: rgba(16, 185, 129, 0.08);
}

.quick-panel-item:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.quick-panel-icon {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #eef2f7;
  color: #475569;
}

.quick-panel-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.quick-panel-copy strong,
.quick-panel-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quick-panel-copy strong {
  font-size: 13px;
  font-weight: 700;
}

.quick-panel-copy small {
  color: #64748b;
  font-size: 11px;
}

.quick-panel-empty {
  color: #64748b;
  font-size: 12px;
  padding: 18px 12px;
  text-align: center;
}

.composer-tool-slot {
  display: inline-flex;
  flex: 0 0 auto;
  border-radius: 10px;
  outline: 1px solid transparent;
  outline-offset: 2px;
  transition: opacity 0.15s ease, outline-color 0.15s ease, transform 0.15s ease;
}

.composer-tool-slot[draggable='true'] {
  cursor: grab;
}

.composer-tool-slot.is-dragging {
  opacity: 0.48;
  transform: scale(0.96);
}

.composer-tool-slot.is-drop-target {
  outline-color: rgba(16, 185, 129, 0.45);
}

.composer-actions :deep(.el-button) {
  width: 34px;
  height: 34px;
  min-height: 34px;
}

.custom-scrollbar::-webkit-scrollbar { width: 5px; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(148,163,184,0.2); border-radius: 10px; }
.custom-scrollbar:hover::-webkit-scrollbar-thumb { background: rgba(148,163,184,0.4); }
@keyframes fade-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
.animate-fade-in { animation: fade-in 0.2s ease-out forwards; }

.scroll-bottom-btn {
  position: sticky;
  bottom: 12px;
  left: 50%;
  z-index: 10;
  display: flex;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(203, 213, 225, 0.6);
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  color: #64748b;
  cursor: pointer;
  font-size: 14px;
  transform: translateX(-50%);
  transition: background 0.15s;
}

.scroll-bottom-btn:hover {
  background: #fff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
}

.md-content :deep(.md-p) { margin: 0 0 8px 0; }
.md-content :deep(.md-p:last-child) { margin-bottom: 0; }
.md-content :deep(.md-code) { background: #f1f5f9; border-radius: 8px; padding: 10px 14px; margin: 8px 0; font-size: 13px; overflow-x: auto; white-space: pre-wrap; }
.md-content :deep(.md-inline) { background: #e2e8f0; padding: 1px 5px; border-radius: 4px; font-size: 0.92em; }
.md-content :deep(.md-link) { color: #6366f1; text-decoration: underline; }
.md-content :deep(.md-li) { margin-left: 16px; list-style: disc; }
.md-content :deep(strong) { font-weight: 700; color: #1e293b; }

.context-menu {
  position: fixed;
  z-index: 100;
  min-width: 140px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  padding: 4px;
}

.context-menu button {
  display: block;
  width: 100%;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #334155;
  cursor: pointer;
  font-size: 13px;
  padding: 8px 14px;
  text-align: left;
}

.context-menu button:hover,
.context-menu button:focus-visible {
  background: #f1f5f9;
  outline: none;
}
.context-menu button.danger {
  color: #b91c1c;
}
.context-menu button.danger:hover,
.context-menu button.danger:focus-visible {
  background: #fef2f2;
  color: #991b1b;
}

.waveform { display: flex; align-items: flex-end; gap: 2px; height: 18px; }
.wave-bar {
  width: 3px;
  height: 80%;
  border-radius: 2px;
  background: linear-gradient(to top, #8b5cf6, #a78bfa);
  animation: wave 0.6s ease-in-out infinite alternate;
}
.wave-bar:nth-child(2) { height: 50%; }
.wave-bar:nth-child(3) { height: 100%; }
.wave-bar:nth-child(4) { height: 60%; }
.wave-bar:nth-child(5) { height: 40%; }
@keyframes wave { from { transform: scaleY(1); } to { transform: scaleY(0.4); } }

.drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
  background: rgba(99, 102, 241, 0.04);
}

.drop-hint {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  color: #64748b;
  font-size: 14px;
  font-weight: 500;
  padding: 16px 24px;
}

.phrase-manager {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.phrase-row,
.phrase-create-row {
  display: grid;
  grid-template-columns: minmax(120px, 0.35fr) minmax(0, 1fr) auto auto;
  align-items: start;
  gap: 8px;
}

.phrase-create-row {
  border-top: 1px solid rgba(226, 232, 240, 0.86);
  padding-top: 12px;
}

.translation-result {
  max-height: 420px;
  overflow-y: auto;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 10px;
  background: #f8fafc;
  color: #334155;
  font-size: 14px;
  line-height: 1.7;
  padding: 12px;
  white-space: pre-wrap;
}

@media (max-width: 1180px) {
  .session-rail-pane {
    flex-basis: 236px;
    width: 236px;
  }

}

@media (max-width: 900px) {
  .chat-workspace {
    flex-direction: column;
  }

  .session-rail-pane {
    width: 100%;
    max-height: 220px;
    flex-basis: auto;
  }

  .voice-console,
  .chat-command-bar,
  .composer-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .voice-console__controls,
  .composer-left-actions,
  .chat-command-actions,
  .composer-actions,
  .chat-tool-strip {
    justify-content: flex-end;
  }

  .chat-workspace--rail-hidden .chat-surface {
    min-height: 0;
  }

  .phrase-row,
  .phrase-create-row {
    grid-template-columns: 1fr;
  }

  .starter-prompt-grid {
    grid-template-columns: 1fr;
  }
}

/* Cherry Studio-style compact chat console overrides. */
.chat-workspace {
  gap: 0;
  height: 100%;
  background: transparent;
}

.session-rail-pane {
  flex: 0 0 276px;
  width: 276px;
  border-radius: 0;
  border-right: 1px solid rgba(226, 232, 240, 0.72);
  background: rgba(248, 250, 252, 0.82);
  box-shadow: none;
  backdrop-filter: none;
}

.chat-surface {
  position: relative;
  min-width: 0;
  background: transparent;
}

.chat-top-corner {
  position: absolute;
  top: 14px;
  right: 18px;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.chat-search-strip {
  display: flex;
  align-items: center;
  gap: 4px;
  width: min(360px, calc(100vw - 168px));
  height: 32px;
  border: 1px solid rgba(226, 232, 240, 0.86);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
  padding: 2px 4px 2px 8px;
}

.chat-search-input {
  min-width: 0;
  flex: 1;
}

.chat-search-input :deep(.el-input__wrapper) {
  min-height: 26px;
  border-radius: 8px;
  background: transparent;
  box-shadow: none;
  padding-inline: 0;
}

.chat-search-count {
  min-width: 34px;
  color: #64748b;
  font-size: 11px;
  text-align: center;
  white-space: nowrap;
}

.search-nav-button {
  display: inline-flex;
  width: 24px;
  height: 24px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  padding: 0;
}

.search-nav-button:hover,
.search-nav-button:focus-visible {
  background: #f1f5f9;
  color: #0f172a;
  outline: none;
}

.search-nav-button:disabled {
  cursor: not-allowed;
  opacity: 0.36;
}

.top-icon-button,
.tool-button,
.send-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
}

.top-icon-button {
  width: 32px;
  height: 32px;
  border: 1px solid rgba(226, 232, 240, 0.86);
  background: rgba(255, 255, 255, 0.82);
  color: #475569;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
}

.top-icon-button:hover,
.tool-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.tool-button {
  width: 30px;
  height: 30px;
  border: 1px solid transparent;
  font-size: 15px;
}

.tool-button.active {
  border-color: rgba(16, 185, 129, 0.22);
  color: #047857;
  background: rgba(16, 185, 129, 0.1);
  box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.08) inset;
}

.tool-button:disabled {
  cursor: not-allowed;
  opacity: 0.38;
}

.tool-button:focus-visible,
.send-button:focus-visible,
.top-icon-button:focus-visible,
.quick-panel-item:focus-visible {
  outline: 2px solid rgba(16, 185, 129, 0.36);
  outline-offset: 2px;
}

.messages-pane {
  width: min(780px, 100%);
  align-self: center;
  padding: 52px 22px 14px !important;
  background: transparent !important;
}

.message-row {
  gap: 0;
}

.message-row[data-role='user'] {
  justify-content: flex-end;
}

.message-row[data-role='assistant'],
.message-row[data-role='system'] {
  justify-content: flex-start;
}

.message-stack {
  max-width: min(64%, 560px);
}

.message-bubble {
  border-radius: 9px;
  border: 1px solid transparent;
  padding: 6px 9px;
  color: #172033;
  font-size: 13px;
  line-height: 1.5;
  background: transparent;
}

.message-bubble-user {
  border-top-right-radius: 4px;
  border-color: rgba(203, 213, 225, 0.88);
  background: #eef2f7;
  color: #111827;
}

.message-bubble-assistant,
.message-bubble-streaming {
  border-color: rgba(226, 232, 240, 0.72);
  border-top-left-radius: 4px;
  background: #fff;
}

.message-bubble-system {
  border-style: dashed;
  border-color: rgba(148, 163, 184, 0.62);
  background: rgba(241, 245, 249, 0.72);
}

.message-actions {
  gap: 8px;
  margin-top: 8px;
}

.message-action-button {
  width: 24px;
  height: 24px;
  border: 0;
  background: transparent;
  color: #8a94a6;
  font-size: 14px;
}

.message-action-button:hover,
.message-action-button:focus-visible {
  background: #f1f5f9;
  color: #111827;
}

.message-action-button.danger:hover,
.message-action-button.danger:focus-visible {
  background: #fef2f2;
  color: #b91c1c;
}

.message-footline {
  font-size: 10.5px;
}

.message-reasoning {
  margin-bottom: 8px;
  border: 1px solid rgba(203, 213, 225, 0.82);
  border-radius: 9px;
  background: #f8fafc;
  color: #334155;
  overflow: hidden;
}

.message-reasoning summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  cursor: pointer;
  color: #475569;
  font-size: 12px;
  font-weight: 760;
  list-style: none;
  padding: 7px 9px;
}

.message-reasoning summary::-webkit-details-marker {
  display: none;
}

.message-reasoning summary::before {
  content: '';
  width: 6px;
  height: 6px;
  flex: 0 0 auto;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(-45deg);
  transition: transform 0.15s ease;
}

.message-reasoning[open] summary::before {
  transform: rotate(45deg);
}

.message-reasoning summary span {
  min-width: 0;
  flex: 1;
}

.message-reasoning summary small {
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.reasoning-content {
  border-top: 1px solid rgba(226, 232, 240, 0.86);
  color: #475569;
  font-size: 12.5px;
  line-height: 1.55;
  padding: 8px 10px;
}

.message-reasoning-hidden {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  border: 1px solid rgba(203, 213, 225, 0.74);
  border-radius: 999px;
  background: #f8fafc;
  color: #64748b;
  cursor: pointer;
  font-size: 12px;
  font-weight: 720;
  margin-bottom: 8px;
  padding: 4px 9px;
}

.message-reasoning-hidden:hover,
.message-reasoning-hidden:focus-visible {
  border-color: rgba(16, 185, 129, 0.34);
  color: #047857;
  outline: none;
}

.message-pending {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-weight: 720;
}

.pending-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #10b981;
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.28);
  animation: pending-pulse 1.25s ease-in-out infinite;
}

@keyframes pending-pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.32);
    opacity: 0.72;
  }
  70% {
    box-shadow: 0 0 0 7px rgba(16, 185, 129, 0);
    opacity: 1;
  }
  100% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
    opacity: 0.72;
  }
}

.composer-panel {
  align-items: center;
  border-top: 0;
  background: transparent;
  padding: 0 18px 14px;
}

.composer-panel > * {
  width: min(880px, 100%);
}

.composer-box {
  gap: 8px;
  min-height: 94px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 11px;
  background: #fff;
  box-shadow: 0 5px 16px rgba(15, 23, 42, 0.06);
  padding: 10px 12px 8px;
  backdrop-filter: none;
}

.composer-box:focus-within {
  border-color: rgba(16, 185, 129, 0.42);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.08), 0 0 0 3px rgba(16, 185, 129, 0.1);
}

.chat-input :deep(.el-textarea__inner) {
  min-height: 52px !important;
  color: #111827;
  font-size: 14px;
  line-height: 1.5;
  padding: 1px 0 !important;
}

.composer-toolbar {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  min-height: 32px;
}

.composer-tools-left,
.composer-tools-right {
  display: flex;
  min-width: 0;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.composer-tools-left {
  flex: 1 1 280px;
  overflow: visible;
  padding: 2px 0;
}

.composer-tools-left::-webkit-scrollbar {
  display: none;
}

.composer-tools-right {
  flex: 1 1 360px;
  justify-content: flex-end;
  overflow: visible;
}

.composer-tools-right::-webkit-scrollbar {
  display: none;
}

.model-select {
  width: 138px;
}

.reasoning-select {
  width: 106px;
}

.model-select :deep(.el-select__wrapper),
.reasoning-select :deep(.el-select__wrapper) {
  min-height: 28px;
  border-radius: 8px;
  background: #f8fafc;
  box-shadow: 0 0 0 1px rgba(226, 232, 240, 0.9) inset;
}

.send-button {
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: #111827;
  color: #fff;
}

.send-button:hover {
  background: #0f172a;
}

.send-button:disabled {
  cursor: not-allowed;
  background: #e2e8f0;
  color: #94a3b8;
}

.send-button.is-warning {
  background: #f59e0b;
}

.composer-meta-line {
  gap: 6px;
  flex-wrap: wrap;
  min-height: 16px;
  color: #64748b;
  font-size: 10.5px;
  line-height: 1.35;
}

.composer-meta-line span + span::before {
  content: none;
}

.composer-meta-chip {
  border: 1px solid rgba(226, 232, 240, 0.78);
  background: #f8fafc;
  color: #64748b;
  font-weight: 600;
}

.composer-meta-value {
  display: inline-block;
  max-width: 128px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.composer-meta-chip.ready,
.composer-meta-chip.is-active {
  border-color: rgba(16, 185, 129, 0.18);
  background: rgba(16, 185, 129, 0.1);
  color: #047857;
}

.voice-console {
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 14px;
  background: #f8fafc;
  box-shadow: none;
  padding: 10px 12px;
}

.voice-status-badge {
  border-radius: 10px;
}

.hold-to-talk {
  height: 30px;
  min-width: 102px;
  border-radius: 10px;
  background: #fff;
}

.tts-indicator,
.attachment-chip,
.permission-card,
.asr-partial-card {
  border-radius: 12px;
  box-shadow: none;
}

.attachment-strip {
  padding: 0 4px;
}

.attachment-chip {
  background: #fff;
}

.scroll-bottom-btn {
  background: #fff;
}

:global([data-theme='dark']) .chat-surface {
  background: transparent;
}

:global([data-theme='dark']) .session-rail-pane {
  border-right-color: rgba(51, 65, 85, 0.82);
  background: rgba(15, 23, 42, 0.9);
}

:global([data-theme='dark']) .top-icon-button,
:global([data-theme='dark']) .chat-search-strip,
:global([data-theme='dark']) .message-bubble-assistant,
:global([data-theme='dark']) .message-bubble-streaming,
:global([data-theme='dark']) .composer-box,
:global([data-theme='dark']) .attachment-chip {
  border-color: rgba(51, 65, 85, 0.9);
  background: #ffffff;
  color: #111827;
}

:global([data-theme='dark']) .tool-button {
  color: #64748b;
}

:global([data-theme='dark']) .tool-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

:global([data-theme='dark']) .search-nav-button:hover,
:global([data-theme='dark']) .search-nav-button:focus-visible {
  background: #f1f5f9;
  color: #0f172a;
}

:global([data-theme='dark']) .tool-button.active {
  border-color: rgba(16, 185, 129, 0.28);
  background: rgba(16, 185, 129, 0.12);
  color: #047857;
}

:global([data-theme='dark']) .composer-box {
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.34);
}

:global([data-theme='dark']) .composer-meta-line {
  color: #64748b;
}

:global([data-theme='dark']) .composer-meta-chip {
  border-color: rgba(226, 232, 240, 0.78);
  background: #f8fafc;
  color: #64748b;
}

:global([data-theme='dark']) .composer-meta-chip.ready,
:global([data-theme='dark']) .composer-meta-chip.is-active {
  border-color: rgba(16, 185, 129, 0.18);
  background: rgba(16, 185, 129, 0.1);
  color: #047857;
}

:global([data-theme='dark']) .voice-console,
:global([data-theme='dark']) .model-select :deep(.el-select__wrapper),
:global([data-theme='dark']) .reasoning-select :deep(.el-select__wrapper) {
  background: #f8fafc;
  color: #111827;
}

:global([data-theme='dark']) .composer-quick-panel {
  border-color: rgba(226, 232, 240, 0.72);
  background: #fff;
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.34);
}

:global([data-theme='dark']) .quick-panel-item {
  color: #111827;
}

:global([data-theme='dark']) .quick-panel-item:hover,
:global([data-theme='dark']) .quick-panel-item.selected {
  background: #f8fafc;
}

@media (max-width: 900px) {
  .session-rail-pane {
    width: 100%;
    max-height: 180px;
    border-right: 0;
    border-bottom: 1px solid rgba(226, 232, 240, 0.72);
  }

  .messages-pane {
    padding: 56px 14px 14px !important;
  }

  .chat-top-corner {
    left: 12px;
    right: 12px;
  }

  .chat-search-strip {
    width: auto;
    flex: 1;
  }

  .message-stack {
    max-width: 88%;
  }

  .composer-panel {
    padding: 0 10px 10px;
  }

  .composer-toolbar,
  .voice-console {
    align-items: stretch;
    flex-direction: column;
  }

  .composer-tools-left {
    width: 100%;
  }

  .composer-tools-right {
    width: 100%;
    justify-content: flex-start;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .model-select {
    min-width: 150px;
  }

  .reasoning-select {
    min-width: 110px;
  }

  .composer-tools-right::-webkit-scrollbar {
    display: none;
  }
}
</style>

<style>
.yuizaki-bg.yuizaki-bg .chat-mode .chat-surface {
  background: transparent;
}

.yuizaki-bg.yuizaki-bg .chat-mode .composer-box {
  border-color: rgba(15, 23, 42, 0.12);
  background: #fff;
  box-shadow: 0 5px 16px rgba(15, 23, 42, 0.06);
  backdrop-filter: none;
}

.yuizaki-bg.yuizaki-bg .chat-mode .composer-box .el-textarea__inner {
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
}

.yuizaki-bg.yuizaki-bg .chat-mode .message-bubble-user {
  border-color: rgba(203, 213, 225, 0.88);
  background: #eef2f7;
  color: #111827;
  box-shadow: none;
  backdrop-filter: none;
}

.yuizaki-bg.yuizaki-bg .chat-mode .message-bubble-assistant,
.yuizaki-bg.yuizaki-bg .chat-mode .message-bubble-streaming {
  border-color: rgba(226, 232, 240, 0.92);
  background: #fff;
  color: #111827;
  box-shadow: none;
  backdrop-filter: none;
}

[data-theme='dark'] .yuizaki-bg.yuizaki-bg .chat-mode .chat-surface {
  background: transparent;
}

[data-theme='dark'] .yuizaki-bg.yuizaki-bg .chat-mode .composer-box {
  border-color: rgba(226, 232, 240, 0.62);
  background: #fff;
  color: #111827;
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.24);
}

[data-theme='dark'] .yuizaki-bg.yuizaki-bg .chat-mode .composer-box .el-textarea__inner {
  color: #111827;
}

[data-theme='dark'] .yuizaki-bg.yuizaki-bg .chat-mode .message-bubble-user {
  border-color: rgba(226, 232, 240, 0.34);
  background: #e5e7eb;
  color: #111827;
}

[data-theme='dark'] .yuizaki-bg.yuizaki-bg .chat-mode .message-bubble-assistant,
[data-theme='dark'] .yuizaki-bg.yuizaki-bg .chat-mode .message-bubble-streaming {
  border-color: rgba(226, 232, 240, 0.42);
  background: #fff;
  color: #111827;
}

</style>
