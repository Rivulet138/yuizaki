<template>
  <PanelShell title="她记住了什么" tone="companion">
    <div class="memory-panel">
      <div class="panel-toolbar">
        <div>
          <h3>关系记忆库</h3>
        </div>
        <div class="toolbar-actions">
          <label class="toolbar-field">
            <span>默认记忆范围</span>
            <el-select
              :model-value="currentMemoryScope"
              size="small"
              class="scope-select"
              :disabled="workspaceScopeSaving"
              @change="updateDefaultMemoryScope"
            >
              <el-option v-for="scope in memoryScopeOptions" :key="scope.value" :label="scope.label" :value="scope.value" />
            </el-select>
          </label>
          <el-button
            data-testid="memory-advanced-tools-toggle"
            plain
            circle
            :icon="Tools"
            :type="advancedToolsVisible ? 'primary' : 'default'"
            :title="advancedToolsVisible ? t('memory.advanced.collapse') : t('memory.advanced.expand')"
            :aria-label="advancedToolsVisible ? t('memory.advanced.collapse') : t('memory.advanced.expand')"
            :aria-expanded="advancedToolsVisible"
            @click="advancedToolsVisible = !advancedToolsVisible"
          />
          <el-button v-if="advancedToolsVisible" plain :loading="rebuildIndexLoading" @click="rebuildMemoryIndex">{{ t('memory.actions.rebuildIndex') }}</el-button>
          <el-button data-testid="memory-refresh" type="primary" plain :loading="docsRequest.loading" @click="refreshMemoryState">{{ t('memory.actions.refresh') }}</el-button>
        </div>
      </div>

      <section class="memory-metrics" aria-label="记忆概况">
        <article v-for="metric in memoryMetrics" :key="metric.label" class="memory-metric" :class="`tone-${metric.tone}`">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.detail }}</small>
        </article>
      </section>

      <div class="layout-grid">
        <div class="left-column">
          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>关系记忆地图</span>
                <el-tag :type="indexStatusTone" size="small">{{ indexStatusLabel }}</el-tag>
              </div>
            </template>
            <div class="index-grid">
              <div>
                <span>文档</span>
                <strong>{{ docs.length }}</strong>
              </div>
              <div>
                <span>索引</span>
                <strong>{{ indexStatus?.count ?? '-' }}</strong>
              </div>
              <div>
                <span>范围</span>
                <strong>{{ scopeLabel(currentMemoryScope) }}</strong>
              </div>
              <div>
                <span>待复核</span>
                <strong>{{ reviewDocs.length }}</strong>
              </div>
            </div>
            <div v-if="advancedToolsVisible && retrievalStrategy.label" class="strategy-status with-margin">
              <span>策略</span>
              <strong>{{ retrievalStrategy.label }}</strong>
            </div>
            <div v-if="advancedToolsVisible && retrievalStrategy.layers.length" class="tag-row with-margin">
              <el-tag v-for="(layer, idx) in retrievalStrategy.layers" :key="idx" type="info">{{ layer }}</el-tag>
            </div>
            <div v-if="indexStatus?.backend || indexStatus?.message" class="index-health with-margin">
              <span>后端 {{ indexStatus.backend || 'memory' }}</span>
              <span>{{ indexAvailabilityLabel }}</span>
            </div>
            <div class="layer-map with-margin">
              <button
                v-for="layer in layerStats"
                :key="layer.value"
                type="button"
                class="layer-map-item"
                :class="{ active: filterLayer === layer.value }"
                @click="setLayerFilter(layer.value)"
              >
                <strong>{{ layer.label }}</strong>
                <span>{{ layer.desc }} · {{ layer.count }}</span>
              </button>
            </div>
          </el-card>

          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>告诉她一件事</span>
                <el-tag size="small" type="info">{{ selectedLayerDefinition.desc }}</el-tag>
              </div>
            </template>
            <el-form label-position="top" @submit.prevent>
              <el-form-item label="她应该记住">
                <el-input v-model="form.text" type="textarea" :rows="4" placeholder="例如：我喜欢被叫溪羽；周五要提醒我检查模型。" />
              </el-form-item>
              <el-form-item label="记到哪里">
                <el-select v-model="form.layer" class="full-width">
                  <el-option v-for="l in layers" :key="l.value" :label="l.label" :value="l.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="记忆类型">
                <el-select
                  v-model="form.type"
                  data-testid="memory-type-select"
                  class="full-width"
                  filterable
                  allow-create
                  default-first-option
                  placeholder="选择或输入类型"
                >
                  <el-option v-for="preset in memoryTypePresets" :key="preset.value" :label="preset.label" :value="preset.value" />
                </el-select>
              </el-form-item>
              <div class="form-grid">
                <el-form-item :label="`重要度：${form.importance.toFixed(2)}`">
                  <el-slider v-model="form.importance" :min="0" :max="1" :step="0.05" />
                </el-form-item>
                <el-form-item :label="`置信度：${form.confidence.toFixed(2)}`">
                  <el-slider v-model="form.confidence" :min="0" :max="1" :step="0.05" />
                </el-form-item>
              </div>
              <el-form-item label="来源">
                <el-select v-model="form.source" class="full-width">
                  <el-option v-for="source in memorySourceOptions" :key="source.value" :label="source.label" :value="source.value" />
                </el-select>
              </el-form-item>
              <el-button type="primary" :loading="addRequest.loading" :disabled="!form.text.trim()" @click="submitMemory">让她记住</el-button>
            </el-form>
          </el-card>

          <div v-if="duplicateCandidates.length" class="duplicate-panel">
            <div class="trace-header">
              <span class="trace-title">合并候选</span>
              <el-tag size="small" type="warning">{{ duplicateCandidates.length }} 条</el-tag>
            </div>
            <article v-for="candidate in duplicateCandidates" :key="candidate.id" class="candidate-row">
              <div class="candidate-main">
                <strong>{{ candidate.id }}</strong>
                <span>{{ candidate.text }}</span>
              </div>
              <div class="tag-row">
                <el-tag size="small" type="info">{{ candidate.layer || 'unknown' }}</el-tag>
                <el-tag v-if="candidate.match_reason" size="small" type="warning">{{ candidate.match_reason }}</el-tag>
                <el-tag v-if="candidate.score !== undefined" size="small">得分 {{ candidate.score.toFixed(4) }}</el-tag>
                <el-tag v-if="candidate.text_similarity !== undefined" size="small">文本 {{ candidate.text_similarity.toFixed(4) }}</el-tag>
              </div>
            </article>
          </div>

          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>整理队列</span>
                <el-tag :type="reviewDocs.length ? 'warning' : 'success'" size="small">{{ reviewDocs.length }} 条</el-tag>
              </div>
            </template>
            <div v-if="reviewDocs.length" class="review-list">
              <article v-for="doc in reviewDocs.slice(0, 5)" :key="doc.id" class="review-item">
                <div>
                  <strong>{{ doc.type || 'memory' }}</strong>
                  <span>{{ compactText(doc.text, 84) }}</span>
                </div>
                <div class="tag-row">
                  <el-tag size="small" :type="layerTagType(doc.layer)">{{ doc.layer || 'unknown' }}</el-tag>
                  <el-tag size="small" :type="qualityTagType(doc)">质量 {{ qualityPercent(doc) }}</el-tag>
                  <el-button size="small" type="primary" link @click="openEditDoc(doc)">复核</el-button>
                </div>
              </article>
            </div>
            <el-empty v-else description="暂无需要复核的记忆" :image-size="56" />
          </el-card>

          <el-card shadow="never" class="maintenance-card">
            <template #header>
              <div class="card-header">
                <span>长期记忆维护</span>
                <el-tag :type="maintenancePreview ? (maintenancePreview.summary.delete_count ? 'danger' : 'success') : 'info'" size="small">
                  {{ maintenancePreview ? `${maintenancePreview.summary.delete_count} 条待永久清理` : '尚未预览' }}
                </el-tag>
              </div>
            </template>
            <div class="maintenance-policy-grid">
              <label class="maintenance-field">
                <span>工作记忆保留</span>
                <el-input-number v-model="maintenancePolicy.workingRetentionDays" :min="1" :max="365" size="small" controls-position="right" />
                <small>天</small>
              </label>
            </div>
            <label class="maintenance-threshold">
              <span>低质量阈值 {{ Math.round(maintenancePolicy.lowQualityThreshold * 100) }}%</span>
              <el-slider v-model="maintenancePolicy.lowQualityThreshold" :min="0" :max="1" :step="0.05" />
            </label>
            <div class="maintenance-switches">
              <label><el-switch v-model="maintenancePolicy.includeStaleWorking" size="small" />过期工作记忆</label>
              <label><el-switch v-model="maintenancePolicy.includeLowQuality" size="small" />低质量记忆</label>
              <label><el-switch v-model="maintenancePolicy.includeExactDuplicates" size="small" />完全重复项</label>
            </div>
            <div class="button-row with-margin">
              <el-button plain :loading="maintenanceSaving" @click="saveMemoryPolicy">保存整理规则</el-button>
              <el-button data-testid="memory-maintenance-preview" type="primary" plain :loading="maintenancePreviewLoading" @click="previewMemoryMaintenance">{{ t('memory.actions.previewImpact') }}</el-button>
              <el-button
                type="danger"
                :loading="maintenanceApplyLoading"
                :disabled="!maintenancePreview?.summary.delete_count || !maintenancePreviewMatchesPolicy"
                @click="applyMemoryMaintenance"
              >永久清理</el-button>
            </div>
            <div v-if="maintenancePreview" class="maintenance-summary with-margin">
              <div><span>已扫描</span><strong>{{ maintenancePreview.summary.scanned_count }}</strong></div>
              <div><span>永久清理</span><strong>{{ maintenancePreview.summary.delete_count }}</strong></div>
            </div>
            <div v-if="maintenancePreview?.candidates.length" class="maintenance-candidates with-margin">
              <article v-for="candidate in maintenancePreview.candidates.slice(0, 8)" :key="candidate.id">
                <div>
                  <strong>{{ compactText(candidate.text, 68) || candidate.id }}</strong>
                  <span>{{ candidate.layer }} · {{ maintenanceReasonLabel(candidate.reasons) }}</span>
                </div>
                <el-tag size="small" :type="maintenanceActionTone(candidate.action)">{{ maintenanceActionLabel(candidate.action) }}</el-tag>
              </article>
              <small v-if="maintenancePreview.candidates.length > 8">另有 {{ maintenancePreview.candidates.length - 8 }} 条</small>
            </div>
          </el-card>

          <el-card v-if="advancedToolsVisible" shadow="never">
            <template #header>写入原始文档</template>
            <el-form label-position="top" @submit.prevent>
              <el-form-item label="文档 ID（可选）">
                <el-input v-model="docForm.id" />
              </el-form-item>
              <el-form-item label="文档内容">
                <el-input data-testid="memory-document-text" v-model="docForm.text" type="textarea" :rows="4" :placeholder="t('memory.document.textPlaceholder')" />
              </el-form-item>
              <el-form-item label="元数据 JSON">
                <el-input data-testid="memory-document-metadata" v-model="docForm.metadataJson" type="textarea" :rows="3" :placeholder="t('memory.document.metadataPlaceholder')" />
              </el-form-item>
              <div class="button-row">
                <el-button data-testid="memory-document-submit" type="primary" plain :loading="docWriteLoading" :disabled="!docForm.text.trim()" @click="submitDocument">{{ t('memory.actions.writeDocument') }}</el-button>
                <el-tag type="info">原始文档</el-tag>
              </div>
            </el-form>
          </el-card>
        </div>

        <div class="right-column">
          <el-card v-if="advancedToolsVisible" shadow="never">
            <template #header>
              <div class="card-header">
                <span>她会想起什么</span>
                <el-tag v-if="querySummary" type="success" size="small">{{ querySummary }}</el-tag>
              </div>
            </template>
            <el-form label-position="top" @submit.prevent>
              <el-form-item label="检索问题">
                <el-input data-testid="memory-query-input" v-model="queryForm.query" :placeholder="t('memory.query.placeholder')" @keyup.enter="submitQuery" />
              </el-form-item>
              <div class="form-grid">
                <el-form-item label="作用域">
                  <el-select v-model="queryForm.scope" class="full-width">
                    <el-option label="全局" value="global" />
                    <el-option label="工作区" value="workspace" />
                    <el-option label="会话" value="session" />
                  </el-select>
                </el-form-item>
                <el-form-item label="返回数量">
                  <el-input-number v-model="queryForm.top_k" :min="1" :max="20" />
                </el-form-item>
              </div>
              <div class="button-row">
                <el-button data-testid="memory-query-submit" type="primary" :loading="queryRequest.loading" :disabled="!queryForm.query.trim()" @click="submitQuery">{{ t('memory.actions.layeredQuery') }}</el-button>
                <el-button plain :loading="rawQueryRequest.loading" :disabled="!queryForm.query.trim()" @click="submitRawQuery">原始检索</el-button>
                <el-tag type="info">平均得分：{{ averageQueryScore }}</el-tag>
              </div>
              <div class="query-layer-picker" aria-label="检索层级">
                <button
                  v-for="layer in layers"
                  :key="layer.value"
                  type="button"
                  class="query-layer-chip"
                  :class="{ active: effectiveQueryLayers.includes(layer.value) }"
                  @click="toggleQueryLayer(layer.value)"
                >
                  <strong>{{ layer.label }}</strong>
                  <span>{{ layer.desc }}</span>
                </button>
                <el-button size="small" link type="primary" @click="resetQueryLayers">重置层级</el-button>
              </div>
            </el-form>

            <div v-if="queryTrace" class="trace-panel">
              <div class="trace-header">
                <span class="trace-title">检索轨迹</span>
                <div class="tag-row">
                  <el-tag type="success" size="small">召回 {{ queryTrace.recall_count ?? queryResult?.results?.length ?? 0 }}</el-tag>
                  <el-tag type="info" size="small">作用域 {{ queryTrace.scope || 'auto' }}</el-tag>
                  <el-tag v-if="queryTrace.workspace_id" type="info" size="small">工作区 {{ queryTrace.workspace_id }}</el-tag>
                  <el-tag v-if="queryTrace.session_id" type="info" size="small">会话 {{ queryTrace.session_id }}</el-tag>
                  <el-tag type="info" size="small">候选 {{ queryTrace.candidate_count ?? 0 }}/{{ queryTrace.candidate_limit ?? 0 }}</el-tag>
                  <el-tag type="warning" size="small">已过滤 {{ queryTrace.filtered_out_count ?? 0 }}</el-tag>
                  <el-tag size="small" :type="queryTrace.backend_filter_downpushed ? 'success' : 'info'">后端过滤 {{ queryTrace.backend_filter_downpushed ? '开启' : '关闭' }}</el-tag>
                </div>
              </div>
              <div class="trace-line">
                <span class="trace-label">得分</span>
                <span>最高 {{ formatScore(queryTrace.top_score) }} · 平均 {{ formatScore(queryTrace.average_score) }} · {{ formatLatency(queryTrace.latency_ms) }}</span>
              </div>
              <div v-if="queryTrace.layers.length" class="trace-line">
                <span class="trace-label">层级</span>
                <span>{{ queryTrace.layers.join(' > ') }}</span>
              </div>
              <div v-if="filterReasonText" class="trace-line">
                <span class="trace-label">过滤</span>
                <span>{{ filterReasonText }}</span>
              </div>
              <div v-if="selectedTraceIds.length" class="trace-line trace-ids">
                <span class="trace-label">命中 ID</span>
                <code v-for="id in selectedTraceIds" :key="id">{{ id }}</code>
                <span v-if="hiddenTraceIdCount" class="trace-more">+{{ hiddenTraceIdCount }}</span>
              </div>
            </div>

            <AsyncState :loading="queryRequest.loading" :error="queryRequest.error" :empty="!queryResult || !queryResult.results?.length" empty-text="暂无检索结果" class="result-state" @retry="submitQuery">
              <div class="query-result-list">
                <article v-for="(row, index) in queryResult?.results || []" :key="row.id || index" class="query-result-card">
                  <div class="query-rank">{{ index + 1 }}</div>
                  <div class="query-result-main">
                    <p>{{ row.text }}</p>
                    <div class="tag-row">
                      <el-tag v-if="row.layer" size="small" :type="layerTagType(row.layer)">{{ row.layer }}</el-tag>
                      <el-tag size="small" type="success">得分 {{ Number(row.score ?? 0).toFixed(4) }}</el-tag>
                      <el-tag v-if="row.id" size="small" type="info">{{ row.id }}</el-tag>
                      <el-button v-if="row.id" size="small" type="primary" link @click="selectDocById(row.id)">查看记忆</el-button>
                    </div>
                  </div>
                </article>
              </div>
            </AsyncState>
          </el-card>

          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>记忆文档</span>
                <div class="doc-filter-stack">
                  <div class="filter-row">
                    <el-button
                      v-for="option in docViewOptions"
                      :key="option.value"
                      size="small"
                      :type="docViewMode === option.value ? 'primary' : 'default'"
                      plain
                      @click="setDocView(option.value)"
                    >
                      {{ option.label }} {{ docViewCount(option.value) }}
                    </el-button>
                  </div>
                  <div class="filter-row">
                    <el-select v-model="filterLayer" size="small" clearable placeholder="层级" class="filter-select">
                      <el-option v-for="l in layers" :key="l.value" :label="l.label" :value="l.value" />
                    </el-select>
                    <el-select v-model="docSortMode" size="small" placeholder="排序" class="filter-select">
                      <el-option label="最近更新" value="updated" />
                      <el-option label="重要度" value="importance" />
                      <el-option label="质量" value="quality" />
                      <el-option label="置信度" value="confidence" />
                    </el-select>
                    <el-input v-model="searchText" size="small" clearable placeholder="搜索内容" class="filter-input" />
                  </div>
                  <div class="filter-row">
                    <el-button size="small" plain :disabled="!hasDocFilters" @click="resetDocFilters">清空筛选</el-button>
                    <el-button size="small" plain :loading="batchActionLoading" :disabled="batchActionDisabled" :title="batchActionHint" @click="batchBoostVisibleDocs">提高筛选结果重要度</el-button>
                    <el-button size="small" type="danger" plain :loading="batchActionLoading" :disabled="batchActionDisabled" :title="batchActionHint" @click="batchDeleteVisibleDocs">{{ batchDeleteLabel }}</el-button>
                  </div>
                </div>
              </div>
            </template>
            <AsyncState :loading="docsRequest.loading" :error="docsRequest.error" :empty="filteredDocs.length === 0" empty-text="暂无匹配的记忆文档" @retry="loadScopedDocs">
              <div class="doc-layout">
                <div class="memory-doc-list">
                  <article
                    v-for="row in visibleDocs"
                    :key="row.id"
                    class="memory-doc-card"
                    :data-memory-id="row.id"
                    :class="{ active: selectedDoc?.id === row.id, hit: isQueryHit(row) }"
                    role="button"
                    tabindex="0"
                    @click="selectDoc(row)"
                    @keyup.enter="selectDoc(row)"
                    @keyup.space.prevent="selectDoc(row)"
                  >
                    <div class="doc-card-main">
                      <div class="doc-card-head">
                        <strong>{{ row.type || 'fact' }}</strong>
                        <div class="tag-row">
                          <el-tag v-if="isQueryHit(row)" size="small" type="success">命中</el-tag>
                          <el-tag size="small" :type="layerTagType(row.layer)">{{ row.layer || 'unknown' }}</el-tag>
                        </div>
                      </div>
                      <p>{{ row.text }}</p>
                      <div class="doc-meta">
                        <span :class="importanceColorClass(row.importance)">重要度 {{ Number(row.importance ?? 0).toFixed(2) }}</span>
                        <span>质量 {{ formatScore(row.quality_score) }}</span>
                        <span>置信 {{ formatScore(row.confidence) }}</span>
                        <span>{{ docSourceLabel(row) }}</span>
                        <span>{{ docScopeLabel(row) }}</span>
                        <span>{{ docExpiryLabel(row) }}</span>
                        <span>{{ docUpdatedLabel(row) }}</span>
                      </div>
                    </div>
                  </article>
                  <button
                    v-if="remainingFilteredDocCount > 0"
                    type="button"
                    class="doc-list-more"
                    @click="showMoreDocs"
                  >
                    显示更多 {{ remainingFilteredDocCount }} 条
                  </button>
                </div>

                <aside class="doc-inspector">
                  <template v-if="selectedDoc">
                    <div class="inspector-head">
                      <div>
                        <span>{{ selectedDoc.id }}</span>
                        <strong>{{ selectedDoc.type || 'fact' }}</strong>
                      </div>
                    </div>
                    <div class="inspector-editor">
                      <label class="editor-field editor-field-full">
                        <span>内容</span>
                        <el-input data-testid="memory-inspector-text" v-model="inspectorDraft.text" type="textarea" :rows="4" resize="none" />
                      </label>
                      <div class="editor-grid">
                        <label class="editor-field">
                          <span>类型</span>
                          <el-input v-model="inspectorDraft.type" size="small" />
                        </label>
                        <label class="editor-field">
                          <span>层级</span>
                          <el-select v-model="inspectorDraft.layer" size="small" class="full-width">
                            <el-option v-for="l in layers" :key="l.value" :label="l.label" :value="l.value" />
                          </el-select>
                        </label>
                        <label class="editor-field">
                          <span>来源</span>
                          <el-select v-model="inspectorDraft.source" size="small" class="full-width">
                            <el-option v-for="source in memorySourceOptions" :key="source.value" :label="source.label" :value="source.value" />
                          </el-select>
                        </label>
                      </div>
                      <div class="form-grid compact">
                        <el-form-item :label="`重要度：${inspectorDraft.importance.toFixed(2)}`">
                          <el-slider v-model="inspectorDraft.importance" :min="0" :max="1" :step="0.05" />
                        </el-form-item>
                        <el-form-item :label="`置信度：${inspectorDraft.confidence.toFixed(2)}`">
                          <el-slider v-model="inspectorDraft.confidence" :min="0" :max="1" :step="0.05" />
                        </el-form-item>
                      </div>
                      <div class="button-row">
                        <el-button
                          data-testid="memory-inspector-save"
                          size="small"
                          type="primary"
                          :loading="inspectorDraftSaving"
                          :disabled="!inspectorDraftDirty || !inspectorDraft.text.trim()"
                          @click="saveInspectorDraft"
                        >
                          保存面板修改
                        </el-button>
                        <el-button size="small" plain :disabled="!inspectorDraftDirty" @click="resetInspectorDraft">重置</el-button>
                      </div>
                    </div>
                    <div class="inspector-grid">
                      <div>
                        <span>层级</span>
                        <strong>{{ selectedDoc.layer || 'unknown' }}</strong>
                      </div>
                      <div>
                        <span>作用域</span>
                        <strong>{{ docScopeLabel(selectedDoc) }}</strong>
                      </div>
                      <div>
                        <span>来源</span>
                        <strong>{{ docSourceLabel(selectedDoc) }}</strong>
                      </div>
                      <div>
                        <span>质量</span>
                        <strong>{{ qualityPercent(selectedDoc) }}</strong>
                      </div>
                    </div>
                    <div class="inspector-actions">
                      <el-button size="small" type="primary" plain @click="openEditDoc(selectedDoc)">完整编辑</el-button>
                      <el-button size="small" plain @click="boostDocImportance(selectedDoc)">提高重要度</el-button>
                        <el-button
                          data-testid="memory-inspector-delete"
                        size="small"
                        type="danger"
                        plain
                        :loading="removingDocIds.has(selectedDoc.id)"
                        :disabled="removingDocIds.has(selectedDoc.id)"
                        @click="removeDoc(selectedDoc.id)"
                      >
                        永久删除
                      </el-button>
                    </div>
                    <div class="layer-action-grid">
                      <button
                        v-for="layer in layers"
                        :key="layer.value"
                        type="button"
                        :class="{ active: selectedDoc.layer === layer.value }"
                        @click="moveDocLayer(selectedDoc, layer.value)"
                      >
                        <strong>{{ layer.label }}</strong>
                        <span>{{ layer.desc }}</span>
                      </button>
                    </div>
                    <details class="inspector-details">
                      <summary>元数据</summary>
                      <pre>{{ metadataPreview(selectedDoc) }}</pre>
                    </details>
                    <details v-if="docAuditEntries(selectedDoc).length" class="inspector-details">
                      <summary>审计记录</summary>
                      <div class="audit-list">
                        <div v-for="(entry, idx) in docAuditEntries(selectedDoc)" :key="idx">
                          <strong>{{ auditActionLabel(entry.action) }}</strong>
                          <span>{{ auditEntrySummary(entry) }}</span>
                        </div>
                      </div>
                    </details>
                  </template>
                  <el-empty v-else description="未选择记忆" :image-size="56" />
                </aside>
              </div>
            </AsyncState>
          </el-card>
        </div>
      </div>
    </div>

    <el-dialog v-model="editDialogVisible" title="编辑记忆" width="640px">
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="记忆内容">
          <el-input v-model="editForm.text" type="textarea" :rows="5" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="记忆层级">
            <el-select v-model="editForm.layer" class="full-width">
              <el-option v-for="l in layers" :key="l.value" :label="l.label" :value="l.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="数据类型">
            <el-input v-model="editForm.type" />
          </el-form-item>
        </div>
        <el-form-item :label="`重要度：${editForm.importance.toFixed(2)}`">
          <el-slider v-model="editForm.importance" :min="0" :max="1" :step="0.05" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item :label="`置信度：${editForm.confidence.toFixed(2)}`">
            <el-slider v-model="editForm.confidence" :min="0" :max="1" :step="0.05" />
          </el-form-item>
          <el-form-item label="来源">
            <el-select v-model="editForm.source" class="full-width">
              <el-option v-for="source in memorySourceOptions" :key="source.value" :label="source.label" :value="source.value" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="元数据 JSON">
          <el-input v-model="editForm.metadataJson" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="button-row footer-actions">
          <el-button @click="editDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="updateRequest.loading" :disabled="!editForm.text.trim()" @click="submitEditDoc">保存修改</el-button>
        </div>
      </template>
    </el-dialog>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from '@/i18n'
import { Tools } from '@element-plus/icons-vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { normalizeDuplicateCandidates, useMemoryDomain } from '../composables/useMemoryDomain'
import { useSessionStore } from '@/stores/sessionStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { systemClient } from '@/api/client'
import { memoryClient } from '@/api/clients/memory-client'
import type { MemoryIndexStatus, MemoryMaintenanceCandidate, MemoryMaintenancePolicyPayload, MemoryMaintenancePreview } from '@/api/clients/memory-client'
import { getMemoryIndexUiStatus } from '../memory-index-status'
import type { MemoryDoc, MemoryDuplicateCandidate } from '../composables/useMemoryDomain'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'
type MetricTone = 'green' | 'blue' | 'amber' | 'rose' | 'slate'
type DocViewMode = 'all' | 'recallable' | 'review' | 'important' | 'hits'
type DocSortMode = 'updated' | 'importance' | 'quality' | 'confidence'
type MemoryScope = 'global' | 'workspace' | 'session'

const { docs, queryResult, docsRequest, addRequest, updateRequest, queryRequest, rawQueryRequest, loadDocs, addMemory, updateDoc, queryMemory, queryRawRag } = useMemoryDomain()
const { t } = useI18n()
const e2eMode = Boolean(window.petApi?.e2e)
const sessionStore = useSessionStore()
const workspaceStore = useWorkspaceStore()
const activeWorkspace = computed(() => workspaceStore.activeWorkspace)
const normalizeMemoryScope = (scope?: string | null): MemoryScope => {
  if (scope === 'global' || scope === 'session') return scope
  return 'workspace'
}
const currentMemoryScope = computed<MemoryScope>(() => normalizeMemoryScope(activeWorkspace.value?.memory_scope))
const indexStatus = ref<MemoryIndexStatus | null>(null)
const retrievalStrategy = ref<{ label: string; layers: string[] }>({ label: '', layers: [] })
const advancedToolsVisible = ref(false)
const searchText = ref('')
const filterLayer = ref('')
const duplicateCandidates = ref<MemoryDuplicateCandidate[]>([])
const docViewMode = ref<DocViewMode>('all')
const docSortMode = ref<DocSortMode>('updated')
const selectedDocId = ref('')
const selectedQueryLayers = ref<string[]>([])
const form = reactive({ text: '', type: 'chat', layer: 'working', importance: 0.6, confidence: 0.86, source: 'manual' })
const docForm = reactive({ id: '', text: '', metadataJson: '' })
const queryForm = reactive({ query: '', scope: currentMemoryScope.value, top_k: 5 })
const editDialogVisible = ref(false)
const editForm = reactive({ id: '', text: '', type: 'fact', layer: 'semantic', importance: 0.5, confidence: 0.72, source: 'manual', metadataJson: '' })
const inspectorDraft = reactive({ id: '', text: '', type: 'fact', layer: 'semantic', importance: 0.5, confidence: 0.72, source: 'manual' })
const docWriteLoading = ref(false)
const rebuildIndexLoading = ref(false)
const batchActionLoading = ref(false)
const workspaceScopeSaving = ref(false)
const inspectorDraftSaving = ref(false)
const removingDocIds = ref(new Set<string>())
const batchDeleteProgress = reactive({ active: false, total: 0, done: 0 })
const maintenancePreview = ref<MemoryMaintenancePreview | null>(null)
const maintenancePreviewPolicyKey = ref('')
const maintenancePreviewLoading = ref(false)
const maintenanceApplyLoading = ref(false)
const maintenanceSaving = ref(false)
const maintenancePolicy = reactive({
  workingRetentionDays: activeWorkspace.value.context.memoryPolicy?.workingRetentionDays ?? 14,
  lowQualityThreshold: activeWorkspace.value.context.memoryPolicy?.lowQualityThreshold ?? 0.55,
  includeStaleWorking: activeWorkspace.value.context.memoryPolicy?.includeStaleWorking !== false,
  includeLowQuality: activeWorkspace.value.context.memoryPolicy?.includeLowQuality !== false,
  includeExactDuplicates: activeWorkspace.value.context.memoryPolicy?.includeExactDuplicates !== false,
})
const hydrateMaintenancePolicy = () => {
  const policy = activeWorkspace.value.context.memoryPolicy
  maintenancePolicy.workingRetentionDays = policy?.workingRetentionDays ?? 14
  maintenancePolicy.lowQualityThreshold = policy?.lowQualityThreshold ?? 0.55
  maintenancePolicy.includeStaleWorking = policy?.includeStaleWorking !== false
  maintenancePolicy.includeLowQuality = policy?.includeLowQuality !== false
  maintenancePolicy.includeExactDuplicates = policy?.includeExactDuplicates !== false
}
const DOC_RENDER_BATCH_SIZE = 80
const visibleDocLimit = ref(DOC_RENDER_BATCH_SIZE)

const layers = [
  { value: 'profile', label: '偏好与称呼', desc: '稳定偏好', color: 'purple' },
  { value: 'working', label: '当下任务', desc: '当前上下文', color: 'blue' },
  { value: 'episodic', label: '最近事件', desc: '具体事件', color: 'amber' },
  { value: 'relationship', label: '关系线索', desc: '陪伴线索', color: 'pink' },
  { value: 'reflective', label: '她的反思', desc: '反思总结', color: 'emerald' },
  { value: 'semantic', label: '长期事实', desc: '全局知识', color: 'slate' },
]

const memoryTypePresets = [
  { value: 'fact', label: '事实' },
  { value: 'preference', label: '偏好' },
  { value: 'event', label: '事件' },
  { value: 'promise', label: '承诺' },
  { value: 'taboo', label: '禁忌' },
  { value: 'summary', label: '摘要' },
]

const memoryScopeOptions: Array<{ value: MemoryScope; label: string }> = [
  { value: 'global', label: '全局' },
  { value: 'workspace', label: '工作区' },
  { value: 'session', label: '会话' },
]

const memorySourceOptions = [
  { value: 'manual', label: '手动录入' },
  { value: 'session', label: '对话片段' },
  { value: 'relationship', label: '关系观察' },
  { value: 'reflection', label: '反思总结' },
  { value: 'import', label: '资料导入' },
  { value: 'profile', label: '画像资料' },
]

const docViewOptions: Array<{ value: DocViewMode; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'recallable', label: '可召回' },
  { value: 'review', label: '待复核' },
  { value: 'important', label: '高重要度' },
  { value: 'hits', label: '本次命中' },
]

const importanceColorClass = (val?: number | null) => {
  const v = Number(val ?? 0)
  if (v >= 0.8) return 'important-high'
  if (v >= 0.5) return 'important-medium'
  return 'important-low'
}

const layerTagType = (layer?: string) => {
  const map: Record<string, TagType> = { profile: 'warning', working: 'primary', episodic: 'info', relationship: 'danger', reflective: 'success', semantic: 'info' }
  return map[layer || ''] || 'info'
}

const formatScore = (value?: number | null) => Number.isFinite(Number(value)) ? Number(value).toFixed(4) : '-'
const formatLatency = (value?: number | null) => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)} ms` : '-'

const scorePercent = (value?: number | null) => {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return `${Math.round(Math.min(1, Math.max(0, number)) * 100)}%`
}

const qualityPercent = (doc: MemoryDoc) => scorePercent(doc.quality_score ?? doc.confidence)

const qualityTagType = (doc: MemoryDoc): TagType => {
  const score = Number(doc.quality_score ?? doc.confidence ?? 1)
  if (score >= 0.78) return 'success'
  if (score >= 0.62) return 'warning'
  return 'danger'
}

const compactText = (text?: string | null, limit = 120) => {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim()
  if (normalized.length <= limit) return normalized
  return `${normalized.slice(0, Math.max(0, limit - 1))}…`
}

const docUpdatedLabel = (doc: MemoryDoc) => {
  const raw = doc.updated_at || (typeof doc.metadata?.timestamp === 'string' ? doc.metadata.timestamp : '')
  if (!raw) return '未记录时间'
  return String(raw).replace('T', ' ').slice(0, 16)
}

const docExpiryLabel = (doc: MemoryDoc) => {
  const raw = doc.expires_at || (typeof doc.metadata?.expires_at === 'string' ? doc.metadata.expires_at : '')
  return raw
    ? t('memory.expiry.until', { value: raw.replace('T', ' ').slice(0, 16) })
    : t('memory.expiry.permanent')
}

const stringMeta = (doc: MemoryDoc, key: string) => {
  const value = doc.metadata?.[key]
  return typeof value === 'string' && value.trim() ? value : ''
}

const docScopeValue = (doc: MemoryDoc) => stringMeta(doc, 'scope') || currentMemoryScope.value
const docWorkspaceId = (doc: MemoryDoc) => stringMeta(doc, 'workspace_id') || activeWorkspace.value?.id
const docSessionId = (doc: MemoryDoc) => stringMeta(doc, 'session_id') || (docScopeValue(doc) === 'session' ? sessionStore.activeSession?.id : undefined)

const scopeLabel = (scope?: string | null) => {
  const map: Record<string, string> = {
    global: '全局',
    workspace: '工作区',
    session: '会话',
  }
  return map[String(scope || '')] || String(scope || '工作区')
}

const maintenancePayload = (): MemoryMaintenancePolicyPayload => ({
  scope: currentMemoryScope.value,
  workspace_id: currentMemoryScope.value === 'global' ? undefined : activeWorkspace.value.id,
  session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
  working_retention_days: maintenancePolicy.workingRetentionDays,
  low_quality_threshold: maintenancePolicy.lowQualityThreshold,
  include_stale_working: maintenancePolicy.includeStaleWorking,
  include_low_quality: maintenancePolicy.includeLowQuality,
  include_exact_duplicates: maintenancePolicy.includeExactDuplicates,
})
const maintenancePolicyKey = () => JSON.stringify(maintenancePayload())
const maintenancePreviewMatchesPolicy = computed(() => Boolean(
  maintenancePreview.value && maintenancePreviewPolicyKey.value === maintenancePolicyKey(),
))

const maintenanceReasonLabel = (reasons: string[]) => reasons.map((reason) => ({
  stale_working: '超过工作记忆期限',
  low_quality: '质量低于阈值',
  exact_duplicate: '与保留项完全重复',
}[reason] || reason)).join('、')

const maintenanceActionLabel = (_action: MemoryMaintenanceCandidate['action']) => '永久删除'

const maintenanceActionTone = (_action: MemoryMaintenanceCandidate['action']): TagType => 'danger'

const saveMemoryPolicy = async () => {
  if (maintenanceSaving.value) return
  maintenanceSaving.value = true
  try {
    workspaceStore.updateWorkspaceContext(activeWorkspace.value.id, {
      memoryPolicy: {
        workingRetentionDays: maintenancePolicy.workingRetentionDays,
        lowQualityThreshold: maintenancePolicy.lowQualityThreshold,
        includeStaleWorking: maintenancePolicy.includeStaleWorking,
        includeLowQuality: maintenancePolicy.includeLowQuality,
        includeExactDuplicates: maintenancePolicy.includeExactDuplicates,
      },
    })
    ElMessage.success('记忆整理规则已保存')
  } finally {
    maintenanceSaving.value = false
  }
}

const previewMemoryMaintenance = async () => {
  if (maintenancePreviewLoading.value || maintenanceApplyLoading.value) return
  maintenancePreviewLoading.value = true
  try {
    maintenancePreview.value = await memoryClient.previewMaintenance(maintenancePayload())
    maintenancePreviewPolicyKey.value = maintenancePolicyKey()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '无法预览记忆整理结果')
  } finally {
    maintenancePreviewLoading.value = false
  }
}

const applyMemoryMaintenance = async () => {
  if (maintenanceApplyLoading.value) return
  if (!maintenancePreviewMatchesPolicy.value) {
    ElMessage.warning('整理规则已变化，请重新预览影响后再执行')
    return
  }
  const previewToken = maintenancePreview.value?.preview_token
  if (!previewToken) {
    ElMessage.warning('请重新预览后再执行')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将永久清理 ${maintenancePreview.value?.summary.delete_count ?? 0} 条记忆，操作不可恢复。`,
      '永久清理记忆',
      { confirmButtonText: '永久清理', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  maintenanceApplyLoading.value = true
  try {
    const result = await memoryClient.applyMaintenance({
      ...maintenancePayload(),
      preview_token: previewToken,
      confirmation: 'PERMANENT_DELETE',
    })
    ElMessage.success(`已永久清理 ${result.changed_count} 条记忆`)
    await refreshMemoryState()
    try {
      maintenancePreview.value = await memoryClient.previewMaintenance(maintenancePayload())
      maintenancePreviewPolicyKey.value = maintenancePolicyKey()
    } catch {
      maintenancePreview.value = null
      maintenancePreviewPolicyKey.value = ''
      ElMessage.warning('整理已完成，但最新预览暂时无法刷新')
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '记忆整理失败')
  } finally {
    maintenanceApplyLoading.value = false
  }
}

const updateDefaultMemoryScope = async (value: string) => {
  const nextScope = normalizeMemoryScope(value)
  const workspaceId = activeWorkspace.value?.id
  if (!workspaceId || workspaceScopeSaving.value || nextScope === currentMemoryScope.value) return
  workspaceScopeSaving.value = true
  try {
    await workspaceStore.updateWorkspaceRemote(workspaceId, { memory_scope: nextScope })
    queryForm.scope = nextScope
    ElMessage.success('记忆作用域已保存')
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存记忆作用域失败')
  } finally {
    workspaceScopeSaving.value = false
  }
}

const recallableDocs = computed(() => docs.value)

const layerStats = computed(() => layers.map(layer => ({
  ...layer,
  count: recallableDocs.value.filter(doc => doc.layer === layer.value).length,
})))
const queryTrace = computed(() => queryResult.value?.trace ?? null)
const queryHitIds = computed(() => new Set([
  ...(queryTrace.value?.selected_ids ?? []),
  ...((queryResult.value?.results ?? []).map(item => item.id).filter(Boolean)),
]))

const highImportanceDocs = computed(() => recallableDocs.value.filter(doc => Number(doc.importance ?? 0) >= 0.8))
const lowConfidenceDocs = computed(() => recallableDocs.value.filter(doc => Number(doc.confidence ?? 1) < 0.7))
const lowQualityDocs = computed(() => recallableDocs.value.filter(doc => Number(doc.quality_score ?? 1) < 0.66))
const reviewDocs = computed(() => recallableDocs.value
  .filter(doc => Number(doc.confidence ?? 1) < 0.72 || Number(doc.quality_score ?? 1) < 0.66)
  .sort((left, right) => Math.min(Number(left.confidence ?? 1), Number(left.quality_score ?? 1)) - Math.min(Number(right.confidence ?? 1), Number(right.quality_score ?? 1))))

const indexedRatio = computed(() => {
  if (!recallableDocs.value.length) return 0
  return Math.min(1, Number(indexStatus.value?.count ?? 0) / recallableDocs.value.length)
})

const memoryMetrics = computed(() => [
  {
    label: '索引覆盖',
    value: `${Math.round(indexedRatio.value * 100)}%`,
    detail: `${indexStatus.value?.count ?? 0}/${recallableDocs.value.length} 条可召回`,
    tone: indexedRatio.value >= 0.9 ? 'green' : indexedRatio.value >= 0.5 ? 'amber' : 'slate',
  },
  {
    label: '活跃记忆',
    value: recallableDocs.value.length,
    detail: `${highImportanceDocs.value.length} 条高重要度`,
    tone: 'blue',
  },
  {
    label: '待复核',
    value: reviewDocs.value.length,
    detail: `${lowConfidenceDocs.value.length} 条低置信；${lowQualityDocs.value.length} 条低质量`,
    tone: reviewDocs.value.length ? 'amber' : 'green',
  },
  {
    label: '当前召回',
    value: queryTrace.value?.recall_count ?? queryResult.value?.results?.length ?? 0,
    detail: queryTrace.value ? `${formatLatency(queryTrace.value.latency_ms)} · ${queryTrace.value.scope || 'auto'}` : '未检索',
    tone: queryTrace.value ? 'green' : 'slate',
  },
] satisfies Array<{ label: string; value: string | number; detail: string; tone: MetricTone }>)

const selectedLayerDefinition = computed(() => layers.find(layer => layer.value === form.layer) || layers[1])

const indexUiStatus = computed(() => getMemoryIndexUiStatus(indexStatus.value, docsRequest.loading))
const indexStatusLabel = computed(() => indexUiStatus.value.label)
const indexAvailabilityLabel = computed(() => indexUiStatus.value.availabilityLabel)
const indexStatusTone = computed<TagType>(() => indexUiStatus.value.tone)

const querySummary = computed(() => {
  const results = queryResult.value?.results ?? []
  if (!results.length) return ''
  const best = Math.max(...results.map(item => Number(item.score ?? 0)))
  return `${results.length} 条命中 · 最高得分 ${best.toFixed(4)}`
})

const defaultQueryLayers = ['profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic']
const effectiveQueryLayers = computed(() => {
  if (selectedQueryLayers.value.length) return selectedQueryLayers.value
  return retrievalStrategy.value.layers.length ? retrievalStrategy.value.layers : defaultQueryLayers
})

const averageQueryScore = computed(() => {
  const results = queryResult.value?.results ?? []
  if (!results.length) return '-'
  const total = results.reduce((sum, item) => sum + Number(item.score ?? 0), 0)
  return (total / results.length).toFixed(4)
})

const selectedTraceIds = computed(() => queryTrace.value?.selected_ids.slice(0, 8) ?? [])
const hiddenTraceIdCount = computed(() => Math.max(0, (queryTrace.value?.selected_ids.length ?? 0) - selectedTraceIds.value.length))
const filterReasonText = computed(() => {
  const reasons = queryTrace.value?.filter_reasons ?? {}
  return Object.entries(reasons)
    .filter(([, count]) => count > 0)
    .map(([reason, count]) => `${reason} ${count}`)
    .join(' · ')
})

const setLayerFilter = (layer: string) => {
  filterLayer.value = filterLayer.value === layer ? '' : layer
}

const setDocView = (mode: DocViewMode) => {
  docViewMode.value = mode
}

const resetDocFilters = () => {
  docViewMode.value = 'all'
  docSortMode.value = 'updated'
  filterLayer.value = ''
  searchText.value = ''
}

const docMatchesView = (doc: MemoryDoc, mode: DocViewMode) => {
  if (mode === 'recallable') return true
  if (mode === 'review') return reviewDocs.value.some(item => item.id === doc.id)
  if (mode === 'important') return Number(doc.importance ?? 0) >= 0.8
  if (mode === 'hits') return queryHitIds.value.has(doc.id)
  return true
}

const docViewCount = (mode: DocViewMode) => docs.value.filter(doc => docMatchesView(doc, mode)).length

const docTimestampValue = (doc: MemoryDoc) => {
  const raw = doc.updated_at || (typeof doc.metadata?.timestamp === 'string' ? doc.metadata.timestamp : '')
  const value = raw ? Date.parse(raw) : 0
  return Number.isFinite(value) ? value : 0
}

const docSortValue = (doc: MemoryDoc, mode: DocSortMode) => {
  if (mode === 'importance') return Number(doc.importance ?? 0)
  if (mode === 'quality') return Number(doc.quality_score ?? 0)
  if (mode === 'confidence') return Number(doc.confidence ?? 0)
  return docTimestampValue(doc)
}

const filteredDocs = computed(() => {
  let list: MemoryDoc[] = docs.value
  list = list.filter(d => docMatchesView(d, docViewMode.value))
  if (filterLayer.value) list = list.filter(d => d.layer === filterLayer.value)
  if (searchText.value.trim()) {
    const q = searchText.value.toLowerCase()
    list = list.filter(d => [
      d.id,
      d.text,
      d.type,
      d.layer,
      typeof d.metadata?.source === 'string' ? d.metadata.source : '',
    ].join(' ').toLowerCase().includes(q))
  }
  return [...list].sort((left, right) => docSortValue(right, docSortMode.value) - docSortValue(left, docSortMode.value))
})

const visibleDocs = computed(() => filteredDocs.value.slice(0, visibleDocLimit.value))
const remainingFilteredDocCount = computed(() => Math.max(0, filteredDocs.value.length - visibleDocs.value.length))
const selectedDoc = computed(() => filteredDocs.value.find(doc => doc.id === selectedDocId.value) || filteredDocs.value[0] || null)
const hasDocFilters = computed(() => docViewMode.value !== 'all' || docSortMode.value !== 'updated' || Boolean(filterLayer.value) || Boolean(searchText.value.trim()))
const batchTargetDocs = computed(() => hasDocFilters.value ? filteredDocs.value : [])
const batchTargetCount = computed(() => batchTargetDocs.value.length)
const batchActionDisabled = computed(() => batchActionLoading.value || !hasDocFilters.value || batchTargetCount.value === 0)
const batchActionHint = computed(() => {
  if (!hasDocFilters.value) return '请先选择视图、层级或输入搜索词，再批量处理'
  if (batchTargetCount.value === 0) return '当前筛选结果为空'
  return `将处理当前筛选结果中的 ${batchTargetCount.value} 条记忆`
})
const batchDeleteLabel = computed(() => {
  if (batchDeleteProgress.active) return `删除中 ${batchDeleteProgress.done}/${batchDeleteProgress.total}`
  if (!hasDocFilters.value) return '先筛选再删除'
  return `永久删除筛选结果 (${batchTargetCount.value})`
})

const showMoreDocs = () => {
  visibleDocLimit.value += DOC_RENDER_BATCH_SIZE
}

const selectDoc = (doc: MemoryDoc) => {
  selectedDocId.value = doc.id
}

const selectDocById = (id: string) => {
  selectedDocId.value = id
  const doc = docs.value.find(item => item.id === id)
  if (!doc) return
  if (docViewMode.value !== 'all' && !docMatchesView(doc, docViewMode.value)) docViewMode.value = 'all'
  if (filterLayer.value && doc.layer !== filterLayer.value) filterLayer.value = ''
  if (searchText.value.trim() && !filteredDocs.value.some(item => item.id === id)) searchText.value = ''
  const visibleIndex = filteredDocs.value.findIndex(item => item.id === id)
  if (visibleIndex >= visibleDocLimit.value) visibleDocLimit.value = visibleIndex + 1
}

const isQueryHit = (doc: MemoryDoc) => queryHitIds.value.has(doc.id)

const toggleQueryLayer = (layer: string) => {
  const set = new Set(effectiveQueryLayers.value)
  if (set.has(layer)) {
    set.delete(layer)
  } else {
    set.add(layer)
  }
  selectedQueryLayers.value = [...set]
}

const resetQueryLayers = () => {
  selectedQueryLayers.value = []
}

const setDocRemoving = (id: string, removing: boolean) => {
  const next = new Set(removingDocIds.value)
  if (removing) {
    next.add(id)
  } else {
    next.delete(id)
  }
  removingDocIds.value = next
}

const scopedDocOptions = () => ({
  scope: currentMemoryScope.value,
  workspaceId: activeWorkspace.value?.id,
  sessionId: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
})

const loadScopedDocs = () => loadDocs(scopedDocOptions())

const refreshIndexStatus = async () => {
  indexStatus.value = await memoryClient.getIndexStatus()
}

const refreshMemoryState = async () => {
  await loadScopedDocs()
  if (e2eMode) return
  try {
    await refreshIndexStatus()
  } catch (error) {
    console.debug('[MemoryPanel] failed to refresh index status:', error)
  }
}

const rebuildMemoryIndex = async () => {
  if (rebuildIndexLoading.value) return
  rebuildIndexLoading.value = true
  try {
    const result = await memoryClient.rebuildIndex()
    const indexedCount = result.indexed_count ?? result.document_count
    ElMessage.success(indexedCount !== undefined ? `索引已重建：${indexedCount} 条` : '索引已重建')
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重建索引失败')
  } finally {
    rebuildIndexLoading.value = false
  }
}

const submitMemory = async () => {
  if (!form.text.trim()) return
  duplicateCandidates.value = []
  const result = await addMemory({
    text: form.text.trim(),
    type: form.type || 'chat',
    layer: form.layer,
    importance: form.importance,
    confidence: form.confidence,
    confidence_source: form.source,
    metadata: {
      source: form.source,
    },
    scope: currentMemoryScope.value,
    session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
  })
  if (result?.skipped) {
    duplicateCandidates.value = normalizeDuplicateCandidates(result.duplicate_candidates)
    ElMessage.warning(result.reason === 'low_importance' ? '重要度低于阈值，后端已跳过写入' : result.reason || '记忆写入已跳过')
    return
  }
  if (result?.status === 'ok') { ElMessage.success('记忆块已注入'); form.text = ''; void refreshMemoryState() }
}

const parseJsonObject = (rawValue: string, label: string) => {
  const raw = rawValue.trim()
  if (!raw) return {}
  const parsed: unknown = JSON.parse(raw)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON object`)
  }
  return parsed as Record<string, unknown>
}

const parseMetadata = () => parseJsonObject(docForm.metadataJson, 'Metadata')

const submitDocument = async () => {
  if (!docForm.text.trim()) return
  docWriteLoading.value = true
  duplicateCandidates.value = []
  try {
    const documentText = docForm.text.trim()
    const metadata = parseMetadata()
    const scopedMetadata = {
      layer: 'semantic',
      scope: currentMemoryScope.value,
      workspace_id: currentMemoryScope.value === 'global' ? undefined : activeWorkspace.value?.id,
      session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
      ...metadata,
    }
    const result = await memoryClient.addDoc({
      id: docForm.id.trim() || undefined,
      text: documentText,
      metadata: scopedMetadata,
      scope: currentMemoryScope.value,
      workspace_id: currentMemoryScope.value === 'global' ? undefined : activeWorkspace.value?.id,
      session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
      layer: typeof scopedMetadata.layer === 'string' ? scopedMetadata.layer : undefined,
    })
    if (result.skipped) {
      duplicateCandidates.value = normalizeDuplicateCandidates(result.duplicate_candidates)
      ElMessage.warning(result.reason || '发现相似文档，已返回合并候选')
      return
    }
    ElMessage.success(`文档已写入：${result.id}`)
    docForm.id = ''
    docForm.text = ''
    docForm.metadataJson = ''
    if (e2eMode) {
      const createdMetadata = scopedMetadata as Record<string, unknown>
      docs.value = [{
        id: result.id,
        text: documentText,
        type: typeof createdMetadata.type === 'string' ? createdMetadata.type : 'fact',
        layer: typeof createdMetadata.layer === 'string' ? createdMetadata.layer : 'semantic',
        importance: Number.isFinite(Number(createdMetadata.importance)) ? Number(createdMetadata.importance) : undefined,
        confidence: Number.isFinite(Number(createdMetadata.confidence)) ? Number(createdMetadata.confidence) : undefined,
        updated_at: typeof createdMetadata.updated_at === 'string' ? createdMetadata.updated_at : undefined,
        source: typeof createdMetadata.source === 'string' ? createdMetadata.source : undefined,
        scope: typeof createdMetadata.scope === 'string' ? createdMetadata.scope : currentMemoryScope.value,
        expires_at: typeof createdMetadata.expires_at === 'string' ? createdMetadata.expires_at : undefined,
        metadata: createdMetadata,
      }, ...docs.value.filter(doc => doc.id !== result.id)]
      selectedDocId.value = result.id
    } else {
      void refreshMemoryState()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '写入文档失败')
  } finally {
    docWriteLoading.value = false
  }
}

const submitQuery = async () => {
  if (!queryForm.query.trim()) return
  await queryMemory({
    query: queryForm.query.trim(),
    top_k: queryForm.top_k,
    session_id: queryForm.scope === 'session' ? sessionStore.activeSession?.id : undefined,
    scope: queryForm.scope,
    layers: selectedQueryLayers.value.length ? effectiveQueryLayers.value : undefined,
  })
}

const submitRawQuery = async () => {
  if (!queryForm.query.trim()) return
  await queryRawRag({
    query: queryForm.query.trim(),
    top_k: queryForm.top_k,
    session_id: queryForm.scope === 'session' ? sessionStore.activeSession?.id : undefined,
    scope: queryForm.scope,
    layers: effectiveQueryLayers.value,
  })
}

const openEditDoc = (doc: MemoryDoc) => {
  editForm.id = doc.id
  editForm.text = doc.text || ''
  editForm.type = doc.type || 'fact'
  editForm.layer = doc.layer || 'semantic'
  editForm.importance = Number(doc.importance ?? 0.5)
  editForm.confidence = Number(doc.confidence ?? 0.72)
  editForm.source = docSourceValue(doc)
  editForm.metadataJson = JSON.stringify(doc.metadata || {}, null, 2)
  editDialogVisible.value = true
}

const openRequestedMemoryDoc = () => {
  const query = window.location.hash.split('?')[1] || ''
  const requestedId = new URLSearchParams(query).get('edit')?.trim() || ''
  if (!requestedId) return
  const doc = docs.value.find(item => item.id === requestedId)
  if (!doc) {
    ElMessage.warning('未找到要纠正的记忆')
    return
  }
  selectDocById(requestedId)
  openEditDoc(doc)
}

const buildDocUpdatePayload = (
  doc: MemoryDoc,
  overrides: {
    text?: string
    type?: string
    layer?: string
    importance?: number
    confidence?: number
    confidence_source?: string
    metadata?: Record<string, unknown>
    edit_reason?: string
  },
) => {
  const scope = docScopeValue(doc)
  const confidenceSource = (overrides.confidence_source ?? stringMeta(doc, 'confidence_source')) || undefined
  return {
    text: overrides.text ?? doc.text ?? '',
    type: overrides.type ?? doc.type ?? 'fact',
    layer: overrides.layer ?? doc.layer ?? 'semantic',
    importance: overrides.importance ?? Number(doc.importance ?? 0.5),
    confidence: overrides.confidence ?? Number(doc.confidence ?? 0.72),
    confidence_source: confidenceSource,
    metadata: {
      ...(doc.metadata || {}),
      ...(overrides.metadata || {}),
    },
    scope,
    workspace_id: scope === 'global' ? undefined : docWorkspaceId(doc),
    session_id: scope === 'session' ? docSessionId(doc) : undefined,
    edit_reason: overrides.edit_reason,
  }
}

const updateSelectedDoc = async (
  doc: MemoryDoc,
  overrides: Parameters<typeof buildDocUpdatePayload>[1],
  successMessage: string,
) => {
  const result = await updateDoc(doc.id, buildDocUpdatePayload(doc, overrides))
  if (result?.status === 'updated') {
    ElMessage.success(successMessage)
    selectedDocId.value = doc.id
    await refreshMemoryState()
  }
}

const moveDocLayer = async (doc: MemoryDoc, layer: string) => {
  if (doc.layer === layer) return
  await updateSelectedDoc(
    doc,
    {
      layer,
      metadata: { layer },
      edit_reason: `move_layer:${doc.layer || 'unknown'}->${layer}`,
    },
    `已移动到 ${layer}`,
  )
}

const boostDocImportance = async (doc: MemoryDoc) => {
  const nextImportance = Math.min(1, Math.max(Number(doc.importance ?? 0.5), 0.85))
  await updateSelectedDoc(
    doc,
    {
      importance: nextImportance,
      edit_reason: 'boost_importance',
    },
    '重要度已提高',
  )
}

const batchUpdateVisibleDocs = async (
  actionLabel: string,
  buildOverrides: (doc: MemoryDoc) => Parameters<typeof buildDocUpdatePayload>[1],
) => {
  const targets = batchTargetDocs.value.slice()
  if (batchActionLoading.value) return
  if (!hasDocFilters.value) {
    ElMessage.info('请先选择视图、层级或搜索词，再批量处理')
    return
  }
  if (!targets.length) return
  try {
    await ElMessageBox.confirm(
      `将对当前筛选结果中的 ${targets.length} 条记忆执行“${actionLabel}”。`,
      '批量整理记忆',
      {
        confirmButtonText: actionLabel,
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  batchActionLoading.value = true
  try {
    for (const doc of targets) {
      await updateDoc(doc.id, buildDocUpdatePayload(doc, buildOverrides(doc)))
    }
    ElMessage.success(`已处理 ${targets.length} 条记忆`)
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '批量整理失败')
  } finally {
    batchActionLoading.value = false
  }
}

const batchBoostVisibleDocs = () => batchUpdateVisibleDocs('提高重要度', doc => ({
  importance: Math.min(1, Math.max(Number(doc.importance ?? 0.5), 0.85)),
  edit_reason: 'batch_boost_importance',
}))

const batchDeleteVisibleDocs = async () => {
  const targets = batchTargetDocs.value.slice()
  if (batchActionLoading.value) return
  if (!hasDocFilters.value) {
    ElMessage.info('请先选择视图、层级或搜索词，再批量删除')
    return
  }
  if (!targets.length) return
  const targetIds = new Set(targets.map(doc => doc.id))
  const ids = [...targetIds]
  const previousDocs = docs.value.slice()
  const previousSelectedDocId = selectedDocId.value
  const nextSelectedId = docs.value.find(doc => !targetIds.has(doc.id))?.id || ''
  try {
    await ElMessageBox.confirm(
      '这些记忆将从存储中永久删除。',
      `永久删除 ${targets.length} 条记忆`,
      {
        confirmButtonText: '永久删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  batchActionLoading.value = true
  batchDeleteProgress.active = true
  batchDeleteProgress.total = ids.length
  batchDeleteProgress.done = 0
  try {
    docs.value = docs.value.filter(doc => !targetIds.has(doc.id))
    if (targetIds.has(selectedDocId.value)) selectedDocId.value = nextSelectedId
    const result = await memoryClient.removeDocs(ids)
    batchDeleteProgress.done = result.deleted_count ?? ids.length
    ElMessage.success(`已永久删除 ${batchDeleteProgress.done} 条记忆`)
    await refreshIndexStatus().catch(error => console.debug('[MemoryPanel] failed to refresh index status after batch delete:', error))
  } catch (error) {
    docs.value = previousDocs
    selectedDocId.value = previousSelectedDocId
    ElMessage.error(error instanceof Error ? error.message : '批量删除失败')
  } finally {
    batchDeleteProgress.active = false
    batchActionLoading.value = false
  }
}

const submitEditDoc = async () => {
  if (!editForm.id || !editForm.text.trim()) return
  try {
    const targetDoc = docs.value.find(doc => doc.id === editForm.id)
    const metadata = {
      ...parseJsonObject(editForm.metadataJson, 'Metadata'),
      source: editForm.source,
      confidence_source: editForm.source,
    }
    const payload = targetDoc ? buildDocUpdatePayload(targetDoc, {
      text: editForm.text.trim(),
      type: editForm.type || 'fact',
      layer: editForm.layer,
      importance: editForm.importance,
      confidence: editForm.confidence,
      confidence_source: editForm.source,
      metadata,
      edit_reason: 'manual_edit',
    }) : {
      text: editForm.text.trim(),
      type: editForm.type || 'fact',
      layer: editForm.layer,
      importance: editForm.importance,
      confidence: editForm.confidence,
      confidence_source: editForm.source,
      metadata,
      scope: currentMemoryScope.value,
      workspace_id: currentMemoryScope.value === 'global' ? undefined : activeWorkspace.value?.id,
      session_id: currentMemoryScope.value === 'session' ? sessionStore.activeSession?.id : undefined,
      edit_reason: 'manual_edit',
    }
    const result = await updateDoc(editForm.id, payload)
    if (result?.status === 'updated') {
      ElMessage.success('记忆已更新')
      editDialogVisible.value = false
      selectedDocId.value = editForm.id
      void refreshMemoryState()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新记忆失败')
  }
}

const removeDoc = async (id: string) => {
  if (removingDocIds.value.has(id)) return
  try {
    await ElMessageBox.confirm(
      '这条记忆将从存储中永久删除。',
      '永久删除记忆',
      {
        confirmButtonText: '永久删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  setDocRemoving(id, true)
  try {
    const fallbackId = filteredDocs.value.find(doc => doc.id !== id)?.id || ''
    await memoryClient.removeDoc(id)
    ElMessage.success('已永久删除这条记忆')
    if (selectedDocId.value === id) selectedDocId.value = fallbackId
    await refreshMemoryState()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '永久删除失败')
  } finally {
    setDocRemoving(id, false)
  }
}

const docScopeLabel = (doc: MemoryDoc) => scopeLabel(typeof doc.metadata?.scope === 'string' ? doc.metadata.scope : currentMemoryScope.value)

const docSourceValue = (doc: MemoryDoc) => {
  const source = stringMeta(doc, 'source')
  const confidenceSource = stringMeta(doc, 'confidence_source')
  const allowed = ['manual', 'session', 'relationship', 'reflection', 'import', 'profile', 'explicit', 'default']
  if (allowed.includes(source)) return source
  if (allowed.includes(confidenceSource)) return confidenceSource
  return 'manual'
}

const docSourceLabel = (doc: MemoryDoc) => {
  const label = docSourceValue(doc)
  const labels: Record<string, string> = {
    manual: '手动',
    session: '会话',
    relationship: '关系',
    reflection: '反思',
    import: '导入',
    profile: '画像',
    default: '默认',
    explicit: '显式',
  }
  return labels[label] || label
}

const hydrateInspectorDraft = (doc: MemoryDoc) => {
  inspectorDraft.id = doc.id
  inspectorDraft.text = doc.text || ''
  inspectorDraft.type = doc.type || 'fact'
  inspectorDraft.layer = doc.layer || 'semantic'
  inspectorDraft.importance = Number(doc.importance ?? 0.5)
  inspectorDraft.confidence = Number(doc.confidence ?? 0.72)
  inspectorDraft.source = docSourceValue(doc)
}

const resetInspectorDraft = () => {
  if (selectedDoc.value) hydrateInspectorDraft(selectedDoc.value)
}

const inspectorDraftDirty = computed(() => {
  const doc = selectedDoc.value
  if (!doc || inspectorDraft.id !== doc.id) return false
  return inspectorDraft.text !== (doc.text || '')
    || inspectorDraft.type !== (doc.type || 'fact')
    || inspectorDraft.layer !== (doc.layer || 'semantic')
    || Number(inspectorDraft.importance.toFixed(4)) !== Number(Number(doc.importance ?? 0.5).toFixed(4))
    || Number(inspectorDraft.confidence.toFixed(4)) !== Number(Number(doc.confidence ?? 0.72).toFixed(4))
    || inspectorDraft.source !== docSourceValue(doc)
})

const saveInspectorDraft = async () => {
  const doc = selectedDoc.value
  if (!doc || !inspectorDraft.text.trim() || inspectorDraftSaving.value) return
  inspectorDraftSaving.value = true
  try {
    await updateSelectedDoc(
      doc,
      {
        text: inspectorDraft.text.trim(),
        type: inspectorDraft.type || 'fact',
        layer: inspectorDraft.layer,
        importance: inspectorDraft.importance,
        confidence: inspectorDraft.confidence,
        confidence_source: inspectorDraft.source,
        metadata: {
          source: inspectorDraft.source,
          confidence_source: inspectorDraft.source,
          layer: inspectorDraft.layer,
          type: inspectorDraft.type || 'fact',
        },
        edit_reason: 'inspector_edit',
      },
      '记忆已保存',
    )
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存记忆失败')
  } finally {
    inspectorDraftSaving.value = false
  }
}

const metadataPreview = (doc: MemoryDoc) => {
  try {
    return JSON.stringify(doc.metadata || {}, null, 2)
  } catch {
    return '{}'
  }
}

const docAuditEntries = (doc: MemoryDoc) => {
  const audit = doc.metadata?.audit
  return Array.isArray(audit) ? audit.filter(item => item && typeof item === 'object') as Array<Record<string, unknown>> : []
}

const auditActionLabel = (value: unknown) => {
  const map: Record<string, string> = {
    create: '创建',
    update: '更新',
  }
  const key = String(value || 'event')
  return map[key] || key
}

const auditEntrySummary = (entry: Record<string, unknown>) => {
  const at = typeof entry.at === 'string' ? entry.at.replace('T', ' ').slice(0, 16) : ''
  const reason = typeof entry.reason === 'string' ? entry.reason : ''
  return [at, reason].filter(Boolean).join(' · ') || '无时间'
}

watch(
  () => [docViewMode.value, docSortMode.value, filterLayer.value, searchText.value] as const,
  () => {
    visibleDocLimit.value = DOC_RENDER_BATCH_SIZE
  },
)

watch(
  () => selectedDoc.value ? [
    selectedDoc.value.id,
    selectedDoc.value.text,
    selectedDoc.value.type,
    selectedDoc.value.layer,
    selectedDoc.value.importance,
    selectedDoc.value.confidence,
    docSourceValue(selectedDoc.value),
  ] : [],
  () => {
    if (selectedDoc.value && !inspectorDraftSaving.value) hydrateInspectorDraft(selectedDoc.value)
  },
  { immediate: true },
)

watch(
  () => [currentMemoryScope.value, activeWorkspace.value?.id, sessionStore.activeSession?.id] as const,
  ([scope]) => {
    queryForm.scope = scope
    hydrateMaintenancePolicy()
    maintenancePreview.value = null
    maintenancePreviewPolicyKey.value = ''
    void loadScopedDocs()
  },
)

onMounted(async () => {
  queryForm.scope = currentMemoryScope.value
  await loadScopedDocs()
  openRequestedMemoryDoc()
  if (e2eMode) return
  try {
    await refreshIndexStatus()
  } catch (error) {
    console.debug('[MemoryPanel] failed to load index status:', error)
  }
  try {
    const payload = await systemClient.companionRuntime(4)
    if (payload.retrieval_strategy) {
      retrievalStrategy.value = {
        label: payload.retrieval_strategy.label || '',
        layers: payload.retrieval_strategy.layers || [],
      }
    }
  } catch (error) {
    console.debug('[MemoryPanel] failed to load retrieval strategy:', error)
  }
})
</script>

<style scoped>
.memory-panel,
.left-column,
.right-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.panel-toolbar,
.card-header,
.button-row,
.tag-row,
.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.panel-toolbar,
.card-header {
  justify-content: space-between;
}

.card-header > span {
  flex: 0 0 auto;
  white-space: nowrap;
}

.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: flex-end;
  gap: 8px;
  flex-shrink: 0;
}

.toolbar-field {
  display: flex;
  min-width: 150px;
  flex-direction: column;
  gap: 4px;
}

.toolbar-field span,
.editor-field span {
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.25;
}

.scope-select {
  width: 150px;
}

.panel-toolbar {
  padding: 14px 16px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
}

.panel-toolbar > div:first-child {
  min-width: 0;
}

.panel-toolbar h3 {
  margin: 0 0 4px;
  color: var(--yui-text);
  font-size: 16px;
  line-height: 1.25;
}

.memory-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: 12px;
}

.memory-metric {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
  padding: 14px;
}

.memory-metric span,
.memory-metric small,
.index-grid span,
.doc-meta span {
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.45;
}

.memory-metric strong {
  display: block;
  margin: 7px 0 4px;
  color: var(--yui-text);
  font-size: 24px;
  line-height: 1;
  font-weight: 900;
}

.tone-green strong { color: #059669; }
.tone-blue strong { color: #2563eb; }
.tone-amber strong { color: #d97706; }
.tone-rose strong { color: #e11d48; }
.tone-slate strong { color: #475569; }

.layout-grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.72fr) minmax(0, 1.28fr);
  gap: 16px;
  min-width: 0;
  max-width: 100%;
}

.memory-panel :deep(.el-card),
.memory-panel :deep(.el-card__header),
.memory-panel :deep(.el-card__body),
.memory-panel :deep(.el-form),
.memory-panel :deep(.el-descriptions),
.memory-panel :deep(.el-table) {
  min-width: 0;
  max-width: 100%;
}

.memory-panel :deep(.el-card__body) {
  overflow: hidden;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.form-grid.compact {
  gap: 8px;
}

.full-width {
  width: 100%;
}

.with-margin,
.result-state {
  margin-top: 12px;
}

.index-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.index-grid > div {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
  padding: 10px;
}

.index-grid strong {
  display: block;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 17px;
  font-weight: 850;
  overflow-wrap: anywhere;
}

.index-health {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
}

.index-health span {
  border-radius: 999px;
  background: var(--yui-surface-muted);
  padding: 3px 8px;
  color: var(--yui-text);
}

.index-health small {
  flex-basis: 100%;
  color: var(--yui-muted);
  overflow-wrap: anywhere;
}

.strategy-status {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: baseline;
  gap: 8px;
  color: var(--yui-muted);
  font-size: 12px;
}

.strategy-status strong {
  min-width: 0;
  color: var(--yui-text);
  overflow-wrap: anywhere;
}

.layer-map {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.layer-map-item {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
  color: var(--yui-text);
  cursor: pointer;
  padding: 10px;
  text-align: left;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.layer-map-item:hover,
.layer-map-item.active {
  transform: translateY(-1px);
  border-color: var(--yui-border-strong);
  box-shadow: var(--yui-shadow-hover);
}

.layer-map-item.active {
  background: rgba(37, 99, 235, 0.08);
}

.layer-map-item strong,
.review-item strong,
.doc-card-head strong {
  display: block;
  color: var(--yui-text);
  font-size: 12px;
  font-weight: 850;
}

.layer-map-item span {
  display: block;
  margin-top: 4px;
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.45;
}

.maintenance-policy-grid,
.maintenance-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.maintenance-field {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--yui-text);
  font-size: 12px;
}

.maintenance-field > span {
  grid-column: 1 / -1;
  font-weight: 650;
}

.maintenance-field :deep(.el-input-number) {
  width: 100%;
}

.maintenance-field small,
.maintenance-threshold span,
.maintenance-candidates span,
.maintenance-candidates > small {
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.45;
}

.maintenance-threshold {
  display: block;
  margin-top: 12px;
}

.maintenance-switches {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin: 4px 0 12px;
}

.maintenance-switches label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--yui-text);
  font-size: 12px;
}

.maintenance-summary {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.maintenance-summary > div {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
  padding: 8px;
}

.maintenance-summary span,
.maintenance-summary strong {
  display: block;
}

.maintenance-summary span {
  color: var(--yui-muted);
  font-size: 11px;
}

.maintenance-summary strong {
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 17px;
}

.maintenance-candidates {
  display: flex;
  max-height: 280px;
  flex-direction: column;
  gap: 7px;
  overflow: auto;
}

.maintenance-candidates article {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
  padding: 9px;
}

.maintenance-candidates article > div {
  min-width: 0;
  flex: 1;
}

.maintenance-candidates strong {
  display: block;
  color: var(--yui-text);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.query-layer-picker {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 8px;
  margin-top: 12px;
}

.query-layer-chip {
  min-width: 108px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
  color: var(--yui-text);
  cursor: pointer;
  padding: 7px 9px;
  text-align: left;
  transition: background-color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.query-layer-chip:hover,
.query-layer-chip:focus-visible,
.query-layer-chip.active {
  outline: none;
  border-color: var(--yui-border-strong);
  box-shadow: 0 0 0 2px var(--yui-accent-soft);
}

.query-layer-chip.active {
  background: var(--yui-accent-soft);
}

.query-layer-chip strong,
.layer-action-grid strong {
  display: block;
  color: var(--yui-text);
  font-size: 11px;
  font-weight: 800;
  line-height: 1.25;
}

.query-layer-chip span,
.layer-action-grid span {
  display: block;
  margin-top: 3px;
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.35;
}

.trace-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.duplicate-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(245, 158, 11, 0.28);
  border-radius: var(--yui-radius-card);
  background: var(--yui-warning-soft);
}

.candidate-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
}

.candidate-main {
  display: grid;
  grid-template-columns: minmax(88px, auto) minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.candidate-main span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-list,
.query-result-list,
.memory-doc-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.review-item,
.query-result-card,
.memory-doc-card {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  padding: 12px;
}

.review-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.review-item span {
  display: block;
  margin-top: 4px;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.5;
}

.query-result-card {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 10px;
}

.query-rank {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: rgba(37, 99, 235, 0.08);
  color: var(--yui-text);
  font-size: 12px;
  font-weight: 850;
}

.query-result-main {
  min-width: 0;
}

.query-result-main p,
.memory-doc-card p {
  margin: 0 0 9px;
  color: var(--yui-text);
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.memory-doc-list {
  max-height: 620px;
  overflow-y: auto;
  padding-right: 4px;
}

.doc-list-more {
  min-height: 38px;
  border: 1px dashed var(--yui-border-strong);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  cursor: pointer;
  font-size: 12px;
  font-weight: 760;
}

.doc-list-more:hover,
.doc-list-more:focus-visible {
  outline: none;
  border-color: var(--yui-accent);
  box-shadow: 0 0 0 2px var(--yui-accent-soft);
}

.doc-filter-stack {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  min-width: 0;
}

.doc-layout {
  display: grid;
  grid-template-columns: minmax(280px, 0.96fr) minmax(260px, 0.74fr);
  gap: 12px;
  align-items: start;
  min-width: 0;
}

.memory-doc-card {
  display: block;
  cursor: pointer;
  transition: background-color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.memory-doc-card:hover,
.memory-doc-card:focus-visible,
.memory-doc-card.active {
  outline: none;
  border-color: var(--yui-border-strong);
  box-shadow: var(--yui-shadow-hover);
}

.memory-doc-card.active {
  background: var(--yui-accent-soft);
}

.memory-doc-card.hit {
  border-color: rgba(16, 185, 129, 0.48);
}

.memory-doc-card.hit:not(.active) {
  background: var(--yui-success-soft);
}

.doc-card-main {
  min-width: 0;
}

.doc-card-head,
.doc-meta,
.doc-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.doc-card-head {
  justify-content: space-between;
  margin-bottom: 8px;
}

.doc-meta {
  flex-wrap: wrap;
}

.doc-meta span {
  border-radius: 999px;
  background: var(--yui-surface-muted);
  padding: 3px 8px;
}

.doc-actions {
  justify-content: flex-start;
  align-self: start;
}

.doc-inspector {
  position: sticky;
  top: 0;
  display: flex;
  min-width: 0;
  max-height: 620px;
  flex-direction: column;
  gap: 12px;
  overflow: auto;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 12px;
}

.inspector-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.inspector-head > div {
  min-width: 0;
}

.inspector-head span {
  display: block;
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.inspector-head strong {
  display: block;
  margin-top: 3px;
  color: var(--yui-text);
  font-size: 14px;
  font-weight: 850;
}

.inspector-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
  padding: 10px;
}

.editor-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.editor-field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
}

.editor-field-full {
  grid-column: 1 / -1;
}

.inspector-text {
  margin: 0;
  color: var(--yui-text);
  font-size: 13px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.inspector-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.inspector-grid > div {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
  padding: 9px;
}

.inspector-grid span {
  display: block;
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.35;
}

.inspector-grid strong {
  display: block;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 12px;
  font-weight: 820;
  overflow-wrap: anywhere;
}

.inspector-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.layer-action-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.layer-action-grid button {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
  cursor: pointer;
  padding: 8px;
  text-align: left;
  transition: background-color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.layer-action-grid button:hover,
.layer-action-grid button:focus-visible,
.layer-action-grid button.active {
  outline: none;
  border-color: var(--yui-border-strong);
  box-shadow: 0 0 0 2px var(--yui-accent-soft);
}

.layer-action-grid button.active {
  background: var(--yui-accent-soft);
}

.inspector-details {
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
  padding: 9px 10px;
}

.inspector-details summary {
  color: var(--yui-text);
  cursor: pointer;
  font-size: 12px;
  font-weight: 760;
}

.inspector-details pre {
  max-height: 210px;
  margin: 10px 0 0;
  overflow: auto;
  color: var(--yui-text);
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.audit-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}

.audit-list > div {
  min-width: 0;
  border-radius: 8px;
  background: var(--yui-surface-muted);
  padding: 8px;
}

.audit-list strong,
.audit-list span {
  display: block;
  font-size: 12px;
  line-height: 1.45;
}

.audit-list strong {
  color: var(--yui-text);
}

.audit-list span {
  margin-top: 2px;
  color: var(--yui-muted);
  overflow-wrap: anywhere;
}

.trace-header,
.trace-line {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.trace-header {
  justify-content: space-between;
}

.trace-title,
.trace-label {
  color: var(--yui-text);
  font-weight: 600;
}

.trace-label {
  min-width: 84px;
  color: var(--yui-muted);
}

.trace-ids {
  align-items: flex-start;
  flex-wrap: wrap;
}

.trace-ids code,
.trace-more {
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--yui-surface-raised);
  color: var(--yui-text);
  font-size: 12px;
}

.tag-row {
  flex-wrap: wrap;
}

.tag-row .el-button,
.button-row .el-button,
.filter-row .el-input,
.filter-row .el-select {
  min-width: 0;
}

.button-row {
  flex-wrap: wrap;
}

.footer-actions {
  justify-content: flex-end;
}

.filter-select {
  width: 140px;
}

.filter-input {
  width: 180px;
}

.important-high {
  color: var(--el-color-danger);
  font-weight: 600;
}

.important-medium {
  color: var(--el-color-warning);
  font-weight: 600;
}

.important-low {
  color: var(--el-text-color-secondary);
}

@media (max-width: 960px) {
  .layout-grid,
  .form-grid,
  .doc-layout {
    grid-template-columns: 1fr;
  }

  .layout-grid,
  .left-column,
  .right-column,
  .panel-toolbar,
  .card-header,
  .doc-filter-stack,
  .toolbar-actions {
    width: 100%;
    max-width: 100%;
  }

  .panel-toolbar,
  .card-header,
  .trace-header,
  .trace-line,
  .filter-row,
  .doc-filter-stack {
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar-actions {
    justify-content: flex-start;
  }

  .filter-select,
  .filter-input,
  .scope-select,
  .toolbar-field {
    width: 100%;
  }

  .candidate-main {
    grid-template-columns: 1fr;
  }

  .layer-map,
  .index-grid,
  .memory-doc-card,
  .inspector-grid,
  .editor-grid,
  .layer-action-grid {
    grid-template-columns: 1fr;
  }

  .doc-inspector {
    position: static;
    max-height: none;
  }

  .doc-card-head,
  .doc-actions {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 760px) {
  .memory-panel,
  .left-column,
  .right-column {
    gap: 12px;
  }

  .panel-toolbar {
    padding: 12px;
  }

  :deep(.el-card__body) {
    padding: 14px;
  }

  .maintenance-policy-grid,
  .maintenance-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

}
</style>
