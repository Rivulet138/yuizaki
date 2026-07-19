<template>
  <PanelShell title="工具权限" tone="admin">
    <div class="governance-console">
      <section class="governance-toolbar" aria-label="治理操作">
        <div>
          <strong>{{ governancePosture }}</strong>
        </div>
        <div class="toolbar-actions">
          <el-tag :type="governancePostureTagType">{{ governancePosture }}</el-tag>
          <el-button type="primary" :loading="refreshing" @click="refreshGovernance">刷新治理快照</el-button>
        </div>
      </section>

      <section class="metric-grid" aria-label="Agent 治理概况">
        <article v-for="metric in governanceMetrics" :key="metric.label" class="metric-card" :class="metric.tone">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.detail }}</small>
        </article>
      </section>

      <section class="governance-grid">
        <el-card class="panel-card mcp-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>MCP 服务</strong>
                <span>{{ connectedMcpCount }} / {{ mcpRows.length }} 个连接可用</span>
              </div>
              <div class="action-row">
                <el-button plain size="small" :loading="mcpRequest.loading" @click="loadMcp">刷新</el-button>
              </div>
            </div>
          </template>
          <AsyncState :loading="mcpRequest.loading" :error="mcpRequest.error" @retry="loadMcp">
            <el-alert
              v-if="mcpMutationError"
              class="panel-alert"
              :title="mcpMutationError"
              type="error"
              show-icon
              :closable="false"
            />
            <div v-if="mcpRows.length" class="mcp-filter-row" role="tablist" aria-label="MCP 服务筛选">
              <button
                v-for="option in mcpFilterOptions"
                :key="option.value"
                type="button"
                class="mcp-filter-button"
                :class="{ active: mcpFilter === option.value }"
                @click="mcpFilter = option.value"
              >
                <span>{{ option.label }}</span>
                <strong>{{ option.count }}</strong>
              </button>
            </div>
            <div v-if="filteredMcpRows.length" class="server-list">
              <article v-for="row in filteredMcpRows" :key="row.name" class="server-card" :class="serverTone(row)">
                <div class="server-main">
                  <div class="server-status-dot" :class="row.connected ? 'online' : 'offline'"></div>
                  <div class="server-title">
                    <strong>{{ row.name }}</strong>
                    <span>{{ mcpEndpointLabel(row) }}</span>
                  </div>
                  <el-tag :type="mcpRowTagType(row)" size="small">{{ mcpRowStatusLabel(row) }}</el-tag>
                </div>
                <div class="server-inventory">
                  <el-tag size="small" type="success" :title="formatInventoryNames(row.tools)">工具 {{ row.tools_count }}</el-tag>
                  <el-tag size="small" type="info" :title="formatInventoryNames(row.resources)">资源 {{ row.resources_count }}</el-tag>
                  <el-tag size="small" type="warning" :title="formatInventoryNames(row.prompts)">Prompt {{ row.prompts_count }}</el-tag>
                  <el-tag v-if="row.inventory_error" size="small" type="danger" :title="row.inventory_error">库存异常</el-tag>
                </div>
                <div class="server-meta">
                  <span>传输：{{ transportLabel(row.transport) }}</span>
                  <span>调用 {{ row.total_calls ?? 0 }}</span>
                  <span>失败 {{ row.total_failures ?? 0 }}</span>
                  <span>待处理 {{ row.pending_requests ?? 0 }}</span>
                  <span v-if="row.env_keys?.length">环境变量 {{ row.env_keys.join(', ') }}</span>
                  <span v-if="row.header_keys?.length">请求头 {{ row.header_keys.join(', ') }}</span>
                </div>
                <div class="server-footer">
                  <el-switch
                    :model-value="row.enabled"
                    size="small"
                    :disabled="togglingMcpNames.has(row.name) || removingMcpNames.has(row.name)"
                    @change="(value) => toggleMcpItem(row.name, Boolean(value))"
                  />
                  <div class="action-row">
                    <el-button
                      type="primary"
                      link
                      size="small"
                      :loading="refreshingMcpNames.has(row.name)"
                      :disabled="refreshingMcpNames.has(row.name) || removingMcpNames.has(row.name)"
                      @click="refreshMcpItem(row.name)"
                    >
                      重连
                    </el-button>
                    <el-button
                      type="danger"
                      link
                      size="small"
                      :loading="removingMcpNames.has(row.name)"
                      :disabled="removingMcpNames.has(row.name)"
                      @click="removeMcpItem(row.name)"
                    >
                      删除
                    </el-button>
                  </div>
                </div>
                <div class="history-strip">
                  <div v-for="entry in recentMcpHistory(row.history).slice(0, 3)" :key="`${row.name}-${entry.timestamp}-${entry.event}-${entry.request_id || ''}`" class="history-chip">
                    <el-tag size="small" :type="mcpHistoryTagType(entry.status)">{{ mcpHistoryStatusLabel(entry.status) }}</el-tag>
                    <span>{{ entry.event }}</span>
                    <small>{{ formatMcpTimestamp(entry.timestamp) }}</small>
                  </div>
                  <span v-if="!row.history.length" class="empty-inline">暂无连接历史</span>
                </div>
              </article>
            </div>
            <el-empty v-else :description="mcpEmptyDescription" :image-size="72" />
          </AsyncState>
        </el-card>

        <aside class="side-stack">
          <el-card class="panel-card register-card" shadow="never">
            <template #header>
              <div class="card-head compact">
                <div>
                  <strong>新增 MCP 服务器</strong>
                </div>
                <el-tag type="primary">{{ transportLabel(mcpForm.transport) }}</el-tag>
              </div>
            </template>
            <div v-if="mcpPresets.length" class="preset-grid">
              <article v-for="preset in mcpPresets" :key="preset.id" class="preset-card" :class="{ installed: preset.installed }">
                <div>
                  <strong>{{ preset.name }}</strong>
                  <span>{{ preset.description }}</span>
                </div>
                <div class="preset-meta">
                  <el-tag size="small" type="info">{{ presetCategoryLabel(preset.category) }}</el-tag>
                  <el-tag size="small" type="primary">{{ transportLabel(preset.transport) }}</el-tag>
                  <el-tag v-if="preset.env_keys?.length" size="small" type="warning">{{ preset.env_keys.length }} 个环境变量</el-tag>
                  <el-tag v-if="preset.header_keys?.length" size="small" type="danger">{{ preset.header_keys.length }} 个请求头</el-tag>
                </div>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :disabled="preset.installed"
                  :loading="installMcpPresetRequest.loading"
                  @click="installPreset(preset.id)"
                >
                  {{ preset.installed ? '已安装' : '安装' }}
                </el-button>
              </article>
            </div>
            <el-alert v-if="installMcpPresetRequest.error" class="panel-alert" :title="installMcpPresetRequest.error" type="error" show-icon :closable="false" />
            <div class="form-grid">
              <el-input v-model="mcpForm.name" size="small" placeholder="服务标识名，例如 fetch" />
              <el-select v-model="mcpForm.transport" size="small">
                <el-option label="HTTP" value="http" />
                <el-option label="SSE" value="sse" />
                <el-option label="STDIO" value="stdio" />
                <el-option label="流式 HTTP" value="streamable_http" />
              </el-select>
              <el-input v-if="mcpForm.transport !== 'stdio'" v-model="mcpForm.base_url" size="small" class="wide" placeholder="服务地址 URL" />
              <template v-else>
                <el-input v-model="mcpForm.command" size="small" placeholder="命令，例如 npx / python" />
                <el-input v-model="mcpForm.args_text" size="small" placeholder='参数 JSON，例如 ["--config","E:\\My App\\mcp.json"]' />
              </template>
              <el-input v-model="mcpForm.env_text" size="small" class="wide" placeholder='环境变量 JSON，例如 {"FIRECRAWL_API_KEY":"{env:FIRECRAWL_API_KEY}"}' />
              <el-input v-model="mcpForm.headers_text" size="small" class="wide" placeholder='请求头 JSON，例如 {"Authorization":"Bearer {env:TOKEN}"}' />
            </div>
            <el-alert v-if="addMcpRequest.error" class="panel-alert" :title="addMcpRequest.error" type="error" show-icon :closable="false" />
            <div class="submit-row">
              <el-button type="primary" :disabled="!canSubmitMcp" :loading="addMcpRequest.loading" @click="submitMcp">注册并刷新</el-button>
            </div>
          </el-card>

          <el-card class="panel-card permission-card" shadow="never">
            <template #header>
              <div class="card-head compact">
                <div>
                  <strong>{{ permissionRows.length }} 条已记住规则</strong>
                </div>
                <div class="action-row">
                  <el-button plain size="small" :loading="permissionsRequest.loading" @click="loadPermissions">刷新</el-button>
                  <el-button size="small" type="danger" :disabled="permissionRows.length === 0" :loading="clearPermissionsRequest.loading" @click="clearAllPermissions">清空</el-button>
                </div>
              </div>
            </template>
            <AsyncState :loading="permissionsRequest.loading" :error="permissionsRequest.error" @retry="loadPermissions">
              <el-alert
                v-if="permissionMutationError"
                class="panel-alert"
                :title="permissionMutationError"
                type="error"
                show-icon
                :closable="false"
              />
              <div v-if="permissionRows.length" class="permission-list">
                <article v-for="row in permissionRows" :key="row.key" class="permission-item" :class="row.approved ? 'approved' : 'denied'">
                  <div>
                    <strong>{{ row.key }}</strong>
                    <span>{{ capabilityLabel(row.capabilityType, row.capabilityKind) }} · 风险 {{ riskLabel(row.riskLevel) }}</span>
                  </div>
                  <el-button
                    type="danger"
                    link
                    size="small"
                    :loading="revokingPermissionKeys.has(row.key)"
                    :disabled="revokingPermissionKeys.has(row.key)"
                    @click="revokePermissionItem(row.key)"
                  >
                    撤销
                  </el-button>
                </article>
              </div>
              <el-empty v-else description="暂无审批记录" :image-size="60" />
            </AsyncState>
          </el-card>
        </aside>
      </section>

      <section class="governance-grid lower-grid">
        <el-card class="panel-card extension-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>扩展宿主</strong>
                <span>Agent / Electron / MCP</span>
              </div>
              <el-button plain size="small" :loading="agentPluginsRequest.loading" @click="refreshExtensions">刷新扩展</el-button>
            </div>
          </template>
          <AsyncState :loading="extensionLoading" :error="extensionError" @retry="refreshExtensions">
            <div class="host-grid">
              <article v-for="host in extensionHosts" :key="host.label" class="host-card" :class="host.tone">
                <span>{{ host.label }}</span>
                <strong>{{ host.value }}</strong>
                <small>{{ host.detail }}</small>
              </article>
            </div>
            <el-alert v-if="agentPluginMutationError" class="panel-alert" :title="agentPluginMutationError" type="error" show-icon :closable="false" />
            <div v-if="agentPluginRows.length" class="agent-plugin-list" aria-label="Agent 插件运行配置">
              <article v-for="plugin in agentPluginRows" :key="plugin.id" class="agent-plugin-item" :class="{ disabled: !plugin.enabled, broken: plugin.error }">
                <div class="agent-plugin-main">
                  <div>
                    <strong>{{ plugin.name || plugin.id }}</strong>
                    <span>{{ plugin.id }}<template v-if="plugin.version"> · {{ plugin.version }}</template></span>
                  </div>
                  <div class="action-row">
                    <el-tag size="small" :type="plugin.loaded ? 'success' : plugin.error ? 'danger' : 'info'">{{ plugin.loaded ? '已加载' : plugin.error ? '异常' : '未加载' }}</el-tag>
                    <el-switch
                      :model-value="plugin.enabled"
                      size="small"
                      :disabled="togglingAgentPluginIds.has(plugin.id)"
                      @change="(value) => toggleAgentPluginItem(plugin.id, Boolean(value))"
                    />
                  </div>
                </div>
                <el-alert v-if="plugin.error" class="plugin-error" :title="plugin.error" type="error" show-icon :closable="false" />
                <div class="plugin-config-row">
                  <el-input
                    v-model="pluginConfigDrafts[plugin.id]"
                    type="textarea"
                    :autosize="{ minRows: 2, maxRows: 6 }"
                    resize="vertical"
                    spellcheck="false"
                  />
                  <el-button size="small" type="primary" plain :loading="updateAgentPluginConfigRequest.loading" @click="saveAgentPluginConfig(plugin.id)">保存配置</el-button>
                </div>
              </article>
            </div>
            <el-empty v-else description="暂无 Agent 插件" :image-size="60" />
            <div class="contribution-matrix">
              <div class="matrix-head">贡献类型</div>
              <div>Electron 插件</div>
              <div>Agent 插件</div>
              <div>MCP</div>
              <template v-for="row in contributionComparisonRows" :key="row.category">
                <div class="matrix-category">{{ contributionCategoryLabel(row.category) }}</div>
                <div>{{ row.electron }}</div>
                <div>{{ row.agent }}</div>
                <div>{{ row.mcp }}</div>
              </template>
            </div>
          </AsyncState>
        </el-card>

        <el-card class="panel-card audit-card" shadow="never">
          <template #header>
            <div class="card-head compact">
              <div>
                <strong>{{ permissionAuditRows.length }} 条事件</strong>
              </div>
              <el-tag :type="permissionAuditRows.length ? 'warning' : 'success'">{{ permissionAuditRows.length ? '可追踪' : '暂无事件' }}</el-tag>
            </div>
          </template>
          <AsyncState :loading="permissionsRequest.loading" :error="permissionsRequest.error" @retry="loadPermissions">
            <div v-if="permissionAuditRows.length" class="audit-timeline">
              <article v-for="item in permissionAuditRows.slice(0, 8)" :key="`${item.timestamp}-${item.capability_id || item.tool_name || item.decision}`" class="audit-item">
                <div class="audit-dot"></div>
                <div>
                  <strong>{{ permissionAuditTitle(item) }}</strong>
                  <span>{{ formatMcpTimestamp(item.timestamp) }} · {{ decisionLabel(item.decision) }} · 风险 {{ riskLabel(item.risk_level) }}</span>
                </div>
              </article>
            </div>
            <el-empty v-else description="暂无审批审计事件" :image-size="60" />
          </AsyncState>
        </el-card>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { onMounted, reactive, computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { useSystemDomain } from '../composables/useSystemDomain'
import { usePluginDomain } from '../../plugin/composables/usePluginDomain'
import type { MCPHistoryEntry, MCPInventoryItem, MCPServerConfigSnapshot, MCPServerPresetSnapshot, MCPServerStatusSnapshot, PermissionAuditRecord, RuntimeContributionSummary } from '@/../shared/agent'
import type { PluginContributionSummary } from '@/../shared/plugin'

const {
  permissions,
  mcp,
  agentPlugins,
  permissionsRequest,
  revokePermissionRequest,
  clearPermissionsRequest,
  mcpRequest,
  toggleMcpRequest,
  addMcpRequest,
  installMcpPresetRequest,
  removeMcpRequest,
  refreshMcpRequest,
  agentPluginsRequest,
  toggleAgentPluginRequest,
  updateAgentPluginConfigRequest,
  loadPermissions,
  revokePermission,
  clearPermissions,
  loadMcp,
  toggleMcp,
  addMcp,
  installMcpPreset,
  removeMcp,
  refreshMcp,
  loadAgentPlugins,
  toggleAgentPlugin,
  updateAgentPluginConfig,
} = useSystemDomain()

const {
  payload: electronPluginSnapshot,
  pluginsRequest,
  loadPlugins: loadElectronPlugins,
} = usePluginDomain()

const mcpForm = reactive({
  name: '',
  base_url: '',
  command: '',
  args_text: '',
  env_text: '',
  headers_text: '',
  transport: 'http',
  enabled: true,
})
const pluginConfigDrafts = reactive<Record<string, string>>({})
const removingMcpNames = ref(new Set<string>())
const togglingMcpNames = ref(new Set<string>())
const refreshingMcpNames = ref(new Set<string>())
const revokingPermissionKeys = ref(new Set<string>())
const togglingAgentPluginIds = ref(new Set<string>())
const mcpFilter = ref<MCPFilter>('all')

const addPending = (setRef: { value: Set<string> }, key: string) => {
  setRef.value = new Set(setRef.value).add(key)
}

const removePending = (setRef: { value: Set<string> }, key: string) => {
  const next = new Set(setRef.value)
  next.delete(key)
  setRef.value = next
}

type MCPRow = MCPServerConfigSnapshot & MCPServerStatusSnapshot & {
  name: string
  statusText: string
  history: MCPHistoryEntry[]
  tools_count: number
  resources_count: number
  prompts_count: number
  tools: MCPInventoryItem[]
  resources: MCPInventoryItem[]
  prompts: MCPInventoryItem[]
}

type MCPFilter = 'all' | 'connected' | 'error' | 'disabled'

interface MCPFilterOption {
  value: MCPFilter
  label: string
  count: number
}

const mcpRows = computed<MCPRow[]>(() => {
  if (!mcp.value) return []
  return Object.entries(mcp.value.servers).map(([name, server]) => {
    const status = mcp.value?.status?.[name]
    return {
      name,
      ...server,
      ...(status || {}),
      enabled: status?.enabled ?? server.enabled,
      transport: status?.transport || server.transport,
      statusText: status?.message || (status?.ok ? 'ok' : 'offline'),
      history: status?.history || [],
      tools: status?.tools || [],
      resources: status?.resources || [],
      prompts: status?.prompts || [],
      tools_count: status?.tools_count ?? status?.tools?.length ?? 0,
      resources_count: status?.resources_count ?? status?.resources?.length ?? 0,
      prompts_count: status?.prompts_count ?? status?.prompts?.length ?? 0,
    }
  })
})

const mcpContributionSummary = computed(() => mcp.value?.contributionSummary || [])
const mcpPresets = computed<MCPServerPresetSnapshot[]>(() => mcp.value?.presets || [])
const agentPluginRows = computed(() => agentPlugins.value?.plugins || [])
const agentPluginContributionSummary = computed(() => agentPlugins.value?.contributionSummary || [])
const electronPluginContributionSummary = computed(() => electronPluginSnapshot.value?.contributionSummary || [])
const permissionAuditRows = computed(() => [...(permissions.value?.audit || [])].reverse())

const formatPluginConfig = (config?: Record<string, unknown>) => JSON.stringify(config ?? {}, null, 2)

watch(agentPluginRows, (rows) => {
  const activeIds = new Set(rows.map((plugin) => plugin.id))
  rows.forEach((plugin) => {
    if (pluginConfigDrafts[plugin.id] === undefined) {
      pluginConfigDrafts[plugin.id] = formatPluginConfig(plugin.config)
    }
  })
  Object.keys(pluginConfigDrafts).forEach((pluginId) => {
    if (!activeIds.has(pluginId)) {
      delete pluginConfigDrafts[pluginId]
    }
  })
}, { immediate: true })

type ContributionCategory = RuntimeContributionSummary['category']
type ContributionSummaryItem = RuntimeContributionSummary | PluginContributionSummary

const contributionCategories: ContributionCategory[] = ['ui', 'capability', 'event', 'policy']
const contributionCount = (items: readonly ContributionSummaryItem[], category: ContributionCategory) => items.find((item) => item.category === category)?.count || 0
const contributionComparisonRows = computed(() => contributionCategories.map((category) => ({
  category,
  electron: contributionCount(electronPluginContributionSummary.value, category),
  agent: contributionCount(agentPluginContributionSummary.value, category),
  mcp: contributionCount(mcpContributionSummary.value, category),
})))

const refreshing = computed(() => mcpRequest.loading || permissionsRequest.loading || agentPluginsRequest.loading || pluginsRequest.loading)
const extensionLoading = computed(() => agentPluginsRequest.loading || pluginsRequest.loading || mcpRequest.loading)
const extensionError = computed(() => agentPluginsRequest.error || pluginsRequest.error || mcpRequest.error)
const mcpMutationError = computed(() => toggleMcpRequest.error || refreshMcpRequest.error || removeMcpRequest.error || installMcpPresetRequest.error)
const permissionMutationError = computed(() => revokePermissionRequest.error || clearPermissionsRequest.error)
const agentPluginMutationError = computed(() => toggleAgentPluginRequest.error || updateAgentPluginConfigRequest.error)
const connectedMcpCount = computed(() => mcpRows.value.filter((row) => row.connected).length)
const enabledMcpCount = computed(() => mcpRows.value.filter((row) => row.enabled).length)
const failingMcpCount = computed(() => mcpRows.value.filter((row) => row.enabled && !row.connected).length)
const disabledMcpCount = computed(() => mcpRows.value.filter((row) => !row.enabled).length)
const mcpFilterOptions = computed<MCPFilterOption[]>(() => [
  { value: 'all', label: '全部', count: mcpRows.value.length },
  { value: 'connected', label: '已连接', count: connectedMcpCount.value },
  { value: 'error', label: '需处理', count: failingMcpCount.value },
  { value: 'disabled', label: '未启用', count: disabledMcpCount.value },
])
const filteredMcpRows = computed(() => mcpRows.value.filter((row) => {
  if (mcpFilter.value === 'connected') return row.connected
  if (mcpFilter.value === 'error') return row.enabled && !row.connected
  if (mcpFilter.value === 'disabled') return !row.enabled
  return true
}))
const mcpEmptyDescription = computed(() => {
  if (!mcpRows.value.length) return '暂无 MCP 服务器配置'
  const selected = mcpFilterOptions.value.find((item) => item.value === mcpFilter.value)
  return `没有${selected?.label || '当前'} MCP 服务`
})
const totalMcpInventory = computed(() => mcpRows.value.reduce((total, row) => total + row.tools_count + row.resources_count + row.prompts_count, 0))
const approvedPermissionCount = computed(() => permissionRows.value.filter((row) => row.approved).length)
const deniedPermissionCount = computed(() => permissionRows.value.filter((row) => !row.approved).length)
const totalContributionCount = computed(() => contributionComparisonRows.value.reduce((total, row) => total + row.electron + row.agent + row.mcp, 0))

const governancePosture = computed(() => {
  if (failingMcpCount.value > 0) return '需要复核 MCP 连接'
  if (mcpRows.value.length === 0 && permissionRows.value.length === 0) return '等待治理快照'
  return '治理面稳定'
})

const governancePostureTagType = computed(() => {
  if (failingMcpCount.value > 0) return 'danger'
  if (mcpRows.value.length === 0 && permissionRows.value.length === 0) return 'info'
  return 'success'
})

const governanceMetrics = computed(() => [
  {
    label: 'MCP 连接',
    value: `${connectedMcpCount.value}/${mcpRows.value.length}`,
    detail: `${enabledMcpCount.value} 个已启用，${failingMcpCount.value} 个需处理`,
    tone: failingMcpCount.value ? 'red' : mcpRows.value.length ? 'green' : 'slate',
  },
  {
    label: '工具库存',
    value: totalMcpInventory.value,
    detail: '工具、资源与 Prompt 总数',
    tone: totalMcpInventory.value ? 'blue' : 'slate',
  },
  {
    label: '已记住规则',
    value: permissionRows.value.length,
    detail: `${approvedPermissionCount.value} 个允许，${deniedPermissionCount.value} 个阻断`,
    tone: permissionRows.value.length ? 'green' : 'slate',
  },
  {
    label: '扩展贡献',
    value: totalContributionCount.value,
    detail: 'UI、能力、事件、策略贡献面',
    tone: totalContributionCount.value ? 'violet' : 'slate',
  },
])

const extensionHosts = computed(() => [
  {
    label: 'Agent 插件',
    value: agentPluginRows.value.length,
    detail: `${agentPluginRows.value.filter((item) => item.enabled).length} 个已启用`,
    tone: 'blue',
  },
  {
    label: 'Electron 插件',
    value: electronPluginSnapshot.value?.plugins.length ?? 0,
    detail: `${electronPluginSnapshot.value?.plugins.filter((item) => item.enabled).length ?? 0} 个已启用`,
    tone: 'violet',
  },
  {
    label: 'MCP 贡献',
    value: mcpContributionSummary.value.reduce((total, item) => total + item.count, 0),
    detail: '来自外部上下文协议服务',
    tone: 'green',
  },
])

const recentMcpHistory = (history: MCPHistoryEntry[]) => [...history].reverse()
const formatMcpTimestamp = (timestamp: string) => timestamp.replace('T', ' ').slice(0, 19)

const mcpHistoryTagType = (status: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' => {
  if (status === 'ok' || status === 'enabled') return 'success'
  if (status === 'started' || status === 'pending' || status === 'closing') return 'warning'
  if (status === 'error' || status === 'failed') return 'danger'
  if (status === 'disabled' || status === 'closed' || status === 'removed') return 'info'
  return 'primary'
}

const mcpHistoryStatusLabel = (status: string) => {
  const labels: Record<string, string> = {
    ok: '成功',
    enabled: '启用',
    started: '启动',
    pending: '等待',
    closing: '关闭中',
    error: '错误',
    failed: '失败',
    disabled: '禁用',
    closed: '已关闭',
    removed: '已删除',
  }
  return labels[status] || status
}

const formatInventoryNames = (items?: MCPInventoryItem[] | null) => {
  if (!items?.length) return '未上报库存条目'
  return items.map((item) => item.description ? `${item.name}: ${item.description}` : item.name).join('\n')
}

const permissionRows = computed(() => {
  const remembered = permissions.value?.remembered || {}
  const audit = permissions.value?.audit || []
  return Object.entries(remembered).map(([key, approved]) => {
    const latest = [...audit].reverse().find((item) => (item.capability_id || item.tool_name) === key || `${item.tool_name || ''}::${item.remember_scope || 'default'}` === key)
    return {
      key,
      approved,
      capabilityType: latest?.capability_type || 'tool',
      capabilityKind: latest?.capability_kind || 'tool',
      riskLevel: latest?.risk_level || null,
    }
  })
})

const transportLabel = (transport: string) => {
  const labels: Record<string, string> = { http: 'HTTP', sse: 'SSE', stdio: 'STDIO', streamable_http: 'Streamable HTTP' }
  return labels[transport] || transport.toUpperCase()
}

const presetCategoryLabel = (category: string) => {
  const labels: Record<string, string> = {
    companion: '桌宠',
    daily: '日常',
    diagnostics: '诊断',
    browser: '浏览器',
    research: '调研',
    web: '网页',
    docs: '文档',
    code: '代码',
  }
  return labels[category] || category
}

const serverTone = (row: MCPRow) => {
  if (!row.enabled) return 'muted'
  if (row.connected) return 'healthy'
  return 'broken'
}

const mcpRowTagType = (row: MCPRow): 'success' | 'warning' | 'danger' | 'info' => {
  if (!row.enabled) return 'info'
  if (row.connected) return 'success'
  if (row.inventory_error) return 'warning'
  return 'danger'
}

const mcpRowStatusLabel = (row: MCPRow) => {
  if (!row.enabled) return '已禁用'
  if (row.connected) return '已连接'
  if (row.inventory_error) return '库存异常'
  return '离线'
}

const mcpEndpointLabel = (row: MCPRow) => row.transport === 'stdio' ? `${row.command || 'stdio'} ${(row.args || []).join(' ')}`.trim() : row.base_url

const isHttpMcpUrl = (value: string) => {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

const canSubmitMcp = computed(() => {
  if (!mcpForm.name.trim() || addMcpRequest.loading) return false
  if (mcpForm.transport === 'stdio') return Boolean(mcpForm.command.trim())
  return isHttpMcpUrl(mcpForm.base_url.trim())
})

const contributionCategoryLabel = (category: ContributionCategory) => {
  const labels: Record<ContributionCategory, string> = {
    ui: '界面入口',
    capability: '能力工具',
    event: '事件钩子',
    policy: '权限策略',
  }
  return labels[category]
}

const capabilityLabel = (type: string, kind: string) => `${type || 'tool'} / ${kind || 'tool'}`
const riskLabel = (risk?: string | null) => risk || '未知'

const decisionLabel = (decision: string) => {
  const labels: Record<string, string> = {
    approved: '已允许',
    allowed: '已允许',
    denied: '已拒绝',
    auto_allow: '自动允许',
    remembered_allow: '记住允许',
    remembered_deny: '记住阻断',
    remembered: '已记住',
    revoked: '已撤销',
    cleared: '已清空',
  }
  return labels[decision] || decision
}

const permissionAuditTitle = (item: PermissionAuditRecord) => item.capability_id || item.tool_name || item.capability_kind || '未命名能力'

const refreshGovernance = async () => {
  await Promise.all([loadPermissions(), loadMcp(), loadAgentPlugins(), loadElectronPlugins()])
}

const refreshExtensions = async () => {
  await Promise.all([loadAgentPlugins(), loadElectronPlugins(), loadMcp()])
}

onMounted(() => {
  void refreshGovernance()
})

const revokePermissionItem = async (toolName: string) => {
  addPending(revokingPermissionKeys, toolName)
  try {
    await revokePermission(toolName)
  } finally {
    removePending(revokingPermissionKeys, toolName)
  }
}

const clearAllPermissions = async () => {
  if (permissionRows.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `将清空 ${permissionRows.value.length} 条已记住的权限规则。之后工具调用会重新询问。`,
      '清空已记住权限',
      {
        confirmButtonText: '清空权限',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  await clearPermissions()
}

const parseRecordJson = (value: string, label: string): Record<string, string> | undefined => {
  const trimmed = value.trim()
  if (!trimmed) return undefined
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    ElMessage.error(`${label} 必须是有效 JSON`)
    return undefined
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    ElMessage.error(`${label} 必须是 JSON 对象`)
    return undefined
  }
  return Object.fromEntries(
    Object.entries(parsed as Record<string, unknown>)
      .filter(([key]) => key.trim())
      .map(([key, raw]) => [key, String(raw)]),
  )
}

const submitMcp = async () => {
  if (!mcpForm.name.trim()) {
    ElMessage.warning('请填写 MCP 服务标识名')
    return
  }
  if (!canSubmitMcp.value) {
    ElMessage.warning(mcpForm.transport === 'stdio' ? '请填写 STDIO 启动命令' : '请填写有效的 MCP 服务 URL')
    return
  }
  const env = parseRecordJson(mcpForm.env_text, '环境变量')
  if (mcpForm.env_text.trim() && !env) return
  const headers = parseRecordJson(mcpForm.headers_text, '请求头')
  if (mcpForm.headers_text.trim() && !headers) return
  let args: string[] | undefined
  if (mcpForm.args_text.trim()) {
    try {
      const parsed = JSON.parse(mcpForm.args_text)
      if (!Array.isArray(parsed) || parsed.some((item) => typeof item !== 'string')) {
        throw new Error('invalid_args')
      }
      args = parsed
    } catch {
      ElMessage.error('参数必须是 JSON 字符串数组')
      return
    }
  }
  const result = await addMcp({
    name: mcpForm.name.trim(),
    base_url: mcpForm.base_url.trim(),
    command: mcpForm.command.trim() || undefined,
    args,
    transport: mcpForm.transport,
    enabled: mcpForm.enabled,
    env,
    headers,
  })
  if (result?.ok) {
    mcpForm.name = ''
    mcpForm.base_url = ''
    mcpForm.command = ''
    mcpForm.args_text = ''
    mcpForm.env_text = ''
    mcpForm.headers_text = ''
  }
}

const installPreset = async (presetId: string) => {
  const result = await installMcpPreset(presetId)
  if (result?.ok) ElMessage.success('MCP 预设已安装')
}

const removeMcpItem = async (serverName: string) => {
  try {
    await ElMessageBox.confirm(
      `将删除 MCP 服务“${serverName}”。重新注册前，它提供的工具和资源不会再出现。`,
      '删除 MCP 服务',
      {
        confirmButtonText: '删除服务',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  addPending(removingMcpNames, serverName)
  try {
    await removeMcp(serverName)
  } finally {
    removePending(removingMcpNames, serverName)
  }
}

const refreshMcpItem = async (serverName: string) => {
  addPending(refreshingMcpNames, serverName)
  try {
    await refreshMcp(serverName)
  } finally {
    removePending(refreshingMcpNames, serverName)
  }
}

const toggleMcpItem = async (serverName: string, enabled: boolean) => {
  addPending(togglingMcpNames, serverName)
  try {
    await toggleMcp(serverName, enabled)
  } finally {
    removePending(togglingMcpNames, serverName)
  }
}

const toggleAgentPluginItem = async (pluginId: string, enabled: boolean) => {
  addPending(togglingAgentPluginIds, pluginId)
  try {
    await toggleAgentPlugin(pluginId, enabled)
  } finally {
    removePending(togglingAgentPluginIds, pluginId)
  }
}

const saveAgentPluginConfig = async (pluginId: string) => {
  const rawConfig = pluginConfigDrafts[pluginId]?.trim() || '{}'
  let config: unknown
  try {
    config = JSON.parse(rawConfig)
  } catch {
    ElMessage.error('插件配置必须是有效 JSON')
    return
  }

  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    ElMessage.error('插件配置必须是 JSON 对象')
    return
  }

  const result = await updateAgentPluginConfig(pluginId, config as Record<string, unknown>)
  if (result?.ok) {
    ElMessage.success('插件配置已保存')
  }
}

</script>

<style scoped>
.governance-console {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.governance-toolbar {
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

.governance-toolbar > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.governance-toolbar strong {
  color: var(--yui-text);
  font-size: 16px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.metric-grid,
.governance-grid,
.host-grid {
  display: grid;
  gap: 14px;
}

.metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.governance-grid {
  grid-template-columns: minmax(0, 1.35fr) minmax(340px, 0.65fr);
}

.lower-grid {
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.7fr);
}

.host-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 14px;
}

.metric-card,
.panel-card,
.server-card,
.preset-card,
.host-card {
  border: 1px solid var(--yui-border);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
}

.metric-card,
.host-card {
  display: flex;
  min-height: 112px;
  flex-direction: column;
  justify-content: space-between;
  padding: 16px;
  border-radius: var(--yui-radius-card);
}

.metric-card span,
.metric-card small,
.host-card span,
.host-card small {
  color: var(--yui-muted);
}

.metric-card strong,
.host-card strong {
  color: var(--yui-text);
  font-size: 26px;
  letter-spacing: 0;
}

.metric-card.green,
.host-card.green { background: var(--yui-success-soft); }
.metric-card.blue,
.host-card.blue { background: var(--yui-accent-soft); }
.metric-card.violet,
.host-card.violet { background: var(--yui-accent-soft); }
.metric-card.amber { background: var(--yui-warning-soft); }
.metric-card.red { background: var(--yui-danger-soft); }
.metric-card.slate { background: var(--yui-surface-muted); }

.panel-card {
  border-radius: var(--yui-radius-card);
}

.card-head,
.action-row,
.server-main,
.server-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-head > div:first-child,
.server-title {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.card-head.compact {
  align-items: flex-start;
}

.side-stack,
.server-list,
.agent-plugin-list,
.permission-list,
.audit-timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-alert {
  margin-bottom: 12px;
  border-radius: 14px;
}

.mcp-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.mcp-filter-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--yui-border);
  border-radius: 999px;
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  cursor: pointer;
  padding: 6px 10px;
  transition: border-color 0.18s ease, background 0.18s ease;
}

.mcp-filter-button:hover,
.mcp-filter-button:focus-visible,
.mcp-filter-button.active {
  border-color: var(--yui-border-strong);
  background: var(--yui-surface-raised);
  outline: none;
}

.mcp-filter-button span {
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 700;
}

.mcp-filter-button strong {
  color: var(--yui-text);
  font-size: 12px;
}

.server-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border-radius: 18px;
}

.server-card.healthy { border-color: rgba(34, 197, 94, 0.28); }
.server-card.broken { border-color: rgba(239, 68, 68, 0.28); background: rgba(254, 242, 242, 0.76); }
.server-card.muted { opacity: 0.78; }

.server-status-dot {
  width: 12px;
  height: 12px;
  flex: 0 0 auto;
  border-radius: 999px;
  background: #ef4444;
  box-shadow: 0 0 0 6px rgba(239, 68, 68, 0.12);
}

.server-status-dot.online {
  background: #22c55e;
  box-shadow: 0 0 0 6px rgba(34, 197, 94, 0.12);
}

.server-title {
  flex: 1;
}

.server-title strong,
.permission-item strong,
.audit-item strong {
  color: var(--yui-text);
}

.server-title span,
.server-meta,
.permission-item span,
.audit-item span,
.empty-inline {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.5;
}

.server-inventory,
.server-meta,
.history-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.server-meta {
  padding: 10px;
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.history-chip,
.permission-item,
.audit-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.history-chip span,
.history-chip small {
  color: var(--yui-muted);
  font-size: 12px;
}

.form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px;
  gap: 10px;
}

.preset-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  margin-bottom: 12px;
}

.preset-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border-radius: var(--yui-radius-card);
}

.preset-card.installed {
  opacity: 0.72;
}

.preset-card > div:first-child {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.preset-card strong {
  color: var(--yui-text);
}

.preset-card span {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
}

.preset-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.agent-plugin-list {
  margin-bottom: 14px;
}

.agent-plugin-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.agent-plugin-item.disabled {
  opacity: 0.76;
}

.agent-plugin-item.broken {
  border-color: rgba(239, 68, 68, 0.24);
  background: var(--yui-danger-soft);
}

.agent-plugin-main,
.plugin-config-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.agent-plugin-main > div:first-child {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.agent-plugin-main strong {
  color: var(--yui-text);
}

.agent-plugin-main span {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.plugin-config-row :deep(.el-textarea) {
  min-width: 0;
}

.plugin-config-row {
  align-items: stretch;
}

.plugin-error {
  border-radius: var(--yui-radius-card);
}

.form-grid .wide {
  grid-column: 1 / -1;
}

.submit-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.permission-item {
  justify-content: space-between;
}

.permission-item > div,
.audit-item > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.permission-item.approved {
  border-color: rgba(34, 197, 94, 0.24);
  background: var(--yui-success-soft);
}

.permission-item.denied {
  border-color: rgba(239, 68, 68, 0.24);
  background: var(--yui-danger-soft);
}

.contribution-matrix {
  display: grid;
  grid-template-columns: 1.2fr repeat(3, 1fr);
  overflow: hidden;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
}

.contribution-matrix > div {
  padding: 12px;
  border-bottom: 1px solid var(--yui-border);
  color: var(--yui-muted);
  font-size: 13px;
}

.contribution-matrix > div:nth-child(-n + 4) {
  background: rgba(15, 23, 42, 0.92);
  color: #e2e8f0;
  font-weight: 800;
}

.matrix-category {
  font-weight: 800;
  color: var(--yui-text) !important;
}

.audit-item {
  align-items: flex-start;
}

.audit-dot {
  width: 10px;
  height: 10px;
  margin-top: 4px;
  border-radius: 999px;
  background: #f59e0b;
  box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.12);
}

@media (max-width: 1200px) {
  .metric-grid,
  .governance-grid,
  .lower-grid,
  .host-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .governance-toolbar {
    display: flex;
    flex-direction: column;
  }

  .toolbar-actions,
  .card-head,
  .server-main,
  .server-footer,
  .action-row {
    align-items: flex-start;
  }

  .card-head,
  .server-main,
  .server-footer,
  .action-row {
    flex-direction: column;
  }

  .contribution-matrix {
    grid-template-columns: 1fr;
  }

  .preset-card {
    grid-template-columns: 1fr;
  }

  .agent-plugin-main,
  .plugin-config-row {
    flex-direction: column;
  }

  .preset-meta {
    justify-content: flex-start;
  }
}
</style>
