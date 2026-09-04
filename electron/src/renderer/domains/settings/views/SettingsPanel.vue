<template>
  <PanelShell :title="t('settings.title')" tone="admin">
    <template #actions>
      <el-button plain @click="openOnboarding">{{ t('onboarding.reopen') }}</el-button>
    </template>
    <AsyncState :loading="settingsRequest.loading && !settings" :empty="!settings && !settingsRequest.error" :empty-text="t('settings.empty')">
      <div class="settings-panel">
        <el-alert
          v-if="settingsRequest.error"
          :title="settingsRequest.error"
          type="error"
          show-icon
          :closable="false"
        />
        <el-alert
          v-if="saveBusy || updateRequest.error || lastSavedAt"
          :title="saveStatusLabel"
          :description="saveStatusDetail"
          :type="saveStatusType"
          show-icon
          :closable="false"
        />

        <div class="settings-workspace">
          <nav class="settings-section-nav" :aria-label="t('settings.sectionNav')">
            <section v-for="group in settingSectionGroups" :key="group.id" class="settings-section-group">
              <span class="settings-section-group-label">{{ group.label }}</span>
              <button
                v-for="item in group.items"
                :key="item.id"
                type="button"
                class="settings-section-button"
                :class="{ active: activeSection === item.id }"
                :aria-current="activeSection === item.id ? 'page' : undefined"
                @click="activeSection = item.id"
              >
                {{ item.label }}
              </button>
            </section>
          </nav>

          <el-tabs v-model="activeSection" class="settings-content-tabs">
          <el-tab-pane :label="t('settings.tabs.access')" name="access" lazy>
            <SettingsAccessSection
              v-model:backend-token="backendTokenInput"
              :backend-token-configured="backendTokenConfigured"
              :backend-token-busy="backendTokenBusy"
              :backend-token-status-known="Boolean(backendTokenStatus)"
              :backend-token-source-label="backendTokenSourceLabel"
              :backend-token-preview="backendTokenPreview"
              :backend-token-requires-restart="backendTokenRequiresRestart"
              @save-backend-token="saveBackendToken"
              @reset-backend-token="resetBackendToken"
            />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.llm')" name="llm" lazy>
            <el-card class="llm-settings-card" shadow="never">
              <template #header>
                <div class="card-header">
                  <div class="header-title">
                    <span>{{ t('settings.llm.service') }}</span>
                  </div>
                  <div class="llm-toolbar">
                    <div class="llm-status-strip">
                      <el-tag :type="hasLlmEndpoint ? 'success' : 'warning'">{{ hasLlmEndpoint ? t('common.configured') : t('settings.tts.incomplete') }}</el-tag>
                      <el-tag :type="hasLlmApiKey ? 'success' : 'info'">{{ llmApiKeyTagLabel }}</el-tag>
                      <el-tag :type="llmDetectionTagType">{{ llmDetectionStatus }}</el-tag>
                      <el-tag :type="llmRuntimeTagType">{{ llmRuntimeLabel }}</el-tag>
                      <el-tag v-if="llmModels.length" type="info">{{ t('settings.llm.modelsCount', { count: llmModels.length }) }}</el-tag>
                    </div>
                    <div class="llm-actions">
                      <div class="llm-action-group">
                        <el-button plain :loading="llmImporting" @click="triggerLlmImport">
                          <el-icon><Upload /></el-icon>
                          {{ t('settings.llm.importProfile') }}
                        </el-button>
                        <el-button plain @click="downloadLlmProfileTemplate">
                          <el-icon><Document /></el-icon>
                          {{ t('settings.llm.templateProfile') }}
                        </el-button>
                        <el-button plain :loading="llmExporting" @click="exportLlmProfile">
                          <el-icon><Download /></el-icon>
                          {{ t('settings.llm.exportProfile') }}
                        </el-button>
                      </div>
                      <div class="llm-action-group">
                        <el-button plain :loading="localDiscoveryRequest.loading" @click="applyLocalLlmDiscovery">
                          <el-icon><Connection /></el-icon>
                          {{ t('settings.discovery.detectLocal') }}
                        </el-button>
                        <el-button plain :loading="llmModelsRequest.loading" :disabled="!canRequestLlmModels" @click="discoverLlmModels({ forceAutoSelect: true, manual: true })">
                          <el-icon><Refresh /></el-icon>
                          {{ t('settings.llm.detectModels') }}
                        </el-button>
                        <el-button plain :loading="llmStatusRequest.loading" @click="refreshLlmStatus">
                          <el-icon><Refresh /></el-icon>
                          {{ t('settings.llm.refreshStatus') }}
                        </el-button>
                        <el-button type="primary" plain :loading="testLlmRequest.loading" :disabled="!hasLlmEndpoint" @click="handleTestLlm">
                          <el-icon><Connection /></el-icon>
                          {{ t('settings.llm.test') }}
                        </el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
              <input ref="llmImportInput" class="sr-only-input" type="file" accept="application/json,.json" @change="handleLlmImportFile" />
              <el-form label-position="top" @submit.prevent>
                <div class="llm-workspace">
                  <aside class="llm-profile-rail">
                    <div class="profile-rail-head">
                      <strong>{{ t('settings.llm.profileTitle') }}</strong>
                    </div>
                    <div class="provider-stack" role="radiogroup" :aria-label="t('settings.llm.providerPreset')">
                      <button
                        v-for="option in llmProviderOptionRows"
                        :key="option.value"
                        class="provider-option"
                        :class="{ 'is-active': option.value === llmProviderPreset }"
                        type="button"
                        role="radio"
                        :aria-checked="option.value === llmProviderPreset"
                        :aria-label="`${option.label}: ${option.status}`"
                        @click="applyLlmProviderPreset(option.value)"
                      >
                        <span class="provider-option-label">
                          <strong>{{ option.label }}</strong>
                          <small :class="`status-${option.statusClass}`">{{ option.status }}</small>
                        </span>
                      </button>
                    </div>
                    <el-button class="profile-reset-button" plain @click="resetCurrentLlmProfile">
                      <el-icon><Refresh /></el-icon>
                      {{ t('settings.llm.resetProfile') }}
                    </el-button>
                    <div class="profile-card">
                      <span>{{ t('settings.llm.activeProfile') }}</span>
                      <strong>{{ activeLlmProfileLabel }}</strong>
                    </div>
                    <div class="llm-connection-summary">
                      <div class="summary-row">
                        <span>{{ t('settings.llm.summaryEndpoint') }}</span>
                        <strong>{{ llmEndpointSummary }}</strong>
                      </div>
                      <div class="summary-row">
                        <span>{{ t('settings.llm.summaryModel') }}</span>
                        <strong>{{ llmModelSummary }}</strong>
                      </div>
                      <div class="summary-row">
                        <span>{{ t('settings.llm.summaryAuth') }}</span>
                        <strong>{{ llmAuthSummary }}</strong>
                      </div>
                    </div>
                  </aside>

                  <div class="llm-main-form">
                    <div class="subsection-title">{{ t('settings.llm.sectionConnection') }}</div>
                    <div class="form-grid">
                      <el-form-item :label="t('settings.llm.baseUrl')">
                        <el-input v-model="form.llm.base_url" name="llm-base-url" @change="handleLlmEndpointChange('base_url', $event)" @keyup.enter="scheduleLlmModelDiscovery">
                          <template #append>{{ llmEndpointAppendLabel }}</template>
                        </el-input>
                      </el-form-item>
                      <el-form-item v-if="llmProviderNeedsApiKey" :label="t('settings.llm.apiKeyLabel')">
                        <el-input v-model="form.llm.api_key" type="password" show-password @change="handleLlmEndpointChange('api_key', $event)" @keyup.enter="scheduleLlmModelDiscovery" />
                      </el-form-item>
                    </div>

                    <el-form-item :label="t('settings.llm.modelName')">
                      <el-select
                        v-model="form.llm.model"
                        class="full-width"
                        filterable
                        allow-create
                        default-first-option
                        :loading="llmModelsRequest.loading"
                        @focus="scheduleLlmModelDiscovery"
                        @change="handleLlmModelChange"
                      >
                        <el-option v-for="model in llmModelSelectOptions" :key="model" :label="model" :value="model" />
                      </el-select>
                      <p v-if="llmModelStatusLabel" class="field-hint" :class="{ error: llmModelsRequest.error }">{{ llmModelStatusLabel }}</p>
                      <SettingsLlmCapabilityPanel
                        :provider="llmProviderPreset"
                        :model="form.llm.model"
                        :context-max-tokens="Number(form.llm.context_max_tokens)"
                        :max-output-tokens="Number(form.llm.default_max_output_tokens)"
                        :vision-enabled="form.llm.vision_enabled"
                      />
                    </el-form-item>

                    <SettingsLlmVisionSection
                      :model-value="llmVisionSettings"
                      :provider-options="llmProviderOptions"
                      @update="applyLlmVisionPatch"
                    />

                    <div class="subsection-title">{{ t('settings.llm.sectionSampling') }}</div>
                    <div class="parameter-strip">
                      <el-form-item :label="t('settings.llm.temperature', { value: form.llm.temperature.toFixed(2) })">
                        <el-slider v-model="form.llm.temperature" :min="0" :max="2" :step="0.1" @change="saveLlmField('temperature', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.topP', { value: form.llm.top_p.toFixed(2) })">
                        <el-slider v-model="form.llm.top_p" :min="0" :max="1" :step="0.05" @change="saveLlmField('top_p', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.minP', { value: form.llm.min_p.toFixed(2) })">
                        <el-slider v-model="form.llm.min_p" :min="0" :max="1" :step="0.01" @change="saveLlmField('min_p', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.frequencyPenalty', { value: form.llm.frequency_penalty.toFixed(2) })">
                        <el-slider v-model="form.llm.frequency_penalty" :min="-2" :max="2" :step="0.05" @change="saveLlmField('frequency_penalty', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.presencePenalty', { value: form.llm.presence_penalty.toFixed(2) })">
                        <el-slider v-model="form.llm.presence_penalty" :min="-2" :max="2" :step="0.05" @change="saveLlmField('presence_penalty', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.repetitionPenalty', { value: form.llm.repetition_penalty.toFixed(2) })">
                        <el-slider v-model="form.llm.repetition_penalty" :min="0" :max="2" :step="0.05" @change="saveLlmField('repetition_penalty', $event)" />
                      </el-form-item>
                    </div>

                    <div class="form-grid three">
                      <el-form-item :label="t('settings.llm.topK')">
                        <el-input-number v-model="form.llm.top_k" :min="0" :max="2000" :step="50" controls-position="right" @change="saveLlmField('top_k', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.contextTokens')">
                        <el-input-number v-model="form.llm.context_max_tokens" :min="1000" :max="2000000" :step="1000" controls-position="right" @change="saveLlmField('context_max_tokens', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.maxOutputTokens')">
                        <el-input-number v-model="form.llm.default_max_output_tokens" :min="256" :max="65535" :step="256" controls-position="right" @change="saveLlmField('default_max_output_tokens', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.timeout')">
                        <el-input-number v-model="form.llm.timeout" :min="10" :max="300" controls-position="right" @change="saveLlmField('timeout', $event)" />
                      </el-form-item>
                    </div>
                  </div>
                </div>
              </el-form>
            </el-card>
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.tts')" name="voice" lazy>
            <el-card shadow="never">
              <template #header>
                <div class="card-header">
                  <div class="header-title">
                    <span>{{ t('settings.tts.service') }}</span>
                  </div>
                  <div class="tts-toolbar">
                    <div class="tts-status-strip">
                      <el-tag :type="ttsRuntimeTagType">{{ ttsRuntimeLabel }}</el-tag>
                      <el-tag :type="hasTtsVoice ? 'success' : 'warning'">{{ hasTtsVoice ? t('common.ready') : t('settings.tts.incomplete') }}</el-tag>
                      <el-tag v-if="ttsRuntimeError" type="danger">{{ t('settings.tts.status.error') }}</el-tag>
                    </div>
                    <div class="button-row">
                      <el-button plain :loading="ttsStatusRequest.loading" @click="refreshTtsStatus">
                        <el-icon><Refresh /></el-icon>
                        {{ t('settings.tts.refreshStatus') }}
                      </el-button>
                      <el-button plain :loading="warmupTtsRequest.loading" :disabled="!hasTtsVoice" @click="handleWarmupTts">
                        <el-icon><Refresh /></el-icon>
                        {{ t('settings.tts.warmup') }}
                      </el-button>
                      <el-button plain :loading="localDiscoveryRequest.loading" @click="applyLocalTtsDiscovery">
                        <el-icon><Connection /></el-icon>
                        {{ t('settings.discovery.detectLocal') }}
                      </el-button>
                      <el-button plain @click="resetCurrentTtsProfile">
                        <el-icon><Refresh /></el-icon>
                        {{ t('settings.tts.resetProfile') }}
                      </el-button>
                      <el-button type="primary" plain :loading="testTtsRequest.loading" @click="handleTestTts">
                        <el-icon><Connection /></el-icon>
                        {{ t('settings.tts.test') }}
                      </el-button>
                    </div>
                  </div>
                </div>
              </template>
              <el-form label-position="top" @submit.prevent>
                <div class="voice-main-form single">
                  <div v-if="ttsStatus || ttsStatusRequest.loading || ttsStatusRequest.error" class="tts-runtime-panel">
                    <div v-for="item in ttsRuntimeMetricItems" :key="item.label" class="tts-runtime-item">
                      <span>{{ item.label }}</span>
                      <strong>{{ item.value }}</strong>
                      <small v-if="item.detail">{{ item.detail }}</small>
                    </div>
                  </div>
                  <el-alert
                    v-if="ttsRuntimeError"
                    class="tts-runtime-alert"
                    :title="ttsRuntimeError"
                    type="error"
                    show-icon
                    :closable="false"
                  />

                  <div class="subsection-title">{{ t('settings.tts.sectionCharacter') }}</div>
                  <div class="form-grid">
                    <el-form-item :label="t('settings.tts.provider')">
                      <el-select v-model="form.tts.provider" class="full-width" @change="saveTtsField('provider', $event, { flush: true })">
                        <el-option :label="t('settings.tts.provider.genie')" value="genie-tts" />
                        <el-option :label="t('settings.tts.provider.openai')" value="openai-compatible" />
                      </el-select>
                    </el-form-item>
                    <template v-if="form.tts.provider === 'openai-compatible'">
                      <el-form-item :label="t('settings.tts.baseUrl')">
                        <el-input v-model="form.tts.base_url" @input="saveTtsField('base_url', $event)" @change="flushTtsSave" />
                      </el-form-item>
                      <el-form-item :label="t('settings.tts.apiKey')">
                        <el-input v-model="form.tts.api_key" type="password" show-password autocomplete="off" @input="saveTtsField('api_key', $event)" @change="flushTtsSave" />
                      </el-form-item>
                      <el-form-item :label="t('settings.tts.model')">
                        <el-input v-model="form.tts.model" @input="saveTtsField('model', $event)" @change="flushTtsSave" />
                      </el-form-item>
                      <el-form-item :label="t('settings.tts.voice')">
                        <el-input v-model="form.tts.voice" @input="saveTtsField('voice', $event)" @change="flushTtsSave" />
                      </el-form-item>
                      <el-form-item :label="t('settings.tts.timeout')">
                        <el-input-number v-model="form.tts.timeout" :min="1" :max="300" @change="saveTtsField('timeout', $event, { flush: true })" />
                      </el-form-item>
                    </template>
                  </div>
                  <div class="form-grid">
                    <el-form-item :label="t('settings.tts.character')">
                      <el-input v-model="form.tts.genie_character" @input="saveTtsField('genie_character', $event)" @change="flushTtsSave" />
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.modelDir')">
                      <el-input v-model="form.tts.genie_model_dir" @input="saveTtsField('genie_model_dir', $event)" @change="flushTtsSave" />
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.lang')">
                      <el-select v-model="form.tts.lang" class="full-width" @change="saveTtsField('lang', $event, { flush: true })">
                        <el-option :label="t('settings.tts.lang.zh')" value="zh" />
                        <el-option :label="t('settings.tts.lang.ja')" value="ja" />
                        <el-option :label="t('settings.tts.lang.en')" value="en" />
                        <el-option :label="t('common.auto')" value="auto" />
                      </el-select>
                    </el-form-item>
                  </div>

                  <div class="subsection-title">{{ t('settings.tts.sectionReference') }}</div>
                  <div class="form-grid">
                    <el-form-item :label="t('settings.tts.referenceAudio')">
                      <el-input v-model="form.tts.ref_audio" :placeholder="t('settings.tts.referenceAudioPlaceholder')" @input="saveTtsField('ref_audio', $event)" @change="flushTtsSave" />
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.referenceText')">
                      <el-input v-model="form.tts.ref_text" type="textarea" :rows="2" :placeholder="t('settings.tts.referenceTextPlaceholder')" @input="saveTtsField('ref_text', $event)" @change="flushTtsSave" />
                    </el-form-item>
                  </div>

                  <div class="subsection-title">{{ t('settings.tts.sectionInference') }}</div>
                  <div class="form-grid three">
                    <el-form-item :label="t('settings.tts.device')">
                      <el-select v-model="form.tts.device" class="full-width" @change="saveTtsField('device', $event, { flush: true })">
                        <el-option label="CPU" value="cpu" />
                        <el-option label="CUDA" value="cuda" />
                      </el-select>
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.quality')">
                      <el-select v-model="form.tts.quality" class="full-width" @change="saveTtsField('quality', $event, { flush: true })">
                        <el-option :label="t('settings.tts.quality.qualityFirst')" value="质量优先" />
                        <el-option :label="t('settings.tts.quality.speedFirst')" value="速度优先" />
                      </el-select>
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.split')">
                      <el-select v-model="form.tts.split" class="full-width" @change="saveTtsField('split', $event, { flush: true })">
                        <el-option :label="t('settings.tts.split.smart')" value="智能切分" />
                        <el-option :label="t('settings.tts.split.disabled')" value="禁用" />
                      </el-select>
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.mode')">
                      <el-select v-model="form.tts.mode" class="full-width" @change="saveTtsField('mode', $event, { flush: true })">
                        <el-option :label="t('settings.tts.mode.serial')" value="串行推理" />
                      </el-select>
                    </el-form-item>
                  </div>
                </div>
              </el-form>
            </el-card>
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.asr')" name="asr" lazy>
            <SettingsAsrSection
              :model-value="form.asr"
              :discovery-loading="localDiscoveryRequest.loading"
              :discovery-error="localDiscoveryRequest.error"
              @discover-local="applyLocalAsrDiscovery"
              @update-field="saveAsrField"
            />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.memory')" name="memory" lazy>
            <SettingsMemorySection
              :model-value="form.memory"
              :discovery-loading="localDiscoveryRequest.loading"
              :rebuild-loading="memoryRebuildRequest.loading"
              :default-embedding-model="DEFAULT_EMBEDDING_MODEL"
              :default-qdrant-docker-image="DEFAULT_QDRANT_DOCKER_IMAGE"
              @change-backend="handleMemoryBackendChange"
              @update-field="saveMemoryField"
              @discover-local="applyLocalMemoryDiscovery"
              @rebuild="handleRebuildMemoryIndex"
            />
            <SettingsProductMetricsConsentSection class="product-metrics-consent-card" />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.summary')" name="summary" lazy>
            <SettingsSummarySection :model-value="form.summary" @update-field="saveSummaryField" />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.svc')" name="svc" lazy>
            <SettingsSvcSection
              :model-value="form.svc"
              :discovery-loading="localDiscoveryRequest.loading"
              :discovery-error="localDiscoveryRequest.error"
              @discover-local="applyLocalSvcDiscovery"
              @update-field="saveSvcField"
            />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.resources')" name="resources" lazy>
            <SettingsResourcesSection
              :resource-message="resourceMessage"
              :resource-message-type="resourceMessageType"
              :resource-loading="resourceLoading"
              :storage-loading="storageLoading"
              :cancellable-resource-ids="cancellableResourceIds"
              :resource-cancel-loading="resourceCancelLoading"
              :active-download-progress="activeDownloadProgress"
              :resource-view="resourceView"
              :selected-resource-ids="selectedResourceIds"
              :resource-download-options="resourceDownloadOptions"
              :storage-status="storageStatus"
              :resource-action-key="resourceActionKey"
              :storage-action-key="storageActionKey"
              @refresh="refreshResourcePanel"
              @cancel-downloads="cancelActiveResourceDownloads"
              @update:selected-resource-ids="selectedResourceIds = $event"
              @download-selected="downloadSelectedResources"
              @prepare-resource="prepareResource"
              @import-soulx-reference="importSoulxReference"
              @remove-resource="removeModelResource"
              @cleanup-storage="cleanupStorage"
              @cleanup-all="cleanupAllStorage"
            />
          </el-tab-pane>
          <el-tab-pane :label="t('settings.tabs.system')" name="system" lazy>
            <SettingsInterfaceSection
              :model-value="form.system"
              :theme-options="themeOptions"
              :language-options="languageOptions"
              @change-theme="handleSystemThemeChange"
              @change-language="handleSystemLanguageChange"
            />

            <SettingsDesktopInputSection
              :state="inputBindingState"
              @reset="resetDesktopInputBindings"
              @set-push-to-talk-enabled="setPushToTalkEnabled"
              @set-push-to-talk-mouse-button="setPushToTalkMouseButton"
              @capture-keyboard="captureKeyboardBinding"
              @clear-keyboard="clearKeyboardBinding"
            />

            <el-card class="settings-admin-card" shadow="never">
              <template #header>{{ t('settings.admin.title') }}</template>
              <el-collapse>
                <el-collapse-item :title="t('settings.admin.editor')" name="metadata">
                  <div class="button-row">
                    <el-button plain @click="loadSettingsAdmin">{{ t('settings.admin.metadata') }}</el-button>
                    <el-button plain type="warning" @click="clearSettingsHistory">{{ t('settings.admin.clearHistory') }}</el-button>
                  </div>
                  <pre class="settings-json">{{ JSON.stringify(settingsMetadata, null, 2) }}</pre>
                  <el-table :data="settingsHistory" size="small" height="220">
                    <el-table-column type="index" width="52" />
                    <el-table-column :label="t('settings.admin.details')">
                      <template #default="scope">
                        <pre class="table-json">{{ JSON.stringify(scope.row, null, 2) }}</pre>
                      </template>
                    </el-table-column>
                  </el-table>
                  <div class="form-grid">
                    <el-form-item :label="t('settings.key.rollbackSteps')">
                      <el-input-number v-model="rollbackSteps" :min="1" :max="20" controls-position="right" />
                    </el-form-item>
                    <el-form-item :label="t('settings.key.delete')">
                      <el-input v-model="deleteKey" placeholder="llm.model / tts.lang" />
                    </el-form-item>
                  </div>
                  <div class="form-grid">
                    <el-form-item :label="t('settings.key.lookup')">
                      <el-input v-model="lookupKey" placeholder="summary.trigger_messages" />
                    </el-form-item>
                    <el-form-item :label="t('settings.key.write')">
                      <el-input v-model="setKey" placeholder="system.theme" />
                    </el-form-item>
                  </div>
                  <el-form-item :label="t('settings.key.valueJson')">
                    <el-input v-model="setValueJson" type="textarea" :rows="2" placeholder='"dark" / 42 / {"enabled":true}' />
                  </el-form-item>
                  <pre v-if="lookupResult" class="settings-json">{{ lookupResult }}</pre>
                  <div class="button-row">
                    <el-button type="warning" plain @click="rollbackSettings">{{ t('common.rollback') }}</el-button>
                    <el-button plain :disabled="!lookupKey.trim()" @click="readSettingKey">{{ t('common.read') }}</el-button>
                    <el-button type="primary" plain :disabled="!setKey.trim() || !setValueJson.trim()" @click="writeSettingKey">{{ t('common.write') }}</el-button>
                    <el-button type="danger" plain :disabled="!deleteKey.trim()" @click="resetSettingKey">{{ t('common.delete') }}</el-button>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </el-card>
          </el-tab-pane>
          <el-tab-pane :label="t('settings.tabs.portable')" name="portable" lazy>
            <PortableSettingsSection
              :before-import="flushPendingSave"
              @imported="handlePortableImported"
            />
          </el-tab-pane>
          </el-tabs>
        </div>
      </div>
    </AsyncState>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Document, Download, Upload } from '@element-plus/icons-vue'
import { currentLocale, localeLabel, normalizeLocale, setLocale, supportedLocales, t } from '@/i18n'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { useDomainRequest } from '@/shared/composables/useDomainRequest'
import { useSettingsStore } from '@/state/settingsStore'
import {
  DEFAULT_LLM_CONTEXT_MAX_TOKENS,
  DEFAULT_LLM_MAX_OUTPUT_TOKENS,
  DEFAULT_QDRANT_DOCKER_IMAGE,
} from '@/../shared/runtime-defaults'
import { useInputBindingsStore } from '@/state/inputBindingsStore'
import { settingsClient, type BackendTokenMutationResponse, type BackendTokenStatusResponse, type LocalRuntimeCandidate, type LocalRuntimeDiscoveryResponse, type TtsRuntimeStatusResponse } from '@/api/clients/settings-client'
import { resourceClient } from '@/api/clients/resource-client'
import { memoryClient } from '@/api/clients/memory-client'
import type { ManagedModelResourceId, ManagedResourceMetadata, ModelResourceStatusPayload, ResumableResourceDownload, ResourceCommandResult, StorageCategoryId, StorageStatusPayload } from '@/../shared/resource-manager'
import { DEFAULT_VAD_MIN_SILENCE_MS } from '@/../shared/runtime-defaults'
import type { InputBindingSettingsPatch, KeyboardShortcutAction, MouseSideButton } from '@/../shared/input-bindings'
import { useSettingsDomain } from '../composables/useSettingsDomain'
import { openOnboarding } from '@/domains/onboarding/onboardingEvents'
import SettingsAsrSection, { type AsrSettings } from '../components/SettingsAsrSection.vue'
import SettingsAccessSection from '../components/SettingsAccessSection.vue'
import SettingsLlmCapabilityPanel from '../components/SettingsLlmCapabilityPanel.vue'
import SettingsLlmVisionSection from '../components/SettingsLlmVisionSection.vue'
import SettingsMemorySection, { type MemorySettings } from '../components/SettingsMemorySection.vue'
import SettingsProductMetricsConsentSection from '../components/SettingsProductMetricsConsentSection.vue'
import SettingsSummarySection, { type SummarySettings } from '../components/SettingsSummarySection.vue'
import SettingsSvcSection, { type SvcSettings } from '../components/SettingsSvcSection.vue'
import SettingsDesktopInputSection from '../components/SettingsDesktopInputSection.vue'
import SettingsInterfaceSection from '../components/SettingsInterfaceSection.vue'
import SettingsResourcesSection from '../components/SettingsResourcesSection.vue'
import PortableSettingsSection from '../components/PortableSettingsSection.vue'
import { isLocalLlmEndpoint, normalizeOpenAiBaseUrl, shouldAutoDiscoverLlmModels } from '../llmDiscovery'
import { LLM_PROVIDER_BASE_URLS, LLM_PROVIDER_ENDPOINTS, choosePreferredLlmModel, getLlmProviderOptions, inferLlmProviderPreset } from '../llmProviders'
import type { LlmProviderPreset } from '../llmProviders'
import { isPlainRecord, normalizeResourceStatus, normalizeStorageStatus } from '../resourceStatus'

type SaveTimeout = ReturnType<typeof window.setTimeout>
type SettingSectionId = 'access' | 'llm' | 'voice' | 'asr' | 'memory' | 'summary' | 'svc' | 'resources' | 'system' | 'portable'
type QualityScorerMode = 'rule' | 'llm'
type SettingsPatch = Record<string, unknown>
type AlertType = 'success' | 'warning' | 'info' | 'error'
type StorageCleanupTarget = Exclude<StorageCategoryId, 'visual_frames'>
const DEFAULT_EMBEDDING_MODEL = 'Qwen/Qwen3-Embedding-0.6B'
type LlmModelDiscoveryOptions = {
  forceAutoSelect?: boolean
  manual?: boolean
}
type LlmProfile = {
  provider: LlmProviderPreset
  base_url: string
  api_key: string
  model: string
  temperature: number
  top_p: number
  top_k: number
  min_p: number
  frequency_penalty: number
  presence_penalty: number
  repetition_penalty: number
  timeout: number
  context_max_tokens: number
  default_max_output_tokens: number
}
type LlmProfileField = keyof LlmProfile
type LlmProfiles = Partial<Record<LlmProviderPreset, LlmProfile>>
type LlmVisionPatch = Partial<{
  enabled: boolean
  provider: LlmProviderPreset
  baseUrl: string
  apiKey: string
  model: string
  timeout: number
  detail: 'low' | 'high' | 'auto' | 'original'
}>
type ProviderStatusClass = 'ready' | 'warning' | 'muted'
type TtsProviderPreset = 'genie-tts' | 'openai-compatible'
type SaveFieldOptions = {
  flush?: boolean
}
type TagType = 'success' | 'warning' | 'info' | 'danger'
type TtsProfile = {
  genie_character: string
  genie_model_dir: string
  ref_audio: string
  ref_text: string
  lang: string
  device: 'cpu' | 'cuda'
  quality: string
  split: string
  mode: string
  save_mode: string
  provider: TtsProviderPreset
  base_url: string
  api_key: string
  model: string
  voice: string
  timeout: number
}
type TtsProfileField = keyof TtsProfile

const KEYLESS_LLM_PROVIDERS = new Set<LlmProviderPreset>(['ollama', 'lmstudio'])
const llmProfileNeedsApiKey = (profile: Pick<LlmProfile, 'provider' | 'base_url'>): boolean => {
  return !KEYLESS_LLM_PROVIDERS.has(profile.provider) && !isLocalLlmEndpoint(normalizeOpenAiBaseUrl(profile.base_url))
}
const TTS_PROVIDER: TtsProviderPreset = 'genie-tts'

const {
  settings,
  settingsRequest,
  updateRequest,
  llmModels,
  llmModelsRequest,
  llmStatus,
  llmStatusRequest,
  ttsStatus,
  ttsStatusRequest,
  testLlmRequest,
  testTtsRequest,
  loadSettings,
  patchSettings,
  loadLlmModels,
  loadLlmStatus,
  loadTtsStatus,
  testLlm,
  testTts,
  warmupTtsRequest,
  warmupTts,
} = useSettingsDomain()

const settingsStore = useSettingsStore()
const inputBindingsStore = useInputBindingsStore()
const inputBindingState = inputBindingsStore.state

const form = reactive({
  llm: {
    provider: 'custom' as LlmProviderPreset,
    base_url: '',
    api_key: '',
    model: '',
    temperature: 1.2,
    top_p: 0.9,
    top_k: 500,
    min_p: 0,
    frequency_penalty: 0.2,
    presence_penalty: 0,
    repetition_penalty: 1,
    timeout: 60,
    context_max_tokens: DEFAULT_LLM_CONTEXT_MAX_TOKENS,
    default_max_output_tokens: DEFAULT_LLM_MAX_OUTPUT_TOKENS,
    vision_enabled: false,
    vision_provider: 'custom' as LlmProviderPreset,
    vision_base_url: '',
    vision_api_key: '',
    vision_model: '',
    vision_timeout: 30,
    vision_detail: 'low' as 'low' | 'high' | 'auto' | 'original',
  },
  tts: {
    genie_character: '',
    genie_model_dir: '',
    ref_audio: '',
    ref_text: '',
    lang: 'ja',
    device: 'cpu',
    quality: '质量优先',
    split: '智能切分',
    mode: '串行推理',
    save_mode: '禁用自动保存',
    provider: TTS_PROVIDER,
    base_url: '',
    api_key: '',
    model: 'tts-1',
    voice: 'alloy',
    timeout: 60,
  },
  asr: {
    provider: 'sherpa-onnx-online',
    base_url: '',
    api_key: '',
    timeout: 60,
    sensevoice_model: 'iic/SenseVoiceSmall',
    sensevoice_device: 'cpu',
    sherpa_model_path: '',
    sherpa_tokens_path: '',
    sherpa_num_threads: 2,
    sherpa_provider: 'cpu',
    language: 'zh',
    vad_threshold: 0.5,
    vad_min_silence_ms: DEFAULT_VAD_MIN_SILENCE_MS,
    asr_partial_every: 15,
  },
  svc: {
    provider: 'soulx-service',
    base_url: '',
    speaker_id: 0,
    pitch: 0,
    timeout: 120,
  },
  summary: {
    trigger_messages: 24,
    keep_recent_messages: 8,
    item_max_chars: 140,
    rewrite_interval_messages: 6,
    quality_scorer_mode: 'rule' as QualityScorerMode,
    quality_score_cooldown_seconds: 300,
    quality_score_budget_per_hour: 20,
  },
  memory: {
    backend: 'sqlite',
    sqlite_path: '',
    qdrant_url: '',
    qdrant_api_key: '',
    qdrant_collection: 'memories',
    qdrant_timeout: 10,
    qdrant_auto_start: false,
    qdrant_docker_image: DEFAULT_QDRANT_DOCKER_IMAGE,
    qdrant_docker_container: 'yuizaki-qdrant',
    qdrant_docker_volume: 'yuizaki-qdrant-storage',
    embedding_model: DEFAULT_EMBEDDING_MODEL,
    reranker_enabled: false,
    reranker_model: 'BAAI/bge-reranker-v2-m3',
    reranker_candidate_count: 32,
  },
  system: {
    language: 'zh-CN',
    theme: 'light',
  },
})

const settingSectionGroups = computed(() => [
  {
    id: 'connection',
    label: t('settings.groups.connection'),
    items: [
      { id: 'access' as const, label: t('settings.tabs.access') },
      { id: 'llm' as const, label: t('settings.tabs.llm') },
    ],
  },
  {
    id: 'voice',
    label: t('settings.groups.voice'),
    items: [
      { id: 'voice' as const, label: t('settings.tabs.tts') },
      { id: 'asr' as const, label: t('settings.tabs.asr') },
      { id: 'svc' as const, label: t('settings.tabs.svc') },
    ],
  },
  {
    id: 'memory',
    label: t('settings.groups.memory'),
    items: [
      { id: 'memory' as const, label: t('settings.tabs.memory') },
      { id: 'summary' as const, label: t('settings.tabs.summary') },
    ],
  },
  {
    id: 'application',
    label: t('settings.groups.application'),
    items: [
      { id: 'resources' as const, label: t('settings.tabs.resources') },
      { id: 'system' as const, label: t('settings.tabs.system') },
      { id: 'portable' as const, label: t('settings.tabs.portable') },
    ],
  },
])
const activeSection = ref<SettingSectionId>('llm')
const lastSavedAt = ref('')
const lastApplied = ref<string[]>([])
let saveTimeout: SaveTimeout | null = null
let modelDiscoveryTimeout: SaveTimeout | null = null
let modelDiscoveryRun = 0
let suppressModelDiscovery = false
const pendingSavePatch = ref<SettingsPatch | null>(null)
const failedSavePatch = ref<SettingsPatch | null>(null)
const saveInFlight = ref(false)
let saveFailureCount = 0
let unmounted = false
let saveIdleResolvers: Array<(value: boolean) => void> = []
const settingsMetadata = ref<Record<string, unknown> | null>(null)
const settingsHistory = ref<unknown[]>([])
const memoryRebuildRequest = useDomainRequest<Record<string, unknown>>()
const rollbackSteps = ref(1)
const deleteKey = ref('')
const lookupKey = ref('')
const lookupResult = ref('')
const setKey = ref('')
const setValueJson = ref('')
const llmModelStatus = ref('')
const llmModelAutoSelected = ref(false)
const backendTokenInput = ref('')
const backendTokenStatus = ref<BackendTokenStatusResponse | null>(null)
const backendTokenStatusRequest = useDomainRequest<BackendTokenStatusResponse>()
const backendTokenMutationRequest = useDomainRequest<BackendTokenMutationResponse>()
const localDiscoveryRequest = useDomainRequest<LocalRuntimeDiscoveryResponse>()
const llmProviderPreset = ref<LlmProviderPreset>('custom')
const llmProfiles = reactive<LlmProfiles>({})
const llmImportInput = ref<HTMLInputElement | null>(null)
const llmImporting = ref(false)
const llmExporting = ref(false)
const resourceStatus = ref<ModelResourceStatusPayload | null>(null)
const resourceLoading = ref(false)
const resourceActionKey = ref('')
const resourceMessage = ref('')
const resourceMessageType = ref<AlertType>('info')
const selectedResourceIds = ref<ManagedModelResourceId[]>([])
const activeResourceIds = ref<ManagedModelResourceId[]>([])
const resourceCancelLoading = ref(false)
let resourceProgressPollTimer: ReturnType<typeof window.setInterval> | null = null
let resourceProgressPollBusy = false
const RESOURCE_PROGRESS_POLL_INTERVAL_MS = 1000
const storageStatus = ref<StorageStatusPayload | null>(null)
const storageLoading = ref(false)
const storageActionKey = ref('')

const invalidateLlmModelDiscovery = () => {
  modelDiscoveryRun += 1
  if (modelDiscoveryTimeout) clearTimeout(modelDiscoveryTimeout)
  modelDiscoveryTimeout = null
  llmModelsRequest.reset()
}

const llmProviderOptions = computed(() => getLlmProviderOptions(t('common.custom')))
const llmVisionSettings = computed(() => ({
  enabled: form.llm.vision_enabled,
  provider: form.llm.vision_provider,
  baseUrl: form.llm.vision_base_url,
  apiKey: form.llm.vision_api_key,
  model: form.llm.vision_model,
  timeout: form.llm.vision_timeout,
  detail: form.llm.vision_detail,
}))
const activeLlmProfileLabel = computed(() => (
  llmProviderOptions.value.find((item) => item.value === llmProviderPreset.value)?.label || t('common.custom')
))
const llmProviderNeedsApiKey = computed(() => llmProfileNeedsApiKey({
  provider: llmProviderPreset.value,
  base_url: form.llm.base_url,
}))
const llmApiKeyTagLabel = computed(() => {
  if (!llmProviderNeedsApiKey.value) return t('settings.llm.apiKeyNotRequired')
  return form.llm.api_key.trim() ? t('settings.llm.apiKeySavedTag') : t('settings.llm.apiKeyMissing')
})

const saveAsrField = (field: keyof AsrSettings, value: string | number) => {
  Object.assign(form.asr, { [field]: value })
  debouncedSave({ asr: { [field]: value } })
}
const saveMemoryField = (field: keyof MemorySettings, value: MemorySettings[keyof MemorySettings]) => {
  Object.assign(form.memory, { [field]: value })
  debouncedSave({ memory: { [field]: value } })
}
const saveSummaryField = (field: keyof SummarySettings, value: number | string) => {
  Object.assign(form.summary, { [field]: value })
  debouncedSave({ summary: { [field]: value } })
}
const activeTtsProviderLabel = computed(() => form.tts.provider === 'openai-compatible'
  ? t('settings.tts.provider.openai')
  : t('settings.tts.genieProvider'))
const formatTtsDuration = (value?: number | null): string => {
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue)) return t('settings.tts.metric.empty')
  if (numericValue >= 1000) {
    const seconds = numericValue / 1000
    return `${seconds.toFixed(seconds >= 10 ? 1 : 2)}s`
  }
  return `${Math.max(0, Math.round(numericValue))}ms`
}
const formatTtsLatencySummary = (summary?: { samples: number; p50_ms?: number | null; p95_ms?: number | null }): string => {
  if (!summary?.samples) return ''
  return `P50 ${formatTtsDuration(summary.p50_ms)} · P95 ${formatTtsDuration(summary.p95_ms)} · n=${summary.samples}`
}
const ttsRuntimeError = computed(() => ttsStatusRequest.error || ttsStatus.value?.last_error || '')
const ttsRuntimeLabel = computed(() => {
  const snapshot = ttsStatus.value
  if (ttsStatusRequest.loading) return t('settings.tts.status.refreshing')
  if (ttsStatusRequest.error) return t('settings.tts.status.unreadable')
  if (!snapshot) return t('settings.tts.status.unread')
  if (snapshot.loading) return t('settings.tts.status.loading')
  if (snapshot.warmup_running || snapshot.warming_up) return t('settings.tts.status.warming')
  if (snapshot.inference_running) return t('settings.tts.status.synthesizing')
  if (snapshot.warmup_done) return t('settings.tts.status.ready')
  if (snapshot.available) return t('settings.tts.status.loaded')
  return t('settings.tts.status.cold')
})
const ttsRuntimeTagType = computed<TagType>(() => {
  const snapshot = ttsStatus.value
  if (ttsStatusRequest.error || snapshot?.last_error) return 'danger'
  if (ttsStatusRequest.loading || snapshot?.loading || snapshot?.warmup_running || snapshot?.warming_up || snapshot?.inference_running) return 'warning'
  if (snapshot?.warmup_done || snapshot?.available) return 'success'
  return 'info'
})
const ttsRuntimeMetricItems = computed(() => {
  const snapshot: TtsRuntimeStatusResponse | null = ttsStatus.value
  const capabilities = snapshot?.capabilities
  const transportMode = capabilities?.output_transport === 'unavailable'
    ? undefined
    : capabilities?.output_transport || snapshot?.streaming_transport
  const transport = transportMode === 'pcm_s16le'
    ? t('settings.tts.transport.pcm')
    : transportMode === 'wav'
      ? t('settings.tts.transport.wav')
      : t('i18n.unknown')
  const locality = capabilities?.locality
    ? t(`settings.tts.locality.${capabilities.locality}`)
    : t('i18n.unknown')
  const providerId = snapshot?.provider || capabilities?.provider
  const provider = providerId === 'genie-tts'
    ? t('settings.tts.provider.genie')
    : providerId || t('i18n.unknown')
  const inputMode = capabilities
    ? capabilities.input_text_streaming
      ? t('settings.tts.input.incremental')
      : t('settings.tts.input.segment')
    : t('i18n.unknown')
  const alignment = capabilities?.alignment
    ? t(`settings.tts.alignment.${capabilities.alignment}`)
    : t('i18n.unknown')
  const cancellation = capabilities?.cancellation
    ? t(`settings.tts.cancellation.${capabilities.cancellation}`)
    : t('i18n.unknown')
  return [
    { label: t('settings.tts.metric.provider'), value: `${provider} · ${locality}` },
    { label: t('settings.tts.metric.input'), value: inputMode },
    { label: t('settings.tts.metric.transport'), value: transport },
    { label: t('settings.tts.metric.alignment'), value: alignment },
    { label: t('settings.tts.metric.cancellation'), value: cancellation },
    { label: t('settings.tts.metric.load'), value: formatTtsDuration(snapshot?.last_load_ms), detail: formatTtsLatencySummary(snapshot?.load_latency_summary?.total) },
    { label: t('settings.tts.metric.loadQueue'), value: formatTtsDuration(snapshot?.last_load_queue_ms), detail: formatTtsLatencySummary(snapshot?.load_latency_summary?.queue) },
    { label: t('settings.tts.metric.loadModel'), value: formatTtsDuration(snapshot?.last_load_model_ms), detail: formatTtsLatencySummary(snapshot?.load_latency_summary?.model) },
    { label: t('settings.tts.metric.warmup'), value: formatTtsDuration(snapshot?.last_warmup_ms), detail: formatTtsLatencySummary(snapshot?.warmup_latency_summary?.total) },
    { label: t('settings.tts.metric.warmupQueue'), value: formatTtsDuration(snapshot?.last_warmup_queue_ms), detail: formatTtsLatencySummary(snapshot?.warmup_latency_summary?.queue) },
    { label: t('settings.tts.metric.warmupInference'), value: formatTtsDuration(snapshot?.last_warmup_inference_ms), detail: formatTtsLatencySummary(snapshot?.warmup_latency_summary?.inference) },
    { label: t('settings.tts.metric.wait'), value: formatTtsDuration(snapshot?.last_ready_wait_ms), detail: formatTtsLatencySummary(snapshot?.ready_wait_latency_summary) },
    { label: t('settings.tts.metric.generation'), value: formatTtsDuration(snapshot?.last_generation_ms), detail: formatTtsLatencySummary(snapshot?.generation_latency_summary) },
    { label: t('settings.tts.metric.cancel'), value: formatTtsDuration(snapshot?.last_cancel_ms), detail: formatTtsLatencySummary(snapshot?.cancel_latency_summary) },
  ]
})

const themeOptions = computed(() => [
  { label: t('settings.theme.light'), value: 'light' },
  { label: t('settings.theme.dark'), value: 'dark' },
  { label: t('settings.theme.system'), value: 'system' },
])

const languageOptions = computed(() => supportedLocales.map((value) => ({ value, label: localeLabel(value) })))

const backendTokenConfigured = computed(() => Boolean(backendTokenStatus.value?.hasToken))
const backendTokenRequiresRestart = computed(() => Boolean(backendTokenStatus.value?.requiresRestart))
const backendTokenBusy = computed(() => backendTokenStatusRequest.loading || backendTokenMutationRequest.loading)
const backendTokenPreview = computed(() => {
  const status = backendTokenStatus.value
  if (!status) return ''
  return status.requiresRestart
    ? status.storedTokenPreview || status.tokenPreview
    : status.tokenPreview
})
const backendTokenSourceLabel = computed(() => {
  const source = backendTokenStatus.value?.source
  return source ? t(`settings.backendToken.source.${source}`) : t('i18n.unknown')
})

const mergePatch = (base: SettingsPatch, patch: SettingsPatch): SettingsPatch => {
  const merged: SettingsPatch = { ...base }
  for (const [key, value] of Object.entries(patch)) {
    const existing = merged[key]
    merged[key] = isPlainRecord(existing) && isPlainRecord(value)
      ? mergePatch(existing, value)
      : value
  }
  return merged
}

const numberValue = (value: unknown, fallback: number): number => {
  const next = Number(value)
  return Number.isFinite(next) ? next : fallback
}

const stringValue = (value: unknown, fallback = ''): string => {
  return typeof value === 'string' ? value : fallback
}

const clearReactiveRecord = (record: Record<string, unknown>) => {
  Object.keys(record).forEach((key) => {
    delete record[key]
  })
}

const defaultLlmProfile = (provider: LlmProviderPreset): LlmProfile => ({
  provider,
  base_url: LLM_PROVIDER_BASE_URLS[provider] || '',
  api_key: '',
  model: '',
  temperature: 1.2,
  top_p: 0.9,
  top_k: 500,
  min_p: 0,
  frequency_penalty: 0.2,
  presence_penalty: 0,
  repetition_penalty: 1,
  timeout: 60,
  context_max_tokens: DEFAULT_LLM_CONTEXT_MAX_TOKENS,
  default_max_output_tokens: DEFAULT_LLM_MAX_OUTPUT_TOKENS,
})

const sanitizeLlmProfile = (provider: LlmProviderPreset, value?: Partial<LlmProfile> | null): LlmProfile => {
  const defaults = defaultLlmProfile(provider)
  const nextProvider = normalizeLlmProviderValue(stringValue(value?.provider, provider), stringValue(value?.base_url, defaults.base_url))
  const baseUrl = normalizeOpenAiBaseUrl(stringValue(value?.base_url, defaults.base_url || LLM_PROVIDER_BASE_URLS[nextProvider] || ''))
  return {
    provider: nextProvider,
    base_url: baseUrl,
    api_key: KEYLESS_LLM_PROVIDERS.has(nextProvider) ? '' : stringValue(value?.api_key, ''),
    model: stringValue(value?.model, defaults.model),
    temperature: numberValue(value?.temperature, defaults.temperature),
    top_p: numberValue(value?.top_p, defaults.top_p),
    top_k: numberValue(value?.top_k, defaults.top_k),
    min_p: numberValue(value?.min_p, defaults.min_p),
    frequency_penalty: numberValue(value?.frequency_penalty, defaults.frequency_penalty),
    presence_penalty: numberValue(value?.presence_penalty, defaults.presence_penalty),
    repetition_penalty: numberValue(value?.repetition_penalty, defaults.repetition_penalty),
    timeout: numberValue(value?.timeout, defaults.timeout),
    context_max_tokens: numberValue(value?.context_max_tokens, defaults.context_max_tokens),
    default_max_output_tokens: numberValue(value?.default_max_output_tokens, defaults.default_max_output_tokens),
  }
}

const snapshotLlmProfile = (provider = llmProviderPreset.value): LlmProfile => sanitizeLlmProfile(provider, form.llm)

const applyLlmProfileToForm = (profile: LlmProfile) => {
  form.llm.provider = profile.provider
  form.llm.base_url = profile.base_url
  form.llm.api_key = KEYLESS_LLM_PROVIDERS.has(profile.provider) ? '' : profile.api_key
  form.llm.model = profile.model
  form.llm.temperature = profile.temperature
  form.llm.top_p = profile.top_p
  form.llm.top_k = profile.top_k
  form.llm.min_p = profile.min_p
  form.llm.frequency_penalty = profile.frequency_penalty
  form.llm.presence_penalty = profile.presence_penalty
  form.llm.repetition_penalty = profile.repetition_penalty
  form.llm.timeout = profile.timeout
  form.llm.context_max_tokens = profile.context_max_tokens
  form.llm.default_max_output_tokens = profile.default_max_output_tokens
}

const llmRuntimePatchFromProfile = (profile: LlmProfile): SettingsPatch => ({
  provider: profile.provider,
  base_url: profile.base_url,
  api_key: profile.api_key,
  model: profile.model,
  temperature: profile.temperature,
  top_p: profile.top_p,
  top_k: profile.top_k,
  min_p: profile.min_p,
  frequency_penalty: profile.frequency_penalty,
  presence_penalty: profile.presence_penalty,
  repetition_penalty: profile.repetition_penalty,
  timeout: profile.timeout,
  context_max_tokens: profile.context_max_tokens,
  default_max_output_tokens: profile.default_max_output_tokens,
})

const cloneLlmProfilesPayload = (activeProfile?: LlmProfile): Record<string, LlmProfile> => {
  const payload: Record<string, LlmProfile> = {}
  if (activeProfile) {
    llmProfiles[activeProfile.provider] = activeProfile
  }
  for (const [key, profile] of Object.entries(llmProfiles)) {
    const provider = normalizeLlmProviderValue(key, profile?.base_url || '')
    payload[provider] = sanitizeLlmProfile(provider, profile)
  }
  return payload
}

const saveActiveLlmPatch = (patch: SettingsPatch) => {
  const activeProfile = snapshotLlmProfile()
  llmProfiles[activeProfile.provider] = activeProfile
  debouncedSave({ llm: { ...patch, profiles: cloneLlmProfilesPayload(activeProfile) } })
}

const saveLlmField = (field: LlmProfileField, value: unknown) => {
  if (field === 'api_key' && !llmProviderNeedsApiKey.value) {
    form.llm.api_key = ''
    saveActiveLlmPatch({ api_key: '' })
    return
  }
  saveActiveLlmPatch({ [field]: value })
}

const defaultTtsProfile = (): TtsProfile => {
  return {
    genie_character: '',
    genie_model_dir: '',
    ref_audio: '',
    ref_text: '',
    lang: 'ja',
    device: 'cpu',
    quality: '质量优先',
    split: '智能切分',
    mode: '串行推理',
    save_mode: '禁用自动保存',
    provider: TTS_PROVIDER,
    base_url: '',
    api_key: '',
    model: 'tts-1',
    voice: 'alloy',
    timeout: 60,
  }
}

const sanitizeTtsProfile = (value?: Partial<TtsProfile> | null): TtsProfile => {
  const defaults = defaultTtsProfile()
  const device = stringValue(value?.device, defaults.device)
  return {
    genie_character: stringValue(value?.genie_character, defaults.genie_character),
    genie_model_dir: stringValue(value?.genie_model_dir, defaults.genie_model_dir),
    ref_audio: stringValue(value?.ref_audio, defaults.ref_audio),
    ref_text: stringValue(value?.ref_text, defaults.ref_text),
    lang: stringValue(value?.lang, defaults.lang),
    device: device === 'cuda' ? 'cuda' : 'cpu',
    quality: stringValue(value?.quality, defaults.quality),
    split: stringValue(value?.split, defaults.split),
    mode: stringValue(value?.mode, defaults.mode),
    save_mode: '禁用自动保存',
    provider: value?.provider === 'openai-compatible' ? 'openai-compatible' : TTS_PROVIDER,
    base_url: stringValue(value?.base_url, defaults.base_url),
    api_key: stringValue(value?.api_key, defaults.api_key),
    model: stringValue(value?.model, defaults.model),
    voice: stringValue(value?.voice, defaults.voice),
    timeout: Number.isFinite(Number(value?.timeout)) ? Math.max(1, Number(value?.timeout)) : defaults.timeout,
  }
}

const snapshotTtsProfile = (): TtsProfile => sanitizeTtsProfile({
  ...form.tts,
})

const applyTtsProfileToForm = (profile: TtsProfile) => {
  form.tts.genie_character = profile.genie_character
  form.tts.genie_model_dir = profile.genie_model_dir
  form.tts.ref_audio = profile.ref_audio
  form.tts.ref_text = profile.ref_text
  form.tts.lang = profile.lang
  form.tts.device = profile.device
  form.tts.quality = profile.quality
  form.tts.split = profile.split
  form.tts.mode = profile.mode
  form.tts.save_mode = profile.save_mode
  form.tts.provider = profile.provider
  form.tts.base_url = profile.base_url
  form.tts.api_key = profile.api_key
  form.tts.model = profile.model
  form.tts.voice = profile.voice
  form.tts.timeout = profile.timeout
}

const ttsRuntimePatchFromProfile = (profile: TtsProfile): SettingsPatch => ({
  genie_character: profile.genie_character,
  genie_model_dir: profile.genie_model_dir,
  ref_audio: profile.ref_audio,
  ref_text: profile.ref_text,
  lang: profile.lang,
  device: profile.device,
  quality: profile.quality,
  split: profile.split,
  mode: profile.mode,
  save_mode: profile.save_mode,
  provider: profile.provider,
  base_url: profile.base_url,
  api_key: profile.api_key,
  model: profile.model,
  voice: profile.voice,
  timeout: profile.timeout,
})

const saveActiveTtsPatch = (patch: SettingsPatch) => {
  const activeProfile = snapshotTtsProfile()
  debouncedSave({ tts: { ...ttsRuntimePatchFromProfile(activeProfile), ...patch, save_mode: '禁用自动保存' } })
}

const setTtsFormField = (field: TtsProfileField, value: unknown) => {
  if (field === 'provider') {
    form.tts.provider = value === 'openai-compatible' ? 'openai-compatible' : 'genie-tts'
    return
  }
  if (field === 'device') {
    form.tts.device = value === 'cuda' ? 'cuda' : 'cpu'
    return
  }
  if (field === 'save_mode') {
    form.tts.save_mode = '禁用自动保存'
    return
  }
  form.tts[field] = String(value ?? '')
}

const flushTtsSave = () => {
  void flushPendingSave()
}

const saveTtsField = (field: TtsProfileField, value: unknown, options?: SaveFieldOptions) => {
  setTtsFormField(field, value)
  saveActiveTtsPatch({ [field]: value })
  if (options?.flush) flushTtsSave()
}

const readLlmProfileForStatus = (provider: LlmProviderPreset): LlmProfile => {
  if (provider === llmProviderPreset.value) {
    return sanitizeLlmProfile(provider, { ...form.llm, provider })
  }
  return sanitizeLlmProfile(provider, llmProfiles[provider] || defaultLlmProfile(provider))
}

const getLlmProviderStatus = (provider: LlmProviderPreset): { status: string; statusClass: ProviderStatusClass } => {
  const profile = readLlmProfileForStatus(provider)
  if (!profile.base_url.trim()) {
    return { status: t('settings.providerStatus.missing'), statusClass: 'muted' }
  }
  if (llmProfileNeedsApiKey(profile) && !profile.api_key.trim()) {
    return { status: t('settings.providerStatus.missingKey'), statusClass: 'warning' }
  }
  if (!profile.model.trim()) {
    return { status: t('settings.providerStatus.modelMissing'), statusClass: 'warning' }
  }
  return { status: t('settings.providerStatus.ready'), statusClass: 'ready' }
}

const ttsProfileHasRunnableConfig = (profile: TtsProfile): boolean => {
  return Boolean(profile.genie_character.trim() || (profile.ref_audio.trim() && profile.ref_text.trim()))
}

const llmProviderOptionRows = computed(() => llmProviderOptions.value.map((option) => ({
  ...option,
  ...getLlmProviderStatus(option.value),
})))

const hasLlmEndpoint = computed(() => Boolean(form.llm.base_url.trim() && form.llm.model.trim()))
const hasLlmApiKey = computed(() => !llmProviderNeedsApiKey.value || Boolean(form.llm.api_key.trim()))
const canRequestLlmModels = computed(() => Boolean(normalizeOpenAiBaseUrl(form.llm.base_url) && hasLlmApiKey.value))
const hasTtsVoice = computed(() => {
  return ttsProfileHasRunnableConfig(sanitizeTtsProfile(form.tts))
})
const llmEndpointSummary = computed(() => {
  const value = normalizeOpenAiBaseUrl(form.llm.base_url)
  if (!value) return t('settings.llm.summaryMissing')
  try {
    const url = new URL(value)
    return `${url.hostname}${url.pathname === '/' ? '' : url.pathname}`.replace(/\/$/, '')
  } catch {
    return value
  }
})
const llmEndpointAppendLabel = computed(() => {
  const endpoints = LLM_PROVIDER_ENDPOINTS[llmProviderPreset.value] || LLM_PROVIDER_ENDPOINTS.custom
  return `${endpoints.modelsPath} + ${endpoints.chatPath}`
})
const llmModelSummary = computed(() => form.llm.model.trim() || t('settings.llm.summaryMissing'))
const llmAuthSummary = computed(() => {
  if (!llmProviderNeedsApiKey.value) return t('settings.llm.apiKeyNotRequired')
  return form.llm.api_key.trim() ? t('settings.llm.apiKeySaved') : t('settings.llm.apiKeyMissing')
})
const llmModelSelectOptions = computed(() => {
  const current = form.llm.model.trim()
  const options = [...llmModels.value]
  if (current && !options.includes(current)) {
    options.unshift(current)
  }
  return options
})

const llmDetectionStatus = computed(() => {
  if (llmModelsRequest.loading) return t('settings.llm.detection.detecting')
  if (llmModelsRequest.error) return t('settings.llm.detection.failed')
  if (llmModels.value.length) return llmModelAutoSelected.value ? t('settings.llm.detection.autoSelected') : t('settings.llm.detection.detected')
  return t('settings.llm.detection.none')
})

const llmDetectionTagType = computed(() => {
  if (llmModelsRequest.error) return 'danger'
  if (llmModelsRequest.loading) return 'warning'
  if (llmModels.value.length) return 'success'
  return 'info'
})

const llmRuntimeLabel = computed(() => {
  if (llmStatusRequest.loading) return t('settings.llm.runtime.reading')
  if (llmStatusRequest.error) return t('settings.llm.runtime.failed')
  const snapshot = llmStatus.value
  if (!snapshot) return t('settings.llm.runtime.unread')
  if (snapshot.preconnect_running) return t('settings.llm.runtime.checking')
  if (snapshot.available && snapshot.last_preconnect_ok !== false) return t('settings.llm.runtime.ready')
  return t('settings.llm.runtime.offline')
})

const llmRuntimeTagType = computed<TagType>(() => {
  if (llmStatusRequest.error || (llmStatus.value && !llmStatus.value.available)) return 'danger'
  if (llmStatusRequest.loading || llmStatus.value?.preconnect_running) return 'warning'
  if (llmStatus.value?.available && llmStatus.value.last_preconnect_ok !== false) return 'success'
  return 'info'
})

const llmModelStatusLabel = computed(() => {
  if (llmModelsRequest.loading) return t('settings.llm.modelsReading')
  if (llmModelsRequest.error) return llmModelsRequest.error
  return llmModelStatus.value
})

const canAutoDiscoverLlmModels = computed(() => {
  return shouldAutoDiscoverLlmModels(form.llm.base_url, llmProviderNeedsApiKey.value ? form.llm.api_key : '')
})

const saveBusy = computed(() => updateRequest.loading || saveInFlight.value || Boolean(pendingSavePatch.value))

const saveStatusType = computed<AlertType>(() => {
  if (saveBusy.value) return 'warning'
  if (updateRequest.error) return 'error'
  if (lastSavedAt.value) return 'success'
  return 'info'
})

const saveStatusLabel = computed(() => {
  if (saveBusy.value) return t('settings.status.saving')
  if (updateRequest.error) return t('settings.status.saveFailed')
  if (lastSavedAt.value) return t('settings.status.saved')
  return ''
})

const saveStatusDetail = computed(() => {
  if (saveBusy.value) return t('settings.status.savingShort')
  if (updateRequest.error) return updateRequest.error
  if (lastApplied.value.length) return t('settings.status.applied', { items: lastApplied.value.join(' / ') })
  if (lastSavedAt.value) return t('settings.status.recent', { time: lastSavedAt.value })
  return ''
})

const resourceView = computed(() => normalizeResourceStatus(resourceStatus.value))
const activeDownloadProgress = computed(() => resourceView.value?.activeDownloads ?? [])
const cancellableResourceIds = computed<ManagedModelResourceId[]>(() => [...new Set([
  ...activeResourceIds.value,
  ...activeDownloadProgress.value.map((progress) => progress.resourceId),
])])
type ResourceDownloadOption = {
  id: ManagedModelResourceId
  label: string
  ready: boolean
  version: string
  requiredOnFirstRun: boolean
  license: string
  downloadBytes: number
  resumable: ResumableResourceDownload | null
}
const resourceDownloadOptions = computed<ResourceDownloadOption[]>(() => {
  const status = resourceView.value
  if (!status) return []
  const options: Array<Omit<ResourceDownloadOption, 'resumable'>> = [
    { ...status.sherpaOnline.metadata, id: 'sherpa_online', label: '流式语音识别', ready: status.sherpaOnline.ready },
    { ...status.sherpa.metadata, id: 'sherpa', label: '离线语音识别', ready: status.sherpa.ready },
    { ...status.tts.metadata, id: 'tts', label: 'Genie TTS', ready: status.tts.ready },
    { ...status.embedding.metadata, id: 'embedding', label: '长期记忆嵌入', ready: status.embedding.ready },
    { ...status.soulx.metadata, id: 'soulx', label: 'SoulX 变声', ready: status.soulx.ready },
  ]
  return options.map((item) => ({
    ...item,
    resumable: status.resumableDownloads.find((download) => download.resourceId === item.id) ?? null,
  }))
})

const selectRequiredResources = (status: ModelResourceStatusPayload | null): void => {
  if (!status || selectedResourceIds.value.length > 0) return
  const options = [
    { id: 'sherpa_online' as const, status: status.sherpaOnline },
    { id: 'sherpa' as const, status: status.sherpa },
    { id: 'tts' as const, status: status.tts },
    { id: 'embedding' as const, status: status.embedding },
  ]
  selectedResourceIds.value = options
    .filter((item) => item.status.metadata.requiredOnFirstRun && !item.status.ready)
    .map((item) => item.id)
}

const formatStorageBytes = (value: number): string => {
  const bytes = Math.max(0, Number(value) || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GiB`
}

const formatResourceDownloadBytes = (value: number): string => value > 0 ? formatStorageBytes(value) : '按模型'

const storageCategoryLabel = (id: StorageCategoryId): string => t(`settings.storage.category.${id}`)

const notifySaveIdle = () => {
  if (saveInFlight.value || pendingSavePatch.value) return
  const resolvers = saveIdleResolvers
  saveIdleResolvers = []
  resolvers.forEach((resolve) => resolve(true))
}

const waitForSaveIdle = async () => {
  if (!saveInFlight.value && !pendingSavePatch.value) return
  await new Promise<boolean>((resolve) => saveIdleResolvers.push(resolve))
}

const promoteFailedSavePatch = () => {
  if (!failedSavePatch.value) return
  pendingSavePatch.value = pendingSavePatch.value
    ? mergePatch(failedSavePatch.value, pendingSavePatch.value)
    : failedSavePatch.value
  failedSavePatch.value = null
}

const queueSavePatch = (patch: SettingsPatch) => {
  promoteFailedSavePatch()
  pendingSavePatch.value = pendingSavePatch.value
    ? mergePatch(pendingSavePatch.value, patch)
    : patch
}

const savePatch = async (patch: SettingsPatch) => {
  const result = await patchSettings(patch)
  if (unmounted) return result
  if (result) {
    const appliedSections = result.runtime_applied || result.runtime_changed || []
    lastSavedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    lastApplied.value = appliedSections
    if (appliedSections.includes('tts')) {
      window.setTimeout(() => {
        void loadTtsStatus()
      }, 500)
    }
    void prepareResourcesForSettingsPatch(patch)
  } else {
    ElMessage.error(t('settings.messages.saveFailed'))
  }
  return result
}

const parkFailedSavePatch = (patch: SettingsPatch | null) => {
  if (!patch) return
  const queuedAfterFailure = pendingSavePatch.value
  pendingSavePatch.value = null
  failedSavePatch.value = queuedAfterFailure
    ? mergePatch(patch, queuedAfterFailure)
    : patch
}

let flushSaveAfterUnmount = false

const drainSaveQueue = async (options: { allowAfterUnmount?: boolean } = {}) => {
  if (options.allowAfterUnmount) flushSaveAfterUnmount = true
  if (saveInFlight.value) return
  saveInFlight.value = true
  let activePatch: SettingsPatch | null = null
  try {
    while (pendingSavePatch.value && (!unmounted || flushSaveAfterUnmount)) {
      activePatch = pendingSavePatch.value
      pendingSavePatch.value = null
      const result = await savePatch(activePatch)
      if (!result) {
        saveFailureCount += 1
        parkFailedSavePatch(activePatch)
        break
      }
      activePatch = null
    }
  } catch (error) {
    console.error('[Settings Save Queue]:', error)
    saveFailureCount += 1
    parkFailedSavePatch(activePatch)
    if (!unmounted) ElMessage.error(t('settings.messages.saveFailed'))
  } finally {
    saveInFlight.value = false
    if (!pendingSavePatch.value) flushSaveAfterUnmount = false
    notifySaveIdle()
  }
}

const debouncedSave = (patch: SettingsPatch) => {
  if (unmounted) return
  if (saveTimeout) clearTimeout(saveTimeout)
  queueSavePatch(patch)

  saveTimeout = setTimeout(() => {
    saveTimeout = null
    void drainSaveQueue()
  }, 1000)
}

const applyLlmVisionPatch = (patch: LlmVisionPatch) => {
  const settingsPatch: Record<string, unknown> = {}
  if (patch.enabled !== undefined) {
    form.llm.vision_enabled = patch.enabled
    settingsPatch.vision_enabled = patch.enabled
  }
  if (patch.provider !== undefined) {
    form.llm.vision_provider = patch.provider
    settingsPatch.vision_provider = patch.provider
  }
  if (patch.baseUrl !== undefined) {
    form.llm.vision_base_url = patch.baseUrl
    settingsPatch.vision_base_url = patch.baseUrl
  }
  if (patch.apiKey !== undefined) {
    form.llm.vision_api_key = patch.apiKey
    settingsPatch.vision_api_key = patch.apiKey
  }
  if (patch.model !== undefined) {
    form.llm.vision_model = patch.model
    settingsPatch.vision_model = patch.model
  }
  if (patch.timeout !== undefined) {
    form.llm.vision_timeout = patch.timeout
    settingsPatch.vision_timeout = patch.timeout
  }
  if (patch.detail !== undefined) {
    form.llm.vision_detail = patch.detail
    settingsPatch.vision_detail = patch.detail
  }
  if (Object.keys(settingsPatch).length) debouncedSave({ llm: settingsPatch })
}

const flushPendingSave = async () => {
  const failureCountBeforeFlush = saveFailureCount
  if (saveTimeout) {
    clearTimeout(saveTimeout)
    saveTimeout = null
  }
  promoteFailedSavePatch()
  void drainSaveQueue()
  await waitForSaveIdle()
  return saveFailureCount === failureCountBeforeFlush && !failedSavePatch.value
}

const setMemoryBackend = (backend: string) => {
  if (form.memory.backend === backend) return
  form.memory.backend = backend
  debouncedSave({ memory: { backend } })
}

const handleMemoryBackendChange = (value: string | number | boolean) => {
  setMemoryBackend(String(value))
}

const waitForMemoryBackend = async (expectedBackend: string) => {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const status = await memoryClient.getIndexStatus()
    if (status.backend === expectedBackend) return true
    await new Promise<void>((resolve) => window.setTimeout(resolve, 100))
  }
  return false
}

const handleRebuildMemoryIndex = async () => {
  if (form.memory.backend === 'inmemory') {
    ElMessage.warning('In-memory 后端没有持久化索引可重建')
    return
  }
  if (!(await flushPendingSave())) return
  if (!(await waitForMemoryBackend(form.memory.backend))) {
    ElMessage.error('记忆后端仍在切换，请稍后重试')
    return
  }
  const result = await memoryRebuildRequest.execute(() => memoryClient.rebuildIndex())
  if (!result) {
    ElMessage.error(memoryRebuildRequest.error || t('settings.messages.memoryRebuildFailed'))
    return
  }
  const indexed = Number(result.indexed_count ?? 0)
  const skipped = Number(result.skipped_count ?? 0)
  ElMessage.success(t('settings.messages.memoryRebuildOk', { count: indexed, skipped }))
}

const handleSystemThemeChange = (value: string | number | boolean) => {
  const rawTheme = String(value || 'light')
  const nextTheme = ['light', 'dark', 'system'].includes(rawTheme) ? rawTheme : 'light'
  form.system.theme = nextTheme
  settingsStore.state.system.theme = nextTheme
  debouncedSave({ system: { theme: nextTheme } })
}

const handleSystemLanguageChange = async (value: string | number | boolean) => {
  const nextLocale = normalizeLocale(String(value ?? ''))
  form.system.language = nextLocale
  try {
    await setLocale(nextLocale)
    ElMessage.success(t('language.changed'))
  } catch {
    ElMessage.warning(t('common.localOnly'))
  }
}

const updateDesktopInputBindings = async (patch: InputBindingSettingsPatch) => {
  try {
    await inputBindingsStore.update(patch)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '桌面快捷键保存失败')
  }
}

const setPushToTalkEnabled = (value: string | number | boolean) => {
  void updateDesktopInputBindings({ pushToTalk: { enabled: Boolean(value) } })
}

const setPushToTalkMouseButton = (value: unknown) => {
  const mouseButton: MouseSideButton = Number(value) === 4 ? 4 : 5
  void updateDesktopInputBindings({ pushToTalk: { mouseButton } })
}

const keyboardEventKey = (event: KeyboardEvent): string | null => {
  const aliases: Record<string, string> = {
    ' ': 'Space',
    ArrowUp: 'Up',
    ArrowDown: 'Down',
    ArrowLeft: 'Left',
    ArrowRight: 'Right',
    Esc: 'Escape',
  }
  const key = aliases[event.key] ?? event.key
  if (['Control', 'Shift', 'Alt', 'Meta'].includes(key)) return null
  if (/^[a-z0-9]$/i.test(key)) return key.toUpperCase()
  if (/^F(?:[1-9]|1\d|2[0-4])$/.test(key)) return key
  if (['Space', 'Tab', 'Enter', 'Escape', 'Up', 'Down', 'Left', 'Right', 'Home', 'End', 'PageUp', 'PageDown', 'Insert', 'Delete'].includes(key)) {
    return key
  }
  return null
}

const captureKeyboardBinding = (action: KeyboardShortcutAction, event: KeyboardEvent) => {
  const key = keyboardEventKey(event)
  if (!key) return
  const modifiers: string[] = []
  if (event.ctrlKey) modifiers.push('Control')
  if (event.metaKey) modifiers.push('Command')
  if (event.altKey) modifiers.push('Alt')
  if (event.shiftKey) modifiers.push('Shift')
  if (!modifiers.length && !key.startsWith('F')) {
    ElMessage.warning('字母、数字和导航键至少需要一个修饰键')
    return
  }
  void updateDesktopInputBindings({ keyboard: { [action]: [...modifiers, key].join('+') } })
  ;(event.currentTarget as HTMLInputElement | null)?.blur()
}

const clearKeyboardBinding = (action: KeyboardShortcutAction) => {
  void updateDesktopInputBindings({ keyboard: { [action]: '' } })
}

const resetDesktopInputBindings = async () => {
  try {
    await inputBindingsStore.reset()
    ElMessage.success('桌面输入已恢复默认')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '恢复默认失败')
  }
}

const discoverLocalRuntime = async (): Promise<LocalRuntimeDiscoveryResponse | null> => {
  const result = await localDiscoveryRequest.execute(() => settingsClient.discoverLocal())
  if (!result) {
    ElMessage.error(localDiscoveryRequest.error || t('settings.messages.localDetectFailed'))
    return null
  }
  return result
}

const firstReadyCandidate = (items: LocalRuntimeCandidate[] | undefined): LocalRuntimeCandidate | null => {
  return items?.find((item) => item.ok) ?? null
}

const warnNoLocalCandidate = (service: string) => {
  ElMessage.warning(t('settings.messages.localDetectNone', { service }))
}

const notifyLocalCandidateApplied = (candidate: LocalRuntimeCandidate, fallback: string) => {
  ElMessage.success(t('settings.messages.localDetectApplied', { service: candidate.label || candidate.provider || candidate.backend || fallback }))
}

const applyLocalLlmDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  if (!discovery) return
  const currentProvider = llmProviderPreset.value
  const candidate = discovery.llm.find((item) => item.ok && item.provider === currentProvider)
    ?? firstReadyCandidate(discovery.llm)
  if (!candidate?.base_url) {
    warnNoLocalCandidate('LLM')
    return
  }

  const provider = normalizeLlmProviderValue(String(candidate.provider || ''), candidate.base_url)
  const models = (candidate.models || []).map(String).filter(Boolean)
  const nextModel = models.length
    ? choosePreferredLlmModel(models, provider)
    : (llmProfiles[provider]?.model || '')
  invalidateLlmModelDiscovery()
  const nextProfile = sanitizeLlmProfile(provider, {
    ...form.llm,
    provider,
    base_url: candidate.base_url,
    api_key: '',
    model: nextModel,
  })
  llmProviderPreset.value = provider
  llmModels.value = models
  llmModelAutoSelected.value = Boolean(models.length && nextModel)
  llmModelStatus.value = candidate.message || ''
  applyLlmProfileToForm(nextProfile)
  llmProfiles[provider] = nextProfile
  saveActiveLlmPatch(llmRuntimePatchFromProfile(nextProfile))
  notifyLocalCandidateApplied(candidate, 'LLM')
}

const applyLocalAsrDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  const candidate = firstReadyCandidate(discovery?.asr)
  if (!candidate?.base_url) {
    warnNoLocalCandidate('ASR')
    return
  }
  const provider = String(candidate.provider || 'sherpa-onnx-online')
  form.asr.provider = provider
  form.asr.base_url = candidate.base_url
  debouncedSave({ asr: { provider, base_url: candidate.base_url } })
  notifyLocalCandidateApplied(candidate, 'ASR')
}

const applyLocalTtsDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  const candidate = firstReadyCandidate(discovery?.tts)
  if (!candidate) {
    warnNoLocalCandidate('Genie TTS')
    return
  }
  const patch: SettingsPatch = { provider: TTS_PROVIDER }
  const modelDir = typeof candidate.model_dir === 'string' ? candidate.model_dir : ''
  if (modelDir && candidate.model_dir_exists) {
    form.tts.genie_model_dir = modelDir
    patch.genie_model_dir = modelDir
  }
  saveActiveTtsPatch(patch)
  if (!candidate.model_dir_exists && candidate.installed) {
    ElMessage.success(t('settings.messages.localTtsLibraryDetected'))
    return
  }
  notifyLocalCandidateApplied(candidate, 'Genie TTS')
}

const saveSvcField = (field: keyof SvcSettings, value: string | number) => {
  form.svc[field] = value as never
  debouncedSave({ svc: { [field]: value } })
}

const applyLocalSvcDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  const candidate = firstReadyCandidate(discovery?.svc)
  if (!candidate?.base_url) {
    warnNoLocalCandidate('SoulX SVC')
    return
  }
  form.svc.provider = 'soulx-service'
  form.svc.base_url = candidate.base_url
  debouncedSave({ svc: { provider: 'soulx-service', base_url: candidate.base_url } })
  notifyLocalCandidateApplied(candidate, 'SoulX SVC')
}

const applyLocalMemoryDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  const candidate = firstReadyCandidate(discovery?.memory)
  if (!candidate?.qdrant_url) {
    warnNoLocalCandidate('Qdrant')
    return
  }
  form.memory.backend = 'qdrant'
  form.memory.qdrant_url = candidate.qdrant_url
  debouncedSave({ memory: { backend: 'qdrant', qdrant_url: candidate.qdrant_url } })
  notifyLocalCandidateApplied(candidate, 'Qdrant')
}

const applyLlmProviderPreset = (value: string | number | boolean) => {
  const preset = String(value) as LlmProviderPreset
  if (!(preset in LLM_PROVIDER_BASE_URLS)) {
    llmProviderPreset.value = 'custom'
    return
  }

  const previousProvider = normalizeLlmProviderValue(form.llm.provider, form.llm.base_url)
  const previousProfile = snapshotLlmProfile(previousProvider)
  llmProfiles[previousProfile.provider] = previousProfile
  llmProviderPreset.value = preset
  const nextProfile = sanitizeLlmProfile(preset, llmProfiles[preset] || defaultLlmProfile(preset))
  applyLlmProfileToForm(nextProfile)
  llmProfiles[preset] = snapshotLlmProfile(preset)
  llmModelAutoSelected.value = false
  llmModels.value = []
  llmModelStatus.value = ''
  saveActiveLlmPatch(llmRuntimePatchFromProfile(nextProfile))
  scheduleLlmModelDiscovery({ manual: false })
}

const resetCurrentLlmProfile = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.resetProviderProfileMessage', { provider: activeLlmProfileLabel.value }),
      t('settings.confirm.resetProviderProfileTitle'),
      {
        confirmButtonText: t('common.reset'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const provider = llmProviderPreset.value
  const nextProfile = defaultLlmProfile(provider)
  llmProfiles[provider] = nextProfile
  applyLlmProfileToForm(nextProfile)
  llmModels.value = []
  llmModelStatus.value = ''
  llmModelAutoSelected.value = false
  saveActiveLlmPatch(llmRuntimePatchFromProfile(nextProfile))
  scheduleLlmModelDiscovery({ manual: false })
  ElMessage.success(t('settings.messages.providerProfileReset'))
}

const resetCurrentTtsProfile = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.resetProviderProfileMessage', { provider: activeTtsProviderLabel.value }),
      t('settings.confirm.resetProviderProfileTitle'),
      {
        confirmButtonText: t('common.reset'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const nextProfile = defaultTtsProfile()
  applyTtsProfileToForm(nextProfile)
  saveActiveTtsPatch(ttsRuntimePatchFromProfile(nextProfile))
  ElMessage.success(t('settings.messages.providerProfileReset'))
}

const shouldAutoSelectLlmModel = (models: string[], options?: LlmModelDiscoveryOptions): boolean => {
  const current = form.llm.model.trim()
  if (options?.forceAutoSelect) return true
  if (!current) return true
  return !models.includes(current)
}

const applyDetectedLlmModel = (models: string[], options?: LlmModelDiscoveryOptions) => {
  if (!shouldAutoSelectLlmModel(models, options)) {
    llmModelAutoSelected.value = false
    return
  }

  const nextModel = choosePreferredLlmModel(models, llmProviderPreset.value)
  if (!nextModel || form.llm.model.trim() === nextModel) return

  form.llm.model = nextModel
  llmModelAutoSelected.value = true
  saveLlmField('model', nextModel)
}

const firstString = (source: SettingsPatch, keys: string[]): string | undefined => {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'string') return value
  }
  return undefined
}

const firstNumber = (source: SettingsPatch, keys: string[]): number | undefined => {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value)
  }
  return undefined
}

const normalizeLlmProviderValue = (value: string | undefined, baseUrl = ''): LlmProviderPreset => {
  const normalized = value?.trim().toLowerCase()
  if (normalized && normalized in LLM_PROVIDER_BASE_URLS) return normalized as LlmProviderPreset
  if (normalized === 'openai') return 'chatgpt'
  if (normalized === 'anthropic') return 'claude'
  if (normalized === 'xai' || normalized === 'x-ai') return 'grok'
  if (normalized === 'dashscope') return 'qwen'
  if (normalized === 'ollama') return 'ollama'
  if (normalized === 'lm-studio' || normalized === 'lm_studio') return 'lmstudio'
  if (normalized === 'azure' || normalized === 'azure-compatible' || normalized === 'openai-compatible') return 'custom'
  return inferLlmProviderPreset(baseUrl)
}

const normalizeLlmProfilePayload = (payload: unknown): SettingsPatch | null => {
  if (!isPlainRecord(payload)) return null
  if (isPlainRecord(payload.llm)) return { llm: payload.llm }

  const nestedProfile = ['connectionProfile', 'profile', 'preset', 'api', 'connection']
    .map((key) => payload[key])
    .find(isPlainRecord)
  const source = nestedProfile || payload
  const llm: SettingsPatch = {}
  const stringFields: Array<[keyof typeof form.llm, string[]]> = [
    ['provider', ['provider', 'llmProvider', 'providerPreset']],
    ['base_url', ['base_url', 'baseUrl', 'api_url', 'apiUrl', 'server_url', 'serverUrl', 'endpoint']],
    ['api_key', ['api_key', 'apiKey', 'key', 'token', 'secret']],
    ['model', ['model', 'model_name', 'modelName', 'chat_model', 'chatModel']],
  ]
  for (const [target, keys] of stringFields) {
    const value = firstString(source, keys)
        if (typeof value === 'string') {
          llm[target] = target === 'base_url'
            ? normalizeOpenAiBaseUrl(value)
            : target === 'provider'
              ? normalizeLlmProviderValue(value, firstString(source, ['base_url', 'baseUrl', 'endpoint']) || '')
              : value
        }
  }

  const numberFields: Array<[keyof typeof form.llm, string[]]> = [
    ['timeout', ['timeout', 'request_timeout', 'requestTimeout']],
    ['context_max_tokens', ['context_max_tokens', 'contextMaxTokens', 'context_size', 'contextSize', 'max_context', 'maxContext', 'openai_max_context', 'openaiMaxContext']],
    ['default_max_output_tokens', ['default_max_output_tokens', 'max_output_tokens', 'maxOutputTokens', 'max_tokens', 'maxTokens', 'openai_max_tokens', 'openaiMaxTokens']],
    ['temperature', ['temperature', 'temp']],
    ['top_p', ['top_p', 'topP']],
    ['top_k', ['top_k', 'topK']],
    ['min_p', ['min_p', 'minP']],
    ['frequency_penalty', ['frequency_penalty', 'frequencyPenalty']],
    ['presence_penalty', ['presence_penalty', 'presencePenalty']],
    ['repetition_penalty', ['repetition_penalty', 'repetitionPenalty', 'repeat_penalty', 'repeatPenalty', 'rep_penalty', 'repPenalty']],
  ]
  for (const [target, keys] of numberFields) {
    const value = firstNumber(source, keys)
    if (typeof value === 'number') llm[target] = value
  }

  return Object.keys(llm).length ? { llm } : null
}

const triggerLlmImport = () => {
  llmImportInput.value?.click()
}

const saveJsonDownload = (payload: unknown, filename: string) => {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

const buildLlmProfilePayload = (useCurrentValues: boolean) => {
  const profile = useCurrentValues ? snapshotLlmProfile() : defaultLlmProfile('custom')
  return {
    kind: 'yuizaki-llm-profile',
    version: 1,
    credentialMode: 'provider-profile',
    provider: profile.provider,
    connectionProfile: {
      name: useCurrentValues ? activeLlmProfileLabel.value : t('common.custom'),
      credentialMode: 'provider-profile',
      provider: profile.provider,
      baseUrl: normalizeOpenAiBaseUrl(profile.base_url),
      apiKey: profile.api_key,
      modelName: profile.model,
      timeout: profile.timeout,
      contextMaxTokens: profile.context_max_tokens,
      maxTokens: profile.default_max_output_tokens,
      temperature: profile.temperature,
      topP: profile.top_p,
      topK: profile.top_k,
      minP: profile.min_p,
      frequencyPenalty: profile.frequency_penalty,
      presencePenalty: profile.presence_penalty,
      repetitionPenalty: profile.repetition_penalty,
    },
  }
}

const downloadLlmProfileTemplate = () => {
  saveJsonDownload(buildLlmProfilePayload(false), 'yuizaki-llm-profile-template.json')
  ElMessage.success(t('settings.messages.templateOk'))
}

const applyImportedSettings = async (payload: unknown) => {
  const normalized = normalizeLlmProfilePayload(payload)
  if (!normalized) {
    ElMessage.error(t('settings.messages.importInvalid'))
    return
  }
  llmImporting.value = true
  try {
    if (!(await flushPendingSave())) return
    const result = await settingsClient.importPayload(normalized)
    lastSavedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    lastApplied.value = result.runtime_applied || result.runtime_changed || []
    await loadSettings()
    hydrateForm()
    scheduleLlmModelDiscovery({ manual: false })
    ElMessage.success(t('settings.messages.importOk'))
  } catch (error) {
    ElMessage.error(t('settings.messages.importFailed', { message: error instanceof Error ? error.message : t('common.error.unknown') }))
  } finally {
    llmImporting.value = false
  }
}

const handleLlmImportFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    const payload = JSON.parse(await file.text()) as unknown
    await applyImportedSettings(payload)
  } catch (error) {
    ElMessage.error(t('settings.messages.importFailed', { message: error instanceof Error ? error.message : t('settings.messages.importInvalid') }))
  }
}

const exportLlmProfile = async () => {
  llmExporting.value = true
  try {
    const stamp = new Date().toISOString().slice(0, 10)
    saveJsonDownload(buildLlmProfilePayload(true), `yuizaki-llm-profile-${stamp}.json`)
    ElMessage.success(t('settings.messages.exportOk'))
  } catch (error) {
    ElMessage.error(t('settings.messages.exportFailed', { message: error instanceof Error ? error.message : t('common.error.unknown') }))
  } finally {
    llmExporting.value = false
  }
}

const refreshBackendTokenStatus = async () => {
  const result = await backendTokenStatusRequest.execute(() => settingsClient.backendTokenStatus())
  if (result) {
    backendTokenStatus.value = result
  }
  return result
}

const saveBackendToken = async () => {
  const token = backendTokenInput.value.trim()
  if (!token) {
    ElMessage.warning(t('settings.messages.backendTokenRequired'))
    return
  }

  const result = await backendTokenMutationRequest.execute(() => settingsClient.setBackendToken(token))
  if (!result?.ok) return

  backendTokenInput.value = ''
  await refreshBackendTokenStatus()
  ElMessage.success(result.requiresRestart ? t('settings.messages.backendTokenSavedRestart') : t('settings.messages.backendTokenSaved'))
}

const resetBackendToken = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.resetBackendTokenMessage'),
      t('settings.confirm.resetBackendTokenTitle'),
      {
        confirmButtonText: t('settings.backendToken.reset'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const result = await backendTokenMutationRequest.execute(() => settingsClient.resetBackendToken())
  if (!result?.ok) return

  backendTokenInput.value = ''
  await refreshBackendTokenStatus()
  ElMessage.success(result.requiresRestart ? t('settings.messages.backendTokenResetRestart') : t('settings.messages.backendTokenReset'))
}

const handleTestLlm = async () => {
  if (!(await flushPendingSave())) return
  const res = await testLlm()
  if (res?.status === 'ok' || res?.ok) {
    ElMessage.success(t('settings.messages.llmOk'))
  } else if (res) {
    ElMessage.error(t('settings.messages.llmFailed', { message: res.message || t('common.error.unknown') }))
  }
}

const refreshLlmStatus = async () => {
  await loadLlmStatus()
}

const refreshTtsStatus = async (): Promise<TtsRuntimeStatusResponse | null> => {
  return loadTtsStatus()
}

const queueTtsWarmup = async () => {
  const snapshot = ttsStatus.value
  if (warmupTtsRequest.loading || snapshot?.warmup_done || snapshot?.warmup_running || snapshot?.warming_up) return
  const result = await warmupTts()
  if (result?.ok) {
    void loadTtsStatus()
  }
}

const handleWarmupTts = async () => {
  if (!hasTtsVoice.value) {
    ElMessage.warning(t('settings.messages.ttsWarmupNeedsConfig'))
    return
  }
  if (!(await flushPendingSave())) return
  const result = await warmupTts()
  await refreshTtsStatus()
  if (result?.ok || result?.queued) {
    ElMessage.success(t('settings.messages.ttsWarmupQueued'))
  } else if (result) {
    ElMessage.error(result.message || t('settings.messages.ttsWarmupFailed'))
  }
}

const handleTestTts = async () => {
  if (!(await flushPendingSave())) return
  const res = await testTts()
  await refreshTtsStatus()
  if (res?.status === 'ok' || res?.ok) {
    ElMessage.success(t('settings.messages.ttsOk'))
  } else if (res) {
    ElMessage.error(t('settings.messages.ttsFailed', { message: res.message || t('settings.messages.ttsHint') }))
  }
}

const loadSettingsAdmin = async () => {
  try {
    settingsMetadata.value = await settingsClient.metadata()
    const history = await settingsClient.history()
    settingsHistory.value = history.history
  } catch (error) {
    settingsMetadata.value = null
    settingsHistory.value = []
    console.info('[Settings] Admin metadata unavailable:', error)
  }
}

const rollbackSettings = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.rollbackMessage', { steps: rollbackSteps.value }),
      t('settings.confirm.rollbackTitle'),
      {
        confirmButtonText: t('common.rollback'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  try {
    if (!(await flushPendingSave())) return
    await settingsClient.rollback(rollbackSteps.value)
    ElMessage.success(t('settings.messages.rollbackOk'))
    await loadSettings()
    hydrateForm()
    await loadSettingsAdmin()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('common.error.unknown'))
  }
}

const clearSettingsHistory = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.clearHistoryMessage'),
      t('settings.confirm.clearHistoryTitle'),
      {
        confirmButtonText: t('settings.admin.clearHistory'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  try {
    await settingsClient.clearHistory()
    settingsHistory.value = []
    ElMessage.success(t('settings.messages.historyCleared'))
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('common.error.unknown'))
  }
}

const stopResourceProgressPolling = () => {
  if (resourceProgressPollTimer === null) return
  window.clearInterval(resourceProgressPollTimer)
  resourceProgressPollTimer = null
}

const pollResourceStatus = async () => {
  if (resourceProgressPollBusy) return
  resourceProgressPollBusy = true
  try {
    const hadActiveDownloads = activeDownloadProgress.value.length > 0
    const progress = await resourceClient.progress()
    if (hadActiveDownloads && progress.activeDownloads.length === 0 && !resourceActionKey.value) {
      resourceStatus.value = normalizeResourceStatus(await resourceClient.status())
    } else if (resourceStatus.value) {
      resourceStatus.value = {
        ...resourceStatus.value,
        activeDownloads: progress.activeDownloads,
      }
    }
  } catch {
    // The foreground command reports actionable failures; polling stays silent.
  } finally {
    resourceProgressPollBusy = false
    if (!resourceActionKey.value && activeDownloadProgress.value.length === 0) stopResourceProgressPolling()
  }
}

const syncResourceProgressPolling = () => {
  const shouldPoll = Boolean(resourceActionKey.value) || activeDownloadProgress.value.length > 0
  if (!shouldPoll || document.hidden) {
    stopResourceProgressPolling()
    return
  }
  if (resourceProgressPollTimer !== null) return
  resourceProgressPollTimer = window.setInterval(() => void pollResourceStatus(), RESOURCE_PROGRESS_POLL_INTERVAL_MS)
}

const handleResourceProgressVisibility = () => {
  if (document.hidden) {
    stopResourceProgressPolling()
    return
  }
  syncResourceProgressPolling()
  if (resourceActionKey.value || activeDownloadProgress.value.length > 0) void pollResourceStatus()
}

const loadResourceStatus = async () => {
  resourceLoading.value = true
  try {
    resourceStatus.value = normalizeResourceStatus(await resourceClient.status())
    selectRequiredResources(resourceStatus.value)
    syncResourceProgressPolling()
  } catch (error) {
    const message = error instanceof Error ? error.message : t('settings.resource.statusFailed')
    resourceMessage.value = message
    resourceMessageType.value = 'error'
    ElMessage.error(message)
  } finally {
    resourceLoading.value = false
  }
}

const runResourceCommand = async (
  key: string,
  task: () => Promise<ResourceCommandResult>,
  resources: ManagedModelResourceId[] = [],
) => {
  if (resourceActionKey.value || activeDownloadProgress.value.length > 0) {
    ElMessage.warning('已有资源任务正在执行')
    return
  }
  resourceActionKey.value = key
  activeResourceIds.value = [...resources]
  resourceMessage.value = ''
  syncResourceProgressPolling()
  try {
    const result = await task()
    resourceStatus.value = normalizeResourceStatus(result.status)
    resourceMessage.value = result.message
    resourceMessageType.value = result.success ? 'success' : 'warning'
    if (result.success) {
      ElMessage.success(result.message)
    } else {
      ElMessage.warning(result.message)
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : t('settings.resource.taskFailed')
    resourceMessage.value = message
    resourceMessageType.value = 'error'
    ElMessage.error(message)
  } finally {
    resourceActionKey.value = ''
    activeResourceIds.value = []
    syncResourceProgressPolling()
  }
}

const cancelActiveResourceDownloads = async () => {
  const resources = [...cancellableResourceIds.value]
  if (resources.length === 0 || resourceCancelLoading.value) return
  resourceCancelLoading.value = true
  try {
    const result = await resourceClient.cancel(resources)
    resourceStatus.value = normalizeResourceStatus(result.status)
    const message = result.cancelled.length > 0 ? `已取消 ${result.cancelled.length} 个下载任务` : '没有可取消的下载任务'
    resourceMessage.value = message
    resourceMessageType.value = result.cancelled.length > 0 ? 'success' : 'info'
    if (result.cancelled.length > 0) {
      ElMessage.success(message)
    } else {
      ElMessage.info(message)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('settings.resource.taskFailed'))
  } finally {
    resourceCancelLoading.value = false
  }
}

const prepareResource = async (resourceId: ManagedModelResourceId) => {
  switch (resourceId) {
    case 'sherpa_online':
      await runResourceCommand('sherpa-online-download', () => resourceClient.prepareSherpaOnline(), [resourceId])
      break
    case 'soulx':
      await runResourceCommand('soulx-download', () => resourceClient.prepareSoulx(), [resourceId])
      break
    case 'sherpa':
      await runResourceCommand('sherpa-download', () => resourceClient.prepareSherpa(), [resourceId])
      break
    case 'embedding':
      await runResourceCommand('embedding-prefetch', () => resourceClient.prepareEmbedding(), [resourceId])
      break
    case 'tts':
      await runResourceCommand('tts-prefetch', () => resourceClient.prepareTts(), [resourceId])
      break
  }
}

const importSoulxReference = () => runResourceCommand(
  'soulx-reference',
  () => resourceClient.importSoulxReference(),
)

const removeModelResource = async (
  resourceId: ManagedModelResourceId,
  label: string,
  metadata: ManagedResourceMetadata,
) => {
  if (resourceActionKey.value) {
    ElMessage.warning('请先完成或取消当前资源任务')
    return
  }
  const usage = metadata.inUseBy.length > 0 ? ` · 使用中：${metadata.inUseBy.join(' / ')}` : ''
  try {
    await ElMessageBox.confirm(
      `${label} · ${formatResourceDownloadBytes(metadata.downloadBytes)}${usage}`,
      '永久卸载模型',
      {
        confirmButtonText: '永久卸载',
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  resourceActionKey.value = `remove-${resourceId}`
  try {
    const result = await resourceClient.remove([resourceId])
    resourceStatus.value = normalizeResourceStatus(result.status)
    resourceMessage.value = result.message
    resourceMessageType.value = result.success ? 'success' : 'warning'
    if (result.success) {
      ElMessage.success(`已永久卸载 ${label}，释放 ${formatStorageBytes(result.reclaimedBytes)}`)
    } else {
      ElMessage.warning(result.failed.map((item) => item.reason).join('; ') || result.message)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('settings.resource.taskFailed'))
  } finally {
    resourceActionKey.value = ''
  }
}

const handlePortableImported = async (): Promise<void> => {
  await loadSettings()
  hydrateForm()
  await loadSettingsAdmin()
}

const handleLlmModelChange = (value: string | number | boolean) => {
  llmModelAutoSelected.value = false
  saveLlmField('model', String(value ?? ''))
}

const loadStorageStatus = async () => {
  storageLoading.value = true
  try {
    storageStatus.value = normalizeStorageStatus(await resourceClient.storageStatus())
  } catch (error) {
    storageStatus.value = null
    ElMessage.error(error instanceof Error ? error.message : t('settings.storage.loadFailed'))
  } finally {
    storageLoading.value = false
  }
}

const resourceIdsForSettingsPatch = (patch: SettingsPatch): ManagedModelResourceId[] => {
  const ids: ManagedModelResourceId[] = []
  const asr = patch.asr as { provider?: unknown } | undefined
  const tts = patch.tts as Record<string, unknown> | undefined
  const svc = patch.svc as { provider?: unknown } | undefined
  const memory = patch.memory as { embedding_model?: unknown } | undefined
  if (asr?.provider === 'sherpa-onnx-online') ids.push('sherpa_online', 'sherpa')
  if (asr?.provider === 'sherpa-onnx') ids.push('sherpa')
  if (tts) ids.push('tts')
  if (svc?.provider === 'soulx-service') ids.push('soulx')
  if (typeof memory?.embedding_model === 'string') ids.push('embedding')
  return [...new Set(ids)]
}

const prepareResourcesForSettingsPatch = async (patch: SettingsPatch) => {
  const ids = resourceIdsForSettingsPatch(patch)
  if (ids.length === 0) return
  await runResourceCommand('first-use-download', () => resourceClient.prepare(ids), ids)
}

const downloadSelectedResources = async () => {
  const requiredMissing = resourceDownloadOptions.value
    .filter((item) => item.requiredOnFirstRun && !item.ready)
    .map((item) => item.id)
  const ids = [...new Set([...selectedResourceIds.value, ...requiredMissing])]
  if (ids.length === 0) return
  await runResourceCommand('selected-download', () => resourceClient.prepare(ids), ids)
  selectedResourceIds.value = selectedResourceIds.value.filter((id) => {
    const item = resourceDownloadOptions.value.find((option) => option.id === id)
    return item ? !item.ready : false
  })
}

const refreshResourcePanel = async () => {
  await Promise.all([loadResourceStatus(), loadStorageStatus()])
}

const cleanupStorage = async (targets: StorageCleanupTarget[]) => {
  if (!storageStatus.value || !targets.length) return
  const selected = storageStatus.value.categories.filter((item) => targets.includes(item.id as StorageCleanupTarget))
  const selectedFiles = selected.reduce((sum, item) => sum + item.files, 0)
  const selectedBytes = selected.reduce((sum, item) => sum + item.bytes, 0)
  const selectedLabels = selected.map((item) => storageCategoryLabel(item.id)).join(' / ')
  try {
    await ElMessageBox.confirm(
      `${selectedLabels} · ${selectedFiles} ${t('settings.storage.files')} · ${formatStorageBytes(selectedBytes)}`,
      t('settings.storage.confirmTitle'),
      {
        confirmButtonText: t('settings.storage.confirm'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  storageActionKey.value = targets.length > 1 ? 'all' : targets[0]
  try {
    const result = await resourceClient.cleanupStorage(targets)
    storageStatus.value = normalizeStorageStatus(result.status)
    if (result.failed_files > 0) {
      ElMessage.warning(t('settings.storage.partial', { count: result.failed_files }))
    } else {
      ElMessage.success(t('settings.storage.cleaned', {
        files: result.deleted_files,
        size: formatStorageBytes(result.reclaimed_bytes),
      }))
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('settings.storage.cleanFailed'))
  } finally {
    storageActionKey.value = ''
  }
}

const cleanupAllStorage = async () => {
  const targets = (storageStatus.value?.categories || [])
    .filter((item) => item.action === 'delete_files' && item.files > 0)
    .map((item) => item.id as StorageCleanupTarget)
  await cleanupStorage(targets)
}

const discoverLlmModels = async (options?: LlmModelDiscoveryOptions) => {
  if (modelDiscoveryTimeout) clearTimeout(modelDiscoveryTimeout)
  modelDiscoveryTimeout = null
  const baseUrl = normalizeOpenAiBaseUrl(form.llm.base_url)
  const provider = llmProviderPreset.value
  const apiKey = llmProviderNeedsApiKey.value ? form.llm.api_key.trim() : ''
  const timeout = form.llm.timeout
  const runId = ++modelDiscoveryRun
  if (!baseUrl) {
    llmModels.value = []
    llmModelStatus.value = ''
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    return
  }
  if (!options?.manual && !canAutoDiscoverLlmModels.value) {
    llmModels.value = []
    llmModelStatus.value = t('settings.llm.modelsSkippedNoKey')
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    return
  }

  const result = await loadLlmModels({
    provider,
    base_url: baseUrl,
    api_key: apiKey,
    timeout,
  })
  const currentApiKey = llmProviderNeedsApiKey.value ? form.llm.api_key.trim() : ''
  if (
    runId !== modelDiscoveryRun
    || provider !== llmProviderPreset.value
    || baseUrl !== normalizeOpenAiBaseUrl(form.llm.base_url)
    || apiKey !== currentApiKey
    || timeout !== form.llm.timeout
  ) return

  if (result?.ok) {
    llmModels.value = result.models
    applyDetectedLlmModel(result.models, options)
    llmModelStatus.value = result.models.length
      ? t('settings.llm.modelsDetected', {
        count: result.models.length,
        selected: llmModelAutoSelected.value ? t('settings.llm.modelsSelected', { model: form.llm.model }) : '',
      })
      : (result.message || t('settings.llm.modelsEmpty'))
  } else if (result) {
    llmModels.value = []
    llmModelStatus.value = result.message || t('settings.llm.modelsFailed')
    llmModelAutoSelected.value = false
  }
}

const scheduleLlmModelDiscovery = (options?: LlmModelDiscoveryOptions) => {
  if (suppressModelDiscovery) return
  invalidateLlmModelDiscovery()
  if (!normalizeOpenAiBaseUrl(form.llm.base_url)) {
    llmModels.value = []
    llmModelStatus.value = ''
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    return
  }
  if (!options?.manual && !canAutoDiscoverLlmModels.value) {
    llmModels.value = []
    llmModelStatus.value = t('settings.llm.modelsSkippedNoKey')
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    return
  }
  modelDiscoveryTimeout = setTimeout(() => {
    modelDiscoveryTimeout = null
    void discoverLlmModels(options)
  }, 650)
}

const handleLlmEndpointChange = (field: 'base_url' | 'api_key', value: string | number | boolean) => {
  if (field === 'base_url') {
    const normalizedBaseUrl = normalizeOpenAiBaseUrl(String(value ?? ''))
    const previousProvider = normalizeLlmProviderValue(form.llm.provider, form.llm.base_url)
    const inferredProvider = inferLlmProviderPreset(normalizedBaseUrl)
    if (inferredProvider !== previousProvider) {
      if (!llmProfiles[previousProvider]) {
        llmProfiles[previousProvider] = snapshotLlmProfile(previousProvider)
      }
      llmProviderPreset.value = inferredProvider
      const nextProfile = sanitizeLlmProfile(inferredProvider, {
        ...(llmProfiles[inferredProvider] || defaultLlmProfile(inferredProvider)),
        base_url: normalizedBaseUrl,
      })
      applyLlmProfileToForm(nextProfile)
    } else {
      form.llm.base_url = normalizedBaseUrl
      form.llm.provider = llmProviderPreset.value
    }
    if (!llmProviderNeedsApiKey.value) {
      form.llm.api_key = ''
    }
    llmModelAutoSelected.value = false
    saveActiveLlmPatch({
      provider: llmProviderPreset.value,
      base_url: normalizedBaseUrl,
      api_key: form.llm.api_key,
    })
    scheduleLlmModelDiscovery({ manual: false })
    return
  }
  llmModelAutoSelected.value = false
  form.llm.api_key = llmProviderNeedsApiKey.value ? String(value ?? '') : ''
  saveLlmField(field, form.llm.api_key)
  if (field === 'api_key') {
    invalidateLlmModelDiscovery()
    modelDiscoveryTimeout = setTimeout(async () => {
      modelDiscoveryTimeout = null
      await flushPendingSave()
      await discoverLlmModels({ manual: false })
    }, 700)
    return
  }
  scheduleLlmModelDiscovery({ manual: false })
}

const readSettingKey = async () => {
  if (!lookupKey.value.trim()) return
  const result = await settingsClient.getSetting(lookupKey.value.trim())
  lookupResult.value = JSON.stringify(result, null, 2)
}

const parseSettingValue = (): unknown => {
  const raw = setValueJson.value.trim()
  try {
    return JSON.parse(raw)
  } catch {
    return raw
  }
}

const writeSettingKey = async () => {
  if (!setKey.value.trim() || !setValueJson.value.trim()) return
  if (!(await flushPendingSave())) return
  await settingsClient.setSetting(setKey.value.trim(), parseSettingValue())
  ElMessage.success(t('settings.messages.settingWritten'))
  await loadSettings()
  hydrateForm()
  await loadSettingsAdmin()
}

const resetSettingKey = async () => {
  const key = deleteKey.value.trim()
  if (!key) return
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.deleteKeyMessage', { key }),
      t('settings.confirm.deleteKeyTitle'),
      {
        confirmButtonText: t('common.delete'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  try {
    if (!(await flushPendingSave())) return
    await settingsClient.deleteSetting(key)
    ElMessage.success(t('settings.messages.settingReset'))
    deleteKey.value = ''
    await loadSettings()
    hydrateForm()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('common.error.unknown'))
  }
}

const hydrateForm = () => {
  if (!settings.value) return
  const s = settings.value
  suppressModelDiscovery = true

  if (s.llm) {
    clearReactiveRecord(llmProfiles as Record<string, unknown>)
    for (const [key, profile] of Object.entries(s.llm.profiles || {})) {
      const provider = normalizeLlmProviderValue(key, profile?.base_url || '')
      llmProfiles[provider] = sanitizeLlmProfile(provider, profile as Partial<LlmProfile>)
    }
    const activeProvider = normalizeLlmProviderValue(s.llm.provider, s.llm.base_url)
    const activeProfile = sanitizeLlmProfile(activeProvider, {
      ...(llmProfiles[activeProvider] || {}),
      provider: activeProvider,
      base_url: s.llm.base_url ?? '',
      api_key: s.llm.api_key ?? '',
      model: s.llm.model ?? '',
      temperature: s.llm.temperature ?? 1.2,
      top_p: s.llm.top_p ?? 0.9,
      top_k: s.llm.top_k ?? 500,
      min_p: s.llm.min_p ?? 0,
      frequency_penalty: s.llm.frequency_penalty ?? 0.2,
      presence_penalty: s.llm.presence_penalty ?? 0,
      repetition_penalty: s.llm.repetition_penalty ?? 1,
      timeout: s.llm.timeout ?? 60,
      context_max_tokens: s.llm.context_max_tokens ?? DEFAULT_LLM_CONTEXT_MAX_TOKENS,
      default_max_output_tokens: s.llm.default_max_output_tokens ?? DEFAULT_LLM_MAX_OUTPUT_TOKENS,
    })
    llmProfiles[activeProvider] = activeProfile
    llmProviderPreset.value = activeProvider
    applyLlmProfileToForm(activeProfile)
    form.llm.vision_enabled = s.llm.vision_enabled ?? false
    form.llm.vision_provider = normalizeLlmProviderValue(s.llm.vision_provider, s.llm.vision_base_url)
    form.llm.vision_base_url = s.llm.vision_base_url ?? ''
    form.llm.vision_api_key = s.llm.vision_api_key ?? ''
    form.llm.vision_model = s.llm.vision_model ?? ''
    form.llm.vision_timeout = s.llm.vision_timeout ?? 30
    form.llm.vision_detail = s.llm.vision_detail ?? 'low'
    llmModelAutoSelected.value = false
  }

  if (s.tts) {
    const activeProfile = sanitizeTtsProfile({
      genie_character: s.tts.genie_character ?? '',
      genie_model_dir: s.tts.genie_model_dir || '',
      ref_audio: s.tts.ref_audio ?? '',
      ref_text: s.tts.ref_text ?? '',
      lang: s.tts.lang || 'ja',
      device: s.tts.device || 'cpu',
      quality: s.tts.quality || '质量优先',
      split: s.tts.split || '智能切分',
      mode: s.tts.mode || '串行推理',
      save_mode: s.tts.save_mode || '禁用自动保存',
      provider: s.tts.provider === 'openai-compatible' ? 'openai-compatible' : TTS_PROVIDER,
      base_url: s.tts.base_url || '',
      api_key: s.tts.api_key || '',
      model: s.tts.model || 'tts-1',
      voice: s.tts.voice || 'alloy',
      timeout: s.tts.timeout ?? 60,
    })
    applyTtsProfileToForm(activeProfile)
  }

  if (s.asr) {
    form.asr.provider = s.asr.provider || 'sherpa-onnx-online'
    form.asr.base_url = s.asr.base_url ?? ''
    form.asr.api_key = s.asr.api_key || ''
    form.asr.timeout = s.asr.timeout ?? 60
    form.asr.sensevoice_model = s.asr.sensevoice_model || 'iic/SenseVoiceSmall'
    form.asr.sensevoice_device = s.asr.sensevoice_device || 'cpu'
    form.asr.sherpa_model_path = s.asr.sherpa_model_path || ''
    form.asr.sherpa_tokens_path = s.asr.sherpa_tokens_path || ''
    form.asr.sherpa_num_threads = s.asr.sherpa_num_threads ?? 2
    form.asr.sherpa_provider = s.asr.sherpa_provider || 'cpu'
  form.asr.language = s.asr.language || 'zh'
    form.asr.vad_threshold = s.asr.vad_threshold ?? 0.5
    form.asr.vad_min_silence_ms = s.asr.vad_min_silence_ms ?? DEFAULT_VAD_MIN_SILENCE_MS
    form.asr.asr_partial_every = s.asr.asr_partial_every ?? 15
  }

  if (s.svc) {
    form.svc.provider = s.svc.provider || 'soulx-service'
    form.svc.base_url = s.svc.base_url ?? ''
    form.svc.speaker_id = s.svc.speaker_id ?? 0
    form.svc.pitch = s.svc.pitch ?? 0
    form.svc.timeout = s.svc.timeout ?? 120
  }

  if (s.summary) {
    form.summary.trigger_messages = s.summary.trigger_messages ?? 24
    form.summary.keep_recent_messages = s.summary.keep_recent_messages ?? 8
    form.summary.item_max_chars = s.summary.item_max_chars ?? 140
    form.summary.rewrite_interval_messages = s.summary.rewrite_interval_messages ?? 6
    form.summary.quality_scorer_mode = s.summary.quality_scorer_mode ?? 'rule'
    form.summary.quality_score_cooldown_seconds = s.summary.quality_score_cooldown_seconds ?? 300
    form.summary.quality_score_budget_per_hour = s.summary.quality_score_budget_per_hour ?? 20
  }

  if (s.memory) {
    form.memory.backend = s.memory.backend ?? 'sqlite'
    form.memory.sqlite_path = s.memory.sqlite_path ?? ''
    form.memory.qdrant_url = s.memory.qdrant_url ?? ''
    form.memory.qdrant_api_key = s.memory.qdrant_api_key ?? ''
    form.memory.qdrant_collection = s.memory.qdrant_collection ?? 'memories'
    form.memory.qdrant_timeout = s.memory.qdrant_timeout ?? 10
    form.memory.qdrant_auto_start = s.memory.qdrant_auto_start ?? false
    form.memory.qdrant_docker_image = s.memory.qdrant_docker_image ?? DEFAULT_QDRANT_DOCKER_IMAGE
    form.memory.qdrant_docker_container = s.memory.qdrant_docker_container ?? 'yuizaki-qdrant'
    form.memory.qdrant_docker_volume = s.memory.qdrant_docker_volume ?? 'yuizaki-qdrant-storage'
    form.memory.embedding_model = s.memory.embedding_model ?? DEFAULT_EMBEDDING_MODEL
    form.memory.reranker_enabled = s.memory.reranker_enabled ?? false
    form.memory.reranker_model = s.memory.reranker_model ?? 'BAAI/bge-reranker-v2-m3'
    form.memory.reranker_candidate_count = s.memory.reranker_candidate_count ?? 32
  }

  if (s.system) {
    form.system.language = normalizeLocale(s.system.language || currentLocale.value)
    form.system.theme = s.system.theme || 'light'
  }

  suppressModelDiscovery = false
}

onMounted(async () => {
  document.addEventListener('visibilitychange', handleResourceProgressVisibility)
  await Promise.all([refreshBackendTokenStatus(), inputBindingsStore.load()])
  await loadSettings()
  hydrateForm()
  if (!settingsRequest.error) {
    await loadSettingsAdmin()
  }
  await Promise.all([refreshResourcePanel(), loadTtsStatus(), loadLlmStatus()])
  void queueTtsWarmup()
  scheduleLlmModelDiscovery({ manual: false })
})

onBeforeUnmount(() => {
  if (saveTimeout) {
    clearTimeout(saveTimeout)
    saveTimeout = null
  }
  promoteFailedSavePatch()
  if (pendingSavePatch.value) {
    void drainSaveQueue({ allowAfterUnmount: true })
  }
})

onUnmounted(() => {
  unmounted = true
  if (modelDiscoveryTimeout) clearTimeout(modelDiscoveryTimeout)
  saveTimeout = null
  modelDiscoveryTimeout = null
  stopResourceProgressPolling()
  document.removeEventListener('visibilitychange', handleResourceProgressVisibility)
  notifySaveIdle()
})

watch(currentLocale, (value) => {
  form.system.language = value
})

watch(activeSection, (value) => {
  if (value === 'voice') {
    void queueTtsWarmup()
  }
})
</script>

<style scoped src="./SettingsPanel.css"></style>
