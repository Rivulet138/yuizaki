<template>
  <PanelShell title="运行检查" subtitle="检查后端连接、就绪状态和桌面控制能力" tone="admin">
    <div class="deploy-console">
      <section class="deploy-hero">
        <div class="hero-actions">
          <el-button type="primary" :loading="refreshing" :disabled="refreshing" @click="refreshAll">刷新运行状态</el-button>
          <span>{{ overallStatusText }}</span>
        </div>
      </section>

      <section class="metric-grid" aria-label="运行状态概况">
        <article v-for="metric in metrics" :key="metric.label" class="metric-card" :class="metric.tone">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.detail }}</small>
        </article>
      </section>

      <section class="deploy-grid">
        <el-card class="panel-card health-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>必需检查 {{ passedRequiredChecks }} / {{ requiredCheckCount }}</strong>
              </div>
              <el-tag :type="health.healthy ? 'success' : 'danger'">{{ health.healthy ? '后端在线' : '等待连接' }}</el-tag>
            </div>
          </template>
          <div class="status-row">
            <div class="status-orb" :class="health.healthy ? 'online' : 'offline'"></div>
            <div>
              <strong>{{ health.message }}</strong>
              <span>{{ lastCheckedAt ? `最近检查：${lastCheckedAt}` : '尚未执行健康检查' }}</span>
            </div>
          </div>
          <div class="actions">
            <el-button :loading="startLoading" :disabled="!hasElectronPythonControls || startLoading || stopLoading" :title="pythonControlHint" @click="startPython">启动后端</el-button>
            <el-button :loading="stopLoading" :disabled="!hasElectronPythonControls || startLoading || stopLoading" :title="pythonControlHint" @click="stopPython">停止后端</el-button>
            <el-button
              type="success"
              plain
              :disabled="!health.healthy"
              :title="health.healthy ? '打开当前后端 /docs' : '后端在线后可打开 /docs'"
              @click="openDocs"
            >
              API 文档
            </el-button>
          </div>
          <el-alert v-if="actionError" class="panel-alert" :title="actionError" type="error" show-icon :closable="false" />
          <div class="service-grid">
            <article v-for="svc in serviceChecks" :key="svc.name" class="service-item" :class="svc.ok ? 'ok' : svc.required ? 'blocked' : 'optional'">
              <div>
                <strong>{{ svc.label }}</strong>
                <span>{{ svc.message }}</span>
              </div>
              <el-tag size="small" :type="svc.ok ? 'success' : svc.required ? 'danger' : 'warning'">
                {{ svc.ok ? '通过' : svc.required ? '阻塞' : '可选' }}
              </el-tag>
            </article>
          </div>
        </el-card>

        <el-card class="panel-card runway-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>运行检查项</strong>
              </div>
              <el-tag type="info">{{ completedRunwaySteps }} / {{ deploySteps.length }}</el-tag>
            </div>
          </template>
          <div class="runway-list">
            <article v-for="step in deploySteps" :key="step.id" class="runway-step" :class="step.status">
              <div class="step-index">{{ step.index }}</div>
              <div>
                <strong>{{ step.title }}</strong>
              </div>
              <el-tag size="small" :type="stepTagType(step.status)">{{ stepStatusLabel(step.status) }}</el-tag>
            </article>
          </div>
        </el-card>
      </section>

      <section class="deploy-grid lower-grid">
        <el-card class="panel-card provider-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>模型与语音运行时</strong>
                <span class="card-subtitle">配置、初始化和健康状态来自同一份后端快照</span>
              </div>
              <el-tag :type="providerSummary.requiredHealthy ? 'success' : 'warning'">
                {{ providerSummary.healthy }}/{{ providerSummary.total }} 正常
              </el-tag>
            </div>
          </template>
          <el-alert v-if="providersError" :title="providersError" type="warning" show-icon :closable="false" />
          <div v-if="providersLoading && !providers.length" class="provider-empty">正在读取 provider 状态...</div>
          <div v-else class="provider-grid">
            <article v-for="provider in providers" :key="provider.id" class="provider-item" :class="provider.healthy ? 'ok' : provider.configured ? 'degraded' : 'optional'">
              <div class="provider-item-head">
                <strong>{{ provider.label }}</strong>
                <el-tag size="small" :type="provider.healthy ? 'success' : provider.configured ? 'warning' : 'info'">
                  {{ provider.healthy ? '正常' : provider.configured ? '待处理' : provider.optional ? '未配置' : '必需' }}
                </el-tag>
              </div>
              <span>{{ provider.provider || '未选择 provider' }}{{ provider.model ? ` · ${provider.model}` : '' }}</span>
              <small>{{ provider.message }}</small>
              <small v-if="provider.capabilities.length">能力：{{ provider.capabilities.join('、') }}</small>
              <el-button
                v-if="provider.retryable"
                class="provider-retry"
                text
                type="primary"
                size="small"
                :loading="providersLoading"
                :data-testid="`provider-retry-${provider.id}`"
                @click="checkProviders"
              >重新检查</el-button>
            </article>
          </div>
        </el-card>

        <el-card class="panel-card command-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>启动命令</strong>
              </div>
              <el-tag type="primary">{{ platformCommands.label }}</el-tag>
            </div>
          </template>
          <div class="command-list">
            <article v-for="command in commandCards" :key="command.title" class="command-item">
              <div>
                <strong>{{ command.title }}</strong>
                <code>{{ command.command }}</code>
              </div>
              <el-button size="small" plain @click="copyCommand(command.command)">复制</el-button>
            </article>
          </div>
        </el-card>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { systemClient, summaryClient } from '@/api/client'
import type { ProviderStatus } from '@/../shared/agent'
import { resolveBackendUrl } from '@/api/clients/http-client'
import { buildDeployPlatformCommands, resolveDeployPlatform } from '../platform-commands'

type StepStatus = 'done' | 'active' | 'pending' | 'blocked'

interface ServiceCheck {
  name: string
  label: string
  ok: boolean
  required: boolean
  message: string
}

const health = reactive({
  healthy: false,
  status: 'unknown',
  message: '等待检测',
})

const readiness = reactive({
  checked: false,
  ready: false,
  message: '等待就绪检查',
})

const healthLoading = ref(false)
const readinessLoading = ref(false)
const startLoading = ref(false)
const stopLoading = ref(false)
const actionError = ref('')
const lastCheckedAt = ref('')
const providers = ref<ProviderStatus[]>([])
const providerSummary = reactive({ total: 0, healthy: 0, requiredHealthy: false })
const providersLoading = ref(false)
const providersError = ref('')
let refreshGeneration = 0

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null

const normalizeHealthStatus = (payload: unknown) => {
  const data = isRecord(payload) ? payload : {}
  const status = typeof data.status === 'string' ? data.status : 'unknown'
  const healthy = data.healthy === true || status === 'healthy' || status === 'ok'
  const message = typeof data.message === 'string'
    ? data.message
    : healthy
      ? '后端服务正常'
      : '后端返回异常'
  return { healthy, status, message }
}

const checkHealthByHttp = async () => {
  const gen = refreshGeneration
  healthLoading.value = true
  actionError.value = ''
  try {
    const data = await systemClient.pythonHealth()
    if (gen !== refreshGeneration) return
    const normalized = normalizeHealthStatus(data)
    health.healthy = normalized.healthy
    health.status = normalized.status
    health.message = normalized.healthy ? '后端服务正常' : normalized.message
  } catch (error) {
    if (gen !== refreshGeneration) return
    health.healthy = false
    health.status = 'offline'
    health.message = '后端未启动或端口不可达'
    actionError.value = error instanceof Error ? error.message : '后端健康检查失败'
  } finally {
    if (gen === refreshGeneration) {
      lastCheckedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
      healthLoading.value = false
    }
  }
}

const checkReadiness = async () => {
  const gen = refreshGeneration
  readinessLoading.value = true
  try {
    const data = await summaryClient.getReadiness()
    if (gen !== refreshGeneration) return
    readiness.checked = true
    readiness.ready = data.ready
    const checks = isRecord(data.checks) ? data.checks : {}
    const llm = isRecord(checks.llm) ? checks.llm : null
    readiness.message = data.ready
      ? '摘要与 LLM 就绪'
      : typeof llm?.message === 'string'
        ? llm.message
        : '后端服务尚未完全就绪'
  } catch (error) {
    if (gen !== refreshGeneration) return
    readiness.checked = true
    readiness.ready = false
    readiness.message = error instanceof Error ? error.message : '就绪检查失败'
  } finally {
    if (gen === refreshGeneration) readinessLoading.value = false
  }
}

const checkProviders = async () => {
  providersLoading.value = true
  providersError.value = ''
  try {
    const data = await systemClient.providers()
    providers.value = Array.isArray(data.providers) ? data.providers : []
    providerSummary.total = Number(data.summary?.total || providers.value.length)
    providerSummary.healthy = Number(data.summary?.healthy || 0)
    providerSummary.requiredHealthy = data.summary?.requiredHealthy === true
  } catch (error) {
    providersError.value = error instanceof Error ? error.message : 'provider 状态读取失败'
  } finally {
    providersLoading.value = false
  }
}

const checkHealth = async () => {
  await Promise.all([checkHealthByHttp(), checkReadiness(), checkProviders()])
}

const startPython = async () => {
  if (startLoading.value || stopLoading.value) return
  startLoading.value = true
  actionError.value = ''
  try {
    const res = await systemClient.startPython()
    if (!res) {
      ElMessage.info('浏览器模式无法直接拉起后端，请在终端执行启动命令')
      return
    }

    if (res.success) {
      ElMessage.success('后端已启动')
    } else {
      actionError.value = `启动失败：${res.error || '未知错误'}`
      ElMessage.error(actionError.value)
    }
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '启动后端失败'
    ElMessage.error(actionError.value)
  } finally {
    startLoading.value = false
    await refreshAll()
  }
}

const stopPython = async () => {
  if (stopLoading.value || startLoading.value) return
  if (!hasElectronPythonControls.value) {
    ElMessage.info('浏览器模式请手动停止后端进程')
    return
  }
  try {
    await ElMessageBox.confirm(
      '停止后端会中断当前对话、模型检测和工具调用，确认继续？',
      '停止后端',
      {
        confirmButtonText: '停止后端',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  stopLoading.value = true
  actionError.value = ''
  try {
    const res = await systemClient.stopPython()
    if (!res) {
      ElMessage.info('浏览器模式请手动停止后端进程')
      return
    }

    if (res.success) {
      ElMessage.success('后端已停止')
    } else {
      actionError.value = `停止失败：${res.error || '未知错误'}`
      ElMessage.error(actionError.value)
    }
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '停止后端失败'
    ElMessage.error(actionError.value)
  } finally {
    stopLoading.value = false
    await refreshAll()
  }
}

const openDocs = async () => {
  const docsUrl = await resolveBackendUrl('/docs')
  try {
    await systemClient.openExternal(docsUrl)
  } catch {
    ElMessage.info(`浏览器模式请手动打开 ${docsUrl}`)
  }
}

const copyCommand = async (command: string) => {
  try {
    await navigator.clipboard.writeText(command)
    ElMessage.success('命令已复制')
  } catch {
    ElMessage.warning('浏览器禁止写入剪贴板，请手动复制命令')
  }
}

const hasElectronBridge = computed(() => Boolean(window.petApi?.python?.health))
const hasElectronPythonControls = computed(() => Boolean(window.petApi?.python?.start && window.petApi?.python?.stop))
const pythonControlHint = computed(() => hasElectronPythonControls.value ? '通过 Electron 主进程启停后端' : '浏览器模式无法直接启停后端，请使用命令手册')
const refreshing = computed(() => healthLoading.value || readinessLoading.value)

const serviceChecks = computed<ServiceCheck[]>(() => [
  {
    name: 'python-api',
    label: 'Python FastAPI',
    ok: health.healthy,
    required: true,
    message: health.message,
  },
  {
    name: 'readiness',
    label: '摘要 / LLM 就绪',
    ok: readiness.ready,
    required: false,
    message: readiness.message,
  },
  {
    name: 'electron-bridge',
    label: 'Electron 桥接',
    ok: hasElectronPythonControls.value,
    required: false,
    message: hasElectronPythonControls.value ? '主进程 API 可直接启停后端' : '当前是浏览器降级模式，需要终端手动启停',
  },
  {
    name: 'api-docs',
    label: 'API 文档入口',
    ok: health.healthy,
    required: false,
    message: health.healthy ? '可打开当前后端 /docs' : '后端在线后可访问 Swagger 文档',
  },
])

const requiredCheckCount = computed(() => serviceChecks.value.filter((item) => item.required).length)
const passedRequiredChecks = computed(() => serviceChecks.value.filter((item) => item.required && item.ok).length)
const passedCheckCount = computed(() => serviceChecks.value.filter((item) => item.ok).length)

const metrics = computed(() => [
  {
    label: '后端健康',
    value: health.healthy ? '在线' : '离线',
    detail: health.message,
    tone: health.healthy ? 'green' : 'red',
  },
  {
    label: '就绪闸门',
    value: `${passedCheckCount.value}/${serviceChecks.value.length}`,
    detail: '健康、就绪、桥接与文档入口',
    tone: passedRequiredChecks.value === requiredCheckCount.value ? 'blue' : 'amber',
  },
  {
    label: '运行模式',
    value: hasElectronBridge.value ? '桌面' : '浏览器',
    detail: hasElectronBridge.value ? '支持主进程启停' : '保留核心运行检查能力',
    tone: hasElectronBridge.value ? 'green' : 'slate',
  },
  {
    label: 'API 文档',
    value: '/docs',
    detail: 'Swagger / OpenAPI 调试入口',
    tone: 'violet',
  },
])

const overallStatusText = computed(() => {
  if (refreshing.value) return '正在刷新运行状态'
  if (passedRequiredChecks.value === requiredCheckCount.value) return '必需闸门已通过'
  return '等待后端健康'
})

const deploySteps = computed(() => {
  const steps = [
    { id: 'backend', title: '后端健康接口', status: health.healthy ? 'done' : 'active' as StepStatus },
    { id: 'readiness', title: 'AI 就绪检查', status: readiness.ready ? 'done' : health.healthy ? 'active' : 'pending' as StepStatus },
    { id: 'electron', title: 'Electron 启停桥接', status: hasElectronBridge.value ? 'done' : 'pending' as StepStatus },
    { id: 'docs', title: 'API 文档入口', status: health.healthy ? 'done' : 'blocked' as StepStatus },
  ]
  return steps.map((step, index) => ({ ...step, index: index + 1 }))
})

const completedRunwaySteps = computed(() => deploySteps.value.filter((step) => step.status === 'done').length)

const stepTagType = (status: StepStatus): 'success' | 'warning' | 'danger' | 'info' => {
  if (status === 'done') return 'success'
  if (status === 'active') return 'warning'
  if (status === 'blocked') return 'danger'
  return 'info'
}

const stepStatusLabel = (status: StepStatus) => {
  const labels: Record<StepStatus, string> = {
    done: '完成',
    active: '当前',
    pending: '等待',
    blocked: '阻塞',
  }
  return labels[status]
}

const platformCommands = buildDeployPlatformCommands(resolveDeployPlatform(navigator.userAgent))
const commandCards = platformCommands.commands

const refreshAll = async () => {
  refreshGeneration++
  await checkHealth()
}

onMounted(() => {
  if (!window.petApi?.e2e) void refreshAll()
})
</script>

<style scoped>
.deploy-console {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.deploy-hero {
  display: flex;
  justify-content: flex-end;
}

.hero-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8px;
  color: #64748b;
  font-size: 12px;
}

.metric-grid,
.deploy-grid,
.service-grid {
  display: grid;
  gap: 14px;
}

.metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.deploy-grid {
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.72fr);
}

.lower-grid { grid-template-columns: minmax(0, 1fr); }

.card-subtitle {
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 400;
}

.provider-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.provider-item {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
  padding: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.provider-item.ok { border-color: rgba(34, 197, 94, 0.26); background: var(--yui-success-soft); }
.provider-item.degraded { border-color: rgba(245, 158, 11, 0.24); background: var(--yui-warning-soft); }
.provider-item-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.provider-item span, .provider-item small { color: var(--yui-muted); overflow-wrap: anywhere; }
.provider-item small { font-size: 11px; line-height: 1.45; }
.provider-empty { padding: 14px; color: var(--yui-muted); }

.service-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 14px;
}

.metric-card,
.panel-card,
.service-item,
.runway-step,
.command-item {
  border: 1px solid var(--yui-border);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
}

.metric-card {
  display: flex;
  min-height: 112px;
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

.metric-card.green { background: var(--yui-success-soft); }
.metric-card.blue,
.metric-card.violet { background: var(--yui-accent-soft); }
.metric-card.amber { background: var(--yui-warning-soft); }
.metric-card.red { background: var(--yui-danger-soft); }
.metric-card.slate { background: var(--yui-surface-muted); }

.panel-card {
  border-radius: var(--yui-radius-card);
}

.card-head,
.actions,
.status-row,
.service-item,
.runway-step,
.command-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-head > div:first-child,
.status-row > div:last-child,
.service-item > div,
.runway-step > div:nth-child(2),
.command-item > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.card-head.compact {
  align-items: flex-start;
}

.status-row {
  justify-content: flex-start;
  padding: 14px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.status-orb {
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: #ef4444;
  box-shadow: 0 0 0 8px rgba(239, 68, 68, 0.12);
}

.status-orb.online {
  background: #22c55e;
  box-shadow: 0 0 0 8px rgba(34, 197, 94, 0.12);
}

.status-row strong,
.service-item strong,
.runway-step strong,
.command-item strong {
  color: var(--yui-text);
}

.status-row span,
.service-item span,
.runway-step span,
.command-item span {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.5;
}

.actions {
  justify-content: flex-start;
  flex-wrap: wrap;
  margin-top: 14px;
}

.panel-alert {
  margin-top: 12px;
  border-radius: 14px;
}

.service-item,
.runway-step,
.command-item {
  padding: 12px;
  border-radius: var(--yui-radius-card);
}

.service-item.ok,
.runway-step.done {
  border-color: rgba(34, 197, 94, 0.26);
  background: var(--yui-success-soft);
}

.service-item.blocked,
.runway-step.blocked {
  border-color: rgba(239, 68, 68, 0.24);
  background: var(--yui-danger-soft);
}

.service-item.optional,
.runway-step.active {
  border-color: rgba(245, 158, 11, 0.24);
  background: var(--yui-warning-soft);
}

.runway-list,
.command-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-index {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 999px;
  background: #0f172a;
  color: #f8fafc;
  font-weight: 800;
}

.command-item code {
  display: block;
  margin-top: 6px;
  overflow-wrap: anywhere;
  color: var(--yui-text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

@media (max-width: 1180px) {
  .metric-grid,
  .deploy-grid,
  .lower-grid,
  .service-grid,
  .provider-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .deploy-hero {
    display: flex;
    flex-direction: column;
  }

  .hero-actions,
  .card-head,
  .service-item,
  .runway-step,
  .command-item {
    align-items: flex-start;
  }

  .card-head,
  .service-item,
  .runway-step,
  .command-item {
    flex-direction: column;
  }
}
</style>
