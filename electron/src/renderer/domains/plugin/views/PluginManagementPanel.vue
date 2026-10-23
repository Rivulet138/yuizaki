<template>
  <PanelShell :title="t('pluginPanel.title')" tone="companion">
    <div class="plugin-console">
      <section class="plugin-toolbar" :aria-label="t('pluginPanel.actionsAria')">
        <div class="toolbar-actions">
          <el-button plain :disabled="problemPluginCount === 0 && loadFailures.length === 0" @click="showProblemPlugins">{{ t('pluginPanel.filterProblems') }}</el-button>
<el-button type="primary" :loading="pluginsRequest.loading" @click="loadPlugins">{{ t('pluginPanel.refresh') }}</el-button>
        </div>
      </section>

      <section class="plugin-layout">
        <el-card class="panel-card plugin-list-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
              <strong>{{ t('pluginPanel.count', { filtered: filteredPluginRows.length, total: pluginRows.length }) }}</strong>
              </div>
              <el-tag :type="blockedOrErrorCount > 0 ? 'danger' : 'success'">{{ blockedOrErrorCount > 0 ? t('pluginPanel.hasProblems') : t('pluginPanel.noProblems') }}</el-tag>
            </div>
          </template>

          <div class="filter-bar">
            <el-input v-model="searchQuery" clearable :placeholder="t('pluginPanel.searchPlaceholder')" />
            <el-select v-model="statusFilter" class="filter-select" :placeholder="t('pluginPanel.statusPlaceholder')">
              <el-option :label="t('pluginPanel.statusAll')" value="all" />
              <el-option :label="t('pluginPanel.statusProblem')" value="problem" />
              <el-option :label="t('pluginPanel.statusLoaded')" value="loaded" />
              <el-option :label="t('pluginPanel.statusDegraded')" value="degraded" />
              <el-option :label="t('pluginPanel.statusBlocked')" value="blocked" />
              <el-option :label="t('pluginPanel.statusError')" value="error" />
            </el-select>
            <el-select v-model="categoryFilter" class="filter-select" :placeholder="t('pluginPanel.categoryPlaceholder')">
              <el-option :label="t('pluginPanel.categoryAll')" value="all" />
              <el-option :label="t('pluginPanel.contributionCapability')" value="capability" />
              <el-option :label="t('pluginPanel.contributionEvent')" value="event" />
              <el-option :label="t('pluginPanel.contributionPolicy')" value="policy" />
            </el-select>
          </div>

          <AsyncState
            :loading="pluginsRequest.loading"
            :error="pluginsRequest.error"
            :empty="pluginRows.length === 0"
            :empty-text="t('pluginPanel.emptySkills')"
            :show-retry="false"
          >
            <div v-if="filteredPluginRows.length" class="plugin-grid">
              <button
                v-for="plugin in filteredPluginRows"
                :key="plugin.id"
                class="plugin-card"
                :class="[{ active: plugin.id === selectedPlugin?.id }, plugin.status]"
                type="button"
                @click="selectPlugin(plugin.id)"
              >
                  <div class="plugin-card-head">
                  <div class="plugin-avatar">{{ plugin.name.slice(0, 1).toUpperCase() }}</div>
                  <div>
                    <strong>{{ plugin.name }}</strong>
                  </div>
                </div>
                <p>{{ pluginSkillSummary(plugin) }}</p>
                <div class="plugin-card-meta">
                  <el-tag size="small" :type="statusTagType(plugin.status)">{{ statusLabel(plugin.status) }}</el-tag>
                  <span>{{ t('pluginPanel.statEntries', { count: plugin.routeCount }) }}</span>
                  <span>{{ t('pluginPanel.statCapabilities', { count: plugin.toolCount }) }}</span>
                  <span v-if="plugin.petEvents?.length">{{ t('pluginPanel.statTriggers', { count: plugin.petEvents.length }) }}</span>
                  <span>{{ t('pluginPanel.statExecutions', { count: plugin.activeCount }) }}</span>
                </div>
              </button>
            </div>
            <el-empty v-else :description="t('pluginPanel.emptyFiltered')" :image-size="72" />
          </AsyncState>
        </el-card>

        <el-card class="panel-card detail-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>{{ selectedPlugin?.name ?? t('pluginPanel.selectHint') }}</strong>
              </div>
              <el-tag :type="statusTagType(selectedPluginState?.status)">{{ statusLabel(selectedPluginState?.status ?? 'loaded') }}</el-tag>
            </div>
          </template>

          <div v-if="selectedPlugin" class="detail-stack">
            <div class="detail-block skill-benefit-block">
              <label>{{ t('pluginPanel.detailCapabilities') }}</label>
              <p class="skill-benefit-text">{{ selectedSkillSummary }}</p>
              <div v-if="selectedPlugin.petEvents?.length" class="tag-wrap">
                <el-tag v-for="event in selectedPlugin.petEvents" :key="`${event.event}-${event.routeId || 'local'}`" type="info">
                  {{ petEventRouteLabel(event) }}
                </el-tag>
              </div>
            </div>

            <div v-if="selectedPetEventRows.length" class="detail-block pet-trigger-block">
              <label>{{ t('pluginPanel.detailEvents') }}</label>
              <div class="pet-trigger-list">
                <div v-for="event in selectedPetEventRows" :key="`${event.event}-${event.routeId || 'local'}`" class="pet-trigger-row">
                  <div class="pet-trigger-head">
                    <strong>{{ event.label }}</strong>
                    <el-tag size="small" :type="event.routeId ? 'success' : 'info'">{{ event.routeLabel }}</el-tag>
                  </div>
                  <p>{{ event.descriptionText }}</p>
                  <small>{{ event.trigger }}</small>
                  <small>{{ event.payloadHint }}</small>
                </div>
              </div>
            </div>

            <div class="detail-block risk-block">
              <label>{{ t('pluginPanel.detailComposition') }}</label>
              <div class="tag-wrap">
                <el-tag v-if="selectedPlugin.toolCapabilities?.length" type="success">{{ t('pluginPanel.compositionTools', { count: selectedPlugin.toolCapabilities.length }) }}</el-tag>
                <el-tag v-if="selectedPlugin.modelProviders?.length" type="warning">{{ t('pluginPanel.compositionModels', { count: selectedPlugin.modelProviders.length }) }}</el-tag>
                <el-tag v-if="selectedPlugin.petEvents?.length" type="info">{{ t('pluginPanel.compositionPetEvents', { count: selectedPlugin.petEvents.length }) }}</el-tag>
                <el-tag v-if="permissionCount > 0" type="danger">{{ t('pluginPanel.compositionPermissions', { count: permissionCount }) }}</el-tag>
                <el-tag v-if="selectedPluginState?.executionIsolation === 'node-permission-process'" type="success">{{ t('pluginPanel.isolationRestricted') }}</el-tag>
                <el-tag v-if="selectedPluginState?.stats.totalInvocations" type="info">{{ t('pluginPanel.compositionInvocations', { count: selectedPluginState.stats.totalInvocations }) }}</el-tag>
              </div>
            </div>

            <div class="detail-block">
              <label>{{ t('pluginPanel.detailPermissions') }}</label>
              <div class="tag-wrap permission-tags">
                <el-tag v-for="routeId in selectedPlugin.permissions.routes" :key="`route:${routeId}`" type="primary">{{ t('pluginPanel.permissionRoute', { id: routeId }) }}</el-tag>
                <el-tag v-for="toolId in selectedPlugin.permissions.toolScopes" :key="`tool:${toolId}`" type="success">{{ t('pluginPanel.permissionTool', { id: toolId }) }}</el-tag>
                <el-tag v-for="providerId in selectedPlugin.permissions.modelScopes" :key="`model:${providerId}`" type="warning">{{ t('pluginPanel.permissionModel', { id: providerId }) }}</el-tag>
                <el-tag v-if="selectedPlugin.permissions.agentBridge" type="danger">{{ t('pluginPanel.permissionAgentBridge') }}</el-tag>
                <el-tag v-for="host in selectedPlugin.permissions.allowedHosts ?? []" :key="`host:${host}`" type="info">{{ t('pluginPanel.permissionHost', { host }) }}</el-tag>
                <el-tag v-for="allowedPath in selectedPlugin.permissions.allowedPaths ?? []" :key="`path:${allowedPath}`">
                  {{ t('pluginPanel.permissionPath', { path: allowedPath }) }}
                </el-tag>
                <el-tag v-for="command in selectedPlugin.permissions.allowedCommands ?? []" :key="`command:${command}`" type="danger">{{ t('pluginPanel.permissionCommand', { command }) }}</el-tag>
                <span v-if="permissionCount === 0" class="muted-text">{{ t('pluginPanel.noExtraPermissions') }}</span>
              </div>
            </div>

            <div class="detail-block">
              <label>{{ t('pluginPanel.auditTitle') }}</label>
              <div class="kv-list">
                <div><strong>{{ t('pluginPanel.auditLastAtLabel') }}</strong>{{ selectedPluginState?.lastAuditAt ?? t('pluginPanel.notAvailable') }}</div>
                <div><strong>{{ t('pluginPanel.auditLastErrorLabel') }}</strong>{{ selectedPluginState?.lastError ?? t('pluginPanel.notAvailable') }}</div>
                <div><strong>{{ t('pluginPanel.auditOkLabel') }}</strong>{{ t('pluginPanel.auditOkValue', { count: selectedPluginState?.stats.okCount ?? 0 }) }}</div>
                <div><strong>{{ t('pluginPanel.auditErrorLabel') }}</strong>{{ t('pluginPanel.auditErrorValue', { count: selectedPluginState?.stats.errorCount ?? 0, timeouts: selectedPluginState?.stats.timeoutCount ?? 0, denied: selectedPluginState?.stats.deniedCount ?? 0 }) }}</div>
              </div>
              <el-alert
                v-for="issue in selectedPluginState?.validationIssues ?? []"
                :key="`${issue.field}-${issue.message}`"
                :title="`${issue.field}: ${issue.message}`"
                :type="issue.severity === 'error' ? 'error' : 'warning'"
                :closable="false"
                style="margin-top: 8px"
              />
            </div>
          </div>
            <el-empty v-else :description="t('pluginPanel.emptySelection')" />
        </el-card>
      </section>

      <section class="lower-grid">
        <el-card class="panel-card" shadow="never">
          <template #header>
            <div class="card-head compact">
            <strong>{{ t('pluginPanel.runningTitle') }}</strong>
              <el-tag type="info">{{ t('pluginPanel.recordCount', { count: selectedPluginState?.activeExecutions.length ?? 0 }) }}</el-tag>
            </div>
          </template>
          <el-empty v-if="selectedPluginState == null || selectedPluginState.activeExecutions.length === 0" :description="t('pluginPanel.emptyRunning')" :image-size="56" />
          <el-table v-else :data="selectedPluginState.activeExecutions" size="small" stripe>
            <el-table-column prop="routeId" :label="t('pluginPanel.columnRoute')" min-width="140" />
            <el-table-column prop="startedAt" :label="t('pluginPanel.columnStartedAt')" min-width="160" />
            <el-table-column prop="status" :label="t('pluginPanel.columnStatus')" width="110">
              <template #default="scope">
                <el-tag size="small" type="info">{{ executionStatusLabel(scope.row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('pluginPanel.columnActions')" width="100">
              <template #default="scope">
                <el-button
                  link
                  type="danger"
                  :loading="cancellingInvocationIds.has(scope.row.invocationId)"
                  :disabled="!selectedPlugin?.execution.allowCancellation || cancellingInvocationIds.has(scope.row.invocationId)"
                  @click="handleCancel(selectedPlugin.id, scope.row.routeId, scope.row.invocationId)"
                >
                  {{ t('pluginPanel.actionCancel') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card class="panel-card" shadow="never">
          <template #header>
            <div class="card-head compact">
            <strong>{{ t('pluginPanel.compositionTitle') }}</strong>
              <el-tag type="info">{{ t('pluginPanel.categoryCount', { count: contributionSummaries.length }) }}</el-tag>
            </div>
          </template>
          <div v-if="contributionSummaries.length" class="contribution-list">
            <div v-for="item in contributionSummaries" :key="item.category" class="contribution-item">
              <span>{{ contributionLabel(item.category) }}</span>
              <strong>{{ item.count }}</strong>
              <small>{{ item.items.slice(0, 4).join(' / ') || t('pluginPanel.noEntries') }}</small>
            </div>
          </div>
          <el-empty v-else :description="t('pluginPanel.emptyComposition')" :image-size="56" />
        </el-card>
      </section>

      <section class="lower-grid audit-grid">
        <el-card class="panel-card" shadow="never">
          <template #header>
            <div class="card-head compact">
            <strong>{{ t('pluginPanel.loadFailuresTitle') }}</strong>
              <el-tag :type="loadFailures.length > 0 ? 'danger' : 'success'">{{ t('pluginPanel.recordCount', { count: loadFailures.length }) }}</el-tag>
            </div>
          </template>
          <el-empty v-if="loadFailures.length === 0" :description="t('pluginPanel.emptyLoadFailures')" :image-size="56" />
          <el-table v-else :data="loadFailures" size="small" stripe height="220">
            <el-table-column prop="manifestPath" :label="t('pluginPanel.columnManifestPath')" min-width="220" />
            <el-table-column prop="pluginId" :label="t('pluginPanel.columnSkillName')" min-width="120" />
            <el-table-column prop="reason" :label="t('pluginPanel.columnReason')" min-width="220" />
          </el-table>
        </el-card>

        <el-card class="panel-card" shadow="never">
          <template #header>
            <div class="card-head compact">
            <strong>{{ t('pluginPanel.auditTitle') }}</strong>
              <el-tag type="info">{{ t('pluginPanel.recentCount', { count: auditLogs.length }) }}</el-tag>
            </div>
          </template>
          <el-empty v-if="auditLogs.length === 0" :description="t('pluginPanel.emptyAudit')" :image-size="56" />
          <el-table v-else :data="auditLogs" size="small" stripe height="240">
            <el-table-column prop="timestamp" :label="t('pluginPanel.columnTime')" min-width="160" />
            <el-table-column prop="pluginId" :label="t('pluginPanel.columnSkill')" min-width="130" />
            <el-table-column prop="routeId" :label="t('pluginPanel.columnRouteId')" min-width="110" />
            <el-table-column prop="status" :label="t('pluginPanel.columnResult')" width="96">
              <template #default="scope">
                <el-tag :type="auditTagType(scope.row.status)">{{ auditStatusLabel(scope.row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="detail" :label="t('pluginPanel.columnDetail')" min-width="220" />
          </el-table>
        </el-card>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { ElAlert, ElEmpty } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/empty/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElCard } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import { ElTable, ElTableColumn, ElTag } from 'element-plus'
import 'element-plus/es/components/table/style/css'
import 'element-plus/es/components/table-column/style/css'
import 'element-plus/es/components/tag/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { t } from '@/i18n'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { usePluginDomain } from '../composables/usePluginDomain'
import { getDesktopPetEventDefinition } from '../../../../shared/plugin'
import type {
  DesktopPetEventName,
  DesktopPetPlugin,
  PluginAuditRecord,
  PluginContributionCategory,
  PluginExecutionStatus,
  PluginPetEventSubscription,
  PluginRuntimeState
} from '../../../../shared/plugin'

type StatusFilter = 'all' | 'problem' | PluginRuntimeState['status']
type CategoryFilter = 'all' | Exclude<PluginContributionCategory, 'ui'>

const {
  payload,
  pluginsRequest,
  cancelRequest,
  pluginRows,
  loadFailures,
  auditLogs,
  selectedPlugin,
  selectedPluginId,
  selectedPluginState,
  blockedOrErrorCount,
  cancellingInvocationIds,
  loadPlugins,
  cancelExecution
} = usePluginDomain()

const searchQuery = ref('')
const statusFilter = ref<StatusFilter>('all')
const categoryFilter = ref<CategoryFilter>('all')

const statusTagType = (status?: PluginRuntimeState['status']) => {
  if (status === 'loaded') return 'success'
  if (status === 'degraded') return 'warning'
  if (status === 'blocked' || status === 'error') return 'danger'
  return 'info'
}

const auditTagType = (status: PluginAuditRecord['status']) => {
  if (status === 'ok') return 'success'
  if (status === 'denied') return 'warning'
  if (status === 'cancelled') return 'info'
  return 'danger'
}

const statusLabel = (status: PluginRuntimeState['status']) => {
  const labels: Record<PluginRuntimeState['status'], string> = {
    loaded: t('pluginPanel.statusLoaded'),
    degraded: t('pluginPanel.statusDegraded'),
    blocked: t('pluginPanel.statusBlocked'),
    error: t('pluginPanel.statusError'),
  }
  return labels[status]
}

const auditStatusLabel = (status: PluginAuditRecord['status']) => {
  const labels: Record<PluginAuditRecord['status'], string> = {
    ok: t('pluginPanel.auditOk'),
    error: t('pluginPanel.auditError'),
    timeout: t('pluginPanel.auditTimeout'),
    denied: t('pluginPanel.auditDenied'),
    cancelled: t('pluginPanel.auditCancelled'),
  }
  return labels[status]
}

const executionStatusLabel = (status: PluginExecutionStatus) => {
  const labels: Record<PluginExecutionStatus, string> = {
    running: t('pluginPanel.executionRunning'),
    cancelled: t('pluginPanel.executionCancelled'),
    timed_out: t('pluginPanel.executionTimedOut'),
  }
  return labels[status]
}

const contributionLabel = (category: PluginContributionCategory) => {
  const labels: Record<PluginContributionCategory, string> = {
    ui: t('pluginPanel.contributionUi'),
    capability: t('pluginPanel.contributionCapability'),
    event: t('pluginPanel.contributionEvent'),
    policy: t('pluginPanel.contributionPolicy'),
  }
  return labels[category]
}

const petEventLabel = (event: DesktopPetEventName) => getDesktopPetEventDefinition(event).label

const petEventRouteLabel = (event: { event: DesktopPetEventName; routeId?: string }) =>
  event.routeId
    ? t('pluginPanel.petEventTriggered', { event: petEventLabel(event.event), route: event.routeId })
    : t('pluginPanel.petEventDeclared', { event: petEventLabel(event.event) })

const buildPetEventRow = (event: PluginPetEventSubscription) => {
  const definition = getDesktopPetEventDefinition(event.event)
  return {
    ...event,
    label: definition.label,
    trigger: definition.trigger,
    payloadHint: definition.payloadHint,
    frequencyHint: definition.frequencyHint,
    routeLabel: event.routeId ? t('pluginPanel.routeCall', { route: event.routeId }) : t('pluginPanel.declaredOnly'),
    descriptionText: event.description || t('pluginPanel.petEventDescription', { label: definition.label }),
  }
}

const pluginSkillSummary = (plugin: DesktopPetPlugin & { lastError?: string }) => {
  if (plugin.lastError && plugin.lastError !== '—') {
    return t('pluginPanel.lastErrorSummary', { error: plugin.lastError })
  }
  const primaryTool = plugin.toolCapabilities?.[0]
  if (primaryTool) {
  return primaryTool.desc || t('pluginPanel.toolSummary', { tool: primaryTool.name })
  }
  const primaryModel = plugin.modelProviders?.[0]
  if (primaryModel) {
    return t('pluginPanel.modelSummary', { type: primaryModel.modelType.toUpperCase(), name: primaryModel.name })
  }
  const primaryEvent = plugin.petEvents?.[0]
  if (primaryEvent) {
    return primaryEvent.description || t('pluginPanel.eventSummary', { event: petEventLabel(primaryEvent.event) })
  }
  return t('pluginPanel.installedNoCapability')
}

const contributionSummaries = computed(() =>
  (payload.value?.contributionSummary ?? []).filter((item) => item.category !== 'ui'),
)
const problemPluginCount = computed(() => pluginRows.value.filter((plugin) => plugin.status !== 'loaded').length)
const selectedSkillSummary = computed(() => selectedPlugin.value ? pluginSkillSummary(selectedPlugin.value) : '')
const selectedPetEventRows = computed(() => (selectedPlugin.value?.petEvents ?? []).map(buildPetEventRow))

const permissionCount = computed(() => {
  const permissions = selectedPlugin.value?.permissions
  if (!permissions) return 0
  return permissions.routes.length
    + permissions.toolScopes.length
    + permissions.modelScopes.length
    + (permissions.agentBridge ? 1 : 0)
    + (permissions.allowedHosts?.length ?? 0)
    + (permissions.allowedPaths?.length ?? 0)
    + (permissions.allowedCommands?.length ?? 0)
})

const pluginPermissionCount = (plugin: (typeof pluginRows.value)[number]) =>
  plugin.permissions.routes.length
  + plugin.permissions.toolScopes.length
  + plugin.permissions.modelScopes.length
  + (plugin.permissions.agentBridge ? 1 : 0)
  + (plugin.permissions.allowedHosts?.length ?? 0)
  + (plugin.permissions.allowedPaths?.length ?? 0)
  + (plugin.permissions.allowedCommands?.length ?? 0)

const pluginHasEventContribution = (pluginId: string) =>
  auditLogs.value.some((item) => item.pluginId === pluginId && item.routeId === 'proactive_dispatch')

const pluginMatchesCategory = (plugin: (typeof pluginRows.value)[number]) => {
  if (categoryFilter.value === 'all') return true
  if (categoryFilter.value === 'capability') return (plugin.toolCapabilities?.length ?? 0) + (plugin.modelProviders?.length ?? 0) > 0
  if (categoryFilter.value === 'event') return (plugin.petEvents?.length ?? 0) > 0 || pluginHasEventContribution(plugin.id)
  return pluginPermissionCount(plugin) > 0
}

const filteredPluginRows = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  return pluginRows.value.filter((plugin) => {
    if (statusFilter.value === 'problem') {
      if (plugin.status === 'loaded') return false
    } else if (statusFilter.value !== 'all' && plugin.status !== statusFilter.value) {
      return false
    }
    if (!pluginMatchesCategory(plugin)) return false
    if (!keyword) return true

    const searchable = [
      plugin.name,
      plugin.id,
      ...(plugin.routes ?? []).map((item) => item.id),
      ...(plugin.toolCapabilities ?? []).map((item) => item.id),
      ...(plugin.toolCapabilities ?? []).map((item) => item.name),
      ...(plugin.toolCapabilities ?? []).map((item) => item.desc),
      ...(plugin.modelProviders ?? []).map((item) => item.id),
      ...(plugin.modelProviders ?? []).map((item) => item.name),
      ...(plugin.petEvents ?? []).map((item) => item.event),
      ...(plugin.petEvents ?? []).map((item) => item.routeId ?? ''),
      ...(plugin.petEvents ?? []).map((item) => item.description ?? ''),
      ...(plugin.petEvents ?? []).flatMap((item) => {
        const definition = getDesktopPetEventDefinition(item.event)
        return [definition.label, definition.trigger, definition.payloadHint]
      }),
      ...(plugin.permissions.agentBridge ? ['agentBridge'] : []),
      ...(plugin.permissions.allowedHosts ?? []),
      ...(plugin.permissions.allowedPaths ?? []),
      ...(plugin.permissions.allowedCommands ?? []),
      plugin.lastError,
    ].join(' ').toLowerCase()
    return searchable.includes(keyword)
  })
})

const selectPlugin = (pluginId: string) => {
  selectedPluginId.value = pluginId
}

const showProblemPlugins = () => {
  statusFilter.value = 'problem'
  categoryFilter.value = 'all'
  searchQuery.value = ''
}

const handleCancel = async (pluginId: string, routeId: string, invocationId: string) => {
  const cancelled = await cancelExecution(pluginId, routeId, invocationId)
  if (cancelled) {
    ElMessage.success(t('pluginPanel.cancelSent'))
  } else {
    ElMessage.error(cancelRequest.error || t('pluginPanel.cancelFailed'))
  }
}

onMounted(() => {
  void loadPlugins()
})
</script>

<style scoped>
.plugin-console {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.plugin-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
  padding: 14px 16px;
  box-shadow: var(--yui-shadow-card);
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.panel-card {
  border: 1px solid var(--yui-border);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
}

.plugin-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(360px, 0.85fr);
  gap: 16px;
  align-items: start;
}

.panel-card {
  border-radius: var(--yui-radius-card);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-head > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-head.compact {
  flex-direction: row;
}

.filter-bar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 140px 140px;
  gap: 10px;
  margin-bottom: 14px;
}

.filter-select {
  width: 100%;
}

.plugin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 12px;
  max-height: 520px;
  overflow: auto;
  padding-right: 4px;
}

.plugin-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 152px;
  padding: 14px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  text-align: left;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.plugin-card:hover,
.plugin-card.active {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.5);
  box-shadow: 0 16px 34px rgba(37, 99, 235, 0.12);
}

.plugin-card.blocked,
.plugin-card.error {
  border-color: rgba(248, 113, 113, 0.55);
}

.plugin-card-head {
  display: flex;
  gap: 12px;
  align-items: center;
}

.plugin-card-head > div:last-child {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.plugin-card-head strong {
  color: var(--yui-text);
}

.plugin-card-head span,
.plugin-card p,
.plugin-card-meta span,
.muted-text {
  color: var(--yui-muted);
  font-size: 12px;
}

.plugin-card p {
  display: -webkit-box;
  min-height: 38px;
  margin: 0;
  overflow: hidden;
  line-height: 1.55;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.plugin-avatar {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 14px;
  background: var(--yui-accent-soft);
  color: var(--yui-accent);
  font-weight: 800;
}

.plugin-card-meta,
.tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.detail-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.manifest-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.manifest-summary > div,
.detail-block,
.contribution-item {
  padding: 13px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.manifest-summary span,
.manifest-summary small,
.contribution-item small {
  display: block;
  color: var(--yui-muted);
  font-size: 12px;
}

.manifest-summary strong {
  display: block;
  margin: 4px 0;
  color: var(--yui-text);
  font-size: 20px;
}

.detail-block label {
  display: block;
  margin-bottom: 10px;
  color: var(--yui-text);
  font-weight: 700;
}

.skill-benefit-text {
  margin: 0 0 10px;
  color: var(--yui-text);
  font-size: 13px;
  line-height: 1.6;
}

.pet-trigger-block {
  background: var(--yui-surface);
}

.pet-trigger-list {
  display: grid;
  gap: 10px;
}

.pet-trigger-row {
  display: grid;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px solid var(--yui-border);
}

.pet-trigger-row:first-child {
  padding-top: 0;
  border-top: 0;
}

.pet-trigger-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.pet-trigger-head strong {
  color: var(--yui-text);
  font-size: 13px;
}

.pet-trigger-row p,
.pet-trigger-row small {
  margin: 0;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.5;
}

.pet-trigger-row p {
  color: var(--yui-text);
}

.permission-explain-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.permission-explain-list p {
  margin: 0;
  color: var(--yui-text);
  font-size: 13px;
  line-height: 1.55;
}

.risk-block {
  background: var(--yui-accent-soft);
}

.permission-tags {
  max-height: 140px;
  overflow: auto;
}

.kv-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: var(--yui-text);
  font-size: 13px;
  line-height: 1.55;
}

.lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.75fr);
  gap: 16px;
}

.audit-grid {
  grid-template-columns: minmax(340px, 0.85fr) minmax(0, 1.15fr);
}

.contribution-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}

.contribution-item {
  display: flex;
  min-height: 104px;
  flex-direction: column;
  justify-content: space-between;
}

.contribution-item span {
  color: var(--yui-muted);
  font-size: 13px;
  font-weight: 700;
}

.contribution-item strong {
  color: var(--yui-text);
  font-size: 24px;
}

@media (max-width: 1180px) {
  .plugin-layout,
  .lower-grid,
  .audit-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .plugin-toolbar,
  .filter-bar,
  .manifest-summary {
    grid-template-columns: 1fr;
  }

  .plugin-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar-actions {
    align-items: flex-start;
  }
}
</style>
