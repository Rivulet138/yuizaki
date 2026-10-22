<template>
  <component :is="embedded ? 'div' : PanelShell" :title="t('navigation.deploy.title')" :class="{ 'deploy-embedded-panel': embedded }">
    <div class="deploy-console">
      <section class="deploy-hero">
        <div class="hero-actions">
          <el-button type="primary" :loading="refreshing" :disabled="refreshing" @click="refreshAll">{{ t('deploy.refresh') }}</el-button>
          <span>{{ overallStatusText }}</span>
        </div>
      </section>

      <section class="deploy-grid">
        <el-card class="panel-card health-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>{{ t('deploy.backendStatus') }}</strong>
              </div>
              <el-tag :type="healthTone">{{ healthTagText }}</el-tag>
            </div>
          </template>
          <div class="status-row">
            <div class="status-orb" :class="healthOrbClass"></div>
            <div>
              <strong>{{ health.message }}</strong>
              <span>{{ lastCheckedAt ? t('deploy.lastChecked', { value: lastCheckedAt }) : t('deploy.noHealthCheck') }}</span>
            </div>
          </div>
          <div class="actions">
            <el-button :loading="startLoading" :disabled="!hasElectronPythonControls || startLoading || stopLoading" @click="startPython">{{ t('deploy.startBackend') }}</el-button>
            <el-button :loading="stopLoading" :disabled="!hasElectronPythonControls || startLoading || stopLoading" @click="stopPython">{{ t('deploy.stopBackend') }}</el-button>
            <el-button
              type="success"
              plain
              :disabled="!health.healthy"
              @click="openDocs"
            >
              {{ t('deploy.apiDocs') }}
            </el-button>
          </div>
          <el-alert v-if="actionError" class="panel-alert" :title="actionError" type="error" show-icon :closable="false" />
        </el-card>

        <el-card class="panel-card runway-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>{{ t('deploy.runChecks') }}</strong>
              </div>
              <el-tag type="info">{{ completedRunwaySteps }} / {{ deploySteps.length }}</el-tag>
            </div>
          </template>
          <div class="runway-list">
            <article v-for="step in deploySteps" :key="step.id" class="runway-step" :class="step.status">
              <div class="step-index">{{ step.index }}</div>
              <strong>{{ step.title }}</strong>
              <el-tag size="small" :type="stepTagType(step.status)">{{ stepStatusLabel(step.status) }}</el-tag>
            </article>
          </div>
        </el-card>
      </section>

      <section class="deploy-grid lower-grid">
        <el-card v-if="providers.length || providersLoading || providersError" class="panel-card provider-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>{{ t('deploy.dependencies') }}</strong>
              </div>
              <el-tag :type="providerSummary.requiredHealthy ? 'success' : 'warning'">
                {{ t('deploy.requiredHealthy', { healthy: providerSummary.healthy, total: providerSummary.total }) }}
              </el-tag>
            </div>
          </template>
          <el-alert v-if="providersError" :title="providersError" type="warning" show-icon :closable="false" />
          <div v-if="providersLoading && !providers.length" class="provider-empty">{{ t('deploy.readingDependencies') }}</div>
          <div v-else-if="providers.length" class="provider-grid">
            <article v-for="provider in providers" :key="provider.id" class="provider-item" :class="provider.healthy ? 'ok' : provider.configured ? 'degraded' : 'optional'">
              <div class="provider-item-head">
                <strong>{{ provider.label }}</strong>
                <el-tag size="small" :type="provider.healthy ? 'success' : provider.configured ? 'warning' : 'info'">
                  {{ provider.healthy ? t('deploy.normal') : provider.configured ? t('deploy.pending') : provider.optional ? t('deploy.unconfigured') : t('deploy.required') }}
                </el-tag>
              </div>
              <span>{{ provider.provider || t('deploy.noProvider') }}{{ provider.model ? ` · ${provider.model}` : '' }}</span>
              <small v-if="!provider.healthy">{{ provider.message }}</small>
              <el-button
                v-if="provider.retryable"
                class="provider-retry"
                text
                type="primary"
                size="small"
                :loading="providersLoading"
                :data-testid="`provider-retry-${provider.id}`"
                @click="checkProviders"
              >{{ t('deploy.retry') }}</el-button>
            </article>
          </div>
          <div v-else class="provider-empty">{{ t('deploy.noDependencyData') }}</div>
        </el-card>

        <el-card class="panel-card command-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>{{ t('deploy.startCommand') }}</strong>
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
              <el-button size="small" plain @click="copyCommand(command.command)">{{ t('deploy.copy') }}</el-button>
            </article>
          </div>
        </el-card>
      </section>
    </div>
  </component>
</template>

<script setup lang="ts">
import { ElAlert } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElCard } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { t } from '@/i18n'
import { systemClient, summaryClient } from '@/api/client'
import type { ProviderStatus } from '@/../shared/agent'
import { resolveBackendUrl } from '@/api/clients/http-client'
import { buildDeployPlatformCommands, resolveDeployPlatform } from '../platform-commands'
import { describeFailure } from '@/shared/errors/describe-error'

const props = defineProps<{
  embedded?: boolean
}>()
const embedded = computed(() => props.embedded === true)

type StepStatus = 'done' | 'active' | 'pending' | 'blocked'

const health = reactive({
  healthy: false,
  status: 'unknown',
  message: t('deploy.waitingHealth'),
})

const readiness = reactive({
  checked: false,
  ready: false,
  message: t('deploy.waitingReadiness'),
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
  const healthy = data.healthy === true || data.ok === true || status === 'healthy' || status === 'ok'
  const message = typeof data.message === 'string'
    ? data.message
    : healthy
      ? t('deploy.backendHealthy')
      : t('deploy.backendError')
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
    health.message = normalized.healthy ? t('deploy.backendHealthy') : normalized.message
  } catch (error) {
    if (gen !== refreshGeneration) return
    health.healthy = false
    health.status = 'offline'
    health.message = t('deploy.backendOffline')
    actionError.value = describeFailure(error, t('deploy.healthCheckFailed'))
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
      ? t('deploy.ready')
      : typeof llm?.message === 'string'
        ? llm.message
        : t('deploy.notReady')
  } catch (error) {
    if (gen !== refreshGeneration) return
    readiness.checked = true
    readiness.ready = false
    readiness.message = describeFailure(error, t('deploy.readinessFailed'))
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
    providersError.value = describeFailure(error, t('deploy.providersFailed'))
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
      ElMessage.info(t('deploy.browserStart'))
      return
    }

    if (res.success) {
      ElMessage.success(t('deploy.started'))
    } else {
      actionError.value = t('deploy.startFailed', { error: res.error || t('common.error.unknown') })
      ElMessage.error(actionError.value)
    }
  } catch (error) {
    actionError.value = describeFailure(error, t('deploy.startError'))
    ElMessage.error(actionError.value)
  } finally {
    startLoading.value = false
    await refreshAll()
  }
}

const stopPython = async () => {
  if (stopLoading.value || startLoading.value) return
  if (!hasElectronPythonControls.value) {
    ElMessage.info(t('deploy.browserStop'))
    return
  }
  try {
    await ElMessageBox.confirm(
      t('deploy.stopConfirm'),
      t('deploy.stopConfirmTitle'),
      {
        confirmButtonText: t('deploy.stopBackend'),
        cancelButtonText: t('deploy.cancel'),
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
      ElMessage.info(t('deploy.browserStop'))
      return
    }

    if (res.success) {
      ElMessage.success(t('deploy.stopped'))
    } else {
      actionError.value = t('deploy.stopFailed', { error: res.error || t('common.error.unknown') })
      ElMessage.error(actionError.value)
    }
  } catch (error) {
    actionError.value = describeFailure(error, t('deploy.stopError'))
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
    ElMessage.info(t('deploy.openDocsBrowser', { url: docsUrl }))
  }
}

const copyCommand = async (command: string) => {
  try {
    await navigator.clipboard.writeText(command)
    ElMessage.success(t('deploy.copied'))
  } catch {
    ElMessage.warning(t('deploy.copyFailed'))
  }
}

const hasElectronBridge = computed(() => Boolean(window.petApi?.python?.health))
const hasElectronPythonControls = computed(() => Boolean(window.petApi?.python?.start && window.petApi?.python?.stop))
const refreshing = computed(() => healthLoading.value || readinessLoading.value)
const healthIsError = computed(() => !health.healthy && ['error', 'failed', 'unhealthy'].includes(health.status))
const healthTone = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  if (health.healthy) return 'success'
  if (healthIsError.value) return 'danger'
  return 'warning'
})
const healthTagText = computed(() => {
  if (health.healthy) return t('deploy.online')
  if (healthIsError.value) return t('deploy.checkFailed')
  return t('deploy.waitingConnection')
})
const healthOrbClass = computed(() => health.healthy ? 'online' : healthIsError.value ? 'error' : 'offline')

const overallStatusText = computed(() => {
  if (refreshing.value) return t('deploy.refreshing')
  if (health.healthy && readiness.ready) return t('deploy.corePassed')
  if (healthIsError.value) return t('deploy.runFailed')
  return t('deploy.waitingBackend')
})

const deploySteps = computed(() => {
  const steps = [
    { id: 'backend', title: t('deploy.backendHealth'), status: health.healthy ? 'done' : healthLoading.value ? 'active' : healthIsError.value ? 'blocked' : 'pending' as StepStatus },
    { id: 'readiness', title: t('deploy.serviceReady'), status: readiness.ready ? 'done' : health.healthy ? 'active' : 'pending' as StepStatus },
    { id: 'electron', title: t('deploy.bridge'), status: hasElectronBridge.value ? 'done' : 'pending' as StepStatus },
    { id: 'docs', title: t('deploy.apiDocs'), status: health.healthy ? 'done' : healthIsError.value ? 'blocked' : 'pending' as StepStatus },
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
    done: t('deploy.stepDone'),
    active: t('deploy.stepCurrent'),
    pending: t('deploy.stepWaiting'),
    blocked: t('deploy.stepBlocked'),
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
  void refreshAll()
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

.deploy-grid {
  display: grid;
  gap: 14px;
}

.deploy-grid {
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.72fr);
}

.lower-grid { grid-template-columns: minmax(0, 1fr); }

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

.panel-card,
.runway-step,
.command-item {
  border: 1px solid var(--yui-border);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
}

.panel-card {
  border-radius: var(--yui-radius-card);
}

.card-head,
.actions,
.status-row,
.runway-step,
.command-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-head > div:first-child,
.status-row > div:last-child,
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
  background: #f59e0b;
  box-shadow: 0 0 0 8px rgba(245, 158, 11, 0.12);
}

.status-orb.online {
  background: #22c55e;
  box-shadow: 0 0 0 8px rgba(34, 197, 94, 0.12);
}

.status-orb.error {
  background: #ef4444;
  box-shadow: 0 0 0 8px rgba(239, 68, 68, 0.12);
}

.status-row strong,
.runway-step strong,
.command-item strong {
  color: var(--yui-text);
}

.status-row span,
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

.runway-step,
.command-item {
  padding: 12px;
  border-radius: var(--yui-radius-card);
}

.runway-step.done {
  border-color: rgba(34, 197, 94, 0.26);
  background: var(--yui-success-soft);
}

.runway-step.blocked {
  border-color: rgba(239, 68, 68, 0.24);
  background: var(--yui-danger-soft);
}

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
  .deploy-grid,
  .lower-grid {
    grid-template-columns: 1fr;
  }

  .provider-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .deploy-hero {
    display: flex;
    flex-direction: column;
  }

  .hero-actions,
  .card-head,
  .runway-step,
  .command-item {
    align-items: flex-start;
  }

  .card-head,
  .runway-step,
  .command-item {
    flex-direction: column;
  }

  .provider-grid {
    grid-template-columns: 1fr;
  }
}
</style>
