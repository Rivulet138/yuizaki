<template>
  <PanelShell
    :title="t('tools.title')"
    tone="tool"
  >
    <div class="tool-panel">
      <nav class="tool-view-nav" :aria-label="t('tools.viewNavAria')" role="tablist">
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
      <section class="tool-health panel-card" :aria-label="t('tools.healthAria')">
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

      <section v-show="activeToolView === 'stream'" class="stream-summary panel-card" :aria-label="t('tools.stream.sectionAria')">
        <div class="section-heading">
          <div>
            <h3>{{ t('tools.stream.title') }}</h3>
          </div>
          <div class="section-actions">
            <el-tag :type="streamStatusTagType" effect="light">{{ streamStatusLabel }}</el-tag>
            <el-button plain :loading="loadingStreamProbe" @click="probeStream">{{ t('tools.stream.probeAdapter') }}</el-button>
            <el-button plain :icon="Refresh" :loading="loadingStream" @click="loadStream">{{ t('tools.refresh') }}</el-button>
          </div>
        </div>
        <el-alert v-if="streamLoadError" class="panel-alert" type="warning" :closable="false" show-icon>
          <div class="alert-row"><span>{{ streamLoadError }}</span></div>
        </el-alert>
        <div v-if="streamSnapshot" class="stream-status-line">
          <span>{{ t('tools.stream.adapterLine', { name: streamSnapshot.adapter?.name || streamSnapshot.adapter?.id || t('tools.state.notConnected') }) }}</span>
          <span>{{ streamSnapshot.adapter?.configured ? t('tools.state.configured') : t('tools.state.notConfigured') }}</span>
           <span>{{ t('tools.stream.eventsubLine', { state: streamSnapshot.platforms?.twitch?.revoked ? t('tools.stream.eventsubRevoked') : streamSnapshot.platforms?.twitch?.eventsubConfigured ? t('tools.stream.eventsubInbound') : t('tools.state.notConfigured') }) }}</span>
           <span>{{ t('tools.stream.outboundLine', { state: streamSnapshot.platforms?.twitch?.outboundActions ? t('tools.stream.outboundNeedsConfirm') : t('tools.state.notConfigured') }) }}</span>
          <span>{{ t('tools.stream.ircLine', { state: twitchIrcStatusLabel }) }}</span>
          <el-button
            v-if="!streamSnapshot.platforms?.twitch?.ircConnection?.desired"
            size="small"
            text
            :loading="connectingTwitch"
            @click="connectTwitch"
          >{{ t('tools.stream.connectIrc') }}</el-button>
          <el-button
            v-else
            size="small"
            text
            :loading="disconnectingTwitch"
            @click="disconnectTwitch"
          >{{ t('tools.stream.disconnectIrc') }}</el-button>
          <el-button
            v-if="streamSnapshot.platforms?.twitch?.revoked"
            size="small"
            text
            :loading="reconfiguringTwitch"
            @click="reconfigureTwitch"
          >{{ t('tools.stream.markReconfigured') }}</el-button>
        </div>
        <div class="stream-safety-controls stream-twitch-config">
          <div>
            <strong>{{ t('tools.stream.twitchCredentials') }}</strong>
            <small>{{ twitchConfigStatusText }}</small>
          </div>
          <div class="stream-twitch-fields">
            <el-input v-model="twitchClientIdDraft" size="small" clearable placeholder="Client ID" />
            <el-input v-model="twitchEventsubSecretDraft" size="small" type="password" show-password clearable placeholder="EventSub Secret" />
            <el-input v-model="twitchEventsubTokenDraft" size="small" type="password" show-password clearable :placeholder="t('tools.stream.eventsubTokenPlaceholder')" />
            <el-input v-model="twitchChatTokenDraft" size="small" type="password" show-password clearable placeholder="Chat Token" />
            <el-input v-model="twitchBroadcasterIdDraft" size="small" clearable placeholder="Broadcaster ID" />
            <el-input v-model="twitchSenderIdDraft" size="small" clearable placeholder="Sender ID" />
            <el-input v-model="twitchModeratorIdDraft" size="small" clearable :placeholder="t('tools.stream.moderatorIdPlaceholder')" />
            <el-input v-model="twitchChannelDraft" size="small" clearable :placeholder="t('tools.stream.channelPlaceholder')" />
            <el-input v-model="twitchUsernameDraft" size="small" clearable :placeholder="t('tools.stream.ircUsernamePlaceholder')" />
            <el-input v-model="twitchEventsubCallbackUrlDraft" size="small" clearable :placeholder="t('tools.stream.callbackUrlPlaceholder')" />
            <el-select v-model="twitchSubscriptionProviderDraft" size="small" clearable :placeholder="t('tools.stream.subscriptionProviderPlaceholder')">
              <el-option :label="t('tools.stream.providerLocalOnly')" value="none" />
              <el-option :label="t('tools.stream.providerLocalStaging')" value="in-memory-staging" />
              <el-option :label="t('tools.stream.providerHelix')" value="helix" />
            </el-select>
            <div class="stream-twitch-actions">
              <el-button size="small" plain :loading="savingTwitchConfig" @click="saveTwitchConfig">{{ t('tools.stream.saveTwitch') }}</el-button>
              <el-button size="small" plain :loading="probingTwitchConfig" @click="probeTwitchConfig">{{ t('tools.stream.readOnlyCheck') }}</el-button>
              <el-button size="small" text type="danger" :loading="savingTwitchConfig" @click="clearTwitchConfig">{{ t('tools.stream.clearCredentials') }}</el-button>
            </div>
          </div>
        </div>
        <div class="stream-safety-controls stream-obs-config">
          <div>
            <strong>OBS WebSocket</strong>
            <small>{{ streamSnapshot?.adapter?.passwordConfigured ? t('tools.stream.obsPasswordConfigured') : t('tools.stream.obsPasswordNotConfigured') }} · {{ t('tools.stream.obsPasswordTemporary') }}</small>
          </div>
          <div class="stream-obs-fields">
            <el-input v-model="obsEndpointDraft" size="small" placeholder="ws://127.0.0.1:4455" clearable />
            <el-input v-model="obsPasswordDraft" size="small" type="password" show-password clearable :placeholder="t('tools.stream.obsPasswordPlaceholder')" />
            <el-checkbox v-model="obsAllowRemote" size="small">{{ t('tools.stream.obsAllowRemote') }}</el-checkbox>
            <el-button size="small" plain :loading="configuringObs" @click="configureObs">{{ t('tools.stream.obsSaveAndProbe') }}</el-button>
            <el-button v-if="streamSnapshot?.adapter?.passwordConfigured" size="small" text type="danger" :loading="configuringObs" @click="clearObsPassword">{{ t('tools.stream.obsClearPassword') }}</el-button>
          </div>
        </div>
        <div class="stream-safety-controls stream-profile-controls">
          <div>
            <strong>{{ t('tools.stream.obsProfileTitle') }}</strong>
            <small>{{ obsProfiles.length ? `${obsCurrentProfile || t('tools.state.notSelected')} · ${t('tools.stream.obsProfileCount', { count: obsProfiles.length })}` : t('tools.state.notLoaded') }}</small>
          </div>
          <div class="stream-profile-fields">
            <el-select v-model="obsProfileDraft" size="small" filterable allow-create clearable :placeholder="t('tools.stream.obsProfileNamePlaceholder')">
              <el-option v-for="profile in obsProfiles" :key="profile.profileName" :label="profile.profileName" :value="profile.profileName" />
            </el-select>
            <el-button size="small" plain :loading="loadingObsProfiles" @click="loadObsProfiles">{{ t('tools.stream.obsReadProfiles') }}</el-button>
            <el-button size="small" type="warning" plain :loading="previewingStreamCapability === 'stream.profile_switch'" :disabled="!obsProfileDraft.trim() || Boolean(previewingStreamCapability)" @click="previewObsProfileSwitch">{{ t('tools.stream.obsPreviewSwitch') }}</el-button>
          </div>
        </div>
        <div class="stream-safety-controls stream-subscription-controls">
          <div>
            <strong>{{ t('tools.stream.subscriptionTitle') }}</strong>
            <small>{{ streamSubscriptionStatusLabel }}</small>
          </div>
          <el-checkbox-group v-model="twitchSubscriptionDraft" class="stream-subscription-options" :disabled="loadingTwitchSubscriptions">
            <el-checkbox v-for="option in twitchSubscriptionOptions" :key="option.value" :value="option.value">{{ option.label }}</el-checkbox>
          </el-checkbox-group>
          <el-button size="small" plain :loading="loadingTwitchSubscriptions" @click="saveTwitchSubscriptions">{{ t('tools.stream.savePlan') }}</el-button>
        </div>
        <div class="stream-safety-controls">
          <div>
            <strong>{{ t('tools.stream.takeoverTitle') }}</strong>
            <small>{{ streamTakeoverEnabled ? t('tools.stream.takeoverEnabled') : t('tools.state.disabled') }}</small>
          </div>
          <el-button
            size="small"
            plain
            :type="streamTakeoverEnabled ? 'warning' : 'default'"
            :loading="loadingStreamTakeover"
            @click="toggleStreamTakeover"
          >{{ streamTakeoverEnabled ? t('tools.stream.takeoverDisable') : t('tools.stream.takeoverEnable') }}</el-button>
        </div>
        <div class="stream-safety-controls stream-moderation-controls">
          <div>
            <strong>{{ t('tools.stream.moderationTitle') }}</strong>
            <small>{{ streamModerationSummary }}</small>
          </div>
          <el-switch v-model="streamModerationEnabled" :disabled="loadingStreamModeration" />
          <el-button size="small" plain :loading="loadingStreamModeration" @click="saveStreamModeration">{{ t('tools.stream.saveModeration') }}</el-button>
          <div class="stream-moderation-fields">
            <el-input v-model="streamModerationTermsInput" size="small" clearable :placeholder="t('tools.stream.moderationTermsPlaceholder')" />
            <el-input-number v-model="streamModerationSlowModeSeconds" size="small" :min="0" :max="3600" :step="1" controls-position="right" :aria-label="t('tools.stream.slowModeSecondsAria')" />
            <el-input-number v-model="streamModerationMaxMessagesPerMinute" size="small" :min="1" :max="600" :step="1" controls-position="right" :aria-label="t('tools.stream.maxMessagesPerMinuteAria')" />
          </div>
        </div>
        <div class="stream-safety-controls">
          <div>
            <strong>{{ t('tools.stream.draftConsumerTitle') }}</strong>
            <small>{{ streamDraftConsumer?.running ? t('tools.stream.draftConsumerRunning') : streamDraftConsumer?.enabled ? t('tools.state.enabled') : t('tools.state.closed') }}</small>
          </div>
          <el-button
            size="small"
            plain
            :type="streamDraftConsumer?.enabled ? 'warning' : 'default'"
            :loading="loadingStreamDraftConsumer"
            @click="toggleStreamDraftConsumer"
          >{{ streamDraftConsumer?.enabled ? t('tools.stream.draftConsumerDisable') : t('tools.stream.draftConsumerEnable') }}</el-button>
        </div>
        <div v-if="streamCapabilities.length" class="stream-capability-list">
          <div v-for="item in streamCapabilities" :key="item.id" class="stream-capability-row">
            <div>
              <strong>{{ item.name || item.id }}</strong>
              <small>{{ item.available ? (item.executionReady ? t('tools.stream.capabilityExecutable') : item.needsConfig ? t('tools.stream.capabilityNeedsObs') : t('tools.stream.capabilityLocalOnly')) : t('tools.state.notConnected') }} · {{ streamRiskLabel(item.riskLevel) }}</small>
            </div>
            <el-button
              size="small"
              plain
              :loading="previewingStreamCapability === item.id"
              :disabled="!item.available || Boolean(previewingStreamCapability)"
              @click="previewStream(item.id)"
            >{{ t('tools.stream.preview') }}</el-button>
          </div>
        </div>
        <el-empty v-else :description="t('tools.stream.emptyCapabilities')" :image-size="48" />
        <div v-if="streamSnapshot?.preview" class="stream-preview-note">
          <strong>{{ t('tools.stream.previewLine', { summary: streamSnapshot.preview.summary || streamActionLabel(streamSnapshot.preview.action || streamSnapshot.preview.kind) }) }}</strong>
           <span>{{ t('tools.stream.riskLine', { risk: streamRiskLabel(streamSnapshot.preview.riskLevel) }) }}</span>
          <el-button
            size="small"
            type="primary"
            plain
            :loading="loadingStreamExecute"
            :disabled="!streamSnapshot.preview.requestId || Boolean(streamExecution?.ok) || !streamPreviewExecutionReady"
            @click="confirmStreamExecution"
          >{{ streamPreviewExecutionReady ? t('tools.stream.confirmExecute') : t('tools.stream.capabilityNeedsObs') }}</el-button>
        </div>
        <div v-if="streamExecution" class="stream-execution-note" :class="{ failed: !streamExecution.ok }">
          <strong>{{ streamExecution.ok ? t('tools.stream.executionDone') : t('tools.stream.executionFailed') }}</strong>
           <span v-if="!streamExecution.ok">{{ t('tools.stream.executionRetryHint') }}</span>
          <el-button v-if="!streamExecution.ok" size="small" plain :loading="loadingStreamExecute" @click="confirmStreamExecution">{{ t('tools.stream.manualRetry') }}</el-button>
        </div>
        <div class="stream-actions-heading">
          <strong>{{ t('tools.stream.auditTitle') }}</strong>
          <el-button size="small" text :loading="loadingStreamActions" @click="loadStreamActions">{{ t('tools.stream.refreshAudit') }}</el-button>
        </div>
        <div v-if="streamActions.length" class="stream-action-list">
          <div v-for="action in streamActions" :key="`${action.requestId}:${action.at}:${action.status}`" class="stream-action-row">
            <div>
              <strong>{{ action.action }}</strong>
              <small>{{ formatStreamActionStatus(action.status) }} · {{ formatStreamEventTime(action.at) }}</small>
            </div>
            <small v-if="action.verificationStatus || action.errorCode">{{ action.verificationStatus || action.errorCode }}</small>
          </div>
        </div>
        <el-empty v-else :description="t('tools.stream.emptyAudit')" :image-size="40" />
        <div class="stream-events-heading">
          <strong>{{ t('tools.stream.eventsTitle') }}</strong>
            <div class="stream-event-heading-actions">
              <el-button size="small" text :loading="consumingStreamDrafts" @click="consumeStreamDrafts">{{ t('tools.stream.generatePendingDrafts') }}</el-button>
              <el-button size="small" text :loading="loadingStreamEvents" @click="loadStreamEvents">{{ t('tools.stream.refreshEvents') }}</el-button>
            </div>
        </div>
        <div v-if="streamEvents.length" class="stream-event-list">
          <div v-for="event in streamEvents" :key="event.eventId || event.id || `${event.kind}-${event.createdAt || event.receivedAt}`" class="stream-event-row">
            <span>{{ streamEventKindLabel(event.kind) }}</span>
            <strong>{{ event.text || event.message || t('tools.stream.noText') }}</strong>
            <small>{{ event.author || event.source || t('tools.stream.localSource') }} · {{ formatStreamEventTime(event.createdAt ?? event.receivedAt ?? event.at) }} · {{ event.delivered ? t('tools.stream.delivered') : t('tools.stream.localQueueOnly') }}</small>
            <div class="stream-event-actions">
              <el-button
                size="small"
                text
                :loading="generatingStreamDraft === streamEventId(event)"
                :disabled="!streamEventId(event) || Boolean(generatingStreamDraft)"
                @click="generateStreamDraft(event)"
              >{{ t('tools.stream.generateDraft') }}</el-button>
              <span v-if="streamDraftByEventId.get(streamEventId(event))" class="stream-draft-status">
                {{ streamDraftByEventId.get(streamEventId(event))?.status === 'generated' ? t('tools.stream.draftGenerated') : t('tools.stream.draftFailed') }}
              </span>
            </div>
          </div>
        </div>
        <el-empty v-else :description="t('tools.stream.emptyEvents')" :image-size="40" />
        <div class="stream-drafts-heading">
          <strong>{{ t('tools.stream.draftsTitle') }}</strong>
          <el-button size="small" text :loading="loadingStreamDrafts" @click="loadStreamDrafts">{{ t('tools.stream.refreshDrafts') }}</el-button>
        </div>
        <div v-if="streamDrafts.length" class="stream-draft-list">
          <div v-for="draft in streamDrafts" :key="draft.draftId" class="stream-draft-row">
            <div>
              <strong>{{ draft.author || t('tools.stream.viewer') }}</strong>
              <small>{{ draft.eventText || t('tools.stream.noOriginalMessage') }}</small>
            </div>
            <p v-if="draft.reply">{{ draft.reply }}</p>
            <p v-else class="stream-draft-error">{{ draft.error || t('tools.stream.noReply') }}</p>
            <el-button
              v-if="draft.status === 'generated' && draft.reply && draft.sendStatus !== 'known_success' && draft.sendStatus !== 'unknown_effect'"
              size="small"
              plain
              :loading="previewingStreamCapability === `stream.chat_send:${draft.draftId}`"
              :disabled="Boolean(previewingStreamCapability)"
              @click="previewDraftSend(draft)"
            >{{ t('tools.stream.previewSend') }}</el-button>
            <el-button
              v-if="draft.status === 'failed'"
              size="small"
              text
              :loading="generatingStreamDraft === draft.eventId"
              :disabled="Boolean(generatingStreamDraft)"
              @click="retryStreamDraft(draft)"
            >{{ t('tools.stream.regenerate') }}</el-button>
            <small>{{ streamDraftDeliveryLabel(draft) }} · {{ formatStreamEventTime(draft.createdAt) }}</small>
          </div>
        </div>
        <el-empty v-else :description="t('tools.stream.emptyDrafts')" :image-size="40" />
      </section>

      <section v-show="activeToolView === 'capabilities'" class="capability-workspace panel-card">
        <div class="capability-list-pane">
          <div class="section-heading compact">
            <div>
              <h3>{{ activeFilterLabel }}</h3>
            </div>
            <div class="section-actions">
              <el-button v-if="filterKind === 'mcp-tool'" plain size="small" @click="openMcpManagement">{{ t('tools.manageMcp') }}</el-button>
              <el-button plain :icon="Refresh" :loading="loadingSnapshots" @click="refreshSnapshots">{{ t('tools.refreshCapabilities') }}</el-button>
            </div>
          </div>

          <div class="toolbar">
            <el-input v-model="searchText" clearable :placeholder="t('tools.searchPlaceholder')">
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
            <el-select v-model="filterKind" :placeholder="t('tools.sourcePlaceholder')" class="toolbar-select" @change="activeHealthKey = ''">
              <el-option v-for="item in sourceCards" :key="item.kind || 'all'" :label="`${item.title} (${item.count})`" :value="item.kind" />
            </el-select>
            <el-select v-model="filterRisk" clearable :placeholder="t('tools.riskPlaceholder')" class="toolbar-select">
              <el-option v-for="risk in riskOptions" :key="risk.value" :label="risk.label" :value="risk.value" />
            </el-select>
            <el-select v-model="filterApproval" :placeholder="t('tools.approvalPlaceholder')" class="toolbar-select">
              <el-option :label="t('tools.approvalAll')" value="all" />
              <el-option :label="t('tools.approvalRequired')" value="required" />
              <el-option :label="t('tools.approvalFree')" value="free" />
            </el-select>
          </div>

          <el-alert v-if="capabilityLoadError" class="panel-alert" type="warning" :closable="false" show-icon>
            <div class="alert-row">
              <span>{{ capabilityLoadError }}</span>
              <el-button size="small" text :loading="loadingCapabilities" @click.stop="loadCapabilities">{{ t('tools.retry') }}</el-button>
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
                <span>{{ item.observability?.trace ? t('tools.recordedCall') : t('tools.unrecordedCall') }}</span>
                <span>{{ t('tools.timeoutInline', { value: formatTimeout(item.timeoutMs) }) }}</span>
                <span v-if="item.hasPostcondition" class="completion-meta">{{ t('tools.verifiableCompletion') }}</span>
                <span v-else-if="item.hasRecheck" class="completion-meta">{{ t('tools.recheckable') }}</span>
              </div>
            </button>
          </div>
          <el-empty v-else :description="t('tools.emptyCapabilities')" />
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
                <span>{{ t('tools.riskAndPermission') }}</span>
                <strong>{{ riskLabel(selectedCapability.riskLevel) }}</strong>
              </div>
              <small>{{ riskHint(selectedCapability) }}</small>
            </div>

            <div class="detail-grid">
              <div>
                <span>{{ t('tools.fieldType') }}</span>
                <strong>{{ kindLabel(selectedCapability.kind) }}</strong>
              </div>
              <div>
                <span>{{ t('tools.fieldOwner') }}</span>
                <strong>{{ ownerLabel(selectedCapability.owner) }}</strong>
              </div>
              <div>
                <span>{{ t('tools.fieldTimeout') }}</span>
                <strong>{{ formatTimeout(selectedCapability.timeoutMs) }}</strong>
              </div>
            </div>

            <details class="capability-identity-details">
              <summary>{{ t('tools.showInternalId') }}</summary>
              <code>{{ selectedCapability.id }}</code>
            </details>

            <div class="detail-section">
              <span class="section-label">{{ t('tools.scopes') }}</span>
              <div class="token-list">
                <el-tag v-for="scope in selectedCapability.scopes || []" :key="scope" size="small" effect="plain">{{ scope }}</el-tag>
                <span v-if="!(selectedCapability.scopes || []).length" class="muted-text">{{ t('tools.noScopes') }}</span>
              </div>
            </div>

            <div class="detail-section">
              <span class="section-label">{{ t('tools.tags') }}</span>
              <div class="token-list">
                <el-tag v-for="tag in capabilityTags(selectedCapability)" :key="tag" size="small" type="info" effect="plain">{{ tag }}</el-tag>
                <span v-if="!capabilityTags(selectedCapability).length" class="muted-text">{{ t('tools.noTags') }}</span>
              </div>
            </div>

            <div class="detail-section">
              <span class="section-label">{{ t('tools.inputSchema') }}</span>
              <div class="schema-summary">
                <strong>{{ schemaSummary(selectedCapability.inputSchema) }}</strong>
                <details>
                  <summary>{{ t('tools.viewJsonSchema') }}</summary>
                  <pre>{{ schemaPreview(selectedCapability.inputSchema) }}</pre>
                </details>
              </div>
            </div>
          </template>
          <el-empty v-else :description="t('tools.emptySelection')" />
        </aside>
      </section>

      <section v-show="activeToolView === 'skills'" class="skill-catalog panel-card">
        <div class="section-heading">
          <div>
            <h3>{{ t('tools.skills.title') }}</h3>
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
              <el-tag type="success" effect="light">{{ t('tools.skills.builtInCount', { count: builtInSkillCount }) }}</el-tag>
              <el-tag v-if="importedSkillItems.length" type="info" effect="light">{{ t('tools.skills.importedCount', { count: importedSkillItems.length }) }}</el-tag>
              <el-tag v-if="importedSkillItems.length" :type="skillStorageTagType" effect="light">{{ skillStorageLabel }}</el-tag>
              <el-tag type="primary" effect="light">{{ t('tools.skills.categoryCount', { count: skillCategoryOptions.length }) }}</el-tag>
            </div>
            <el-button plain :icon="Upload" :loading="loadingImportedSkills || savingImportedSkills" @click="openSkillImport">{{ t('tools.skills.import') }}</el-button>
          </div>
        </div>

        <div class="toolbar skill-toolbar">
          <el-input v-model="skillSearchText" clearable :placeholder="t('tools.skills.searchPlaceholder')">
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-select v-model="skillCategoryFilter" :placeholder="t('tools.skills.categoryPlaceholder')" class="toolbar-select">
            <el-option :label="t('tools.skills.allCategories')" value="all" />
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
              {{ t('tools.skills.filterResult') }}
            </el-checkbox>
            <span>{{ t('tools.skills.selectedSummary', { selected: selectedSkillCount, total: importedSkillItems.length }) }}</span>
            <span v-if="hasActiveSkillFilter">{{ t('tools.skills.matchSummary', { count: filteredImportedSkillItems.length }) }}</span>
          </div>
          <div class="skill-bulkbar-actions">
            <el-button size="small" plain :icon="Check" :disabled="!hasActiveSkillFilter || !filteredImportedSkillItems.length || savingImportedSkills" @click="selectFilteredImportedSkills">
              {{ t('tools.skills.selectFiltered') }}
            </el-button>
            <el-button size="small" plain :icon="Close" :disabled="!selectedSkillCount || savingImportedSkills" @click="clearSkillSelection">
              {{ t('tools.skills.clearSelection') }}
            </el-button>
            <el-button size="small" plain type="danger" :icon="Delete" :disabled="!selectedSkillCount || savingImportedSkills" :loading="savingImportedSkills" @click="deleteSelectedSkills">
              {{ t('tools.skills.deleteSelected') }}
            </el-button>
            <el-button size="small" plain type="danger" :icon="Delete" :disabled="!canDeleteFilteredSkills || savingImportedSkills" :loading="savingImportedSkills" @click="deleteFilteredImportedSkills">
              {{ t('tools.skills.deleteFiltered') }}
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
              <el-tag v-if="!skill.imported" size="small" type="success" effect="plain">{{ t('tools.kind.builtin') }}</el-tag>
              <el-tag v-else size="small" type="warning" effect="plain">{{ t('tools.skills.badgeImported') }}</el-tag>
              <el-tag v-if="skill.imported && skill.runtimeBinding === 'catalog_only'" size="small" type="info" effect="plain">{{ t('tools.skills.badgeCatalogOnly') }}</el-tag>
              <el-tag v-if="skill.fit === 'high'" size="small" type="primary" effect="plain">{{ t('tools.skills.badgeHighFit') }}</el-tag>
              <el-tag v-else-if="skill.fit === 'medium'" size="small" type="info" effect="plain">{{ t('tools.skills.badgeMediumFit') }}</el-tag>
            </div>
            <div v-if="skill.imported" class="skill-actions">
              <el-button size="small" plain type="danger" :icon="Delete" :loading="savingImportedSkills" @click="removeImportedSkill(skill.id)">{{ t('tools.skills.delete') }}</el-button>
            </div>
          </article>
        </div>
        <el-empty v-else :description="t('tools.skills.emptyFiltered')" />
      </section>

      <section v-show="activeToolView === 'history'" class="bottom-grid">
        <article class="panel-card plugin-panel">
          <div class="section-heading compact">
            <div>
              <h3>{{ t('tools.source.plugin') }}</h3>
            </div>
            <el-tag :type="pluginHealthTagType" effect="light">{{ pluginHealthLabel }}</el-tag>
          </div>
          <div v-if="pluginTools.length" class="plugin-list">
            <div v-for="tool in pluginTools" :key="tool.id" class="mini-item">
              <strong>{{ tool.name }}</strong>
              <span>{{ tool.desc || t('tools.history.pluginNoDescription') }}</span>
            </div>
          </div>
          <el-empty v-else :description="t('tools.history.emptyPluginTools')" :image-size="64" />
        </article>

        <article class="panel-card log-panel">
          <div class="section-heading compact">
            <div>
              <h3>{{ t('tools.history.recentTitle') }}</h3>
            </div>
            <el-tag effect="plain">{{ t('tools.history.recordCount', { count: recentToolLogs.length }) }}</el-tag>
          </div>
          <div v-if="recentToolLogs.length" class="log-list">
            <div v-for="(log, idx) in recentToolLogs" :key="`${log.sortKey}-${idx}`" class="log-item">
              <span>{{ log.time }}</span>
              <el-tag size="small" :title="log.source" :type="toolLogTagType(log.actionStatus || log.status)" effect="plain">{{ toolActionStatusLabel(log.actionStatus || log.status) }}</el-tag>
              <strong>{{ log.text }}</strong>
              <small v-if="log.evidence?.length" class="log-evidence">{{ log.evidence[0] }}</small>
            </div>
          </div>
          <el-empty v-else :description="t('tools.history.emptyLogs')" :image-size="64" />
        </article>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { ElAlert, ElEmpty, ElIcon } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/empty/style/css'
import 'element-plus/es/components/icon/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElCheckbox, ElCheckboxGroup, ElSwitch } from 'element-plus'
import 'element-plus/es/components/checkbox/style/css'
import 'element-plus/es/components/checkbox-group/style/css'
import 'element-plus/es/components/switch/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Close, Delete, Refresh, Search, Upload } from '@element-plus/icons-vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { t } from '@/i18n'
import { pluginClient, systemClient } from '@/api/client'
import { curatedSkillRecommendations } from '../skillRecommendations'
import type { PluginLoadFailure, PluginRuntimeState, PluginToolCapabilityContribution } from '../../../../shared/plugin'
import type { CapabilityDescriptor, CapabilityKind, CapabilityRiskLevel, SkillCatalogItem, StreamActionRecord, StreamActionsSnapshot, StreamCapabilityDescriptor, StreamDraftConsumerSnapshot, StreamDraftsSnapshot, StreamExecuteResponse, StreamLocalEvent, StreamObsProfile, StreamReplyDraft, StreamRuntimeSnapshot } from '../../../../shared/capability'
import type { AgentTraceSnapshot, MCPSnapshot, MCPServerConfigSnapshot, MCPServerStatusSnapshot, RuntimeLoopRecord, StepExecutionRecord } from '../../../../shared/agent'
import { projectToolActionStatus, toolActionStatusLabel, toolEvidenceFromRecord, type ToolActionStatus } from '../toolActionProjection'
import { describeFailure } from '@/shared/errors/describe-error'

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
const toolViews = computed<Array<{ id: ToolViewId; label: string }>>(() => [
  { id: 'status', label: t('tools.view.status') },
  { id: 'stream', label: t('tools.view.stream') },
  { id: 'capabilities', label: t('tools.view.capabilities') },
  { id: 'skills', label: t('tools.view.skills') },
  { id: 'history', label: t('tools.view.history') },
])
const activeToolView = ref<ToolViewId>('status')
const route = useRoute()
const router = useRouter()

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

const openMcpManagement = () => {
  const workspaceId = String(route.params.workspaceId || 'default')
  void router.push(`/w/${encodeURIComponent(workspaceId)}/agent-governance`)
}

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

const riskOptions = computed<RiskOption[]>(() => [
  { value: 'safe', label: t('tools.risk.safe') },
  { value: 'low', label: t('tools.risk.low') },
  { value: 'medium', label: t('tools.risk.medium') },
  { value: 'high', label: t('tools.risk.high') },
  { value: 'critical', label: t('tools.risk.critical') },
])

const capabilityDescriptionOverrides = computed<Record<string, string>>(() => ({
  open_app: t('tools.capDesc.openApp'),
  open_url: t('tools.capDesc.openUrl'),
  read_file: t('tools.capDesc.readFile'),
  write_file: t('tools.capDesc.writeFile'),
  web_search: t('tools.capDesc.webSearch'),
  'browser.open_page': t('tools.capDesc.browserOpenPage'),
  'time.now': t('tools.capDesc.timeNow'),
  mcp_playwright_browser_open_page: t('tools.capDesc.playwrightOpenPage'),
  mcp_playwright_browser_click: t('tools.capDesc.playwrightClick'),
  'yuizaki.observe-recall-loop': t('tools.capDesc.observeRecall'),
  'yuizaki.capability-routing': t('tools.capDesc.capabilityRouting'),
  'yuizaki.create-once-task': t('tools.capDesc.createOnceTask'),
  'yuizaki.create-interval-task': t('tools.capDesc.createIntervalTask'),
  'yuizaki.skill.voice-dialogue-chain': t('tools.capDesc.voiceDialogueChain'),
  'yuizaki.skill.long-dialogue-summary': t('tools.capDesc.longDialogueSummary'),
  'yuizaki.skill.companion-reflection': t('tools.capDesc.companionReflection'),
  'yuizaki.skill.memory-capture': t('tools.capDesc.memoryCapture'),
  'yuizaki.skill.realtime-screen-vision': t('tools.capDesc.realtimeScreenVision'),
  'yuizaki.skill.local-file-organizer': t('tools.capDesc.localFileOrganizer'),
  'yuizaki.skill.ocr-document-organizer': t('tools.capDesc.ocrDocumentOrganizer'),
  'yuizaki.skill.webapp-testing': t('tools.capDesc.webappTesting'),
  'yuizaki.skill.frontend-design': t('tools.capDesc.frontendDesign'),
  'yuizaki.skill.interface-hardening': t('tools.capDesc.interfaceHardening'),
  'yuizaki.skill.code-review': t('tools.capDesc.codeReview'),
  'yuizaki.skill.repo-analysis': t('tools.capDesc.repoAnalysis'),
  'yuizaki.skill.best-practice-research': t('tools.capDesc.bestPracticeResearch'),
  'yuizaki.skill.mcp-builder': t('tools.capDesc.mcpBuilder'),
  'yuizaki.skill.skill-authoring': t('tools.capDesc.skillAuthoring'),
  'yuizaki.skill.image-generation': t('tools.capDesc.imageGeneration'),
  'yuizaki.skill.image-enhancement': t('tools.capDesc.imageEnhancement'),
  'yuizaki.skill.document-export': t('tools.capDesc.documentExport'),
  'yuizaki.skill.spreadsheet-helper': t('tools.capDesc.spreadsheetHelper'),
  'yuizaki.skill.task-triage': t('tools.capDesc.taskTriage'),
  'yuizaki.skill.agent-trace-debug': t('tools.capDesc.agentTraceDebug'),
  'yuizaki.skill.release-notes': t('tools.capDesc.releaseNotes'),
  'yuizaki.skill.design-system': t('tools.capDesc.designSystem'),
  'yuizaki.skill.web-research': t('tools.capDesc.webResearch'),
  'yuizaki.skill.content-writing': t('tools.capDesc.contentWriting'),
  'yuizaki.skill.project-planning': t('tools.capDesc.projectPlanning'),
  'yuizaki.skill.quality-cleanup': t('tools.capDesc.qualityCleanup'),
}))

const capabilityNameDescriptionOverrides = computed<Record<string, string>>(() => ({
  open_app: t('tools.capDesc.openApp'),
  open_url: t('tools.capDesc.openUrl'),
  read_file: t('tools.capDesc.readFile'),
  write_file: t('tools.capDesc.writeFile'),
  web_search: t('tools.capDesc.webSearch'),
  'browser.open_page': t('tools.capDesc.browserOpenPage'),
  'time.now': t('tools.capDesc.timeNow'),
  mcp_playwright_browser_open_page: t('tools.capDesc.playwrightOpenPage'),
  mcp_playwright_browser_click: t('tools.capDesc.playwrightClick'),
  'Observe / Recall Loop': t('tools.capDesc.observeRecall'),
  'Capability Routing': t('tools.capDesc.capabilityRouting'),
  'Create Once Task': t('tools.capDesc.createOnceTask'),
  'Create Interval Task': t('tools.capDesc.createIntervalTask'),
}))

const capabilityRawDescriptionOverrides = computed<Record<string, string>>(() => ({
  'launch a desktop application by name': t('tools.capDesc.openApp'),
  'open a url in the default browser': t('tools.capDesc.openUrl'),
  'read a local text file': t('tools.capDesc.readFile'),
  'write text content to a local file': t('tools.capDesc.writeFile'),
  'search the web for current public information and return concise results with urls': t('tools.capDesc.webSearch'),
  'open a browser page via playwright mcp server': t('tools.capDesc.browserOpenPage'),
  'get the current local time': t('tools.capDesc.timeNow'),
  'open a url in a playwright browser context and wait for network idle. (mcp: playwright/browser.open_page)': t('tools.capDesc.playwrightOpenPage'),
  'open a url and click a css selector with playwright. (mcp: playwright/browser.click)': t('tools.capDesc.playwrightClick'),
  'collect runtime input, recall memory, and feed the companion agent pipeline.': t('tools.capDesc.observeRecall'),
  'route builtin, plugin, and mcp capabilities through the unified registry snapshot.': t('tools.capDesc.capabilityRouting'),
  'create a one-shot scheduled task in the local scheduler.': t('tools.capDesc.createOnceTask'),
  'create a recurring scheduled task in the local scheduler.': t('tools.capDesc.createIntervalTask'),
}))

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
    disconnected: t('tools.stream.stateDisconnected'), ready: t('tools.stream.stateReady'), preview: t('tools.stream.statePreview'), live: t('tools.stream.stateLive'), ending: t('tools.stream.stateEnding'), ended: t('tools.stream.stateEnded'), error: t('tools.stream.stateError'),
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
const streamPreviewExecutionReady = computed(() => {
  const action = streamSnapshot.value?.preview?.action || streamSnapshot.value?.preview?.kind
  if (!action) return false
  return streamCapabilities.value.find(item => item.id === action)?.executionReady === true
})
function streamActionLabel(action: unknown) {
  const labels: Record<string, string> = {
    'stream.chat_send': t('tools.stream.actionChatSend'),
    'stream.profile_switch': t('tools.stream.actionProfileSwitch'),
    'stream.scene_switch': t('tools.stream.actionSceneSwitch'),
    'stream.start': t('tools.stream.actionStart'),
    'stream.stop': t('tools.stream.actionStop'),
  }
  const value = typeof action === 'string' ? action : ''
  return labels[value] || value || t('tools.stream.actionFallback')
}

const twitchSubscriptionOptions = computed(() => [
  { value: 'channel.chat.message', label: t('tools.stream.subscriptionChatMessage') },
  { value: 'channel.follow', label: t('tools.stream.subscriptionFollow') },
  { value: 'channel.subscribe', label: t('tools.stream.subscriptionSubscribe') },
])
const streamSubscriptionStatusLabel = computed(() => {
  const plan = streamSnapshot.value?.platforms?.twitch?.subscriptionPlan
  if (!plan) return t('tools.state.notLoaded')
  if (plan.status === 'planned') return t('tools.stream.subscriptionSaved', { count: plan.desired?.length || 0 })
  if (plan.status === 'revoked') return t('tools.stream.subscriptionRevoked')
  if (plan.status === 'unconfigured') return t('tools.stream.subscriptionMissingSecret')
  return t('tools.state.notSelected')
})

const skillCategoryOptions = computed(() => (
  [...new Set(allSkillItems.value.map(item => item.category).filter(Boolean))]
    .sort((a, b) => skillCategoryLabel(a).localeCompare(skillCategoryLabel(b), 'zh-CN'))
))

const healthItems = computed<HealthItem[]>(() => [
  { key: 'ready', label: t('tools.health.ready'), value: readyCapabilityCount.value, detail: t('tools.health.readyDetail'), tone: 'emerald' },
  { key: 'approval', label: t('tools.health.approval'), value: approvalRequiredCount.value, detail: t('tools.health.approvalDetail'), tone: 'amber' },
  { key: 'mcp-error', label: t('tools.health.mcpError'), value: mcpErrorCount.value, detail: t('tools.health.mcpErrorDetail'), tone: mcpErrorCount.value ? 'rose' : 'emerald' },
  { key: 'plugin-error', label: t('tools.health.pluginError'), value: pluginIssueCount.value, detail: t('tools.health.pluginErrorDetail'), tone: pluginIssueCount.value ? 'rose' : 'emerald' },
  { key: 'trace', label: t('tools.health.trace'), value: recentToolLogs.value.length, detail: t('tools.health.traceDetail'), tone: 'blue' },
])

const sourceCards = computed<SourceCard[]>(() => [
  {
    kind: '',
    title: t('tools.source.all'),
    count: capabilities.value.length,
  },
  {
    kind: 'builtin-tool',
    title: t('tools.source.builtin'),
    count: countByKind('builtin-tool'),
  },
  {
    kind: 'mcp-tool',
    title: t('tools.source.mcp'),
    count: countByKind('mcp-tool'),
  },
  {
    kind: 'plugin-tool',
    title: t('tools.source.plugin'),
    count: countByKind('plugin-tool'),
  },
  {
    kind: 'skill',
    title: t('tools.source.skill'),
    count: countByKind('skill'),
  },
  {
    kind: 'command',
    title: t('tools.source.command'),
    count: countByKind('command'),
  },
])

const pluginHealthLabel = computed(() => {
  const blocked = pluginStates.value.filter(item => ['blocked', 'error'].includes(item.status)).length
  const degraded = pluginStates.value.filter(item => item.status === 'degraded').length
  if (pluginLoadFailures.value.length) return t('tools.history.pluginLoadFailures', { count: pluginLoadFailures.value.length })
  if (blocked) return t('tools.history.pluginBlocked', { count: blocked })
  if (degraded) return t('tools.history.pluginDegraded', { count: degraded })
  if (pluginStates.value.length) return t('tools.history.pluginLoaded', { count: pluginStates.value.length })
  return t('tools.history.pluginEmpty')
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
  if (savingImportedSkills.value) return t('tools.skills.storageSaving')
  if (loadingImportedSkills.value) return t('tools.skills.storageLoading')
  if (importedSkillBackendReady.value) return t('tools.skills.storageBackend')
  return t('tools.skills.storageLocal')
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
  const kind = sourceCards.value.find(item => item.kind === filterKind.value)?.title || t('tools.source.all')
  const risk = filterRisk.value ? riskLabel(filterRisk.value) : t('tools.filter.allRisks')
  const approval = filterApproval.value === 'required' ? t('tools.health.approval') : filterApproval.value === 'free' ? t('tools.approvalFree') : t('tools.filter.allApprovals')
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
    'builtin-tool': t('tools.kind.builtin'),
    'plugin-tool': t('tools.kind.plugin'),
    'mcp-tool': 'MCP',
    skill: 'Skill',
    command: t('tools.kind.command'),
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
    'builtin-tool': t('tools.kindFallback.builtin'),
    'plugin-tool': t('tools.kindFallback.plugin'),
    'mcp-tool': t('tools.kindFallback.mcp'),
    skill: t('tools.kindFallback.skill'),
    command: t('tools.kindFallback.command'),
  }
  return map[kind]
}

function normalizeDescriptionKey(value?: string) {
  return String(value || '').trim().replace(/\s+/g, ' ').toLowerCase()
}

function displayCapabilityDescription(item: CapabilityDescriptor) {
  const idOverride = capabilityDescriptionOverrides.value[item.id]
  if (idOverride) return idOverride

  const nameOverride = capabilityNameDescriptionOverrides.value[item.name]
  if (nameOverride) return nameOverride

  const rawDescriptionOverride = capabilityRawDescriptionOverrides.value[normalizeDescriptionKey(item.description)]
  if (rawDescriptionOverride) return rawDescriptionOverride

  return item.description || kindFallbackDescription(item.kind)
}

function executionLabel(item: CapabilityDescriptor) {
  if (item.requiresApproval) return t('tools.execution.confirm')
  if (['mcp-tool', 'plugin-tool'].includes(item.kind)) return t('tools.execution.serviceGrants')
  if (['high', 'critical'].includes(item.riskLevel)) return t('tools.execution.highRiskFree')
  return t('tools.execution.direct')
}

function ownerLabel(owner?: string) {
  if (!owner) return t('tools.state.notDeclared')
  const labels: Record<string, string> = {
    'yuizaki.builtin-tools': t('tools.source.builtin'),
    'yuizaki.companion-orchestrator': t('tools.owner.companionOrchestrator'),
    'yuizaki.task-router': t('tools.owner.taskRouter'),
  }
  if (owner.startsWith('plugin:')) return t('tools.owner.pluginPrefix', { name: owner.slice('plugin:'.length) })
  if (owner.startsWith('mcp:')) return `MCP ${owner.slice('mcp:'.length)}`
  return labels[owner] || owner
}

function riskLabel(risk: CapabilityRiskLevel) {
  return riskOptions.value.find(item => item.value === risk)?.label || risk
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
  if (item.requiresApproval) return t('tools.riskHint.confirm')
  if (['mcp-tool', 'plugin-tool'].includes(item.kind)) return t('tools.riskHint.serviceGrants')
  if (['high', 'critical'].includes(item.riskLevel)) return t('tools.riskHint.high')
  if (item.riskLevel === 'medium') return t('tools.riskHint.medium')
  return t('tools.riskHint.default')
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
  if (!fields.length) return t('tools.schema.noFields')
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
  if (!timeoutMs) return t('tools.timeout.default')
  if (timeoutMs >= 1000) return `${Math.round(timeoutMs / 1000)}s`
  return `${timeoutMs}ms`
}

function skillCategoryLabel(category: string) {
  const labels: Record<string, string> = {
    companion: t('tools.skillCategory.companion'),
    perception: t('tools.skillCategory.perception'),
    development: t('tools.skillCategory.development'),
    frontend: t('tools.skillCategory.frontend'),
    research: t('tools.skillCategory.research'),
    automation: t('tools.skillCategory.automation'),
    document: t('tools.skillCategory.document'),
    mcp: t('tools.skillCategory.mcp'),
    governance: t('tools.skillCategory.governance'),
    media: t('tools.skillCategory.media'),
    authoring: t('tools.skillCategory.authoring'),
    general: t('tools.skillCategory.general'),
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
      ElMessage.warning(t('tools.skills.importNone'))
      return
    }
    await mergeImportedSkills(imported)
    ElMessage.success(t('tools.skills.imported', { count: imported.length }))
  } catch (error) {
    const message = describeFailure(error, t('tools.skills.importFailed'))
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
    throw new Error(t('tools.skills.invalidJson', { fileName }))
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
  const description = frontmatter.description || firstParagraph || t('tools.skills.importedDescription')

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
  const description = stringField(candidate.description) || stringField(candidate.desc) || stringField(candidate.summary) || t('tools.skills.importedDescription')
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
  if (/(ui|ux|frontend|visual|design|\u754c\u9762)/i.test(haystack)) return 'frontend'
  if (/(memory|dialogue|companion|voice|tts|asr|\u684c\u5ba0|\u8bed\u97f3|\u8bb0\u5fc6)/i.test(haystack)) return 'companion'
  if (/(doc|pdf|sheet|ppt|document|\u6587\u6863|\u8868\u683c)/i.test(haystack)) return 'document'
  if (/(test|debug|review|code|ci|repo|\u6d4b\u8bd5|\u4ee3\u7801)/i.test(haystack)) return 'development'
  if (/(image|media|audio|video|\u56fe\u50cf|\u5a92\u4f53)/i.test(haystack)) return 'media'
  if (/(research|search|docs|\u8c03\u7814|\u641c\u7d22)/i.test(haystack)) return 'research'
  if (/(plan|quality|cleanup|\u6cbb\u7406)/i.test(haystack)) return 'governance'
  if (/(skill|author|prompt|\u7f16\u5199)/i.test(haystack)) return 'authoring'
  if (/(task|file|automation|\u81ea\u52a8\u5316|\u4efb\u52a1|\u6587\u4ef6)/i.test(haystack)) return 'automation'
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
  await deleteImportedSkills([skillId], { confirm: false, successMessage: t('tools.skills.deleted') })
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
    importedSkillStorageError.value = describeFailure(error, t('tools.skills.backendUnavailable'))
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
    importedSkillStorageError.value = describeFailure(error, t('tools.skills.backendSaveFailed'))
    markImportedSkillsDirty(true)
    ElMessage.warning(t('tools.skills.backendSaveWarning'))
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
    title: t('tools.skills.deleteSelectedTitle'),
    successMessage: t('tools.skills.deleteSelectedDone'),
  })
}

async function deleteFilteredImportedSkills() {
  if (!canDeleteFilteredSkills.value) return
  await deleteImportedSkills(filteredImportedSkillIds.value, {
    confirm: true,
    title: t('tools.skills.deleteFilteredTitle'),
    successMessage: t('tools.skills.deleteFilteredDone'),
  })
}

async function deleteImportedSkills(skillIds: string[], options: { confirm?: boolean; title?: string; successMessage?: string } = {}) {
  const uniqueIds = [...new Set(skillIds.filter(Boolean))]
  if (!uniqueIds.length) return
  if (options.confirm !== false) {
    try {
      await ElMessageBox.confirm(
        t('tools.skills.deleteConfirm', { count: uniqueIds.length }),
        options.title || t('tools.skills.deleteTitle'),
        {
          confirmButtonText: t('tools.action.delete'),
          cancelButtonText: t('tools.action.cancel'),
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
        importedSkillStorageError.value = describeFailure(error, t('tools.skills.backendDeleteFailed'))
        markImportedSkillsDirty(true)
        ElMessage.warning(t('tools.skills.backendDeleteWarning'))
      }
    } finally {
      savingImportedSkills.value = false
      pruneSelectedSkillIds()
    }
  }

  ElMessage.success(options.successMessage || t('tools.skills.deleted'))
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
    source: t('tools.stream.localSource'),
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
  const result = step.error ? t('tools.log.stepFailed', { error: step.error }) : (step.title || step.reply_preview || step.status || t('tools.log.recorded'))
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
    const message = describeFailure(error, t('tools.log.unknownError'))
    pushLog(t('tools.log.pluginLoadFailed', { message }))
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
    const message = describeFailure(error, t('tools.log.unknownError'))
    capabilityLoadError.value = t('tools.log.capabilityLoadFailed', { message })
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
    const message = describeFailure(error, t('tools.log.unknownError'))
    pushLog(t('tools.log.traceLoadFailed', { message }))
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
    const message = describeFailure(error, t('tools.log.unknownError'))
    mcpLoadError.value = t('tools.log.mcpLoadFailed', { message })
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
    const message = describeFailure(error, t('tools.log.unknownError'))
    streamLoadError.value = t('tools.log.streamLoadFailed', { message })
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
      ElMessage.warning(t('tools.stream.secureStoreUnavailable'))
    }
  } catch {
    twitchConfigStatus.value = null
  }
}

const twitchConfigStatusText = computed(() => {
  const status = twitchConfigStatus.value
  if (!status) return t('tools.stream.twitchStatusFailed')
  if (!status.secureStorageAvailable) return t('tools.stream.twitchStatusUnavailable')
  const configured = Object.entries(status.configured).filter(([, value]) => value).map(([key]) => key)
  return configured.length ? t('tools.stream.twitchStatusSaved', { count: configured.length }) : t('tools.stream.twitchStatusUnconfigured')
})

async function probeTwitchConfig() {
  probingTwitchConfig.value = true
  try {
    const result = await systemClient.probeTwitch()
    if (result.ok !== true) {
      ElMessage.warning(String(result.error || t('tools.stream.twitchProbeFailed')))
      return
    }
    const configured = result.configured as Record<string, unknown> | undefined
    const ready = configured && Object.values(configured).filter(Boolean).length
    ElMessage.info(t('tools.stream.twitchProbeDone', { count: ready || 0 }))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.twitchProbeError', { message }))
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
      ElMessage.warning(String(result.error || t('tools.stream.twitchSaveNotApplied')))
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
    ElMessage.success(t('tools.stream.twitchSaved', { count: ready }))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.twitchSaveError', { message }))
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
      ElMessage.warning(String(result.error || t('tools.stream.twitchClearNotApplied')))
      return
    }
    await Promise.all([loadStream(), loadTwitchConfigStatus()])
    ElMessage.success(t('tools.stream.twitchCleared'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.twitchClearError', { message }))
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
    if (probe.status === 'reachable') ElMessage.success(t('tools.stream.obsConfigured'))
    else ElMessage.warning(t('tools.stream.obsSavedWithStatus', { status: String(probe.status || 'unknown') }))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.obsConfigureError', { message }))
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
    ElMessage.success(t('tools.stream.obsPasswordCleared'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.obsPasswordClearError', { message }))
  } finally {
    configuringObs.value = false
  }
}

const streamModerationSummary = computed(() => {
  if (!streamModerationEnabled.value) return t('tools.state.closed')
  const terms = streamModerationTermsInput.value.split(',').map(item => item.trim()).filter(Boolean).length
  const slow = streamModerationSlowModeSeconds.value > 0 ? t('tools.stream.moderationSlow', { seconds: streamModerationSlowModeSeconds.value }) : t('tools.stream.moderationNoSlow')
  return t('tools.stream.moderationSummary', { terms, slow, rate: streamModerationMaxMessagesPerMinute.value })
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
      ElMessage.warning(t('tools.stream.moderationNotUpdated'))
      return
    }
    await loadStream()
    ElMessage.success(t('tools.stream.moderationSaved'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.moderationError', { message }))
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
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.warning(t('tools.stream.eventsLoadFailed', { message }))
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
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.warning(t('tools.stream.draftsLoadFailed', { message }))
  } finally {
    loadingStreamDrafts.value = false
  }
}

async function loadStreamDraftConsumer() {
  try {
    streamDraftConsumer.value = await systemClient.streamDraftConsumer()
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.warning(t('tools.stream.draftConsumerLoadFailed', { message }))
  }
}

async function toggleStreamDraftConsumer() {
  loadingStreamDraftConsumer.value = true
  try {
    streamDraftConsumer.value = await systemClient.setStreamDraftConsumer(!streamDraftConsumer.value?.enabled)
    ElMessage.success(streamDraftConsumer.value.enabled ? t('tools.stream.draftConsumerEnabled') : t('tools.stream.draftConsumerDisabled'))
    await Promise.all([loadStreamEvents(), loadStreamDrafts()])
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.draftConsumerError', { message }))
  } finally {
    loadingStreamDraftConsumer.value = false
  }
}

async function consumeStreamDrafts() {
  consumingStreamDrafts.value = true
  try {
    const result = await systemClient.consumeStreamDrafts({ limit: 3 })
    if (!result.ok && !(result.created ?? 0)) {
      ElMessage.warning(result.errors?.[0]?.error || t('tools.stream.noPendingEvents'))
      return
    }
    await Promise.all([loadStreamEvents(), loadStreamDrafts()])
    ElMessage.success(t('tools.stream.draftsConsumed', { attempted: result.attempted ?? 0, created: result.created ?? 0 }))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.consumeDraftsError', { message }))
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
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.warning(t('tools.stream.auditLoadFailed', { message }))
  } finally {
    loadingStreamActions.value = false
  }
}

async function reconfigureTwitch() {
  reconfiguringTwitch.value = true
  try {
    const result = await systemClient.reconfigureTwitch()
    if (result.ok !== true) {
      ElMessage.warning(String(result.error || t('tools.stream.twitchReconfigureNotApplied')))
      return
    }
    await loadStream()
    ElMessage.success(t('tools.stream.twitchReconfigured'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.twitchReconfigureError', { message }))
  } finally {
    reconfiguringTwitch.value = false
  }
}

async function saveTwitchSubscriptions() {
  loadingTwitchSubscriptions.value = true
  try {
    const result = await systemClient.configureTwitchSubscriptions(twitchSubscriptionDraft.value)
    if (result.ok !== true) {
      ElMessage.warning(String(result.error || t('tools.stream.subscriptionNotSaved')))
      return
    }
    await loadStream()
    ElMessage.success(t('tools.stream.subscriptionSavedMessage'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.subscriptionSaveError', { message }))
  } finally {
    loadingTwitchSubscriptions.value = false
  }
}

const twitchIrcStatusLabel = computed(() => {
  const connection = streamSnapshot.value?.platforms?.twitch?.ircConnection
  if (!connection) return t('tools.state.disabled')
  if (connection.status === 'connected') return t('tools.stream.ircConnected')
  if (connection.status === 'connecting') return t('tools.stream.ircConnecting')
  if (connection.status === 'backoff') {
    const seconds = connection.nextRetryInSeconds
    return seconds == null ? t('tools.stream.ircWaitingReconnect') : t('tools.stream.ircWaitingReconnectSeconds', { seconds: Math.ceil(seconds) })
  }
  if (connection.status === 'unconfigured') return t('tools.state.notConfigured')
  if (connection.status === 'revoked') return t('tools.stream.ircRevoked')
  return t('tools.stream.ircDisconnected')
})

async function connectTwitch() {
  connectingTwitch.value = true
  try {
    const result = await systemClient.connectTwitch()
    await loadStream()
    if (result.ok) ElMessage.success(t('tools.stream.ircConnectRequested'))
    else ElMessage.warning(t('tools.stream.ircNotConnected'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.ircConnectError', { message }))
  } finally {
    connectingTwitch.value = false
  }
}

async function disconnectTwitch() {
  disconnectingTwitch.value = true
  try {
    await systemClient.disconnectTwitch()
    await loadStream()
    ElMessage.success(t('tools.stream.ircDisconnectedMessage'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.ircDisconnectError', { message }))
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
    ElMessage.warning(t('tools.stream.eventMissingId'))
    return
  }
  generatingStreamDraft.value = eventId
  try {
    const result = await systemClient.generateStreamDraft({ eventId })
    if (!result.ok && !result.draft) {
      ElMessage.warning(result.error || t('tools.stream.draftGenerateFailed'))
      return
    }
    if (result.draft) {
      streamDrafts.value = [result.draft, ...streamDrafts.value.filter(item => item.requestId !== result.draft?.requestId)].slice(0, 20)
    }
    ElMessage.success(result.draft?.status === 'generated' ? t('tools.stream.draftGeneratedLocal') : t('tools.stream.draftGenerateFailedNoSend'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.draftGenerateError', { message }))
  } finally {
    generatingStreamDraft.value = ''
  }
}

async function retryStreamDraft(draft: StreamReplyDraft) {
  const eventId = String(draft.eventId || '').trim()
  if (!eventId) {
    ElMessage.warning(t('tools.stream.draftMissingId'))
    return
  }
  generatingStreamDraft.value = eventId
  try {
    const result = await systemClient.generateStreamDraft({ eventId, retry: true })
    if (!result.ok && !result.draft) {
      ElMessage.warning(result.error || t('tools.stream.draftRetryFailed'))
      return
    }
    if (result.draft) {
      streamDrafts.value = [result.draft, ...streamDrafts.value.filter(item => item.requestId !== result.draft?.requestId)].slice(0, 20)
    }
    ElMessage.success(result.draft?.status === 'generated' ? t('tools.stream.draftRegenerated') : t('tools.stream.draftRetryFailedNoSend'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.draftRetryError', { message }))
  } finally {
    generatingStreamDraft.value = ''
  }
}

function streamDraftDeliveryLabel(draft: StreamReplyDraft) {
  if (draft.sendStatus === 'known_success' || draft.sent) return t('tools.stream.deliveryConfirmed')
  if (draft.sendStatus === 'unknown_effect') return t('tools.stream.deliveryUnknown')
  if (draft.sendStatus === 'failed') return t('tools.stream.deliveryFailed')
  return draft.status === 'generated' ? t('tools.stream.deliveryDraftOnly') : t('tools.stream.deliveryGenerateFailed')
}

async function toggleStreamTakeover() {
  loadingStreamTakeover.value = true
  try {
    const result = await systemClient.setStreamTakeover(!streamTakeoverEnabled.value)
    if (!result.ok) {
      ElMessage.warning(result.error || t('tools.stream.takeoverNotUpdated'))
      return
    }
    streamTakeoverEnabled.value = result.enabled ?? !streamTakeoverEnabled.value
    if (result.state && streamSnapshot.value) streamSnapshot.value = { ...streamSnapshot.value, state: result.state, policy: result.policy ?? streamSnapshot.value.policy }
    ElMessage.success(streamTakeoverEnabled.value ? t('tools.stream.takeoverEnabledMessage') : t('tools.stream.takeoverDisabledMessage'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.takeoverError', { message }))
  } finally {
    loadingStreamTakeover.value = false
  }
}

function formatStreamEventTime(value: number | string | null | undefined) {
  if (value == null || value === '') return t('tools.time.unknown')
  const date = new Date(typeof value === 'number' ? value : String(value))
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString()
}

function formatStreamActionStatus(status: string | undefined) {
  const labels: Record<string, string> = {
    sending: t('tools.stream.statusSending'),
    known_success: t('tools.stream.statusKnownSuccess'),
    unknown_effect: t('tools.stream.statusUnknownEffect'),
    failed: t('tools.stream.statusFailed'),
  }
  return labels[status || ''] || status || t('tools.stream.statusUnknown')
}

function streamEventKindLabel(kind: string | undefined) {
  const labels: Record<string, string> = {
    'channel.chat.message': t('tools.stream.subscriptionChatMessage'),
    'channel.follow': t('tools.stream.eventKindFollow'),
    'channel.subscribe': t('tools.stream.eventKindSubscribe'),
    'channel.cheer': t('tools.stream.eventKindCheer'),
    'channel.raid': 'Raid',
    'stream.online': t('tools.stream.eventKindOnline'),
    'stream.offline': t('tools.stream.eventKindOffline'),
  }
  return labels[kind || ''] || kind || t('tools.stream.eventKindFallback')
}

async function probeStream() {
  loadingStreamProbe.value = true
  streamLoadError.value = ''
  try {
    const result = await systemClient.probeStream()
    streamProbe.value = result.probe ?? null
    if (result.state && streamSnapshot.value) streamSnapshot.value = { ...streamSnapshot.value, state: result.state }
    await loadStream()
    if (!result.ok) ElMessage.warning(result.error || t('tools.stream.probeNotPassed'))
    else ElMessage.success(t('tools.stream.probeDone'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.probeError', { message }))
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
    if (result.ok) ElMessage.success(t('tools.stream.obsProfilesLoaded', { count: obsProfiles.value.length }))
    else ElMessage.warning(result.error || t('tools.stream.obsProfilesFailed'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.obsProfilesError', { message }))
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
    if (!result.ok) ElMessage.warning(result.error || t('tools.stream.previewUnavailable'))
    else ElMessage.success(t('tools.stream.previewReady'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
    ElMessage.error(t('tools.stream.previewError', { message }))
  } finally {
    previewingStreamCapability.value = ''
  }
}

async function previewDraftSend(draft: StreamReplyDraft) {
  if (!draft.reply) return
  await previewStream('stream.chat_send', { text: draft.reply, draftId: draft.draftId }, `stream.chat_send:${draft.draftId}`)
}

function streamRiskLabel(risk: string | undefined) {
  const labels: Record<string, string> = { safe: t('tools.risk.safe'), low: t('tools.risk.low'), medium: t('tools.risk.medium'), high: t('tools.risk.high'), critical: t('tools.risk.critical') }
  return labels[risk || ''] || risk || t('tools.risk.undeclared')
}

async function confirmStreamExecution() {
  const pending = streamPendingExecution.value
  if (!pending?.requestId) {
    ElMessage.warning(t('tools.stream.previewExpired'))
    return
  }
  try {
    await ElMessageBox.confirm(
        t('tools.stream.confirmExecuteMessage', { action: streamActionLabel(pending.action), risk: streamRiskLabel(streamSnapshot.value?.preview?.riskLevel) }),
      t('tools.stream.confirmTitle'),
      { type: 'warning', confirmButtonText: t('tools.stream.confirmExecute'), cancelButtonText: t('tools.action.cancel') },
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
    if (result.ok) ElMessage.success(t('tools.stream.executionDoneWith', { status: result.verificationStatus || result.outcome || t('tools.stream.submitted') }))
    else ElMessage.error(result.message || result.error || t('tools.stream.executionFailedHint'))
  } catch (error) {
    const message = describeFailure(error, t('tools.log.unknownError'))
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
    ElMessage.error(t('tools.stream.executionError', { message }))
  } finally {
    loadingStreamExecute.value = false
  }
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

.capability-identity-details {
  margin-top: 12px;
  color: var(--yui-muted);
  font-size: 12px;
}

.capability-identity-details summary {
  cursor: pointer;
}

.capability-identity-details code {
  display: block;
  margin-top: 6px;
  overflow-wrap: anywhere;
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
