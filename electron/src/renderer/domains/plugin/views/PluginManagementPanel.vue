<template>
  <PanelShell title="桌宠插件" tone="companion">
    <div class="plugin-console">
<section class="plugin-toolbar" aria-label="插件操作">
        <div class="toolbar-summary">
          <strong>{{ pluginRows.length }} 个插件 · {{ auditLogs.length }} 条调用记录</strong>
          <span>运行 {{ activeExecutionCount }} · 失败 {{ loadFailures.length }}</span>
        </div>
        <div class="toolbar-actions">
          <el-tag :type="blockedOrErrorCount > 0 ? 'danger' : 'success'">{{ blockedOrErrorCount > 0 ? '存在异常' : '无异常' }}</el-tag>
          <el-button plain :disabled="problemPluginCount === 0 && loadFailures.length === 0" @click="showProblemPlugins">筛选异常插件</el-button>
<el-button type="primary" :loading="pluginsRequest.loading" @click="loadPlugins">刷新插件状态</el-button>
        </div>
      </section>

      <section class="metric-grid" aria-label="技能运行概况">
        <article v-for="metric in metrics" :key="metric.label" class="metric-card" :class="metric.tone">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.detail }}</small>
        </article>
      </section>

      <section class="plugin-layout">
        <el-card class="panel-card plugin-list-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
              <strong>{{ filteredPluginRows.length }} / {{ pluginRows.length }} 个插件</strong>
              </div>
              <el-tag :type="blockedOrErrorCount > 0 ? 'danger' : 'success'">{{ blockedOrErrorCount > 0 ? '存在异常' : '无异常' }}</el-tag>
            </div>
          </template>

          <div class="filter-bar">
            <el-input v-model="searchQuery" clearable placeholder="搜索技能名称、能做的事、工具或模型" />
            <el-select v-model="statusFilter" class="filter-select" placeholder="状态">
              <el-option label="全部状态" value="all" />
              <el-option label="需处理" value="problem" />
              <el-option label="已加载" value="loaded" />
              <el-option label="降级" value="degraded" />
              <el-option label="阻断" value="blocked" />
              <el-option label="异常" value="error" />
            </el-select>
            <el-select v-model="categoryFilter" class="filter-select" placeholder="类型">
              <el-option label="全部类型" value="all" />
              <el-option label="桌宠能力" value="capability" />
              <el-option label="事件联动" value="event" />
              <el-option label="权限范围" value="policy" />
            </el-select>
          </div>

          <AsyncState
            :loading="pluginsRequest.loading"
            :error="pluginsRequest.error"
            :empty="pluginRows.length === 0"
            empty-text="暂无技能"
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
                    <span>{{ plugin.id }}</span>
                  </div>
                </div>
                <p>{{ pluginSkillSummary(plugin) }}</p>
                <div class="plugin-card-meta">
                  <el-tag size="small" :type="statusTagType(plugin.status)">{{ statusLabel(plugin.status) }}</el-tag>
                  <span>入口 {{ plugin.routeCount }}</span>
                  <span>能力 {{ plugin.toolCount }}</span>
                  <span v-if="plugin.petEvents?.length">触发 {{ plugin.petEvents.length }}</span>
                  <span>执行 {{ plugin.activeCount }}</span>
                </div>
              </button>
            </div>
            <el-empty v-else description="没有匹配当前筛选的插件" :image-size="72" />
          </AsyncState>
        </el-card>

        <el-card class="panel-card detail-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>{{ selectedPlugin?.name ?? '选择插件查看详情' }}</strong>
              </div>
              <el-tag :type="statusTagType(selectedPluginState?.status)">{{ statusLabel(selectedPluginState?.status ?? 'loaded') }}</el-tag>
            </div>
          </template>

          <div v-if="selectedPlugin" class="detail-stack">
            <div class="manifest-summary">
              <div>
                <span>技能包版本</span>
                <strong>v{{ selectedPlugin.manifestVersion }}</strong>
                <small>{{ selectedPlugin.version ? `技能版本 ${selectedPlugin.version}` : '未声明技能版本' }}</small>
              </div>
              <div>
                <span>调用预算</span>
                <strong>{{ selectedPlugin.execution.maxExecutionTimeMs }}ms</strong>
                <small>并发 {{ selectedPlugin.execution.maxConcurrentExecutions }} · {{ selectedPlugin.execution.allowCancellation ? '支持取消' : '不可取消' }}</small>
              </div>
            </div>

            <div class="detail-block skill-benefit-block">
              <label>插件能力</label>
              <p class="skill-benefit-text">{{ selectedSkillSummary }}</p>
              <div v-if="selectedPlugin.petEvents?.length" class="tag-wrap">
                <el-tag v-for="event in selectedPlugin.petEvents" :key="`${event.event}-${event.routeId || 'local'}`" type="info">
                  {{ petEventRouteLabel(event) }}
                </el-tag>
              </div>
            </div>

            <div v-if="selectedPetEventRows.length" class="detail-block pet-trigger-block">
              <label>事件触发</label>
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
              <label>技能组成</label>
              <div class="tag-wrap">
                <el-tag v-if="selectedPlugin.toolCapabilities?.length" type="success">工具能力 {{ selectedPlugin.toolCapabilities.length }}</el-tag>
                <el-tag v-if="selectedPlugin.modelProviders?.length" type="warning">角色模型 {{ selectedPlugin.modelProviders.length }}</el-tag>
                <el-tag v-if="selectedPlugin.petEvents?.length" type="info">桌宠事件 {{ selectedPlugin.petEvents.length }}</el-tag>
                <el-tag v-if="permissionCount > 0" type="danger">权限项 {{ permissionCount }}</el-tag>
                <el-tag v-if="selectedPluginState?.executionIsolation === 'node-permission-process'" type="success">受限进程</el-tag>
                <el-tag v-if="selectedPluginState?.stats.totalInvocations" type="info">调用记录 {{ selectedPluginState.stats.totalInvocations }}</el-tag>
              </div>
            </div>

            <div class="detail-block">
              <label>权限说明</label>
              <div class="permission-explain-list">
                <p v-for="item in selectedPermissionExplanations" :key="item">{{ item }}</p>
              </div>
            </div>

            <div class="detail-block">
              <label>底层权限</label>
              <div class="tag-wrap permission-tags">
                <el-tag v-for="routeId in selectedPlugin.permissions.routes" :key="`route:${routeId}`" type="primary">路由：{{ routeId }}</el-tag>
                <el-tag v-for="toolId in selectedPlugin.permissions.toolScopes" :key="`tool:${toolId}`" type="success">工具：{{ toolId }}</el-tag>
                <el-tag v-for="providerId in selectedPlugin.permissions.modelScopes" :key="`model:${providerId}`" type="warning">模型：{{ providerId }}</el-tag>
                <el-tag v-if="selectedPlugin.permissions.agentBridge" type="danger">Agent 桥接</el-tag>
                <el-tag v-for="host in selectedPlugin.permissions.allowedHosts ?? []" :key="`host:${host}`" type="info">主机：{{ host }}</el-tag>
                <el-tag v-for="allowedPath in selectedPlugin.permissions.allowedPaths ?? []" :key="`path:${allowedPath}`">路径：{{ allowedPath }}</el-tag>
                <el-tag v-for="command in selectedPlugin.permissions.allowedCommands ?? []" :key="`command:${command}`" type="danger">命令：{{ command }}</el-tag>
                <span v-if="permissionCount === 0" class="muted-text">未申请额外权限</span>
              </div>
            </div>

            <div class="detail-block">
              <label>运行记录</label>
              <div class="kv-list">
                <div><strong>最近审计：</strong>{{ selectedPluginState?.lastAuditAt ?? '暂无' }}</div>
                <div><strong>最近错误：</strong>{{ selectedPluginState?.lastError ?? '暂无' }}</div>
                <div><strong>累计成功：</strong>{{ selectedPluginState?.stats.okCount ?? 0 }} 次</div>
                <div><strong>累计失败：</strong>{{ selectedPluginState?.stats.errorCount ?? 0 }} 次 · 超时 {{ selectedPluginState?.stats.timeoutCount ?? 0 }} 次 · 拒绝 {{ selectedPluginState?.stats.deniedCount ?? 0 }} 次</div>
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
            <el-empty v-else description="未选择插件" />
        </el-card>
      </section>

      <section class="lower-grid">
        <el-card class="panel-card" shadow="never">
          <template #header>
            <div class="card-head compact">
            <strong>运行中的插件</strong>
              <el-tag type="info">{{ selectedPluginState?.activeExecutions.length ?? 0 }} 条</el-tag>
            </div>
          </template>
          <el-empty v-if="selectedPluginState == null || selectedPluginState.activeExecutions.length === 0" description="当前没有插件在运行" :image-size="56" />
          <el-table v-else :data="selectedPluginState.activeExecutions" size="small" stripe>
            <el-table-column prop="invocationId" label="调用 ID" min-width="240" />
            <el-table-column prop="routeId" label="路由" min-width="120" />
            <el-table-column prop="startedAt" label="开始时间" min-width="160" />
            <el-table-column prop="status" label="状态" width="110">
              <template #default="scope">
                <el-tag size="small" type="info">{{ executionStatusLabel(scope.row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="scope">
                <el-button
                  link
                  type="danger"
                  :loading="cancellingInvocationIds.has(scope.row.invocationId)"
                  :disabled="!selectedPlugin?.execution.allowCancellation || cancellingInvocationIds.has(scope.row.invocationId)"
                  @click="handleCancel(selectedPlugin.id, scope.row.routeId, scope.row.invocationId)"
                >
                  取消
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card class="panel-card" shadow="never">
          <template #header>
            <div class="card-head compact">
            <strong>插件能力组成</strong>
              <el-tag type="info">{{ contributionSummaries.length }} 类</el-tag>
            </div>
          </template>
          <div v-if="contributionSummaries.length" class="contribution-list">
            <div v-for="item in contributionSummaries" :key="item.category" class="contribution-item">
              <span>{{ contributionLabel(item.category) }}</span>
              <strong>{{ item.count }}</strong>
              <small>{{ item.items.slice(0, 4).join(' / ') || '暂无条目' }}</small>
            </div>
          </div>
          <el-empty v-else description="暂无插件能力摘要" :image-size="56" />
        </el-card>
      </section>

      <section class="lower-grid audit-grid">
        <el-card class="panel-card" shadow="never">
          <template #header>
            <div class="card-head compact">
            <strong>加载失败 / 清单错误</strong>
              <el-tag :type="loadFailures.length > 0 ? 'danger' : 'success'">{{ loadFailures.length }} 条</el-tag>
            </div>
          </template>
          <el-empty v-if="loadFailures.length === 0" description="暂无插件加载失败记录" :image-size="56" />
          <el-table v-else :data="loadFailures" size="small" stripe height="220">
            <el-table-column prop="manifestPath" label="清单路径" min-width="220" />
            <el-table-column prop="pluginId" label="技能 ID" min-width="120" />
            <el-table-column prop="reason" label="原因" min-width="220" />
          </el-table>
        </el-card>

        <el-card class="panel-card" shadow="never">
          <template #header>
            <div class="card-head compact">
            <strong>调用审计记录</strong>
              <el-tag type="info">最近 {{ auditLogs.length }} 条</el-tag>
            </div>
          </template>
          <el-empty v-if="auditLogs.length === 0" description="暂无插件调用记录" :image-size="56" />
          <el-table v-else :data="auditLogs" size="small" stripe height="240">
            <el-table-column prop="timestamp" label="时间" min-width="160" />
            <el-table-column prop="pluginId" label="技能" min-width="130" />
            <el-table-column prop="routeId" label="路由" min-width="110" />
            <el-table-column prop="status" label="结果" width="96">
              <template #default="scope">
                <el-tag :type="auditTagType(scope.row.status)">{{ auditStatusLabel(scope.row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="durationMs" label="耗时(ms)" width="100" />
            <el-table-column prop="detail" label="详情" min-width="220" />
          </el-table>
        </el-card>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
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
  plugins,
  pluginRows,
  loadFailures,
  auditLogs,
  selectedPlugin,
  selectedPluginId,
  selectedPluginState,
  blockedOrErrorCount,
  activeExecutionCount,
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
    loaded: '已加载',
    degraded: '降级',
    blocked: '阻断',
    error: '异常',
  }
  return labels[status]
}

const auditStatusLabel = (status: PluginAuditRecord['status']) => {
  const labels: Record<PluginAuditRecord['status'], string> = {
    ok: '成功',
    error: '错误',
    timeout: '超时',
    denied: '拒绝',
    cancelled: '取消',
  }
  return labels[status]
}

const executionStatusLabel = (status: PluginExecutionStatus) => {
  const labels: Record<PluginExecutionStatus, string> = {
    running: '运行中',
    cancelled: '已取消',
    timed_out: '已超时',
  }
  return labels[status]
}

const contributionLabel = (category: PluginContributionCategory) => {
  const labels: Record<PluginContributionCategory, string> = {
    ui: '界面入口',
    capability: '桌宠能力',
    event: '事件联动',
    policy: '权限范围',
  }
  return labels[category]
}

const petEventLabel = (event: DesktopPetEventName) => getDesktopPetEventDefinition(event).label

const petEventRouteLabel = (event: { event: DesktopPetEventName; routeId?: string }) =>
  event.routeId ? `${petEventLabel(event.event)}触发 ${event.routeId}` : `${petEventLabel(event.event)}仅声明`

const buildPetEventRow = (event: PluginPetEventSubscription) => {
  const definition = getDesktopPetEventDefinition(event.event)
  return {
    ...event,
    label: definition.label,
    trigger: definition.trigger,
    payloadHint: definition.payloadHint,
    frequencyHint: definition.frequencyHint,
    routeLabel: event.routeId ? `调用 ${event.routeId}` : '仅声明',
    descriptionText: event.description || `${definition.label}时让桌宠技能做出响应。`,
  }
}

const pluginSkillSummary = (plugin: DesktopPetPlugin & { lastError?: string }) => {
  if (plugin.lastError && plugin.lastError !== '—') {
    return `最近异常：${plugin.lastError}`
  }
  const primaryTool = plugin.toolCapabilities?.[0]
  if (primaryTool) {
  return primaryTool.desc || `可调用工具：${primaryTool.name}`
  }
  const primaryModel = plugin.modelProviders?.[0]
  if (primaryModel) {
    return `提供 ${primaryModel.modelType.toUpperCase()} 角色模型「${primaryModel.name}」`
  }
  const primaryEvent = plugin.petEvents?.[0]
  if (primaryEvent) {
    return primaryEvent.description || `响应「${petEventLabel(primaryEvent.event)}」事件`
  }
  return '已安装，暂未声明额外桌宠能力'
}

const buildPermissionExplanations = (plugin: DesktopPetPlugin) => {
  const permissions = plugin.permissions
  const items: string[] = []
  if (permissions.routes.length) {
    items.push(`可执行 ${permissions.routes.length} 个技能动作：${permissions.routes.join('、')}`)
  }
  if (permissions.toolScopes.length) {
    items.push(`可调用 ${permissions.toolScopes.length} 个工具能力：${permissions.toolScopes.join('、')}`)
  }
  if (permissions.modelScopes.length) {
    items.push(`可提供 ${permissions.modelScopes.length} 个角色模型：${permissions.modelScopes.join('、')}`)
  }
  if (permissions.agentBridge) {
    items.push('可接入 Agent 执行链，适合需要主动规划或调用工具的技能')
  }
  if (permissions.allowedHosts?.length) {
    items.push(`可访问指定网络主机：${permissions.allowedHosts.join('、')}`)
  }
  if (permissions.allowedPaths?.length) {
    items.push(`可读取或写入指定路径范围：${permissions.allowedPaths.join('、')}`)
  }
  if (permissions.allowedCommands?.length) {
    items.push(`可运行指定本地命令：${permissions.allowedCommands.join('、')}`)
  }
  return items.length ? items : ['不申请额外权限，只提供本地展示或静态能力']
}

const contributionSummaries = computed(() =>
  (payload.value?.contributionSummary ?? []).filter((item) => item.category !== 'ui'),
)
const problemPluginCount = computed(() => pluginRows.value.filter((plugin) => plugin.status !== 'loaded').length)
const selectedSkillSummary = computed(() => selectedPlugin.value ? pluginSkillSummary(selectedPlugin.value) : '选择插件查看能力、权限和触发条件')
const selectedPetEventRows = computed(() => (selectedPlugin.value?.petEvents ?? []).map(buildPetEventRow))
const selectedPermissionExplanations = computed(() => selectedPlugin.value ? buildPermissionExplanations(selectedPlugin.value) : [])

const metrics = computed(() => [
  {
    label: '已启用技能',
    value: plugins.value.length,
    detail: `${pluginRows.value.length} 个已注册`,
    tone: 'blue',
  },
  {
    label: '需处理',
    value: blockedOrErrorCount.value,
    detail: blockedOrErrorCount.value > 0 ? '需处理' : '暂无异常',
    tone: blockedOrErrorCount.value > 0 ? 'red' : 'green',
  },
  {
    label: '正在行动',
    value: activeExecutionCount.value,
    detail: activeExecutionCount.value > 0 ? '可取消支持的调用' : '当前无运行',
    tone: activeExecutionCount.value > 0 ? 'amber' : 'slate',
  },
  {
    label: '安装异常',
    value: loadFailures.value.length,
    detail: loadFailures.value.length > 0 ? '检查清单' : '装载正常',
    tone: loadFailures.value.length > 0 ? 'red' : 'green',
  },
])

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
    ElMessage.success('技能执行取消请求已发送')
  } else {
    ElMessage.error(cancelRequest.error || '取消技能执行失败')
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

.toolbar-summary {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.plugin-toolbar strong {
  color: var(--yui-text);
  font-size: 16px;
}

.toolbar-summary span {
  color: var(--yui-muted);
  font-size: 12px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.metric-card,
.panel-card {
  border: 1px solid var(--yui-border);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
}

.metric-card {
  display: flex;
  min-height: 96px;
  flex-direction: column;
  justify-content: space-between;
  padding: 16px;
  border-radius: var(--yui-radius-card);
}

.metric-card span,
.metric-card small {
  color: var(--yui-muted);
}

.metric-card strong {
  color: var(--yui-text);
  font-size: 26px;
  letter-spacing: 0;
}

.metric-card.blue { background: var(--yui-accent-soft); }
.metric-card.green { background: var(--yui-success-soft); }
.metric-card.amber { background: var(--yui-warning-soft); }
.metric-card.red { background: var(--yui-danger-soft); }
.metric-card.slate { background: var(--yui-surface-muted); }

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
  .metric-grid,
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
