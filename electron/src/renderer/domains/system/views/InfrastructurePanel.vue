<template>
  <PanelShell title="基础设施" tone="admin">
    <div class="infra-console">
      <section class="infra-hero">
        <div class="hero-copy">
          <strong>本地运行状态</strong>
          <span>{{ serviceStatusLabel }}，{{ envStatusLabel }}</span>
        </div>
        <div class="hero-actions">
          <el-button type="primary" :loading="refreshing" @click="refreshAll">刷新全部</el-button>
          <span>{{ controlServerLabel }}</span>
        </div>
      </section>

      <section class="metric-grid" aria-label="基础设施概况">
        <article v-for="metric in metrics" :key="metric.label" class="metric-card" :class="metric.tone">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.detail }}</small>
        </article>
      </section>

      <section class="infra-grid">
        <el-card class="panel-card status-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>服务状态</strong>
              </div>
              <el-tag :type="serviceStatusTagType">{{ serviceStatusLabel }}</el-tag>
            </div>
          </template>
          <AsyncState :loading="diagnosticsRequest.loading" :error="diagnosticsRequest.error" @retry="loadDiagnostics">
            <div v-if="diagnostics" class="service-list">
              <article v-for="item in serviceCards" :key="item.label" class="service-item" :class="item.tone">
                <div class="service-dot"></div>
                <div>
                  <strong>{{ item.label }}</strong>
                  <span>{{ item.detail }}</span>
                </div>
                <el-tag size="small" :type="item.ok ? 'success' : 'danger'">{{ item.ok ? '正常' : '异常' }}</el-tag>
              </article>
            </div>
            <el-empty v-else description="暂无诊断快照" :image-size="64" />
          </AsyncState>
        </el-card>

        <el-card class="panel-card env-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>环境检查 · {{ envStatusLabel }}</strong>
              </div>
              <el-button plain size="small" :loading="diagnosticsRequest.loading" @click="loadDiagnostics">刷新诊断</el-button>
            </div>
          </template>
          <AsyncState :loading="diagnosticsRequest.loading" :error="diagnosticsRequest.error" @retry="loadDiagnostics">
            <div v-if="diagnostics" class="env-list">
              <div v-for="item in envChecks" :key="item.label" class="env-item">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <el-tag size="small" :type="item.ok ? 'success' : 'danger'">{{ item.ok ? '存在' : '缺失' }}</el-tag>
              </div>
            </div>
            <div v-if="diagnostics?.envCheck.electronRoot" class="root-path" :title="diagnostics.envCheck.electronRoot">
              Electron 根目录：{{ diagnostics.envCheck.electronRoot }}
            </div>
            <el-empty v-if="!diagnostics" description="等待诊断快照" :image-size="64" />
          </AsyncState>
        </el-card>

        <el-card class="panel-card runtime-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>运行时资源</strong>
                <span>{{ runtimeSnapshot ? `采样于 ${formatRuntimeTime(runtimeSnapshot.measuredAt)}` : 'Electron 进程与 HTTP 缓存' }}</span>
              </div>
              <div class="action-row">
                <el-button plain size="small" :loading="runtimeLoading" :disabled="!runtimeAvailable" @click="loadRuntimeSnapshot">刷新采样</el-button>
                <el-button type="primary" plain size="small" :loading="runtimeClearing" :disabled="!runtimeAvailable" @click="clearRuntimeCache">清理 HTTP 缓存</el-button>
              </div>
            </div>
          </template>
          <el-alert v-if="runtimeError" class="runtime-alert" :title="runtimeError" type="error" show-icon :closable="false" />
          <div v-if="runtimeSnapshot" class="runtime-overview">
            <div><span>进程私有内存</span><strong>{{ formatBytes(runtimeSnapshot.totalPrivateKb * 1024) }}</strong></div>
            <div><span>HTTP 缓存</span><strong>{{ formatBytes(runtimeSnapshot.cacheBytes) }}</strong></div>
            <div><span>进程数量</span><strong>{{ runtimeSnapshot.processes.length }}</strong></div>
          </div>
          <div v-if="runtimeSnapshot?.processes.length" class="runtime-processes">
            <article v-for="item in runtimeProcesses" :key="`${item.pid}-${item.type}`">
              <div><strong>{{ runtimeProcessLabel(item.type) }}</strong><span>PID {{ item.pid }}</span></div>
              <span>{{ formatBytes(item.privateKb * 1024) }}</span>
            </article>
          </div>
          <el-empty v-else-if="!runtimeAvailable" description="浏览器模式无法读取 Electron 进程资源" :image-size="56" />
          <el-empty v-else-if="!runtimeLoading" description="等待运行时资源采样" :image-size="56" />
        </el-card>

        <el-card class="panel-card api-gap-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>接口快照</strong>
              </div>
              <div class="action-row">
                <el-button plain size="small" :loading="apiGapLoading" @click="loadApiGaps">读取快照</el-button>
                <el-button plain size="small" :loading="apiGapLoading" @click="updateStats">更新统计</el-button>
              </div>
            </div>
          </template>
          <el-alert v-if="apiGapError" :title="apiGapError" type="error" show-icon :closable="false" />
          <el-skeleton v-if="apiGapLoading" :rows="4" animated />
          <el-collapse v-else-if="apiGapLoaded" class="api-collapse">
            <el-collapse-item title="接口响应" name="api-snapshots">
              <div class="api-grid">
                <article>
                  <strong>system/status</strong>
                  <pre>{{ JSON.stringify(systemStatus, null, 2) }}</pre>
                </article>
                <article>
                  <strong>database/stats</strong>
                  <pre>{{ JSON.stringify(databaseStats, null, 2) }}</pre>
                </article>
                <article>
                  <strong>statistics</strong>
                  <pre>{{ JSON.stringify(statistics, null, 2) }}</pre>
                </article>
                <article>
                  <strong>/v1/models</strong>
                  <pre>{{ JSON.stringify(models, null, 2) }}</pre>
                </article>
                <article>
                  <strong>effective-preset(default)</strong>
                  <pre>{{ JSON.stringify(effectivePreset, null, 2) }}</pre>
                </article>
              </div>
            </el-collapse-item>
          </el-collapse>
          <el-empty v-else description="暂无接口快照" :image-size="56" />
          <div class="action-row">
            <el-button type="primary" plain :loading="exportingKind === 'json'" @click="downloadExport('json')">导出 JSON</el-button>
            <el-button type="primary" plain :loading="exportingKind === 'csv'" @click="downloadExport('csv')">导出 CSV</el-button>
          </div>
        </el-card>
      </section>

      <section class="infra-grid lower-grid">
        <el-card class="panel-card backup-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>数据备份 · {{ backupTargets.length }} 个目标</strong>
              </div>
              <div class="action-row">
                <el-button plain size="small" :loading="backupTargetsRequest.loading" @click="loadBackupTargets">刷新目标</el-button>
                <el-button size="small" type="primary" :loading="createBackupRequest.loading" @click="createAndSelectBackup">创建备份</el-button>
              </div>
            </div>
          </template>
          <el-alert
            v-if="createBackupRequest.error"
            class="backup-error"
            :title="createBackupRequest.error"
            type="error"
            show-icon
            :closable="false"
          />
          <AsyncState :loading="backupTargetsRequest.loading" :error="backupTargetsRequest.error" @retry="loadBackupTargets">
            <div v-if="backupResult" class="backup-success">
              <strong>备份清单已创建</strong>
              <span>{{ backupResult }}</span>
            </div>
            <div class="restore-panel">
              <div class="restore-fields">
                <el-input v-model="restoreBackupDir" size="small" placeholder="选择或粘贴 backups 目录下的备份路径" />
                <el-button size="small" plain :disabled="!restoreBackupDir.trim() || restoreMode === 'apply'" :loading="restoreMode === 'preview'" @click="previewRestore">预览恢复</el-button>
                <el-button size="small" type="danger" plain :disabled="!canConfirmRestore || restoreMode === 'preview'" :loading="restoreMode === 'apply'" @click="confirmRestore">确认恢复</el-button>
              </div>
              <el-alert
                class="restore-warning"
                title="恢复会覆盖数据库、配置、音频缓存、桌宠状态和插件目录。请先预览，并确认当前已有可回退备份。"
                type="warning"
                show-icon
                :closable="false"
              />
              <el-alert v-if="restoreBackupRequest.error" class="backup-error" :title="restoreBackupRequest.error" type="error" show-icon :closable="false" />
              <div v-if="restorePreview" class="restore-summary">
                <div class="restore-summary-head">
                  <strong>{{ restorePreview.dryRun ? '恢复预览' : '恢复结果' }}</strong>
                  <el-tag size="small" :type="restorePreview.dryRun ? 'warning' : 'success'">{{ restorePreview.dryRun ? '尚未写入' : '已执行' }}</el-tag>
                </div>
                <div class="restore-plan-list">
                  <article v-for="item in restorePreview.restorePlan" :key="item.path" class="restore-plan-item" :class="{ skipped: item.skippedReason, restored: item.restored }">
                    <div>
                      <strong>{{ targetLabel(item.path) }}</strong>
                      <span :title="item.path">{{ item.path }}</span>
                    </div>
                    <el-tag size="small" :type="restorePlanTagType(item)">{{ restorePlanLabel(item) }}</el-tag>
                  </article>
                </div>
              </div>
            </div>
            <div v-if="backupTargets.length" class="target-list">
              <div v-for="target in backupTargets" :key="target.path" class="target-item">
                <div>
                  <strong>{{ targetLabel(target.path) }}</strong>
                  <span :title="target.path">{{ target.path }}</span>
                </div>
                <el-tag size="small" :type="target.exists ? 'success' : 'warning'">{{ target.exists ? targetTypeLabel(target.type) : '未生成' }}</el-tag>
              </div>
            </div>
            <el-empty v-else description="暂无备份目标" :image-size="64" />
          </AsyncState>
        </el-card>

        <el-card class="panel-card exception-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>运行异常 · {{ exceptionStatusLabel }}</strong>
              </div>
              <el-tag :type="exceptionTagType">{{ exceptionTagLabel }}</el-tag>
            </div>
          </template>
          <AsyncState :loading="diagnosticsRequest.loading" :error="diagnosticsRequest.error" @retry="loadDiagnostics">
            <div v-if="diagnostics && runtimeExceptions.length" class="exception-list">
              <article v-for="item in runtimeExceptions.slice(0, 6)" :key="`${item.timestamp}-${item.type}`" class="exception-item">
                <div>
                  <strong>{{ item.type }}</strong>
                  <span>{{ item.timestamp }}</span>
                </div>
                <p>{{ item.detail }}</p>
              </article>
            </div>
            <el-empty v-else-if="diagnostics" description="当前没有运行时异常" :image-size="64" />
            <el-empty v-else description="等待诊断快照" :image-size="64" />
          </AsyncState>
        </el-card>
      </section>

      <details class="logs-disclosure" @toggle="handleLogsToggle">
        <summary>按需查看日志追踪</summary>
        <el-card class="panel-card logs-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>日志追踪</strong>
              </div>
              <el-button plain :loading="logsRequest.loading" @click="refreshLogs">刷新日志</el-button>
            </div>
          </template>
          <AsyncState :loading="logsRequest.loading" :error="logsRequest.error" @retry="refreshLogs">
            <div class="log-grid">
              <article v-for="channel in logChannels" :key="channel.key" class="log-panel" :class="channel.tone">
                <div class="log-head">
                  <div>
                    <strong>{{ channel.label }}</strong>
                    <span>{{ channel.description }}</span>
                  </div>
                  <el-tag size="small" :type="channel.content ? 'success' : 'info'">{{ channel.content ? '有日志' : '暂无' }}</el-tag>
                </div>
                <pre>{{ channel.content || '暂无日志输出' }}</pre>
              </article>
            </div>
          </AsyncState>
        </el-card>
      </details>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { systemClient } from '@/api/client'
import { useSystemDomain } from '../composables/useSystemDomain'
import type { BackupRestorePlanItem, BackupRestoreResponse, BackupTarget } from '../../../../shared/agent'

interface RuntimeResourceSnapshot {
  measuredAt: string
  cacheBytes: number
  totalPrivateKb: number
  processes: Array<{
    pid: number
    type: string
    privateKb: number
    workingSetKb: number
    peakWorkingSetKb: number
  }>
}

const {
  diagnostics,
  logs,
  backupTargets,
  backupResult,
  diagnosticsRequest,
  logsRequest,
  backupTargetsRequest,
  createBackupRequest,
  restoreBackupRequest,
  loadDiagnostics,
  loadLogs,
  loadBackupTargets,
  createBackup,
  restoreBackup,
} = useSystemDomain()

const runtimeExceptions = computed(() => diagnostics.value?.runtimeExceptions ?? [])
const refreshing = computed(() => diagnosticsRequest.loading || logsRequest.loading || backupTargetsRequest.loading)
const hasDiagnostics = computed(() => Boolean(diagnostics.value))
const systemStatus = ref<Record<string, unknown> | null>(null)
const databaseStats = ref<Record<string, unknown> | null>(null)
const statistics = ref<Record<string, unknown> | null>(null)
const models = ref<Record<string, unknown> | null>(null)
const effectivePreset = ref<Record<string, unknown> | null>(null)
const apiGapError = ref('')
const apiGapLoading = ref(false)
const apiGapLoaded = ref(false)
const exportingKind = ref<'json' | 'csv' | null>(null)
const restoreBackupDir = ref('')
const restorePreview = ref<BackupRestoreResponse | null>(null)
const logsLoaded = ref(false)
const restoreMode = ref<'preview' | 'apply' | null>(null)
const runtimeSnapshot = ref<RuntimeResourceSnapshot | null>(null)
const runtimeLoading = ref(false)
const runtimeClearing = ref(false)
const runtimeError = ref('')
const runtimeAvailable = computed(() => Boolean(window.petApi?.runtime?.getResourceSnapshot && window.petApi?.runtime?.clearSessionCache))
const runtimeProcesses = computed(() => [...(runtimeSnapshot.value?.processes ?? [])]
  .sort((left, right) => right.privateKb - left.privateKb)
  .slice(0, 8))
const canConfirmRestore = computed(() => Boolean(restoreBackupDir.value.trim() && restorePreview.value?.dryRun && restorePreview.value.restorePlan.some((item) => !item.skippedReason && item.backedUpAtSnapshot)))
const controlServerLabel = computed(() => {
  const panelUrl = diagnostics.value?.panelUrl
  return panelUrl ? `控制服务 · ${panelUrl}` : '控制服务 · 等待检测'
})

const envChecks = computed(() => {
  const env = diagnostics.value?.envCheck
  if (!env) return []
  return [
    { label: 'Python 应用', value: 'python/app.py', ok: env.pythonAppExists },
    { label: 'Python 虚拟环境', value: env.pythonVenvPath, ok: env.pythonVenvExists },
    { label: '渲染产物', value: 'dist/renderer/index.html', ok: env.rendererDistExists },
    { label: '插件目录', value: 'electron/plugins', ok: env.pluginDirExists },
    { label: '备份目录', value: '../backups', ok: env.backupDirExists },
  ]
})

const envPassedCount = computed(() => envChecks.value.filter((item) => item.ok).length)
const existingBackupTargets = computed(() => backupTargets.value.filter((item) => item.exists).length)
const envStatusLabel = computed(() => {
  if (diagnosticsRequest.loading) return '诊断刷新中'
  if (diagnosticsRequest.error) return '诊断失败'
  if (!diagnostics.value) return '等待诊断快照'
  return `${envPassedCount.value} / ${envChecks.value.length} 项通过`
})

const isElectronPanel = computed(() => Boolean(window.petApi?.window))

const serviceCards = computed(() => {
  const snapshot = diagnostics.value
  if (!snapshot) return []
  return [
    {
      label: '控制服务',
      detail: snapshot.status === 'ok' ? '本地 HTTP 控制服务已响应' : `状态：${snapshot.status}`,
      ok: snapshot.status === 'ok',
      tone: 'emerald',
    },
    {
      label: '桌宠窗口',
      detail: isElectronPanel.value
        ? (snapshot.petWindowVisible ? '桌宠主窗口可见' : '桌宠主窗口未显示')
        : '当前为浏览器模式，不存在独立桌宠主窗口',
      ok: !isElectronPanel.value || snapshot.petWindowVisible,
      tone: 'blue',
    },
    {
      label: 'Live2D 覆盖层',
      detail: snapshot.petOverlayVisible ? '渲染覆盖层可见' : '渲染覆盖层未显示',
      ok: snapshot.petOverlayVisible,
      tone: 'violet',
    },
    {
      label: '插件运行时',
      detail: `${snapshot.pluginCount} 个插件 · ${snapshot.activePluginExecutions} 个活动执行`,
      ok: snapshot.pluginErrorCount === 0,
      tone: snapshot.pluginErrorCount === 0 ? 'emerald' : 'rose',
    },
  ]
})

const overallHealthy = computed(() => {
  const snapshot = diagnostics.value
  return Boolean(
    snapshot &&
    snapshot.status === 'ok' &&
    snapshot.pluginErrorCount === 0 &&
    runtimeExceptions.value.length === 0 &&
    (snapshot.petWindowVisible || !isElectronPanel.value)
  )
})

const serviceStatusLabel = computed(() => {
  if (diagnosticsRequest.loading) return '检查中'
  if (diagnosticsRequest.error) return '诊断失败'
  if (!diagnostics.value) return '等待诊断'
  return overallHealthy.value ? '全部可用' : '需要处理'
})

const serviceStatusTagType = computed(() => {
  if (!diagnostics.value || diagnosticsRequest.loading) return 'info'
  return overallHealthy.value ? 'success' : 'danger'
})

const exceptionStatusLabel = computed(() => {
  if (diagnosticsRequest.loading) return '诊断刷新中'
  if (diagnosticsRequest.error) return '诊断失败'
  if (!diagnostics.value) return '等待诊断快照'
  return `${runtimeExceptions.value.length} 条记录`
})

const exceptionTagLabel = computed(() => {
  if (diagnosticsRequest.loading) return '检查中'
  if (diagnosticsRequest.error) return '诊断失败'
  if (!diagnostics.value) return '等待诊断'
  return runtimeExceptions.value.length ? '有异常' : '干净'
})

const exceptionTagType = computed(() => {
  if (!diagnostics.value || diagnosticsRequest.loading) return 'info'
  return runtimeExceptions.value.length ? 'danger' : 'success'
})

const metrics = computed(() => [
  {
    label: '环境检查',
    value: hasDiagnostics.value ? `${envPassedCount.value}/${envChecks.value.length}` : '待诊断',
    detail: hasDiagnostics.value ? '关键文件与目录可用性' : '等待诊断快照',
    tone: hasDiagnostics.value && envPassedCount.value === envChecks.value.length ? 'green' : 'amber',
  },
  {
    label: '插件异常',
    value: hasDiagnostics.value ? (diagnostics.value?.pluginErrorCount ?? 0) : '待诊断',
    detail: hasDiagnostics.value ? `${diagnostics.value?.pluginCount ?? 0} 个插件已纳入诊断` : '等待诊断快照',
    tone: diagnostics.value?.pluginErrorCount ? 'red' : hasDiagnostics.value ? 'green' : 'amber',
  },
  {
    label: '运行异常',
    value: hasDiagnostics.value ? runtimeExceptions.value.length : '待诊断',
    detail: hasDiagnostics.value ? (runtimeExceptions.value.length ? '请查看异常列表' : '暂无运行时异常') : '等待诊断快照',
    tone: runtimeExceptions.value.length ? 'red' : hasDiagnostics.value ? 'green' : 'amber',
  },
  {
    label: '备份目标',
    value: `${existingBackupTargets.value}/${backupTargets.value.length || 6}`,
    detail: backupResult.value ? '最近已创建备份清单' : '覆盖数据库、配置与桌宠状态',
    tone: existingBackupTargets.value === backupTargets.value.length && backupTargets.value.length > 0 ? 'green' : 'slate',
  },
  {
    label: '进程内存',
    value: runtimeSnapshot.value ? formatBytes(runtimeSnapshot.value.totalPrivateKb * 1024) : '待采样',
    detail: runtimeSnapshot.value ? `${runtimeSnapshot.value.processes.length} 个 Electron 进程` : '仅桌面客户端可读取',
    tone: runtimeSnapshot.value ? 'blue' : 'slate',
  },
])

const formatBytes = (bytes: number) => {
  const value = Math.max(0, Number(bytes) || 0)
  if (value < 1024) return `${Math.round(value)} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`
}

const formatRuntimeTime = (value: string) => {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const runtimeProcessLabel = (type: string) => ({
  Browser: '主进程',
  Tab: '渲染进程',
  GPU: 'GPU 进程',
  Utility: '工具进程',
}[type] || type)

const loadRuntimeSnapshot = async () => {
  if (!runtimeAvailable.value || runtimeLoading.value) return
  runtimeLoading.value = true
  runtimeError.value = ''
  try {
    runtimeSnapshot.value = await window.petApi.runtime.getResourceSnapshot()
  } catch (error) {
    runtimeError.value = error instanceof Error ? error.message : '无法读取运行时资源'
  } finally {
    runtimeLoading.value = false
  }
}

const clearRuntimeCache = async () => {
  if (!runtimeAvailable.value || runtimeClearing.value) return
  runtimeClearing.value = true
  runtimeError.value = ''
  try {
    const result = await window.petApi.runtime.clearSessionCache()
    ElMessage.success(`已清理 ${formatBytes(result.clearedBytes)} HTTP 缓存`)
    await loadRuntimeSnapshot()
  } catch (error) {
    runtimeError.value = error instanceof Error ? error.message : 'HTTP 缓存清理失败'
    ElMessage.error(runtimeError.value)
  } finally {
    runtimeClearing.value = false
  }
}

const logChannels = computed(() => [
  {
    key: 'renderer',
    label: '渲染层日志',
    description: 'Live2D / 前端运行输出',
    content: logs.value?.renderer ?? '',
    tone: 'green',
  },
  {
    key: 'python',
    label: 'Python 后端日志',
    description: 'FastAPI 与 AI 服务输出',
    content: logs.value?.python ?? '',
    tone: 'blue',
  },
  {
    key: 'electron',
    label: 'Electron 主进程日志',
    description: '窗口、托盘与控制服务输出',
    content: logs.value?.electron ?? '',
    tone: 'amber',
  },
])

const loadApiGaps = async () => {
  apiGapError.value = ''
  apiGapLoading.value = true
  try {
    const [status, db, stats, modelList] = await Promise.all([
      systemClient.systemStatus(),
      systemClient.databaseStats(),
      systemClient.statistics(),
      systemClient.models(),
    ])
    systemStatus.value = status
    databaseStats.value = db
    statistics.value = stats
    models.value = modelList
    try {
      effectivePreset.value = await systemClient.effectivePreset('default')
    } catch {
      effectivePreset.value = null
    }
    apiGapLoaded.value = true
  } catch (error) {
    apiGapError.value = error instanceof Error ? error.message : String(error)
  } finally {
    apiGapLoading.value = false
  }
}

const downloadExport = async (kind: 'json' | 'csv') => {
  apiGapError.value = ''
  exportingKind.value = kind
  try {
    const blob = await systemClient.exportData(kind)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `yuizaki-export.${kind}`
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${kind.toUpperCase()} 文件`)
  } catch (error) {
    apiGapError.value = error instanceof Error ? error.message : String(error)
    ElMessage.error(apiGapError.value)
  } finally {
    exportingKind.value = null
  }
}

const updateStats = async () => {
  if (apiGapLoading.value) return
  apiGapError.value = ''
  apiGapLoading.value = true
  try {
    await systemClient.updateStatistics()
    await loadApiGaps()
    ElMessage.success('统计快照已更新')
  } catch (error) {
    apiGapError.value = error instanceof Error ? error.message : String(error)
    ElMessage.error(apiGapError.value)
  } finally {
    apiGapLoading.value = false
  }
}

const refreshAll = async () => {
  const requests = [loadDiagnostics(), loadBackupTargets(), loadRuntimeSnapshot()]
  if (logsLoaded.value) requests.push(loadLogs())
  await Promise.all(requests)
}

const refreshLogs = async () => {
  logsLoaded.value = true
  await loadLogs()
}

const handleLogsToggle = (event: Event) => {
  const details = event.currentTarget as HTMLDetailsElement | null
  if (details?.open && !logsLoaded.value) void refreshLogs()
}

const createAndSelectBackup = async () => {
  await createBackup()
  if (backupResult.value) {
    restoreBackupDir.value = backupResult.value
    restorePreview.value = null
  }
}

const previewRestore = async () => {
  const backupDir = restoreBackupDir.value.trim()
  if (!backupDir || restoreMode.value) return
  restoreMode.value = 'preview'
  try {
    const result = await restoreBackup(backupDir, true)
    if (result) {
      restorePreview.value = result
      ElMessage.success('恢复预览已生成，尚未写入文件')
    }
  } finally {
    restoreMode.value = null
  }
}

const confirmRestore = async () => {
  const backupDir = restoreBackupDir.value.trim()
  if (!backupDir || !canConfirmRestore.value || restoreMode.value) return
  try {
    await ElMessageBox.confirm('确认恢复后会覆盖当前本地数据。建议确认刚刚的预览结果和备份目录无误。', '确认恢复备份', {
      confirmButtonText: '恢复备份',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  restoreMode.value = 'apply'
  try {
    const result = await restoreBackup(backupDir, false)
    if (result) {
      restorePreview.value = result
      ElMessage.success('备份已恢复')
    }
  } finally {
    restoreMode.value = null
  }
}

const targetLabel = (targetPath: string) => {
  const normalized = targetPath.replace(/\\/g, '/')
  const name = normalized.split('/').filter(Boolean).pop()
  return name || targetPath
}

const targetTypeLabel = (type: BackupTarget['type']) => (type === 'directory' ? '目录' : '文件')

const restorePlanLabel = (item: BackupRestorePlanItem) => {
  if (item.restored) return '已恢复'
  if (item.skippedReason) return item.skippedReason
  if (!item.backedUpAtSnapshot) return '快照缺失'
  return '将恢复'
}

const restorePlanTagType = (item: BackupRestorePlanItem): 'success' | 'warning' | 'info' => {
  if (item.restored) return 'success'
  if (item.skippedReason || !item.backedUpAtSnapshot) return 'info'
  return 'warning'
}

onMounted(() => {
  void refreshAll()
})
</script>

<style scoped>
.infra-console {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.infra-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 20px;
  padding: 16px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  color: var(--yui-text);
  box-shadow: var(--yui-shadow-card);
}

.infra-hero h2 {
  margin: 8px 0;
  font-size: 30px;
  line-height: 1.08;
  letter-spacing: 0;
}

.infra-hero p {
  max-width: 780px;
  margin: 0;
  color: var(--yui-muted);
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  color: var(--yui-muted);
  font-size: 12px;
}

.section-kicker {
  color: var(--yui-accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.metric-grid,
.infra-grid,
.log-grid {
  display: grid;
  gap: 14px;
}

.metric-grid {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

.infra-grid {
  grid-template-columns: minmax(0, 1.1fr) minmax(360px, 0.9fr);
}

.lower-grid {
  grid-template-columns: minmax(0, 1fr) minmax(340px, 0.8fr);
}

.log-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.logs-disclosure {
  display: grid;
  gap: 10px;
}

.logs-disclosure > summary {
  width: fit-content;
  cursor: pointer;
  color: var(--yui-muted);
  font-size: 13px;
  font-weight: 700;
}

.logs-disclosure[open] > summary {
  color: var(--yui-text);
}

.metric-card,
.panel-card {
  border: 1px solid var(--yui-border);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
}

.metric-card {
  display: flex;
  min-height: 126px;
  flex-direction: column;
  justify-content: space-between;
  padding: 16px;
  border-radius: var(--yui-radius-card);
}

.metric-card span,
.metric-card small {
  color: #64748b;
}

.metric-card strong {
  color: var(--yui-text);
  font-size: 26px;
  letter-spacing: 0;
}

.metric-card.green { background: var(--yui-success-soft); }
.metric-card.blue { background: rgba(37, 99, 235, 0.08); }
.metric-card.amber { background: var(--yui-warning-soft); }
.metric-card.red { background: var(--yui-danger-soft); }
.metric-card.slate { background: var(--yui-surface-muted); }

.panel-card {
  border-radius: var(--yui-radius-card);
}

.card-head,
.action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-head > div:first-child {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.service-list,
.env-list,
.target-list,
.exception-list,
.runtime-processes {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.api-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.api-grid pre {
  max-height: 180px;
  overflow: auto;
  padding: 10px;
  border-radius: 10px;
  background: #0f172a;
  color: #e2e8f0;
}

.service-item,
.env-item,
.target-item,
.exception-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.runtime-alert {
  margin-top: 10px;
}

.runtime-overview {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.runtime-overview > div,
.runtime-processes article {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
  padding: 10px;
}

.runtime-overview span,
.runtime-processes span {
  color: var(--yui-muted);
  font-size: 11px;
}

.runtime-overview strong {
  display: block;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 17px;
}

.runtime-processes {
  margin-top: 10px;
}

.runtime-processes article {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.runtime-processes article > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.runtime-processes strong {
  color: var(--yui-text);
  font-size: 12px;
}

.service-item > div:nth-child(2),
.target-item > div,
.exception-item > div {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}

.service-item strong,
.target-item strong,
.exception-item strong {
  color: var(--yui-text);
}

.service-item span,
.target-item span,
.exception-item span,
.exception-item p,
.root-path {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.5;
}

.service-dot {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: #22c55e;
  box-shadow: 0 0 0 6px rgba(34, 197, 94, 0.12);
}

.service-item.rose .service-dot { background: #ef4444; box-shadow: 0 0 0 6px rgba(239, 68, 68, 0.12); }
.service-item.blue .service-dot { background: #3b82f6; box-shadow: 0 0 0 6px rgba(59, 130, 246, 0.12); }
.service-item.violet .service-dot { background: #8b5cf6; box-shadow: 0 0 0 6px rgba(139, 92, 246, 0.12); }

.env-item,
.target-item {
  justify-content: space-between;
}

.env-item span {
  color: #475569;
  font-weight: 700;
}

.env-item strong {
  flex: 1;
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  text-align: right;
}

.root-path {
  margin-top: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.backup-success {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
  padding: 12px;
  border: 1px solid rgba(34, 197, 94, 0.24);
  border-radius: var(--yui-radius-card);
  background: var(--yui-success-soft);
  color: #166534;
}

.backup-error {
  margin-bottom: 12px;
  border-radius: 14px;
}

.backup-success span {
  word-break: break-all;
  font-size: 12px;
}

.restore-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 12px;
  padding: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.restore-fields,
.restore-summary-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.restore-fields :deep(.el-input) {
  min-width: 0;
  flex: 1;
}

.restore-warning {
  border-radius: var(--yui-radius-card);
}

.restore-summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.restore-summary-head {
  justify-content: space-between;
}

.restore-plan-list {
  display: flex;
  max-height: 260px;
  flex-direction: column;
  gap: 8px;
  overflow: auto;
}

.restore-plan-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
}

.restore-plan-item.restored {
  border-color: rgba(34, 197, 94, 0.24);
  background: var(--yui-success-soft);
}

.restore-plan-item.skipped {
  opacity: 0.72;
}

.restore-plan-item > div {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}

.restore-plan-item strong {
  color: var(--yui-text);
}

.restore-plan-item span {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.target-item span {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.exception-item {
  align-items: flex-start;
  flex-direction: column;
}

.exception-item p {
  margin: 0;
}

.log-panel {
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.16);
  border-radius: 18px;
  background: #0f172a;
}

.log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  color: #e2e8f0;
}

.log-head > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.log-head span {
  color: #94a3b8;
  font-size: 12px;
}

.log-panel pre {
  min-height: 260px;
  max-height: 360px;
  margin: 0;
  overflow: auto;
  padding: 14px;
  color: #86efac;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.log-panel.blue pre { color: #93c5fd; }
.log-panel.amber pre { color: #fde68a; }

:deep(.el-card) {
  border-radius: 0.75rem;
  border: none;
  box-shadow: 0 0 0 1px rgba(243, 244, 246, 0.6);
  background: rgba(255, 255, 255, 0.8);
}

@media (max-width: 1180px) {
  .metric-grid,
  .infra-grid,
  .lower-grid,
  .log-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .infra-hero {
    grid-template-columns: 1fr;
  }

  .infra-hero {
    display: flex;
    flex-direction: column;
  }

  .hero-actions,
  .card-head {
    align-items: flex-start;
  }

  .card-head,
  .action-row,
  .restore-fields,
  .restore-summary-head,
  .restore-plan-item {
    flex-direction: column;
    align-items: stretch;
  }

  .runtime-overview {
    grid-template-columns: 1fr;
  }
}
</style>
