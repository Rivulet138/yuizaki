<template>
  <PanelShell
    title="能力与工具"
    tone="tool"
  >
    <div class="tool-panel">
      <nav class="tool-view-nav" aria-label="工具视图" role="tablist">
        <button
          v-for="view in toolViews"
          :key="view.id"
          type="button"
          role="tab"
          class="tool-view-button"
          :class="{ active: activeToolView === view.id }"
          :aria-selected="activeToolView === view.id"
          @click="activeToolView = view.id"
        >
          {{ view.label }}
        </button>
      </nav>

      <div v-show="activeToolView === 'status'" class="tool-view-stack">
      <section class="tool-health panel-card" aria-label="本地能力状态">
        <button
          v-for="item in healthItems"
          :key="item.key"
          type="button"
          class="health-item"
          :class="[`tone-${item.tone}`, { active: activeHealthKey === item.key }]"
          @click="applyHealthAction(item.key)"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.detail }}</small>
        </button>
      </section>

      </div>

      <section v-show="activeToolView === 'stream'" class="stream-summary panel-card" aria-label="直播能力状态">
        <div class="section-heading">
          <div>
            <h3>直播能力</h3>
            <p>{{ streamSummaryText }}</p>
          </div>
          <div class="section-actions">
            <el-tag :type="streamStatusTagType" effect="light">{{ streamStatusLabel }}</el-tag>
            <el-button plain :loading="loadingStreamProbe" @click="probeStream">探测适配器</el-button>
            <el-button plain :icon="Refresh" :loading="loadingStream" @click="loadStream">刷新</el-button>
          </div>
        </div>
        <el-alert v-if="streamLoadError" class="panel-alert" type="warning" :closable="false" show-icon>
          <div class="alert-row"><span>{{ streamLoadError }}</span></div>
        </el-alert>
        <div v-if="streamSnapshot" class="stream-status-line">
          <span>适配器：{{ streamSnapshot.adapter?.name || streamSnapshot.adapter?.id || '未连接' }}</span>
          <span>{{ streamSnapshot.adapter?.configured ? '已配置' : '未配置' }}</span>
          <span>{{ streamSnapshot.policy?.humanApprovalRequired !== false ? '需要人工确认' : '可自动执行' }}</span>
          <span>Twitch EventSub：{{ streamSnapshot.platforms?.twitch?.revoked ? '订阅已撤销，需重新配置' : streamSnapshot.platforms?.twitch?.eventsubConfigured ? '已配置，仅接收入站事件' : '未配置' }}</span>
          <span>Twitch 出站聊天：{{ streamSnapshot.platforms?.twitch?.outboundActions ? '已配置，仍需确认' : '未配置' }}</span>
          <span>Twitch IRC：{{ twitchIrcStatusLabel }}</span>
          <el-button
            v-if="!streamSnapshot.platforms?.twitch?.ircConnection?.desired"
            size="small"
            text
            :loading="connectingTwitch"
            @click="connectTwitch"
          >连接 IRC</el-button>
          <el-button
            v-else
            size="small"
            text
            :loading="disconnectingTwitch"
            @click="disconnectTwitch"
          >断开 IRC</el-button>
          <el-button
            v-if="streamSnapshot.platforms?.twitch?.revoked"
            size="small"
            text
            :loading="reconfiguringTwitch"
            @click="reconfigureTwitch"
          >标记已重新配置</el-button>
          <span v-if="streamSnapshot.platforms?.twitch?.inboundRateLimitPerMinute">Twitch 入站配额：{{ streamSnapshot.platforms.twitch.inboundRateLimitPerMinute }}/分钟</span>
          <span v-if="streamSnapshot.platforms?.twitch?.throttledEvents">已限流：{{ streamSnapshot.platforms.twitch.throttledEvents }} 条</span>
        </div>
        <div class="stream-safety-controls stream-twitch-config">
          <div>
            <strong>Twitch 凭据</strong>
            <small>{{ twitchConfigStatusText }}</small>
          </div>
          <div class="stream-twitch-fields">
            <el-input v-model="twitchClientIdDraft" size="small" clearable placeholder="Client ID" />
            <el-input v-model="twitchEventsubSecretDraft" size="small" type="password" show-password clearable placeholder="EventSub Secret" />
            <el-input v-model="twitchEventsubTokenDraft" size="small" type="password" show-password clearable placeholder="EventSub Token（可选）" />
            <el-input v-model="twitchChatTokenDraft" size="small" type="password" show-password clearable placeholder="Chat Token" />
            <el-input v-model="twitchBroadcasterIdDraft" size="small" clearable placeholder="Broadcaster ID" />
            <el-input v-model="twitchSenderIdDraft" size="small" clearable placeholder="Sender ID" />
            <el-input v-model="twitchModeratorIdDraft" size="small" clearable placeholder="Moderator ID（可选）" />
            <el-input v-model="twitchChannelDraft" size="small" clearable placeholder="频道名（不含 #）" />
            <el-input v-model="twitchUsernameDraft" size="small" clearable placeholder="IRC 用户名" />
            <el-input v-model="twitchEventsubCallbackUrlDraft" size="small" clearable placeholder="EventSub HTTPS 回调（可选）" />
            <el-select v-model="twitchSubscriptionProviderDraft" size="small" clearable placeholder="订阅管理方式">
              <el-option label="仅本地计划" value="none" />
              <el-option label="本地 staging" value="in-memory-staging" />
              <el-option label="Twitch Helix" value="helix" />
            </el-select>
            <div class="stream-twitch-actions">
              <el-button size="small" plain :loading="savingTwitchConfig" @click="saveTwitchConfig">保存并重配置</el-button>
              <el-button size="small" plain :loading="probingTwitchConfig" @click="probeTwitchConfig">只读检查</el-button>
              <el-button size="small" text type="danger" :loading="savingTwitchConfig" @click="clearTwitchConfig">清除凭据</el-button>
            </div>
          </div>
        </div>
        <div class="stream-safety-controls stream-obs-config">
          <div>
            <strong>OBS WebSocket</strong>
            <small>{{ streamSnapshot?.adapter?.passwordConfigured ? '密码已配置' : '密码未配置' }} · 临时保存</small>
          </div>
          <div class="stream-obs-fields">
            <el-input v-model="obsEndpointDraft" size="small" placeholder="ws://127.0.0.1:4455" clearable />
            <el-input v-model="obsPasswordDraft" size="small" type="password" show-password clearable placeholder="OBS 密码（可选，仅内存）" />
            <el-checkbox v-model="obsAllowRemote" size="small">允许非本机 endpoint</el-checkbox>
            <el-button size="small" plain :loading="configuringObs" @click="configureObs">保存并探测</el-button>
            <el-button v-if="streamSnapshot?.adapter?.passwordConfigured" size="small" text type="danger" :loading="configuringObs" @click="clearObsPassword">清除密码</el-button>
          </div>
        </div>
        <div class="stream-safety-controls stream-profile-controls">
          <div>
            <strong>OBS 配置档</strong>
            <small>{{ obsProfiles.length ? `${obsCurrentProfile || '未选择'} · ${obsProfiles.length} 个` : '未读取' }}</small>
          </div>
          <div class="stream-profile-fields">
            <el-select v-model="obsProfileDraft" size="small" filterable allow-create clearable placeholder="配置档名称">
              <el-option v-for="profile in obsProfiles" :key="profile.profileName" :label="profile.profileName" :value="profile.profileName" />
            </el-select>
            <el-button size="small" plain :loading="loadingObsProfiles" @click="loadObsProfiles">读取配置档</el-button>
            <el-button size="small" type="warning" plain :loading="previewingStreamCapability === 'stream.profile_switch'" :disabled="!obsProfileDraft.trim() || Boolean(previewingStreamCapability)" @click="previewObsProfileSwitch">预览切换</el-button>
          </div>
        </div>
        <div class="stream-safety-controls stream-subscription-controls">
          <div>
            <strong>EventSub 本地订阅计划</strong>
            <small>{{ streamSubscriptionStatusLabel }}</small>
          </div>
          <el-checkbox-group v-model="twitchSubscriptionDraft" class="stream-subscription-options" :disabled="loadingTwitchSubscriptions">
            <el-checkbox v-for="option in twitchSubscriptionOptions" :key="option.value" :value="option.value">{{ option.label }}</el-checkbox>
          </el-checkbox-group>
          <el-button size="small" plain :loading="loadingTwitchSubscriptions" @click="saveTwitchSubscriptions">保存计划</el-button>
        </div>
        <div class="stream-safety-controls">
          <div>
            <strong>本地人工接管</strong>
            <small>{{ streamTakeoverEnabled ? '已启用 · 需确认' : '未启用' }}</small>
          </div>
          <el-button
            size="small"
            plain
            :type="streamTakeoverEnabled ? 'warning' : 'default'"
            :loading="loadingStreamTakeover"
            @click="toggleStreamTakeover"
          >{{ streamTakeoverEnabled ? '关闭接管' : '启用接管' }}</el-button>
        </div>
        <div class="stream-safety-controls stream-moderation-controls">
          <div>
            <strong>聊天内容治理</strong>
            <small>{{ streamModerationSummary }}</small>
          </div>
          <el-switch v-model="streamModerationEnabled" :disabled="loadingStreamModeration" />
          <el-button size="small" plain :loading="loadingStreamModeration" @click="saveStreamModeration">保存治理</el-button>
          <div class="stream-moderation-fields">
            <el-input v-model="streamModerationTermsInput" size="small" clearable placeholder="敏感词，用逗号分隔" />
            <el-input-number v-model="streamModerationSlowModeSeconds" size="small" :min="0" :max="3600" :step="1" controls-position="right" aria-label="慢模式秒数" />
            <el-input-number v-model="streamModerationMaxMessagesPerMinute" size="small" :min="1" :max="600" :step="1" controls-position="right" aria-label="每分钟最多消息数" />
          </div>
        </div>
        <div class="stream-safety-controls">
          <div>
            <strong>自动生成本地草稿</strong>
            <small>{{ streamDraftConsumer?.running ? '运行中 · 仅草稿' : streamDraftConsumer?.enabled ? '已启用' : '已关闭' }}</small>
          </div>
          <el-button
            size="small"
            plain
            :type="streamDraftConsumer?.enabled ? 'warning' : 'default'"
            :loading="loadingStreamDraftConsumer"
            @click="toggleStreamDraftConsumer"
          >{{ streamDraftConsumer?.enabled ? '关闭自动草稿' : '启用自动草稿' }}</el-button>
        </div>
        <div v-if="streamCapabilities.length" class="stream-capability-list">
          <div v-for="item in streamCapabilities" :key="item.id" class="stream-capability-row">
            <div>
              <strong>{{ item.name || item.id }}</strong>
              <small>{{ item.available ? (item.executionReady ? '可执行' : item.needsConfig ? '需配置 OBS' : '仅本地') : '未连接' }} · {{ streamRiskLabel(item.riskLevel) }}</small>
            </div>
            <el-button
              size="small"
              plain
              :loading="previewingStreamCapability === item.id"
              :disabled="!item.available || Boolean(previewingStreamCapability)"
              @click="previewStream(item.id)"
            >预览</el-button>
          </div>
        </div>
        <el-empty v-else description="暂无可用能力" :image-size="48" />
        <div v-if="streamSnapshot?.preview" class="stream-preview-note">
          <strong>预览：{{ streamSnapshot.preview.summary || streamSnapshot.preview.action || streamSnapshot.preview.kind }}</strong>
          <span>风险：{{ streamRiskLabel(streamSnapshot.preview.riskLevel) }} · 参数：{{ formatStreamParams(streamSnapshot.preview.params) }}</span>
          <span v-if="streamSnapshot.preview.steps?.length">{{ streamSnapshot.preview.steps.join(' → ') }}</span>
          <el-button
            size="small"
            type="primary"
            plain
            :loading="loadingStreamExecute"
            :disabled="!streamSnapshot.preview.requestId || Boolean(streamExecution?.ok) || !streamPreviewExecutionReady"
            @click="confirmStreamExecution"
          >{{ streamPreviewExecutionReady ? '确认执行' : '需配置 OBS' }}</el-button>
        </div>
        <div v-if="streamExecution" class="stream-execution-note" :class="{ failed: !streamExecution.ok }">
          <strong>{{ streamExecution.ok ? '执行完成' : '执行失败' }}</strong>
          <span>结果：{{ streamExecution.outcome || (streamExecution.ok ? 'known_success' : 'failed') }} · 验证：{{ streamExecution.verificationStatus || '未提供' }}</span>
          <span v-if="streamExecution.auditEvent">审计事件已记录</span>
          <el-button v-if="!streamExecution.ok" size="small" plain :loading="loadingStreamExecute" @click="confirmStreamExecution">手动重试</el-button>
        </div>
        <div class="stream-actions-heading">
          <strong>直播动作审计</strong>
          <el-button size="small" text :loading="loadingStreamActions" @click="loadStreamActions">刷新审计</el-button>
        </div>
        <div v-if="streamActions.length" class="stream-action-list">
          <div v-for="action in streamActions" :key="`${action.requestId}:${action.at}:${action.status}`" class="stream-action-row">
            <div>
              <strong>{{ action.action }}</strong>
              <small>{{ formatStreamActionStatus(action.status) }} · {{ formatStreamEventTime(action.at) }}</small>
            </div>
            <span :class="`stream-action-status status-${action.status}`">{{ formatStreamActionStatus(action.status) }}</span>
            <small v-if="action.verificationStatus || action.errorCode">{{ action.verificationStatus || action.errorCode }}</small>
          </div>
        </div>
        <el-empty v-else description="暂无直播动作审计" :image-size="40" />
        <div v-if="streamProbeSummary" class="stream-probe-note">探测：{{ streamProbeSummary }}</div>
        <div class="stream-events-heading">
          <strong>最近本地事件</strong>
            <div class="stream-event-heading-actions">
              <el-button size="small" text :loading="consumingStreamDrafts" @click="consumeStreamDrafts">生成未处理草稿</el-button>
              <el-button size="small" text :loading="loadingStreamEvents" @click="loadStreamEvents">刷新事件</el-button>
            </div>
        </div>
        <div v-if="streamEvents.length" class="stream-event-list">
          <div v-for="event in streamEvents" :key="event.eventId || event.id || `${event.kind}-${event.createdAt || event.receivedAt}`" class="stream-event-row">
            <span>{{ event.kind }}</span>
            <strong>{{ event.text || event.message || '（无文本）' }}</strong>
            <small>{{ event.author || event.source || '本地' }} · {{ formatStreamEventTime(event.createdAt ?? event.receivedAt ?? event.at) }} · {{ event.delivered ? '已投递' : '仅本地队列' }}</small>
            <div class="stream-event-actions">
              <el-button
                size="small"
                text
                :loading="generatingStreamDraft === streamEventId(event)"
                :disabled="!streamEventId(event) || Boolean(generatingStreamDraft)"
                @click="generateStreamDraft(event)"
              >生成草稿</el-button>
              <span v-if="streamDraftByEventId.get(streamEventId(event))" class="stream-draft-status">
                {{ streamDraftByEventId.get(streamEventId(event))?.status === 'generated' ? '已有草稿' : '草稿失败' }}
              </span>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无本地事件" :image-size="40" />
        <div class="stream-drafts-heading">
          <strong>回复草稿</strong>
          <el-button size="small" text :loading="loadingStreamDrafts" @click="loadStreamDrafts">刷新草稿</el-button>
        </div>
        <div v-if="streamDrafts.length" class="stream-draft-list">
          <div v-for="draft in streamDrafts" :key="draft.draftId" class="stream-draft-row">
            <div>
              <strong>{{ draft.author || '观众' }}</strong>
              <small>{{ draft.eventText || '（无原始消息）' }}</small>
            </div>
            <p v-if="draft.reply">{{ draft.reply }}</p>
            <p v-else class="stream-draft-error">{{ draft.error || '未生成回复' }}</p>
            <el-button
              v-if="draft.status === 'generated' && draft.reply && draft.sendStatus !== 'known_success' && draft.sendStatus !== 'unknown_effect'"
              size="small"
              plain
              :loading="previewingStreamCapability === `stream.chat_send:${draft.draftId}`"
              :disabled="Boolean(previewingStreamCapability)"
              @click="previewDraftSend(draft)"
            >预览发送</el-button>
            <el-button
              v-if="draft.status === 'failed'"
              size="small"
              text
              :loading="generatingStreamDraft === draft.eventId"
              :disabled="Boolean(generatingStreamDraft)"
              @click="retryStreamDraft(draft)"
            >重新生成</el-button>
            <small>{{ streamDraftDeliveryLabel(draft) }} · {{ formatStreamEventTime(draft.createdAt) }}</small>
          </div>
        </div>
        <el-empty v-else description="暂无草稿" :image-size="40" />
      </section>

      <section v-show="activeToolView === 'capabilities'" class="capability-workspace panel-card">
        <div class="capability-list-pane">
          <div class="section-heading compact">
            <div>
              <h3>{{ activeFilterLabel }}</h3>
            </div>
            <el-button plain :icon="Refresh" :loading="loadingSnapshots" @click="refreshSnapshots">刷新能力</el-button>
          </div>

          <div class="toolbar">
            <el-input v-model="searchText" clearable placeholder="搜索能力、范围、标签">
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
            <el-select v-model="filterKind" placeholder="能力来源" class="toolbar-select" @change="activeHealthKey = ''">
              <el-option v-for="item in sourceCards" :key="item.kind || 'all'" :label="`${item.title} (${item.count})`" :value="item.kind" />
            </el-select>
            <el-select v-model="filterRisk" clearable placeholder="风险级别" class="toolbar-select">
              <el-option v-for="risk in riskOptions" :key="risk.value" :label="risk.label" :value="risk.value" />
            </el-select>
            <el-select v-model="filterApproval" placeholder="权限确认" class="toolbar-select">
              <el-option label="全部" value="all" />
              <el-option label="需确认" value="required" />
              <el-option label="免确认" value="free" />
            </el-select>
          </div>

          <el-alert v-if="capabilityLoadError" class="panel-alert" type="warning" :closable="false" show-icon>
            <div class="alert-row">
              <span>{{ capabilityLoadError }}</span>
              <el-button size="small" text :loading="loadingCapabilities" @click.stop="loadCapabilities">重试</el-button>
            </div>
          </el-alert>

          <div v-if="filteredCapabilities.length" class="capability-list">
            <button
              v-for="item in filteredCapabilities"
              :key="item.id"
              type="button"
              class="capability-row"
              :class="{ active: selectedCapability?.id === item.id }"
              @click="selectedCapabilityId = item.id"
            >
              <div class="row-title">
                <strong>{{ item.name }}</strong>
                <el-tag size="small" :type="kindTagType(item.kind)" effect="light">{{ kindLabel(item.kind) }}</el-tag>
                <el-tag size="small" :type="riskTagType(item.riskLevel)" effect="plain">{{ riskLabel(item.riskLevel) }}</el-tag>
              </div>
              <p>{{ displayCapabilityDescription(item) }}</p>
              <div class="row-meta">
                <span>{{ executionLabel(item) }}</span>
                <span>{{ item.observability?.trace ? '记录调用' : '未记录调用' }}</span>
                <span>超时 {{ formatTimeout(item.timeoutMs) }}</span>
                <span v-if="item.hasPostcondition" class="completion-meta">完成可验证</span>
                <span v-else-if="item.hasRecheck" class="completion-meta">可复查</span>
              </div>
            </button>
          </div>
          <el-empty v-else description="没有匹配的能力" />
        </div>

        <aside class="detail-pane">
          <template v-if="selectedCapability">
            <div class="detail-heading">
              <el-tag :type="kindTagType(selectedCapability.kind)" effect="light">{{ kindLabel(selectedCapability.kind) }}</el-tag>
              <h3>{{ selectedCapability.name }}</h3>
              <p>{{ displayCapabilityDescription(selectedCapability) }}</p>
            </div>

            <div class="risk-card" :class="`risk-${selectedCapability.riskLevel}`">
              <div>
                <span>风险和权限</span>
                <strong>{{ riskLabel(selectedCapability.riskLevel) }}</strong>
              </div>
              <small>{{ riskHint(selectedCapability) }}</small>
            </div>

            <div class="detail-grid">
              <div>
                <span>ID</span>
                <strong>{{ selectedCapability.id }}</strong>
              </div>
              <div>
                <span>类型</span>
                <strong>{{ kindLabel(selectedCapability.kind) }}</strong>
              </div>
              <div>
                <span>归属</span>
                <strong>{{ ownerLabel(selectedCapability.owner) }}</strong>
              </div>
              <div>
                <span>超时</span>
                <strong>{{ formatTimeout(selectedCapability.timeoutMs) }}</strong>
              </div>
            </div>

            <div class="detail-section">
              <span class="section-label">作用范围</span>
              <div class="token-list">
                <el-tag v-for="scope in selectedCapability.scopes || []" :key="scope" size="small" effect="plain">{{ scope }}</el-tag>
                <span v-if="!(selectedCapability.scopes || []).length" class="muted-text">未声明范围</span>
              </div>
            </div>

            <div class="detail-section">
              <span class="section-label">标签</span>
              <div class="token-list">
                <el-tag v-for="tag in capabilityTags(selectedCapability)" :key="tag" size="small" type="info" effect="plain">{{ tag }}</el-tag>
                <span v-if="!capabilityTags(selectedCapability).length" class="muted-text">暂无标签</span>
              </div>
            </div>

            <div class="detail-section">
              <span class="section-label">输入结构</span>
              <div class="schema-summary">
                <strong>{{ schemaSummary(selectedCapability.inputSchema) }}</strong>
                <details>
                  <summary>查看 JSON schema</summary>
                  <pre>{{ schemaPreview(selectedCapability.inputSchema) }}</pre>
                </details>
              </div>
            </div>
          </template>
          <el-empty v-else description="未选择能力" />
        </aside>
      </section>

      <section v-show="activeToolView === 'skills'" class="skill-catalog panel-card">
        <div class="section-heading">
          <div>
            <h3>项目技能</h3>
          </div>
          <div class="section-actions">
            <input
              ref="skillImportInput"
              class="file-input"
              type="file"
              accept=".json,.md,.markdown,application/json,text/markdown,text/plain"
              multiple
              @change="handleSkillFileImport"
            />
            <div class="skill-summary">
              <el-tag type="success" effect="light">内置 {{ builtInSkillCount }}</el-tag>
              <el-tag v-if="importedSkillItems.length" type="info" effect="light">导入 {{ importedSkillItems.length }}</el-tag>
              <el-tag v-if="importedSkillItems.length" :type="skillStorageTagType" effect="light">{{ skillStorageLabel }}</el-tag>
              <el-tag type="primary" effect="light">分类 {{ skillCategoryOptions.length }}</el-tag>
            </div>
            <el-button plain :icon="Upload" :loading="loadingImportedSkills || savingImportedSkills" @click="openSkillImport">导入 Skills</el-button>
          </div>
        </div>

        <div class="toolbar skill-toolbar">
          <el-input v-model="skillSearchText" clearable placeholder="搜索技能、分类、标签">
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-select v-model="skillCategoryFilter" placeholder="分类" class="toolbar-select">
            <el-option label="全部分类" value="all" />
            <el-option v-for="category in skillCategoryOptions" :key="category" :label="skillCategoryLabel(category)" :value="category" />
          </el-select>
        </div>

        <div v-if="importedSkillItems.length" class="skill-bulkbar">
          <div class="skill-bulkbar-main">
            <el-checkbox
              :model-value="allFilteredImportedSelected"
              :indeterminate="filteredImportedIndeterminate"
              :disabled="!hasActiveSkillFilter || !filteredImportedSkillItems.length || savingImportedSkills"
              @change="(value) => toggleFilteredSkillSelection(Boolean(value))"
            >
              筛选结果
            </el-checkbox>
            <span>已选 {{ selectedSkillCount }} 个，自定义 {{ importedSkillItems.length }} 个</span>
            <span v-if="hasActiveSkillFilter">当前匹配 {{ filteredImportedSkillItems.length }} 个</span>
          </div>
          <div class="skill-bulkbar-actions">
            <el-button size="small" plain :icon="Check" :disabled="!hasActiveSkillFilter || !filteredImportedSkillItems.length || savingImportedSkills" @click="selectFilteredImportedSkills">
              选择筛选结果
            </el-button>
            <el-button size="small" plain :icon="Close" :disabled="!selectedSkillCount || savingImportedSkills" @click="clearSkillSelection">
              清除选择
            </el-button>
            <el-button size="small" plain type="danger" :icon="Delete" :disabled="!selectedSkillCount || savingImportedSkills" :loading="savingImportedSkills" @click="deleteSelectedSkills">
              删除选中
            </el-button>
            <el-button size="small" plain type="danger" :icon="Delete" :disabled="!canDeleteFilteredSkills || savingImportedSkills" :loading="savingImportedSkills" @click="deleteFilteredImportedSkills">
              删除筛选结果
            </el-button>
          </div>
        </div>

        <div v-if="filteredSkillItems.length" class="skill-grid">
          <article v-for="skill in filteredSkillItems" :key="skill.id" class="skill-card" :class="{ selected: skill.imported && isSkillSelected(skill.id) }">
            <div class="skill-card-head">
              <div>
                <strong>{{ skill.name }}</strong>
                <span>{{ skillCategoryLabel(skill.category) }}</span>
              </div>
              <el-checkbox
                v-if="skill.imported"
                class="skill-select"
                :model-value="isSkillSelected(skill.id)"
                :disabled="savingImportedSkills"
                @click.stop
                @change="(value) => toggleSkillSelection(skill.id, Boolean(value))"
              />
            </div>
            <p>{{ skill.description }}</p>
            <div class="skill-meta">
              <el-tag v-if="!skill.imported" size="small" type="success" effect="plain">内置</el-tag>
              <el-tag v-else size="small" type="warning" effect="plain">自定义</el-tag>
              <el-tag v-if="skill.imported && skill.runtimeBinding === 'catalog_only'" size="small" type="info" effect="plain">仅目录</el-tag>
              <el-tag v-if="skill.fit === 'high'" size="small" type="primary" effect="plain">高适配</el-tag>
              <el-tag v-else-if="skill.fit === 'medium'" size="small" type="info" effect="plain">中适配</el-tag>
            </div>
            <div v-if="skill.imported" class="skill-actions">
              <el-button size="small" plain type="danger" :icon="Delete" :loading="savingImportedSkills" @click="removeImportedSkill(skill.id)">删除</el-button>
            </div>
          </article>
        </div>
        <el-empty v-else description="没有匹配的技能" />
      </section>

      <section v-show="activeToolView === 'history'" class="bottom-grid">
        <article class="panel-card plugin-panel">
          <div class="section-heading compact">
            <div>
              <h3>插件工具</h3>
            </div>
            <el-tag :type="pluginHealthTagType" effect="light">{{ pluginHealthLabel }}</el-tag>
          </div>
          <div v-if="pluginTools.length" class="plugin-list">
            <div v-for="tool in pluginTools" :key="tool.id" class="mini-item">
              <strong>{{ tool.name }}</strong>
              <span>{{ tool.desc || '插件未提供说明' }}</span>
            </div>
          </div>
          <el-empty v-else description="暂无插件工具" :image-size="64" />
        </article>

        <article class="panel-card log-panel">
          <div class="section-heading compact">
            <div>
              <h3>最近调用</h3>
            </div>
            <el-tag effect="plain">{{ recentToolLogs.length }} 条记录</el-tag>
          </div>
          <div v-if="recentToolLogs.length" class="log-list">
            <div v-for="(log, idx) in recentToolLogs" :key="`${log.sortKey}-${idx}`" class="log-item">
              <span>{{ log.time }}</span>
              <el-tag size="small" :title="log.source" :type="toolLogTagType(log.actionStatus || log.status)" effect="plain">{{ toolActionStatusLabel(log.actionStatus || log.status) }}</el-tag>
              <strong>{{ log.text }}</strong>
              <small v-if="log.evidence?.length" class="log-evidence">{{ log.evidence[0] }}</small>
            </div>
          </div>
          <el-empty v-else description="暂无工具调用记录" :image-size="64" />
        </article>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Close, Delete, Refresh, Search, Upload } from '@element-plus/icons-vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { pluginClient, systemClient } from '@/api/client'
import { curatedSkillRecommendations } from '../skillRecommendations'
import type { PluginLoadFailure, PluginRuntimeState, PluginToolCapabilityContribution } from '../../../../shared/plugin'
import type { CapabilityDescriptor, CapabilityKind, CapabilityRiskLevel, SkillCatalogItem, StreamActionRecord, StreamActionsSnapshot, StreamCapabilityDescriptor, StreamDraftConsumerSnapshot, StreamDraftsSnapshot, StreamExecuteResponse, StreamLocalEvent, StreamObsProfile, StreamReplyDraft, StreamRuntimeSnapshot } from '../../../../shared/capability'
import type { AgentTraceSnapshot, MCPSnapshot, MCPServerConfigSnapshot, MCPServerStatusSnapshot, RuntimeLoopRecord, StepExecutionRecord } from '../../../../shared/agent'
import { projectToolActionStatus, toolActionStatusLabel, toolEvidenceFromRecord, type ToolActionStatus } from '../toolActionProjection'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'
type CapabilityKindFilter = CapabilityKind | ''
type CapabilityRiskFilter = CapabilityRiskLevel | ''
type ApprovalFilter = 'all' | 'required' | 'free'
type MetricTone = 'blue' | 'amber' | 'rose' | 'emerald'
type SkillCategoryFilter = 'all' | string
type ImportedSkillCatalogItem = SkillCatalogItem & { imported?: boolean }
type HealthActionKey = 'ready' | 'approval' | 'mcp-error' | 'plugin-error' | 'trace'
type ToolViewId = 'status' | 'stream' | 'capabilities' | 'skills' | 'history'

const IMPORTED_SKILLS_STORAGE_KEY = 'yuizaki.importedSkills'
const IMPORTED_SKILLS_MIGRATION_KEY = 'yuizaki.importedSkills.backendMigrated'
const IMPORTED_SKILLS_DIRTY_KEY = 'yuizaki.importedSkills.localDirty'
const toolViews: Array<{ id: ToolViewId; label: string }> = [
  { id: 'status', label: '状态' },
  { id: 'stream', label: '直播' },
  { id: 'capabilities', label: '能力' },
  { id: 'skills', label: '技能' },
  { id: 'history', label: '记录' },
]
const activeToolView = ref<ToolViewId>('status')

interface SourceCard {
  kind: CapabilityKindFilter
  title: string
  count: number
}

interface RiskOption {
  value: CapabilityRiskLevel
  label: string
}

interface ToolLogItem {
  time: string
  text: string
  source: string
  status?: string | null
  sortKey: string
  actionStatus?: ToolActionStatus
  evidence?: string[]
}

interface HealthItem {
  key: HealthActionKey
  label: string
  value: number
  detail: string
  tone: MetricTone
}

type MCPRow = MCPServerConfigSnapshot & MCPServerStatusSnapshot & {
  name: string
  connected: boolean
  tools_count: number
  resources_count: number
  prompts_count: number
}

const logs = ref<ToolLogItem[]>([])
const pluginTools = ref<PluginToolCapabilityContribution[]>([])
const pluginStates = ref<PluginRuntimeState[]>([])
const pluginLoadFailures = ref<PluginLoadFailure[]>([])
const capabilities = ref<CapabilityDescriptor[]>([])
const agentTrace = ref<AgentTraceSnapshot | null>(null)
const mcpSnapshot = ref<MCPSnapshot | null>(null)
const streamSnapshot = ref<StreamRuntimeSnapshot | null>(null)
const streamProbe = ref<Record<string, unknown> | null>(null)
const obsProfiles = ref<StreamObsProfile[]>([])
const obsCurrentProfile = ref('')
const streamEvents = ref<StreamLocalEvent[]>([])
const streamDrafts = ref<StreamReplyDraft[]>([])
const streamActions = ref<StreamActionRecord[]>([])
const streamExecution = ref<StreamExecuteResponse | null>(null)
const streamPendingExecution = ref<{ requestId: string; action: string; params: Record<string, unknown> } | null>(null)

const filterKind = ref<CapabilityKindFilter>('')
const filterRisk = ref<CapabilityRiskFilter>('')
const filterApproval = ref<ApprovalFilter>('all')
const searchText = ref('')
const selectedCapabilityId = ref('')
const activeHealthKey = ref<HealthActionKey | ''>('')
const skillSearchText = ref('')
const skillCategoryFilter = ref<SkillCategoryFilter>('all')
const skillImportInput = ref<HTMLInputElement | null>(null)
const importedSkillItems = ref<ImportedSkillCatalogItem[]>([])
const selectedSkillIds = ref(new Set<string>())

const loadingCapabilities = ref(false)
const loadingPlugins = ref(false)
const loadingMcp = ref(false)
const loadingStream = ref(false)
const loadingStreamProbe = ref(false)
const loadingObsProfiles = ref(false)
const loadingStreamEvents = ref(false)
const loadingStreamDrafts = ref(false)
const loadingStreamActions = ref(false)
const consumingStreamDrafts = ref(false)
const loadingStreamDraftConsumer = ref(false)
const loadingTwitchSubscriptions = ref(false)
const loadingStreamModeration = ref(false)
const streamDraftConsumer = ref<StreamDraftConsumerSnapshot | null>(null)
const generatingStreamDraft = ref('')
const reconfiguringTwitch = ref(false)
const connectingTwitch = ref(false)
const disconnectingTwitch = ref(false)
const loadingStreamTakeover = ref(false)
const loadingStreamExecute = ref(false)
const streamTakeoverEnabled = ref(false)
const streamModerationEnabled = ref(true)
const streamModerationTermsInput = ref('')
const streamModerationSlowModeSeconds = ref(0)
const streamModerationMaxMessagesPerMinute = ref(30)
const obsEndpointDraft = ref('')
const obsPasswordDraft = ref('')
const obsAllowRemote = ref(false)
const obsProfileDraft = ref('')
const configuringObs = ref(false)
const savingTwitchConfig = ref(false)
const probingTwitchConfig = ref(false)
const twitchConfigStatus = ref<{ secureStorageAvailable: boolean; configured: Record<string, boolean> } | null>(null)
const twitchClientIdDraft = ref('')
const twitchEventsubSecretDraft = ref('')
const twitchEventsubTokenDraft = ref('')
const twitchChatTokenDraft = ref('')
const twitchBroadcasterIdDraft = ref('')
const twitchSenderIdDraft = ref('')
const twitchModeratorIdDraft = ref('')
const twitchChannelDraft = ref('')
const twitchUsernameDraft = ref('')
const twitchEventsubCallbackUrlDraft = ref('')
const twitchSubscriptionProviderDraft = ref('none')
const twitchSubscriptionDraft = ref<string[]>([])
const previewingStreamCapability = ref('')
const loadingImportedSkills = ref(false)
const savingImportedSkills = ref(false)
const capabilityLoadError = ref('')
const mcpLoadError = ref('')
const streamLoadError = ref('')
const importedSkillStorageError = ref('')
const importedSkillBackendReady = ref(false)
let pluginLoadSequence = 0
let capabilityLoadSequence = 0
let toolTraceLoadSequence = 0
let mcpLoadSequence = 0

const riskOptions: RiskOption[] = [
  { value: 'safe', label: '安全' },
  { value: 'low', label: '低风险' },
  { value: 'medium', label: '中风险' },
  { value: 'high', label: '高风险' },
  { value: 'critical', label: '关键风险' },
]

const capabilityDescriptionOverrides: Record<string, string> = {
  open_app: '按名称启动本地桌面应用。',
  open_url: '使用默认浏览器打开链接。',
  read_file: '读取本地文本文件内容。',
  write_file: '将文本内容写入本地文件。',
  web_search: '搜索当前公开网络信息，并返回带链接的简明结果。',
  'browser.open_page': '通过 Playwright MCP 服务打开浏览器页面。',
  'time.now': '获取当前本地时间。',
  mcp_playwright_browser_open_page: '在 Playwright 浏览器上下文中打开 URL，并等待网络空闲。',
  mcp_playwright_browser_click: '打开 URL 后点击指定 CSS 选择器。',
  'yuizaki.observe-recall-loop': '收集运行时输入，召回相关记忆，并送入桌宠 Agent 链路。',
  'yuizaki.capability-routing': '通过统一能力快照选择内置工具、插件工具或 MCP 工具。',
  'yuizaki.create-once-task': '在本地调度器中创建一次性任务。',
  'yuizaki.create-interval-task': '在本地调度器中创建按间隔重复执行的任务。',
  'yuizaki.skill.voice-dialogue-chain': '把麦克风输入整理成文本，交给 LLM 生成回复，再触发 TTS 和桌宠动作。',
  'yuizaki.skill.long-dialogue-summary': '把长聊天、语音转写和会话记录整理成摘要、决定、待办和风险。',
  'yuizaki.skill.companion-reflection': '分析对话里的情绪、沟通模式和可改进点，用于长期桌宠记忆和关系反馈。',
  'yuizaki.skill.memory-capture': '把事实、偏好、项目决定和待办沉淀到可检索记忆。',
  'yuizaki.skill.realtime-screen-vision': '把桌面截图作为短时视觉帧交给桌宠理解，OCR 仅用于需要精确读字的场景。',
  'yuizaki.skill.local-file-organizer': '识别本机文件、素材和导入资源用途，给出整理、重命名和归档建议。',
  'yuizaki.skill.ocr-document-organizer': '读取截图、票据或扫描文档里的关键信息，生成结构化条目并建议归档位置。',
  'yuizaki.skill.webapp-testing': '用 Playwright 检查本地 Electron/Vite 页面、交互、截图和控制台错误。',
  'yuizaki.skill.frontend-design': '优化桌宠面板、设置页、本地能力页和调试页的布局、文案、状态和响应式细节。',
  'yuizaki.skill.interface-hardening': '检查空状态、错误提示、长文本溢出、中文文案、深色模式和失败降级。',
  'yuizaki.skill.code-review': '按缺陷、回归风险、缺失测试和行为变化审查改动。',
  'yuizaki.skill.repo-analysis': '只读梳理代码结构、调用关系和风险点，用于复杂改动前建立事实图。',
  'yuizaki.skill.best-practice-research': '优先查官方文档和上游资料，适合接新模型、TTS、ASR、MCP、Ollama、LM Studio 或 SDK 前使用。',
  'yuizaki.skill.mcp-builder': '把本地工具、资源读取、浏览器控制或外部服务包装成标准 MCP 工具。',
  'yuizaki.skill.skill-authoring': '把常用链路沉淀成可复用 Skill，包括触发条件、输入、流程、校验和失败兜底。',
  'yuizaki.skill.image-generation': '生成或编辑头像、背景、UI 参考图和透明素材。',
  'yuizaki.skill.image-enhancement': '提升截图清晰度和可读性，适合 UI 验收、反馈图和文档插图。',
  'yuizaki.skill.document-export': '把摘要、报告和会话结果导出为 PDF、DOCX、PPTX 或 XLSX。',
  'yuizaki.skill.spreadsheet-helper': '编写和调试 Excel/表格公式，适合导入数据、统计结果和批量整理。',
  'yuizaki.skill.task-triage': '把用户反馈、长对话或问题清单拆成优先级、复现步骤、下一步动作和回复草稿。',
  'yuizaki.skill.agent-trace-debug': '分析 LLM、工具调用、记忆召回和插件钩子的执行轨迹，用于排查输出和耗时问题。',
  'yuizaki.skill.release-notes': '把技术改动整理成用户可读的更新说明。',
  'yuizaki.skill.design-system': '沉淀颜色、间距、组件状态和文案规则，让设置页、桌宠页和能力页保持一致。',
  'yuizaki.skill.web-research': '对需要时效性的模型、插件、依赖和工具信息进行搜索、比对和资料整理。',
  'yuizaki.skill.content-writing': '把调研结果、教程、FAQ 和版本说明写成清晰中文内容。',
  'yuizaki.skill.project-planning': '把模糊需求拆成范围、里程碑、验收标准和风险。',
  'yuizaki.skill.quality-cleanup': '清理重复抽象、冗余 UI 文案、过度包装和不一致命名，保持改动小而可验收。',
}

const capabilityNameDescriptionOverrides: Record<string, string> = {
  open_app: '按名称启动本地桌面应用。',
  open_url: '使用默认浏览器打开链接。',
  read_file: '读取本地文本文件内容。',
  write_file: '将文本内容写入本地文件。',
  web_search: '搜索当前公开网络信息，并返回带链接的简明结果。',
  'browser.open_page': '通过 Playwright MCP 服务打开浏览器页面。',
  'time.now': '获取当前本地时间。',
  mcp_playwright_browser_open_page: '在 Playwright 浏览器上下文中打开 URL，并等待网络空闲。',
  mcp_playwright_browser_click: '打开 URL 后点击指定 CSS 选择器。',
  'Observe / Recall Loop': '收集运行时输入，召回相关记忆，并送入桌宠 Agent 链路。',
  'Capability Routing': '通过统一能力快照选择内置工具、插件工具或 MCP 工具。',
  'Create Once Task': '在本地调度器中创建一次性任务。',
  'Create Interval Task': '在本地调度器中创建按间隔重复执行的任务。',
}

const capabilityRawDescriptionOverrides: Record<string, string> = {
  'launch a desktop application by name': '按名称启动本地桌面应用。',
  'open a url in the default browser': '使用默认浏览器打开链接。',
  'read a local text file': '读取本地文本文件内容。',
  'write text content to a local file': '将文本内容写入本地文件。',
  'search the web for current public information and return concise results with urls': '搜索当前公开网络信息，并返回带链接的简明结果。',
  'open a browser page via playwright mcp server': '通过 Playwright MCP 服务打开浏览器页面。',
  'get the current local time': '获取当前本地时间。',
  'open a url in a playwright browser context and wait for network idle. (mcp: playwright/browser.open_page)': '在 Playwright 浏览器上下文中打开 URL，并等待网络空闲。',
  'open a url and click a css selector with playwright. (mcp: playwright/browser.click)': '打开 URL 后点击指定 CSS 选择器。',
  'collect runtime input, recall memory, and feed the companion agent pipeline.': '收集运行时输入，召回相关记忆，并送入桌宠 Agent 链路。',
  'route builtin, plugin, and mcp capabilities through the unified registry snapshot.': '通过统一能力快照选择内置工具、插件工具或 MCP 工具。',
  'create a one-shot scheduled task in the local scheduler.': '在本地调度器中创建一次性任务。',
  'create a recurring scheduled task in the local scheduler.': '在本地调度器中创建按间隔重复执行的任务。',
}

const normalizedSearch = computed(() => searchText.value.trim().toLowerCase())
const normalizedSkillSearch = computed(() => skillSearchText.value.trim().toLowerCase())
const loadingSnapshots = computed(() => loadingCapabilities.value || loadingPlugins.value || loadingMcp.value)

const readyCapabilityCount = computed(() => capabilities.value.filter(isDirectExecutableCapability).length)
const approvalRequiredCount = computed(() => capabilities.value.filter(item => item.requiresApproval).length)
const pluginIssueCount = computed(() => (
  pluginLoadFailures.value.length +
  pluginStates.value.filter(item => ['blocked', 'error', 'degraded'].includes(item.status)).length
))
const allSkillItems = computed<ImportedSkillCatalogItem[]>(() => {
  const merged = new Map<string, ImportedSkillCatalogItem>()
  for (const skill of curatedSkillRecommendations) {
    merged.set(skill.id, { ...skill, imported: false })
  }
  for (const skill of importedSkillItems.value) {
    merged.set(skill.id, { ...skill, imported: true })
  }
  return [...merged.values()]
})
const builtInSkillCount = computed(() => allSkillItems.value.filter(item => !item.imported).length)
const mcpRows = computed<MCPRow[]>(() => {
  const snapshot = mcpSnapshot.value
  if (!snapshot) return []
  return Object.entries(snapshot.servers || {})
    .map(([name, server]) => {
      const status = snapshot.status?.[name] || {}
      return {
        ...server,
        ...status,
        name,
        enabled: server.enabled,
        connected: Boolean(status.connected),
        tools_count: status.tools_count ?? 0,
        resources_count: status.resources_count ?? 0,
        prompts_count: status.prompts_count ?? 0,
      }
    })
    .sort((left, right) => Number(right.enabled) - Number(left.enabled) || left.name.localeCompare(right.name, 'zh-CN'))
})
const mcpErrorCount = computed(() => mcpLoadError.value ? 1 : mcpRows.value.filter(isMcpErrored).length)
const streamCapabilities = computed<StreamCapabilityDescriptor[]>(() => streamSnapshot.value?.capabilities ?? [])
const streamDraftByEventId = computed(() => {
  const index = new Map<string, StreamReplyDraft>()
  for (const draft of streamDrafts.value) {
    if (draft.eventId) index.set(draft.eventId, draft)
  }
  return index
})
const streamStatusLabel = computed(() => {
  const state = streamSnapshot.value?.state || 'disconnected'
  const labels: Record<string, string> = {
    disconnected: '未连接', ready: '已就绪', preview: '预览中', live: '直播中', ending: '结束中', ended: '已结束', error: '故障',
  }
  return labels[state] || state
})
const streamStatusTagType = computed<TagType>(() => {
  const state = streamSnapshot.value?.state
  if (state === 'live' || state === 'ready') return 'success'
  if (state === 'preview') return 'primary'
  if (state === 'error') return 'danger'
  return 'info'
})
const streamSummaryText = computed(() => {
  if (!streamSnapshot.value) return '读取直播适配器状态与可预览动作'
  const available = streamCapabilities.value.filter(item => item.available).length
  return `${available}/${streamCapabilities.value.length} 可预览`
})
const streamPreviewExecutionReady = computed(() => {
  const action = streamSnapshot.value?.preview?.action || streamSnapshot.value?.preview?.kind
  if (!action) return false
  return streamCapabilities.value.find(item => item.id === action)?.executionReady === true
})
const streamProbeSummary = computed(() => {
  if (!streamProbe.value) return ''
  const values = Object.entries(streamProbe.value).slice(0, 4).map(([key, value]) => `${key}=${String(value)}`)
  return values.length ? values.join('，') : '已完成，未返回附加信息'
})

const twitchSubscriptionOptions = [
  { value: 'channel.chat.message', label: '聊天消息' },
  { value: 'channel.follow', label: '关注事件' },
  { value: 'channel.subscribe', label: '订阅事件' },
]
const streamSubscriptionStatusLabel = computed(() => {
  const plan = streamSnapshot.value?.platforms?.twitch?.subscriptionPlan
  if (!plan) return '未读取'
  if (plan.status === 'planned') return `已保存 ${plan.desired?.length || 0} 类 · 本地`
  if (plan.status === 'revoked') return '已撤销 · 需重配'
  if (plan.status === 'unconfigured') return '缺少 Secret'
  return '未选择'
})

const skillCategoryOptions = computed(() => (
  [...new Set(allSkillItems.value.map(item => item.category).filter(Boolean))]
    .sort((a, b) => skillCategoryLabel(a).localeCompare(skillCategoryLabel(b), 'zh-CN'))
))

const healthItems = computed<HealthItem[]>(() => [
  { key: 'ready', label: '可执行', value: readyCapabilityCount.value, detail: '低风险', tone: 'emerald' },
  { key: 'approval', label: '需确认', value: approvalRequiredCount.value, detail: '执行前确认', tone: 'amber' },
  { key: 'mcp-error', label: 'MCP 异常', value: mcpErrorCount.value, detail: '连接/清单', tone: mcpErrorCount.value ? 'rose' : 'emerald' },
  { key: 'plugin-error', label: '插件异常', value: pluginIssueCount.value, detail: '加载/阻断', tone: pluginIssueCount.value ? 'rose' : 'emerald' },
  { key: 'trace', label: '调用记录', value: recentToolLogs.value.length, detail: '最近链路', tone: 'blue' },
])

const sourceCards = computed<SourceCard[]>(() => [
  {
    kind: '',
    title: '全部能力',
    count: capabilities.value.length,
  },
  {
    kind: 'builtin-tool',
    title: '内置工具',
    count: countByKind('builtin-tool'),
  },
  {
    kind: 'mcp-tool',
    title: 'MCP 工具',
    count: countByKind('mcp-tool'),
  },
  {
    kind: 'plugin-tool',
    title: '插件工具',
    count: countByKind('plugin-tool'),
  },
  {
    kind: 'skill',
    title: '编排技能',
    count: countByKind('skill'),
  },
  {
    kind: 'command',
    title: '本地命令',
    count: countByKind('command'),
  },
])

const pluginHealthLabel = computed(() => {
  const blocked = pluginStates.value.filter(item => ['blocked', 'error'].includes(item.status)).length
  const degraded = pluginStates.value.filter(item => item.status === 'degraded').length
  if (pluginLoadFailures.value.length) return `${pluginLoadFailures.value.length} 个加载失败`
  if (blocked) return `${blocked} 个不可用`
  if (degraded) return `${degraded} 个降级`
  if (pluginStates.value.length) return `${pluginStates.value.length} 个已加载`
  return '暂无插件'
})

const pluginHealthTagType = computed<TagType>(() => {
  if (pluginLoadFailures.value.length) return 'danger'
  if (pluginStates.value.some(item => ['blocked', 'error'].includes(item.status))) return 'danger'
  if (pluginStates.value.some(item => item.status === 'degraded')) return 'warning'
  if (pluginStates.value.length) return 'success'
  return 'info'
})

const filteredCapabilities = computed(() => capabilities.value.filter((item) => {
  if (activeHealthKey.value === 'ready' && !isDirectExecutableCapability(item)) return false
  if (activeHealthKey.value === 'trace' && !item.observability?.trace) return false
  if (filterKind.value && item.kind !== filterKind.value) return false
  if (filterRisk.value && item.riskLevel !== filterRisk.value) return false
  if (filterApproval.value === 'required' && !item.requiresApproval) return false
  if (filterApproval.value === 'free' && item.requiresApproval) return false
  const query = normalizedSearch.value
  return !query || searchableText(item).includes(query)
}))

const selectedCapability = computed(() => {
  const selected = filteredCapabilities.value.find(item => item.id === selectedCapabilityId.value)
  return selected ?? filteredCapabilities.value[0] ?? null
})

const filteredSkillItems = computed(() => {
  const query = normalizedSkillSearch.value
  return allSkillItems.value.filter((item) => {
    if (skillCategoryFilter.value !== 'all' && item.category !== skillCategoryFilter.value) return false
    if (!query) return true
    return [
      item.name,
      item.description,
      item.category,
      ...(item.tags || []),
    ].filter(Boolean).join(' ').toLowerCase().includes(query)
  })
})

const hasActiveSkillFilter = computed(() => Boolean(normalizedSkillSearch.value) || skillCategoryFilter.value !== 'all')
const filteredImportedSkillItems = computed(() => filteredSkillItems.value.filter(skill => skill.imported))
const filteredImportedSkillIds = computed(() => filteredImportedSkillItems.value.map(skill => skill.id))
const selectedSkillCount = computed(() => selectedSkillIds.value.size)
const selectedFilteredImportedCount = computed(() => filteredImportedSkillIds.value.filter(id => selectedSkillIds.value.has(id)).length)
const allFilteredImportedSelected = computed(() => (
  filteredImportedSkillIds.value.length > 0 &&
  selectedFilteredImportedCount.value === filteredImportedSkillIds.value.length
))
const filteredImportedIndeterminate = computed(() => (
  selectedFilteredImportedCount.value > 0 &&
  selectedFilteredImportedCount.value < filteredImportedSkillIds.value.length
))
const canDeleteFilteredSkills = computed(() => hasActiveSkillFilter.value && filteredImportedSkillItems.value.length > 0)
const skillStorageLabel = computed(() => {
  if (savingImportedSkills.value) return '保存中'
  if (loadingImportedSkills.value) return '读取中'
  if (importedSkillBackendReady.value) return '后端已保存'
  return '本地暂存'
})
const skillStorageTagType = computed<TagType>(() => {
  if (savingImportedSkills.value || loadingImportedSkills.value) return 'info'
  if (importedSkillBackendReady.value) return 'success'
  return importedSkillStorageError.value ? 'warning' : 'info'
})

const traceToolLogs = computed<ToolLogItem[]>(() => {
  const snapshot = agentTrace.value
  if (!snapshot) return []
  const items: ToolLogItem[] = []
  for (const step of snapshot.steps || []) {
    if (!step.tool && !step.capability_id && !step.capability_kind) continue
    items.push(toolLogFromStep(step))
  }
  for (const loop of snapshot.runtime_loop || []) {
    const entry = toolLogFromRuntimeLoop(loop)
    if (entry) items.push(entry)
  }
  return items
})

const recentToolLogs = computed(() => (
  [...logs.value, ...traceToolLogs.value]
    .sort((a, b) => b.sortKey.localeCompare(a.sortKey))
    .slice(0, 20)
))

const activeFilterLabel = computed(() => {
  const kind = sourceCards.value.find(item => item.kind === filterKind.value)?.title || '全部能力'
  const risk = filterRisk.value ? riskLabel(filterRisk.value) : '全部风险'
  const approval = filterApproval.value === 'required' ? '需确认' : filterApproval.value === 'free' ? '免确认' : '全部权限'
  const preset = healthItems.value.find(item => item.key === activeHealthKey.value)?.label
  return `${preset || kind} · ${risk} · ${approval}`
})

function searchableText(item: CapabilityDescriptor) {
  return [
    item.id,
    item.name,
    displayCapabilityDescription(item),
    item.type,
    item.kind,
    item.source,
    item.owner,
    item.riskLevel,
    ...(item.tags || []),
    ...(item.contributionCategories || []),
    ...(item.scopes || []),
    ...(item.memoryHooks || []),
  ].filter(Boolean).join(' ').toLowerCase()
}

function countByKind(kind: CapabilityKindFilter) {
  if (!kind) return capabilities.value.length
  return capabilities.value.filter(item => item.kind === kind).length
}

function isDirectExecutableCapability(item: CapabilityDescriptor) {
  return !item.requiresApproval && (
    ['safe', 'low'].includes(item.riskLevel)
    || ['mcp-tool', 'plugin-tool'].includes(item.kind)
  )
}

function isMcpErrored(server: MCPRow) {
  return Boolean(server.enabled && !server.connected && (server.last_error || server.inventory_error || server.message))
}

function applyHealthAction(action: HealthActionKey) {
  activeHealthKey.value = action
  activeToolView.value = 'capabilities'
  if (action === 'ready') {
    filterKind.value = ''
    filterRisk.value = ''
    filterApproval.value = 'all'
    searchText.value = ''
    return
  }
  if (action === 'approval') {
    filterKind.value = ''
    filterRisk.value = ''
    filterApproval.value = 'required'
    searchText.value = ''
    return
  }
  if (action === 'mcp-error') {
    filterKind.value = 'mcp-tool'
    filterRisk.value = ''
    filterApproval.value = 'all'
    searchText.value = ''
    return
  }
  if (action === 'plugin-error') {
    filterKind.value = 'plugin-tool'
    filterRisk.value = ''
    filterApproval.value = 'all'
    searchText.value = ''
    return
  }
  if (action === 'trace') {
    filterKind.value = ''
    filterRisk.value = ''
    filterApproval.value = 'all'
    searchText.value = ''
  }
}

function kindLabel(kind: CapabilityKind) {
  const labels: Record<CapabilityKind, string> = {
    'builtin-tool': '内置',
    'plugin-tool': '插件',
    'mcp-tool': 'MCP',
    skill: 'Skill',
    command: '命令',
  }
  return labels[kind] || kind
}

function kindTagType(kind: CapabilityKind): TagType {
  const map: Record<CapabilityKind, TagType> = {
    'builtin-tool': 'primary',
    'plugin-tool': 'success',
    'mcp-tool': 'warning',
    skill: 'danger',
    command: 'info',
  }
  return map[kind]
}

function kindFallbackDescription(kind: CapabilityKind) {
  const map: Record<CapabilityKind, string> = {
    'builtin-tool': 'Yuizaki 后端内置能力，用于基础动作或本地资源访问。',
    'plugin-tool': '插件贡献能力，是否可用取决于插件加载状态。',
    'mcp-tool': 'MCP 服务暴露的工具，是否可用取决于对应服务连接状态。',
    skill: '编排技能，用来描述一段可复用的 Agent 流程。',
    command: '本地命令入口，用来触发后端任务或调度动作。',
  }
  return map[kind]
}

function normalizeDescriptionKey(value?: string) {
  return String(value || '').trim().replace(/\s+/g, ' ').toLowerCase()
}

function displayCapabilityDescription(item: CapabilityDescriptor) {
  const idOverride = capabilityDescriptionOverrides[item.id]
  if (idOverride) return idOverride

  const nameOverride = capabilityNameDescriptionOverrides[item.name]
  if (nameOverride) return nameOverride

  const rawDescriptionOverride = capabilityRawDescriptionOverrides[normalizeDescriptionKey(item.description)]
  if (rawDescriptionOverride) return rawDescriptionOverride

  return item.description || kindFallbackDescription(item.kind)
}

function executionLabel(item: CapabilityDescriptor) {
  if (item.requiresApproval) return '执行前确认'
  if (['mcp-tool', 'plugin-tool'].includes(item.kind)) return '启用即授权'
  if (['high', 'critical'].includes(item.riskLevel)) return '高风险免确认'
  return '可直接执行'
}

function ownerLabel(owner?: string) {
  if (!owner) return '未声明'
  const labels: Record<string, string> = {
    'yuizaki.builtin-tools': '内置工具',
    'yuizaki.companion-orchestrator': '桌宠编排',
    'yuizaki.task-router': '任务路由',
  }
  if (owner.startsWith('plugin:')) return `插件 ${owner.slice('plugin:'.length)}`
  if (owner.startsWith('mcp:')) return `MCP ${owner.slice('mcp:'.length)}`
  return labels[owner] || owner
}

function riskLabel(risk: CapabilityRiskLevel) {
  return riskOptions.find(item => item.value === risk)?.label || risk
}

function riskTagType(risk: CapabilityRiskLevel): TagType {
  const map: Record<CapabilityRiskLevel, TagType> = {
    safe: 'success',
    low: 'info',
    medium: 'warning',
    high: 'danger',
    critical: 'danger',
  }
  return map[risk]
}

function riskHint(item: CapabilityDescriptor) {
  if (item.requiresApproval) return '执行前会弹出确认。'
  if (['mcp-tool', 'plugin-tool'].includes(item.kind)) return '由对应服务或插件的启用开关授权，关闭后停止调用。'
  if (['high', 'critical'].includes(item.riskLevel)) return '会触碰文件、桌面或外部服务，建议保留记录。'
  if (item.riskLevel === 'medium') return '适合按需调用并保留执行记录。'
  return '适合作为常规入口。'
}

function capabilityTags(item: CapabilityDescriptor) {
  return [...(item.tags || []), ...(item.contributionCategories || [])]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function schemaFieldNames(schema?: Record<string, unknown>) {
  if (!schema) return []
  const properties = schema.properties
  if (isRecord(properties)) return Object.keys(properties)
  return Object.keys(schema)
}

function schemaSummary(schema?: Record<string, unknown>) {
  const fields = schemaFieldNames(schema)
  if (!fields.length) return '未声明字段'
  if (fields.length <= 4) return fields.join(', ')
  return `${fields.slice(0, 4).join(', ')} +${fields.length - 4}`
}

function schemaPreview(schema?: Record<string, unknown>) {
  if (!schema || !Object.keys(schema).length) return '{}'
  try {
    return JSON.stringify(schema, null, 2)
  } catch {
    return '{...}'
  }
}

function formatTimeout(timeoutMs?: number) {
  if (!timeoutMs) return '默认'
  if (timeoutMs >= 1000) return `${Math.round(timeoutMs / 1000)}s`
  return `${timeoutMs}ms`
}

function skillCategoryLabel(category: string) {
  const labels: Record<string, string> = {
    companion: '桌宠与记忆',
    perception: '感知能力',
    development: '开发工程',
    frontend: '界面体验',
    research: '资料调研',
    automation: '自动化',
    document: '文档数据',
    mcp: 'MCP 扩展',
    governance: '质量治理',
    media: '图像媒体',
    authoring: '技能编写',
    general: '通用',
  }
  return labels[category] || category
}

function openSkillImport() {
  skillImportInput.value?.click()
}

async function handleSkillFileImport(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) return

  try {
    const imported = await importSkillFiles(files)
    if (!imported.length) {
      ElMessage.warning('没有识别到可导入的 Skill')
      return
    }
    await mergeImportedSkills(imported)
    ElMessage.success(`已导入 ${imported.length} 个 Skill`)
  } catch (error) {
    const message = error instanceof Error ? error.message : '导入 Skills 失败'
    ElMessage.error(message)
  }
}

async function importSkillFiles(files: File[]) {
  const imported: ImportedSkillCatalogItem[] = []
  for (const file of files) {
    const text = await file.text()
    if (file.name.toLowerCase().endsWith('.json')) {
      imported.push(...parseSkillJson(text, file.name))
    } else {
      const skill = parseSkillMarkdown(text, file.name)
      if (skill) imported.push(skill)
    }
  }
  return imported
}

function parseSkillJson(text: string, fileName: string): ImportedSkillCatalogItem[] {
  let payload: unknown
  try {
    payload = JSON.parse(text)
  } catch {
    throw new Error(`${fileName} 不是有效 JSON`)
  }

  const candidates = Array.isArray(payload)
    ? payload
    : isRecord(payload) && Array.isArray(payload.items)
      ? payload.items
      : isRecord(payload) && Array.isArray(payload.skills)
        ? payload.skills
        : [payload]

  return candidates
    .map((candidate, index) => normalizeImportedSkill(candidate, `${fileName}-${index + 1}`))
    .filter((item): item is ImportedSkillCatalogItem => Boolean(item))
}

function parseSkillMarkdown(text: string, fileName: string): ImportedSkillCatalogItem | null {
  const frontmatter = parseFrontmatter(text)
  const body = text.replace(/^---\s*[\s\S]*?\s*---/, '').trim()
  const heading = body.match(/^#\s+(.+)$/m)?.[1]?.trim()
  const firstParagraph = body
    .split(/\r?\n/)
    .map(line => line.trim())
    .find(line => line && !line.startsWith('#') && !line.startsWith('---'))
  const name = frontmatter.name || frontmatter.title || heading || fileName.replace(/\.(md|markdown)$/i, '')
  const description = frontmatter.description || firstParagraph || '导入的本地 Skill'

  return normalizeImportedSkill({
    id: frontmatter.id,
    name,
    description,
    category: frontmatter.category,
    fit: frontmatter.fit,
    tags: frontmatter.tags,
  }, fileName)
}

function parseFrontmatter(text: string): Record<string, string> {
  const match = text.match(/^---\s*\r?\n([\s\S]*?)\r?\n---/)
  if (!match) return {}
  return Object.fromEntries(
    match[1]
      .split(/\r?\n/)
      .map((line) => line.match(/^([A-Za-z0-9_-]+):\s*(.+)$/))
      .filter((item): item is RegExpMatchArray => Boolean(item))
      .map((item) => [item[1], item[2].replace(/^['"]|['"]$/g, '').trim()]),
  )
}

function normalizeImportedSkill(candidate: unknown, fallbackId: string): ImportedSkillCatalogItem | null {
  if (!isRecord(candidate)) return null
  const name = stringField(candidate.name) || stringField(candidate.title) || stringField(candidate.id) || fallbackId
  const description = stringField(candidate.description) || stringField(candidate.desc) || stringField(candidate.summary) || '导入的本地 Skill'
  const tags = normalizeTags(candidate.tags)
  const category = normalizeSkillCategory(stringField(candidate.category), name, description, tags)

  return {
    id: normalizeSkillId(stringField(candidate.id) || name || fallbackId),
    name,
    description,
    category,
    source: 'imported',
    status: 'built-in',
    fit: normalizeSkillFit(stringField(candidate.fit)),
    installed: true,
    enabled_codex: true,
    executionReady: false,
    runtimeBinding: 'catalog_only',
    directory: stringField(candidate.directory) || null,
    tags,
    imported: true,
  }
}

function normalizeTags(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(item => String(item).trim()).filter(Boolean)
  }
  if (typeof value === 'string') {
    return value.split(/[,\s]+/).map(item => item.trim()).filter(Boolean)
  }
  return []
}

function normalizeSkillCategory(category: string, name: string, description: string, tags: string[]) {
  const allowed = new Set(['companion', 'development', 'frontend', 'research', 'automation', 'document', 'mcp', 'governance', 'media', 'authoring', 'general'])
  if (allowed.has(category)) return category
  const haystack = `${name} ${description} ${tags.join(' ')}`.toLowerCase()
  if (haystack.includes('mcp')) return 'mcp'
  if (/(ui|ux|frontend|visual|design|界面)/i.test(haystack)) return 'frontend'
  if (/(memory|dialogue|companion|voice|tts|asr|桌宠|语音|记忆)/i.test(haystack)) return 'companion'
  if (/(doc|pdf|sheet|ppt|document|文档|表格)/i.test(haystack)) return 'document'
  if (/(test|debug|review|code|ci|repo|测试|代码)/i.test(haystack)) return 'development'
  if (/(image|media|audio|video|图像|媒体)/i.test(haystack)) return 'media'
  if (/(research|search|docs|调研|搜索)/i.test(haystack)) return 'research'
  if (/(plan|quality|cleanup|治理)/i.test(haystack)) return 'governance'
  if (/(skill|author|prompt|编写)/i.test(haystack)) return 'authoring'
  if (/(task|file|automation|自动化|任务|文件)/i.test(haystack)) return 'automation'
  return 'general'
}

function normalizeSkillFit(value: string): SkillCatalogItem['fit'] {
  if (value === 'high' || value === 'medium' || value === 'low') return value
  return 'medium'
}

function normalizeSkillId(value: string) {
  const raw = value.trim() || 'skill'
  if (/^[a-z0-9_.:-]+$/i.test(raw)) return raw
  const slug = raw
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `imported.skill.${slug || hashString(raw)}`
}

function hashString(value: string) {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0
  }
  return Math.abs(hash).toString(36)
}

function stringField(value: unknown) {
  return typeof value === 'string' ? value.trim() : ''
}

async function mergeImportedSkills(skills: ImportedSkillCatalogItem[]) {
  importedSkillItems.value = mergeSkillItems(importedSkillItems.value, skills)
  await persistImportedSkills()
}

async function removeImportedSkill(skillId: string) {
  await deleteImportedSkills([skillId], { confirm: false, successMessage: '已删除 Skill' })
}

async function loadImportedSkills() {
  if (typeof window === 'undefined') return
  loadingImportedSkills.value = true
  const localItems = readImportedSkillsFromLocalStorage()
  importedSkillItems.value = localItems
  try {
    const snapshot = await systemClient.importedSkills()
    let backendItems = normalizeImportedSkillList(snapshot.items || [])
    if (localItems.length && (!hasMigratedImportedSkills() || hasDirtyImportedSkills())) {
      backendItems = await saveImportedSkillsToBackend(mergeSkillItems(backendItems, localItems))
    }
    importedSkillItems.value = backendItems
    importedSkillBackendReady.value = true
    importedSkillStorageError.value = ''
    markImportedSkillsMigrated()
    markImportedSkillsDirty(false)
    persistImportedSkillsToLocalStorage()
  } catch (error) {
    importedSkillBackendReady.value = false
    importedSkillStorageError.value = error instanceof Error ? error.message : '后端技能存储不可用'
    importedSkillItems.value = localItems
  } finally {
    loadingImportedSkills.value = false
  }
}

function readImportedSkillsFromLocalStorage() {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(IMPORTED_SKILLS_STORAGE_KEY)
    const payload = raw ? JSON.parse(raw) : []
    const items = Array.isArray(payload) ? payload : []
    return normalizeImportedSkillList(items)
  } catch {
    return []
  }
}

async function persistImportedSkills() {
  persistImportedSkillsToLocalStorage()
  if (!importedSkillBackendReady.value) {
    markImportedSkillsDirty(true)
    return
  }
  savingImportedSkills.value = true
  try {
    const savedItems = await saveImportedSkillsToBackend(importedSkillItems.value)
    importedSkillItems.value = savedItems
    importedSkillStorageError.value = ''
    markImportedSkillsDirty(false)
  } catch (error) {
    importedSkillBackendReady.value = false
    importedSkillStorageError.value = error instanceof Error ? error.message : '后端技能保存失败'
    markImportedSkillsDirty(true)
    ElMessage.warning('后端保存失败，已先保存在本地')
  } finally {
    savingImportedSkills.value = false
  }
}

function persistImportedSkillsToLocalStorage() {
  if (typeof window === 'undefined') return
  const payload = toPersistableSkills(importedSkillItems.value)
  window.localStorage.setItem(IMPORTED_SKILLS_STORAGE_KEY, JSON.stringify(payload))
}

async function saveImportedSkillsToBackend(skills: ImportedSkillCatalogItem[]) {
  const snapshot = await systemClient.saveImportedSkills(toPersistableSkills(skills))
  return normalizeImportedSkillList(snapshot.items || [])
}

function normalizeImportedSkillList(items: unknown[]) {
  return items
    .map((item, index) => normalizeImportedSkill(item, `stored-${index + 1}`))
    .filter((item): item is ImportedSkillCatalogItem => Boolean(item))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
}

function mergeSkillItems(baseItems: ImportedSkillCatalogItem[], nextItems: ImportedSkillCatalogItem[]) {
  const merged = new Map(baseItems.map(skill => [skill.id, skill]))
  for (const skill of nextItems) merged.set(skill.id, { ...skill, imported: true })
  return [...merged.values()].sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
}

function toPersistableSkills(skills: ImportedSkillCatalogItem[]) {
  return skills.map(({ imported: _imported, ...skill }) => ({
    ...skill,
    source: 'imported',
    status: 'built-in',
    installed: true,
    enabled_codex: true,
    executionReady: false,
    runtimeBinding: 'catalog_only',
  }))
}

function hasMigratedImportedSkills() {
  if (typeof window === 'undefined') return true
  return window.localStorage.getItem(IMPORTED_SKILLS_MIGRATION_KEY) === '1'
}

function markImportedSkillsMigrated() {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(IMPORTED_SKILLS_MIGRATION_KEY, '1')
}

function hasDirtyImportedSkills() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(IMPORTED_SKILLS_DIRTY_KEY) === '1'
}

function markImportedSkillsDirty(dirty: boolean) {
  if (typeof window === 'undefined') return
  if (dirty) {
    window.localStorage.setItem(IMPORTED_SKILLS_DIRTY_KEY, '1')
  } else {
    window.localStorage.removeItem(IMPORTED_SKILLS_DIRTY_KEY)
  }
}

function isSkillSelected(skillId: string) {
  return selectedSkillIds.value.has(skillId)
}

function toggleSkillSelection(skillId: string, selected: boolean) {
  if (!importedSkillItems.value.some(skill => skill.id === skillId)) return
  const next = new Set(selectedSkillIds.value)
  if (selected) {
    next.add(skillId)
  } else {
    next.delete(skillId)
  }
  selectedSkillIds.value = next
}

function toggleFilteredSkillSelection(selected: boolean) {
  const next = new Set(selectedSkillIds.value)
  for (const skillId of filteredImportedSkillIds.value) {
    if (selected) {
      next.add(skillId)
    } else {
      next.delete(skillId)
    }
  }
  selectedSkillIds.value = next
}

function selectFilteredImportedSkills() {
  if (!hasActiveSkillFilter.value) return
  toggleFilteredSkillSelection(true)
}

function clearSkillSelection() {
  selectedSkillIds.value = new Set()
}

async function deleteSelectedSkills() {
  await deleteImportedSkills([...selectedSkillIds.value], {
    confirm: true,
    title: '删除选中 Skills',
    successMessage: '已删除选中的 Skill',
  })
}

async function deleteFilteredImportedSkills() {
  if (!canDeleteFilteredSkills.value) return
  await deleteImportedSkills(filteredImportedSkillIds.value, {
    confirm: true,
    title: '删除筛选结果',
    successMessage: '已删除当前筛选结果中的 Skill',
  })
}

async function deleteImportedSkills(skillIds: string[], options: { confirm?: boolean; title?: string; successMessage?: string } = {}) {
  const uniqueIds = [...new Set(skillIds.filter(Boolean))]
  if (!uniqueIds.length) return
  if (options.confirm !== false) {
    try {
      await ElMessageBox.confirm(
        `将直接删除 ${uniqueIds.length} 个自定义 Skill，内置技能不会受影响。`,
        options.title || '删除 Skills',
        {
          confirmButtonText: '删除',
          cancelButtonText: '取消',
          type: 'warning',
        },
      )
    } catch {
      return
    }
  }

  const nextItems = importedSkillItems.value.filter(skill => !uniqueIds.includes(skill.id))
  importedSkillItems.value = nextItems
  pruneSelectedSkillIds()
  persistImportedSkillsToLocalStorage()
  if (!importedSkillBackendReady.value) markImportedSkillsDirty(true)

  if (importedSkillBackendReady.value) {
    savingImportedSkills.value = true
    try {
      const snapshot = await systemClient.removeImportedSkills(uniqueIds)
      importedSkillItems.value = normalizeImportedSkillList(snapshot.items || [])
      persistImportedSkillsToLocalStorage()
      importedSkillStorageError.value = ''
      markImportedSkillsDirty(false)
    } catch {
      try {
        const savedItems = await saveImportedSkillsToBackend(nextItems)
        importedSkillItems.value = savedItems
        persistImportedSkillsToLocalStorage()
        importedSkillStorageError.value = ''
        markImportedSkillsDirty(false)
      } catch (error) {
        importedSkillBackendReady.value = false
        importedSkillStorageError.value = error instanceof Error ? error.message : '后端技能删除失败'
        markImportedSkillsDirty(true)
        ElMessage.warning('后端删除失败，已先更新本地列表')
      }
    } finally {
      savingImportedSkills.value = false
      pruneSelectedSkillIds()
    }
  }

  ElMessage.success(options.successMessage || '已删除 Skill')
}

function pruneSelectedSkillIds() {
  const validIds = new Set(importedSkillItems.value.map(skill => skill.id))
  const next = new Set([...selectedSkillIds.value].filter(skillId => validIds.has(skillId)))
  if (next.size !== selectedSkillIds.value.size) selectedSkillIds.value = next
}

const pushLog = (text: string) => {
  const now = new Date()
  logs.value.unshift({
    time: now.toLocaleTimeString(),
    text,
    source: '本地',
    status: 'ok',
    sortKey: now.toISOString(),
  })
  if (logs.value.length > 20) logs.value.pop()
}

function formatTraceTime(timestamp?: string) {
  if (!timestamp) return '-'
  const parts = timestamp.split('T')
  if (parts.length > 1) return parts[1].replace('Z', '').slice(0, 8)
  return timestamp
}

function toolLogTagType(status?: string | null): TagType {
  const raw = String(status || '').toLowerCase()
  if (raw.includes('error') || raw.includes('fail')) return 'danger'
  if (raw.includes('skip') || raw.includes('partial')) return 'warning'
  if (raw.includes('completed') && !raw.includes('verified')) return 'info'
  if (raw === 'ok' || raw.includes('success') || raw.includes('complete')) return 'success'
  return 'info'
}

function toolLogFromStep(step: StepExecutionRecord): ToolLogItem {
  const capability = step.capability_id || step.tool || step.capability_kind || step.kind
  const result = step.error ? `失败: ${step.error}` : (step.title || step.reply_preview || step.status || '已记录')
  return {
    time: formatTraceTime(step.timestamp),
    text: `${capability} · ${result}`,
    source: 'trace',
    status: step.status,
    sortKey: step.timestamp || '',
    actionStatus: projectToolActionStatus(step.status, undefined),
    evidence: toolEvidenceFromRecord(step),
  }
}

function toolLogFromRuntimeLoop(loop: RuntimeLoopRecord): ToolLogItem | null {
  const data = isRecord(loop.data) ? loop.data : null
  const capability = data && typeof data.capability_id === 'string'
    ? data.capability_id
    : data && typeof data.capability_kind === 'string'
      ? data.capability_kind
      : null
  if (!capability && loop.stage !== 'tool_call') return null
  return {
    time: formatTraceTime(loop.timestamp),
    text: `${capability || loop.stage} · ${loop.summary || loop.status}`,
    source: 'runtime',
    status: loop.status,
    sortKey: loop.timestamp || '',
    actionStatus: projectToolActionStatus(loop.status, data?.verificationStatus ?? data?.verification_status),
    evidence: toolEvidenceFromRecord(data || {}),
  }
}

async function loadPlugins() {
  const requestId = ++pluginLoadSequence
  loadingPlugins.value = true
  try {
    const payload = await pluginClient.list()
    if (requestId !== pluginLoadSequence) return
    pluginTools.value = payload.toolCapabilities ?? []
    pluginStates.value = payload.pluginStates ?? []
    pluginLoadFailures.value = payload.loadFailures ?? []
  } catch (error) {
    if (requestId !== pluginLoadSequence) return
    const message = error instanceof Error ? error.message : '未知错误'
    pushLog(`插件工具加载失败: ${message}`)
  } finally {
    if (requestId === pluginLoadSequence) loadingPlugins.value = false
  }
}

async function loadCapabilities() {
  const requestId = ++capabilityLoadSequence
  loadingCapabilities.value = true
  capabilityLoadError.value = ''
  try {
    const snapshot = await systemClient.capabilities()
    if (requestId !== capabilityLoadSequence) return
    capabilities.value = snapshot.capabilities ?? []
    if (!capabilities.value.some(item => item.id === selectedCapabilityId.value) && capabilities.value[0]) {
      selectedCapabilityId.value = capabilities.value[0].id
    }
  } catch (error) {
    if (requestId !== capabilityLoadSequence) return
    const message = error instanceof Error ? error.message : '未知错误'
    capabilityLoadError.value = `能力快照加载失败: ${message}`
  } finally {
    if (requestId === capabilityLoadSequence) loadingCapabilities.value = false
  }
}

async function loadToolTrace() {
  const requestId = ++toolTraceLoadSequence
  try {
    const snapshot = await systemClient.agentTrace()
    if (requestId !== toolTraceLoadSequence) return
    agentTrace.value = snapshot
  } catch (error) {
    if (requestId !== toolTraceLoadSequence) return
    const message = error instanceof Error ? error.message : '未知错误'
    pushLog(`后端工具记录加载失败: ${message}`)
  }
}

async function loadMcpServers() {
  const requestId = ++mcpLoadSequence
  loadingMcp.value = true
  mcpLoadError.value = ''
  try {
    const snapshot = await systemClient.mcp()
    if (requestId !== mcpLoadSequence) return
    mcpSnapshot.value = snapshot
  } catch (error) {
    if (requestId !== mcpLoadSequence) return
    const message = error instanceof Error ? error.message : '未知错误'
    mcpLoadError.value = `MCP 服务加载失败: ${message}`
  } finally {
    if (requestId === mcpLoadSequence) loadingMcp.value = false
  }
}

async function loadStream() {
  loadingStream.value = true
  streamLoadError.value = ''
  try {
    streamSnapshot.value = await systemClient.stream()
    obsEndpointDraft.value = streamSnapshot.value.adapter?.endpoint || ''
    obsAllowRemote.value = streamSnapshot.value.adapter?.remoteAllowed === true
    streamTakeoverEnabled.value = streamSnapshot.value.policy?.humanTakeover !== false
    const moderation = streamSnapshot.value.policy?.moderation
    streamModerationEnabled.value = moderation?.enabled !== false
    streamModerationTermsInput.value = (moderation?.blockedTerms || []).join(', ')
    streamModerationSlowModeSeconds.value = Number(moderation?.slowModeSeconds || 0)
    streamModerationMaxMessagesPerMinute.value = Number(moderation?.maxMessagesPerMinute || 30)
    twitchSubscriptionDraft.value = [...(streamSnapshot.value.platforms?.twitch?.subscriptionPlan?.desired || [])]
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    streamLoadError.value = `直播能力加载失败: ${message}`
  } finally {
    loadingStream.value = false
  }
}

async function loadTwitchConfigStatus() {
  try {
    const result = await systemClient.twitchConfig()
    twitchConfigStatus.value = result
    twitchSubscriptionProviderDraft.value = result.subscriptionProvider === 'twitch-helix'
      ? 'helix'
      : result.subscriptionProvider || 'none'
    if (!result.secureStorageAvailable) {
      ElMessage.warning('系统安全凭据存储不可用，Twitch 配置已禁用')
    }
  } catch {
    twitchConfigStatus.value = null
  }
}

const twitchConfigStatusText = computed(() => {
  const status = twitchConfigStatus.value
  if (!status) return '读取配置状态失败'
  if (!status.secureStorageAvailable) return '系统安全存储不可用'
  const configured = Object.entries(status.configured).filter(([, value]) => value).map(([key]) => key)
  return configured.length ? `已安全保存 ${configured.length} 项；输入框不会回显凭据` : '未配置；凭据仅保存到系统安全存储'
})

async function probeTwitchConfig() {
  probingTwitchConfig.value = true
  try {
    const result = await systemClient.probeTwitch()
    if (result.ok !== true) {
      ElMessage.warning(String(result.error || 'Twitch 只读检查未通过'))
      return
    }
    const configured = result.configured as Record<string, unknown> | undefined
    const ready = configured && Object.values(configured).filter(Boolean).length
    ElMessage.info(`Twitch 只读检查完成：${ready || 0} 项能力就绪；未建立连接或发送消息`)
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`Twitch 只读检查失败: ${message}`)
  } finally {
    probingTwitchConfig.value = false
  }
}

function twitchConfigPayload() {
  const fields: Record<string, string> = {
    clientId: twitchClientIdDraft.value,
    eventsubSecret: twitchEventsubSecretDraft.value,
    eventsubToken: twitchEventsubTokenDraft.value,
    chatToken: twitchChatTokenDraft.value,
    broadcasterId: twitchBroadcasterIdDraft.value,
    senderId: twitchSenderIdDraft.value,
    moderatorId: twitchModeratorIdDraft.value,
    channel: twitchChannelDraft.value,
    username: twitchUsernameDraft.value,
    eventsubCallbackUrl: twitchEventsubCallbackUrlDraft.value,
    subscriptionProvider: twitchSubscriptionProviderDraft.value,
  }
  return Object.fromEntries(Object.entries(fields).filter(([, value]) => value.trim()))
}

async function saveTwitchConfig() {
  savingTwitchConfig.value = true
  try {
    const result = await systemClient.updateTwitchConfig(twitchConfigPayload())
    if (result.ok !== true) {
      ElMessage.warning(String(result.error || 'Twitch 配置未保存'))
      return
    }
    twitchEventsubSecretDraft.value = ''
    twitchEventsubTokenDraft.value = ''
    twitchChatTokenDraft.value = ''
    twitchClientIdDraft.value = ''
    twitchBroadcasterIdDraft.value = ''
    twitchSenderIdDraft.value = ''
    twitchModeratorIdDraft.value = ''
    twitchChannelDraft.value = ''
    twitchUsernameDraft.value = ''
    twitchEventsubCallbackUrlDraft.value = ''
    await Promise.all([loadStream(), loadTwitchConfigStatus()])
    const probe = await systemClient.probeTwitch()
    const ready = probe.configured && typeof probe.configured === 'object'
      ? Object.values(probe.configured as Record<string, unknown>).filter(Boolean).length
      : 0
    ElMessage.success(`Twitch 凭据已安全保存并完成内存重配置；只读检查就绪 ${ready} 项，不会自动连接或发言`)
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`Twitch 配置失败: ${message}`)
  } finally {
    savingTwitchConfig.value = false
  }
}

async function clearTwitchConfig() {
  savingTwitchConfig.value = true
  try {
    const fields = ['ClientId', 'EventsubSecret', 'EventsubToken', 'ChatToken', 'BroadcasterId', 'SenderId', 'ModeratorId', 'Channel', 'Username', 'EventsubCallbackUrl', 'SubscriptionProvider']
    const result = await systemClient.updateTwitchConfig(Object.fromEntries(fields.map(field => [`clear${field}`, true])))
    if (result.ok !== true) {
      ElMessage.warning(String(result.error || 'Twitch 凭据未清除'))
      return
    }
    await Promise.all([loadStream(), loadTwitchConfigStatus()])
    ElMessage.success('Twitch 凭据已清除，IRC 自动重连意图已停止')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`清除 Twitch 凭据失败: ${message}`)
  } finally {
    savingTwitchConfig.value = false
  }
}

async function configureObs() {
  configuringObs.value = true
  streamLoadError.value = ''
  try {
    await systemClient.configureObs({
      endpoint: obsEndpointDraft.value.trim(),
      ...(obsPasswordDraft.value ? { password: obsPasswordDraft.value } : {}),
      allowRemote: obsAllowRemote.value,
    })
    obsPasswordDraft.value = ''
    await loadStream()
    const probe = await systemClient.probeStream()
    streamProbe.value = probe.probe ?? probe
    if (probe.status === 'reachable') ElMessage.success('OBS 已配置并完成只读探测')
    else ElMessage.warning(`OBS 配置已保存，但探测状态为 ${String(probe.status || 'unknown')}`)
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`OBS 配置失败: ${message}`)
  } finally {
    configuringObs.value = false
  }
}

async function clearObsPassword() {
  configuringObs.value = true
  try {
    await systemClient.configureObs({
      endpoint: obsEndpointDraft.value.trim(),
      allowRemote: obsAllowRemote.value,
      clearPassword: true,
    })
    obsPasswordDraft.value = ''
    await loadStream()
    ElMessage.success('OBS 密码已从当前运行时清除')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`OBS 密码清除失败: ${message}`)
  } finally {
    configuringObs.value = false
  }
}

const streamModerationSummary = computed(() => {
  if (!streamModerationEnabled.value) return '已关闭'
  const terms = streamModerationTermsInput.value.split(',').map(item => item.trim()).filter(Boolean).length
  const slow = streamModerationSlowModeSeconds.value > 0 ? `慢 ${streamModerationSlowModeSeconds.value}s` : '无慢'
  return `${terms} 词 · ${slow} · ${streamModerationMaxMessagesPerMinute.value}/分`
})

async function saveStreamModeration() {
  loadingStreamModeration.value = true
  try {
    const blockedTerms = streamModerationTermsInput.value
      .split(',')
      .map(item => item.trim())
      .filter(Boolean)
    const result = await systemClient.updateStreamModeration({
      enabled: streamModerationEnabled.value,
      blockedTerms,
      slowModeSeconds: streamModerationSlowModeSeconds.value,
      maxMessagesPerMinute: streamModerationMaxMessagesPerMinute.value,
    })
    if (!result.ok) {
      ElMessage.warning('聊天治理策略未更新')
      return
    }
    await loadStream()
    ElMessage.success('聊天治理策略已保存；出站消息仍需人工确认')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`聊天治理策略更新失败: ${message}`)
  } finally {
    loadingStreamModeration.value = false
  }
}

async function loadStreamEvents() {
  loadingStreamEvents.value = true
  try {
    const result = await systemClient.streamEvents(20)
    streamEvents.value = result.events ?? result.items ?? []
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.warning(`本地直播事件加载失败: ${message}`)
  } finally {
    loadingStreamEvents.value = false
  }
}

async function loadStreamDrafts() {
  loadingStreamDrafts.value = true
  try {
    const result: StreamDraftsSnapshot = await systemClient.streamDrafts(20)
    streamDrafts.value = result.drafts ?? []
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.warning(`回复草稿加载失败: ${message}`)
  } finally {
    loadingStreamDrafts.value = false
  }
}

async function loadStreamDraftConsumer() {
  try {
    streamDraftConsumer.value = await systemClient.streamDraftConsumer()
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.warning(`自动草稿状态加载失败: ${message}`)
  }
}

async function toggleStreamDraftConsumer() {
  loadingStreamDraftConsumer.value = true
  try {
    streamDraftConsumer.value = await systemClient.setStreamDraftConsumer(!streamDraftConsumer.value?.enabled)
    ElMessage.success(streamDraftConsumer.value.enabled ? '已启用自动本地草稿，未发送消息' : '已关闭自动本地草稿')
    await Promise.all([loadStreamEvents(), loadStreamDrafts()])
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`自动草稿状态更新失败: ${message}`)
  } finally {
    loadingStreamDraftConsumer.value = false
  }
}

async function consumeStreamDrafts() {
  consumingStreamDrafts.value = true
  try {
    const result = await systemClient.consumeStreamDrafts({ limit: 3 })
    if (!result.ok && !(result.created ?? 0)) {
      ElMessage.warning(result.errors?.[0]?.error || '未处理直播事件')
      return
    }
    await Promise.all([loadStreamEvents(), loadStreamDrafts()])
    ElMessage.success(`已尝试 ${result.attempted ?? 0} 条，生成 ${result.created ?? 0} 条本地草稿；未发送`)
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`批量生成草稿失败: ${message}`)
  } finally {
    consumingStreamDrafts.value = false
  }
}

async function loadStreamActions() {
  loadingStreamActions.value = true
  try {
    const result: StreamActionsSnapshot = await systemClient.streamActions(50)
    streamActions.value = result.actions ?? []
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.warning(`直播动作审计加载失败: ${message}`)
  } finally {
    loadingStreamActions.value = false
  }
}

async function reconfigureTwitch() {
  reconfiguringTwitch.value = true
  try {
    const result = await systemClient.reconfigureTwitch()
    if (result.ok !== true) {
      ElMessage.warning(String(result.error || 'Twitch 状态未更新'))
      return
    }
    await loadStream()
    ElMessage.success('已清除本地撤销标记；仍需在 Twitch 侧确认订阅状态')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`Twitch 状态更新失败: ${message}`)
  } finally {
    reconfiguringTwitch.value = false
  }
}

async function saveTwitchSubscriptions() {
  loadingTwitchSubscriptions.value = true
  try {
    const result = await systemClient.configureTwitchSubscriptions(twitchSubscriptionDraft.value)
    if (result.ok !== true) {
      ElMessage.warning(String(result.error || 'EventSub 订阅计划未保存'))
      return
    }
    await loadStream()
    ElMessage.success('已保存本地 EventSub 订阅计划，未连接 Twitch 创建订阅')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`EventSub 订阅计划保存失败: ${message}`)
  } finally {
    loadingTwitchSubscriptions.value = false
  }
}

const twitchIrcStatusLabel = computed(() => {
  const connection = streamSnapshot.value?.platforms?.twitch?.ircConnection
  if (!connection) return '未启用'
  if (connection.status === 'connected') return '已连接'
  if (connection.status === 'connecting') return '连接中'
  if (connection.status === 'backoff') {
    const seconds = connection.nextRetryInSeconds
    return seconds == null ? '等待重连' : `等待重连 ${Math.ceil(seconds)} 秒`
  }
  if (connection.status === 'unconfigured') return '未配置'
  if (connection.status === 'revoked') return '已撤销'
  return '已断开'
})

async function connectTwitch() {
  connectingTwitch.value = true
  try {
    const result = await systemClient.connectTwitch()
    await loadStream()
    if (result.ok) ElMessage.success('已请求 Twitch IRC 连接')
    else ElMessage.warning('Twitch IRC 尚未连接，请检查配置或稍后重试')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`Twitch IRC 连接失败: ${message}`)
  } finally {
    connectingTwitch.value = false
  }
}

async function disconnectTwitch() {
  disconnectingTwitch.value = true
  try {
    await systemClient.disconnectTwitch()
    await loadStream()
    ElMessage.success('已断开 Twitch IRC，停止自动重连意图')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`Twitch IRC 断开失败: ${message}`)
  } finally {
    disconnectingTwitch.value = false
  }
}

function streamEventId(event: StreamLocalEvent) {
  return String(event.eventId || event.id || '').trim()
}

async function generateStreamDraft(event: StreamLocalEvent) {
  const eventId = streamEventId(event)
  if (!eventId) {
    ElMessage.warning('该事件缺少可用标识，无法生成草稿')
    return
  }
  generatingStreamDraft.value = eventId
  try {
    const result = await systemClient.generateStreamDraft({ eventId })
    if (!result.ok && !result.draft) {
      ElMessage.warning(result.error || '回复草稿生成失败')
      return
    }
    if (result.draft) {
      streamDrafts.value = [result.draft, ...streamDrafts.value.filter(item => item.requestId !== result.draft?.requestId)].slice(0, 20)
    }
    ElMessage.success(result.draft?.status === 'generated' ? '已生成本地回复草稿，未发送' : '草稿生成失败，未发送任何消息')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`回复草稿生成失败: ${message}`)
  } finally {
    generatingStreamDraft.value = ''
  }
}

async function retryStreamDraft(draft: StreamReplyDraft) {
  const eventId = String(draft.eventId || '').trim()
  if (!eventId) {
    ElMessage.warning('该草稿缺少事件标识，无法重新生成')
    return
  }
  generatingStreamDraft.value = eventId
  try {
    const result = await systemClient.generateStreamDraft({ eventId, retry: true })
    if (!result.ok && !result.draft) {
      ElMessage.warning(result.error || '草稿重新生成失败')
      return
    }
    if (result.draft) {
      streamDrafts.value = [result.draft, ...streamDrafts.value.filter(item => item.requestId !== result.draft?.requestId)].slice(0, 20)
    }
    ElMessage.success(result.draft?.status === 'generated' ? '已重新生成本地回复草稿，未发送' : '草稿重新生成失败，未发送任何消息')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`草稿重新生成失败: ${message}`)
  } finally {
    generatingStreamDraft.value = ''
  }
}

function streamDraftDeliveryLabel(draft: StreamReplyDraft) {
  if (draft.sendStatus === 'known_success' || draft.sent) return '已确认发送'
  if (draft.sendStatus === 'unknown_effect') return '发送效果未知，需人工确认'
  if (draft.sendStatus === 'failed') return '发送失败，可重新预览'
  return draft.status === 'generated' ? '仅本地草稿，未发送' : '生成失败'
}

async function toggleStreamTakeover() {
  loadingStreamTakeover.value = true
  try {
    const result = await systemClient.setStreamTakeover(!streamTakeoverEnabled.value)
    if (!result.ok) {
      ElMessage.warning(result.error || '本地接管策略未更新')
      return
    }
    streamTakeoverEnabled.value = result.enabled ?? !streamTakeoverEnabled.value
    if (result.state && streamSnapshot.value) streamSnapshot.value = { ...streamSnapshot.value, state: result.state, policy: result.policy ?? streamSnapshot.value.policy }
    ElMessage.success(streamTakeoverEnabled.value ? '已启用本地人工接管，未发送平台指令' : '已关闭本地人工接管')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`本地接管策略更新失败: ${message}`)
  } finally {
    loadingStreamTakeover.value = false
  }
}

function formatStreamEventTime(value: number | string | null | undefined) {
  if (value == null || value === '') return '时间未知'
  const date = new Date(typeof value === 'number' ? value : String(value))
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString()
}

function formatStreamActionStatus(status: string | undefined) {
  const labels: Record<string, string> = {
    sending: '发送中',
    known_success: '已确认成功',
    unknown_effect: '效果未知',
    failed: '失败',
  }
  return labels[status || ''] || status || '未知'
}

async function probeStream() {
  loadingStreamProbe.value = true
  streamLoadError.value = ''
  try {
    const result = await systemClient.probeStream()
    streamProbe.value = result.probe ?? null
    if (result.state && streamSnapshot.value) streamSnapshot.value = { ...streamSnapshot.value, state: result.state }
    await loadStream()
    if (!result.ok) ElMessage.warning(result.error || '适配器探测未通过')
    else ElMessage.success('适配器只读探测完成，未执行直播动作')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`适配器探测失败: ${message}`)
  } finally {
    loadingStreamProbe.value = false
  }
}

async function loadObsProfiles() {
  loadingObsProfiles.value = true
  streamLoadError.value = ''
  try {
    const result = await systemClient.obsProfiles()
    obsProfiles.value = (result.profiles || []).filter((profile) => typeof profile?.profileName === 'string' && profile.profileName.trim())
    obsCurrentProfile.value = typeof result.currentProfileName === 'string' ? result.currentProfileName : ''
    if (!obsProfileDraft.value && obsCurrentProfile.value) obsProfileDraft.value = obsCurrentProfile.value
    if (result.ok) ElMessage.success(`已读取 ${obsProfiles.value.length} 个 OBS 配置档`)
    else ElMessage.warning(result.error || 'OBS 配置档读取失败')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`OBS 配置档读取失败: ${message}`)
  } finally {
    loadingObsProfiles.value = false
  }
}

async function previewObsProfileSwitch() {
  const profileName = obsProfileDraft.value.trim()
  if (!profileName) return
  await previewStream('stream.profile_switch', { profileName })
}

async function previewStream(kind: string, params: Record<string, unknown> = {}, loadingKey = kind) {
  previewingStreamCapability.value = loadingKey
  try {
    const result = await systemClient.previewStream(kind, params)
    if (result.preview) {
      streamSnapshot.value = { ...(streamSnapshot.value || { state: 'disconnected' }), state: 'preview', preview: result.preview }
      streamExecution.value = null
      streamPendingExecution.value = {
        requestId: String(result.preview.requestId || ''),
        action: String(result.preview.action || result.preview.kind || kind),
        params: result.preview.params || {},
      }
    }
    if (!result.ok) ElMessage.warning(result.error || '直播动作暂不可预览')
    else ElMessage.success('已生成直播动作预览，未执行真实操作')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    ElMessage.error(`直播动作预览失败: ${message}`)
  } finally {
    previewingStreamCapability.value = ''
  }
}

async function previewDraftSend(draft: StreamReplyDraft) {
  if (!draft.reply) return
  await previewStream('stream.chat_send', { text: draft.reply, draftId: draft.draftId }, `stream.chat_send:${draft.draftId}`)
}

function streamRiskLabel(risk: string | undefined) {
  const labels: Record<string, string> = { safe: '安全', low: '低风险', medium: '中风险', high: '高风险', critical: '关键风险' }
  return labels[risk || ''] || risk || '未声明风险'
}

async function confirmStreamExecution() {
  const pending = streamPendingExecution.value
  if (!pending?.requestId) {
    ElMessage.warning('预览已失效，请重新生成预览')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认执行“${pending.action}”？风险：${streamRiskLabel(streamSnapshot.value?.preview?.riskLevel)}。`,
      '确认直播动作',
      { type: 'warning', confirmButtonText: '确认执行', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  loadingStreamExecute.value = true
  try {
    const result = await systemClient.executeStream({ ...pending, confirmed: true })
    streamExecution.value = result
    if (result.state && streamSnapshot.value) streamSnapshot.value = { ...streamSnapshot.value, state: result.state }
    await Promise.all([loadStream(), loadStreamEvents(), loadStreamActions(), loadStreamDraftConsumer()])
    if (result.ok) ElMessage.success(`执行完成：${result.verificationStatus || result.outcome || '已提交'}`)
    else ElMessage.error(result.message || result.error || '直播动作执行失败，可手动重试')
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    streamExecution.value = { ok: false, outcome: 'failed', message }
    // Provider state can change while the confirmation dialog is open (for
    // example, Twitch EventSub may be revoked). Refresh the read-only
    // snapshot so stale capabilities or previews cannot remain actionable.
    try {
      await loadStream()
    } catch {
      // Keep the original execution error visible when the status refresh is
      // unavailable; the next explicit refresh can reconcile the snapshot.
    }
    ElMessage.error(`直播动作执行失败: ${message}`)
  } finally {
    loadingStreamExecute.value = false
  }
}

function formatStreamParams(params: Record<string, unknown> | undefined) {
  if (!params || !Object.keys(params).length) return '无'
  return Object.entries(params).slice(0, 6).map(([key, value]) => `${key}=${String(value)}`).join('，')
}

async function refreshSnapshots() {
  await Promise.all([loadPlugins(), loadCapabilities(), loadToolTrace(), loadMcpServers(), loadStream(), loadTwitchConfigStatus(), loadStreamEvents(), loadStreamDrafts(), loadStreamActions(), loadStreamDraftConsumer()])
}

watch(importedSkillItems, pruneSelectedSkillIds)

onMounted(async () => {
  await loadImportedSkills()
  await refreshSnapshots()
})
</script>

<style scoped>
.tool-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tool-view-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--yui-border);
}

.tool-view-button {
  flex: 0 0 auto;
  min-height: 34px;
  padding: 0 13px;
  border: 1px solid transparent;
  border-radius: 7px;
  color: var(--yui-text);
  background: transparent;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}

.tool-view-button:hover,
.tool-view-button:focus-visible {
  border-color: var(--yui-border-strong);
  background: var(--yui-surface-muted);
  outline: none;
}

.tool-view-button.active {
  border-color: color-mix(in srgb, var(--yui-accent) 34%, var(--yui-border));
  color: var(--yui-accent-strong, var(--yui-accent));
  background: var(--yui-accent-soft);
}

.tool-view-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-card {
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
}

.detail-grid span,
.risk-card span,
.section-label {
  display: block;
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 700;
}

.tone-blue strong { color: #2563eb; }
.tone-amber strong { color: #d97706; }
.tone-rose strong { color: #e11d48; }
.tone-emerald strong { color: #059669; }

.stream-summary,
.skill-catalog,
.plugin-panel,
.log-panel {
  padding: 16px;
}

.stream-status-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin: 12px 0;
  color: var(--yui-muted);
  font-size: 12px;
}

.stream-safety-controls,
.stream-events-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
}

.stream-safety-controls > div {
  display: grid;
  gap: 3px;
}

.stream-safety-controls small {
  color: var(--yui-muted);
  font-size: 11px;
}

.stream-subscription-controls {
  align-items: flex-start;
  flex-wrap: wrap;
}

.stream-subscription-options {
  display: flex;
  flex: 1 1 320px;
  flex-wrap: wrap;
  gap: 4px 12px;
}

.stream-moderation-controls {
  align-items: flex-start;
  flex-wrap: wrap;
}

.stream-moderation-fields {
  display: grid !important;
  grid-template-columns: minmax(180px, 1fr) 120px 130px;
  flex: 1 1 100%;
  gap: 8px;
  width: 100%;
}

.stream-obs-config {
  align-items: flex-start;
  flex-wrap: wrap;
}

.stream-twitch-config {
  align-items: flex-start;
  flex-wrap: wrap;
}

.stream-twitch-fields {
  display: grid !important;
  grid-template-columns: repeat(3, minmax(150px, 1fr));
  align-items: center;
  flex: 1 1 620px;
  gap: 8px;
  min-width: 0;
}

.stream-twitch-actions {
  display: flex !important;
  align-items: center;
  gap: 8px;
}

.stream-obs-fields {
  display: grid;
  grid-template-columns: minmax(190px, 1fr) minmax(190px, 1fr) auto auto;
  align-items: center;
  flex: 1 1 520px;
  gap: 8px;
  min-width: 0;
}

.stream-profile-controls {
  align-items: flex-start;
  flex-wrap: wrap;
}

.stream-profile-fields {
  display: grid !important;
  grid-template-columns: minmax(180px, 1fr) auto auto;
  align-items: center;
  flex: 1 1 520px;
  gap: 8px;
  min-width: 0;
}

@media (max-width: 980px) {
  .stream-moderation-fields {
    grid-template-columns: minmax(180px, 1fr) repeat(2, minmax(110px, 1fr));
  }

  .stream-twitch-fields {
    grid-template-columns: repeat(2, minmax(150px, 1fr));
  }
}

@media (max-width: 760px) {
  .stream-moderation-fields,
  .stream-obs-fields,
  .stream-profile-fields,
  .stream-twitch-fields {
    grid-template-columns: 1fr;
  }
}

.stream-events-heading {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--yui-border);
}

.stream-actions-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--yui-border);
}

.stream-action-list {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.stream-action-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 3px 10px;
  padding: 8px 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-control);
  background: var(--yui-surface-muted);
}

.stream-action-row > div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.stream-action-row small {
  color: var(--yui-muted);
  font-size: 10px;
  overflow-wrap: anywhere;
}

.stream-action-status {
  align-self: start;
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.stream-action-status.status-known_success { color: #047857; }
.stream-action-status.status-unknown_effect { color: #b45309; }
.stream-action-status.status-failed { color: #be123c; }
.stream-action-status.status-sending { color: #2563eb; }

.stream-action-row > small {
  grid-column: 1 / -1;
}

.stream-event-list {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.stream-event-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 3px 10px;
  padding: 8px 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-control);
}

.stream-event-row > span,
.stream-event-row small {
  color: var(--yui-muted);
  font-size: 10px;
}

.stream-event-row small {
  grid-column: 1 / -1;
}

.stream-event-actions {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 8px;
}

.stream-draft-status {
  color: var(--yui-muted);
  font-size: 10px;
}

.stream-drafts-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--yui-border);
}

.stream-draft-list {
  display: grid;
  gap: 8px;
  margin-top: 8px;
}

.stream-draft-row {
  display: grid;
  gap: 5px;
  padding: 10px 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-control);
}

.stream-draft-row > div {
  display: grid;
  gap: 3px;
}

.stream-draft-row small {
  color: var(--yui-muted);
  font-size: 10px;
}

.stream-draft-row p {
  margin: 0;
  white-space: pre-wrap;
}

.stream-draft-error {
  color: var(--el-color-danger);
}

.stream-capability-list {
  display: grid;
  gap: 8px;
}

.stream-capability-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-control);
  background: var(--yui-surface);
}

.stream-capability-row > div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.stream-capability-row small,
.stream-preview-note span {
  color: var(--yui-muted);
  font-size: 11px;
}

.stream-preview-note {
  display: grid;
  gap: 4px;
  margin-top: 12px;
  padding: 10px 12px;
  border-left: 3px solid var(--el-color-primary);
  background: var(--yui-surface-sunken);
}

.stream-probe-note {
  margin-top: 10px;
  color: var(--yui-muted);
  font-size: 11px;
}

.stream-execution-note {
  display: grid;
  gap: 4px;
  margin-top: 10px;
  padding: 10px 12px;
  border-left: 3px solid var(--el-color-success);
  background: var(--yui-success-soft);
  color: var(--yui-text);
  font-size: 11px;
}

.stream-execution-note.failed {
  border-left-color: var(--el-color-danger);
  background: var(--yui-danger-soft);
}

.tool-health {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  padding: 10px;
}

.health-item {
  min-width: 0;
  border: 1px solid transparent;
  border-radius: 10px;
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  cursor: pointer;
  padding: 10px 12px;
  text-align: left;
  transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}

.health-item:hover,
.health-item:focus-visible,
.health-item.active {
  border-color: var(--yui-border-strong);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-hover);
  outline: none;
}

.health-item span,
.health-item small {
  display: block;
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 700;
}

.health-item strong {
  display: block;
  margin: 5px 0;
  color: var(--yui-text);
  font-size: 22px;
  line-height: 1;
  font-weight: 900;
}

.health-item.tone-blue strong { color: #2563eb; }
.health-item.tone-amber strong { color: #d97706; }
.health-item.tone-rose strong { color: #e11d48; }
.health-item.tone-emerald strong { color: #059669; }

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.section-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.file-input {
  display: none;
}

.section-heading.compact {
  margin-bottom: 10px;
}

.section-heading h3 {
  margin: 0;
  color: var(--yui-text);
  font-size: 16px;
  font-weight: 850;
}

.section-heading p,
.capability-row p,
.detail-heading p,
.skill-card p,
.mini-item span {
  margin: 5px 0 0;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.55;
}

.capability-row:hover,
.capability-row.active,
.skill-card:hover {
  transform: translateY(-1px);
  border-color: var(--yui-border-strong);
  box-shadow: var(--yui-shadow-hover);
}

.skill-card strong,
.mini-item strong {
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 850;
}

.capability-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  min-height: 620px;
  overflow: hidden;
}

.capability-list-pane {
  min-width: 0;
  padding: 16px;
  border-right: 1px solid var(--yui-border);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.toolbar-select {
  width: 142px;
  flex-shrink: 0;
}

.skill-toolbar .toolbar-select {
  width: 132px;
}

.panel-alert {
  margin-bottom: 12px;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.capability-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 458px;
  overflow-y: auto;
  padding-right: 4px;
}

.capability-row {
  width: 100%;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  cursor: pointer;
  padding: 13px;
  text-align: left;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.row-title,
.row-meta,
.skill-summary,
.skill-meta,
.skill-actions,
.token-list {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.row-title strong {
  color: var(--yui-text);
  font-size: 14px;
  font-weight: 850;
}

.row-meta {
  margin-top: 10px;
}

.row-meta span,
.skill-meta span {
  border-radius: 999px;
  background: var(--yui-surface-muted);
  color: #64748b;
  padding: 3px 8px;
  font-size: 11px;
}

.detail-pane {
  min-width: 0;
  padding: 16px;
  background: var(--yui-surface-muted);
}

.detail-heading {
  margin-bottom: 14px;
}

.detail-heading h3 {
  margin: 9px 0 0;
  color: var(--yui-text);
  font-size: 20px;
  font-weight: 900;
}

.risk-card {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  padding: 13px;
}

.risk-card strong {
  display: block;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 19px;
}

.risk-card small {
  max-width: 188px;
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.5;
}

.risk-high,
.risk-critical {
  background: var(--yui-danger-soft);
  border-color: rgba(244, 63, 94, 0.22);
}

.risk-medium {
  background: var(--yui-warning-soft);
  border-color: rgba(245, 158, 11, 0.24);
}

.risk-safe,
.risk-low {
  background: var(--yui-success-soft);
  border-color: rgba(34, 197, 94, 0.2);
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.detail-grid > div,
.schema-summary {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  padding: 10px;
}

.detail-grid strong,
.schema-summary strong {
  display: block;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.detail-section {
  margin-top: 14px;
}

.token-list {
  margin-top: 7px;
}

.muted-text {
  color: #94a3b8;
  font-size: 12px;
}

.schema-summary details {
  margin-top: 8px;
}

.schema-summary summary {
  color: #475569;
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}

.schema-summary pre {
  max-height: 190px;
  overflow: auto;
  margin: 8px 0 0;
  color: #334155;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.skill-toolbar {
  margin-bottom: 14px;
}

.skill-bulkbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: -2px 0 14px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 9px 10px;
}

.skill-bulkbar-main,
.skill-bulkbar-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.skill-bulkbar-main span {
  color: var(--yui-muted);
  font-size: 12px;
}

.skill-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  max-height: 560px;
  overflow-y: auto;
  padding-right: 4px;
}

.skill-card {
  display: flex;
  min-height: 166px;
  flex-direction: column;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  padding: 13px;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.skill-card.selected {
  border-color: rgba(37, 99, 235, 0.42);
  background: color-mix(in srgb, var(--yui-surface-raised) 84%, rgba(37, 99, 235, 0.16));
}

.skill-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.skill-card-head > div {
  min-width: 0;
}

.skill-select {
  flex-shrink: 0;
}

.skill-card-head span {
  display: block;
  margin-top: 4px;
  color: var(--yui-muted);
  font-size: 11px;
}

.skill-card p {
  flex: 1;
}

.skill-actions {
  justify-content: flex-end;
  min-height: 28px;
  margin-top: 10px;
}

.bottom-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 16px;
}

.plugin-list,
.log-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mini-item,
.log-item {
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 10px;
}

.mini-item strong,
.mini-item span {
  display: block;
}

.log-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.log-item span {
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.log-item strong {
  min-width: 0;
  color: var(--yui-text);
  overflow-wrap: anywhere;
}

.log-evidence {
  min-width: 0;
  color: #047857;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.el-input__wrapper),
:deep(.el-select__wrapper) {
  border-radius: 10px;
}

@media (max-width: 1180px) {
  .skill-grid,
  .bottom-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .capability-workspace {
    grid-template-columns: 1fr;
  }

  .capability-list-pane {
    border-right: none;
    border-bottom: 1px solid var(--yui-border);
  }
}

@media (max-width: 760px) {
  .skill-grid,
  .bottom-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .section-heading,
  .section-actions,
  .skill-bulkbar,
  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .toolbar-select,
  .skill-toolbar .toolbar-select {
    width: 100%;
  }
}
</style>
