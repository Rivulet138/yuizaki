<template>
  <PanelShell title="运行状态" subtitle="读取服务、摘要和桌宠状态；异常项提供可执行入口" tone="admin">
    <template #actions>
      <el-button plain @click="openOnboarding">{{ t('onboarding.reopen') }}</el-button>
      <el-button plain :loading="overviewRefreshLoading" @click="refreshOverview">刷新</el-button>
    </template>
    <div class="overview-console">
      <section class="ops-hero">
        <div class="ops-status-grid">
          <article v-for="card in connectionCards" :key="card.label" class="ops-status-card" :class="card.tone" :title="card.desc">
            <span>{{ card.label }}</span>
            <strong>{{ card.value }}</strong>
          </article>
        </div>
      </section>
      <nav class="canonical-links" :aria-label="t('canonical.system.aria')">
        <router-link :to="canonicalPath('infrastructure')">{{ t('canonical.system.diagnostics') }}</router-link>
        <router-link :to="canonicalPath('deploy')">{{ t('canonical.system.runtimeChecks') }}</router-link>
      </nav>

      <section class="ops-card chain-card">
        <div class="ops-card-head">
          <div>
            <h3>依赖检查</h3>
          </div>
        </div>
        <div class="chain-grid">
          <article v-for="item in chainChecks" :key="item.label" class="chain-check" :class="item.tone" :title="item.desc">
            <div>
              <strong>{{ item.label }}</strong>
              <span>{{ item.value }}</span>
            </div>
          </article>
        </div>
        <div v-if="chainIssues.length" class="chain-issues" aria-label="链路问题">
          <div v-for="issue in chainIssues" :key="issue.key" class="chain-issue" :class="issue.tone">
            <strong>{{ issue.title }}</strong>
            <span>{{ issue.desc }}</span>
          </div>
        </div>
      </section>

      <section class="ops-card runtime-checklist-card" aria-label="运行状态清单">
        <div class="ops-card-head">
          <div>
            <h3>运行状态清单</h3>
            <span>只读检查；异常项可直接进入对应设置</span>
          </div>
          <el-button plain size="small" :loading="runtimeRequest.loading" @click="loadRuntimeDependencies">刷新检查</el-button>
        </div>
        <AsyncState :loading="runtimeRequest.loading" :error="runtimeRequest.error" @retry="loadRuntimeDependencies">
          <div class="runtime-checklist">
            <article v-for="item in runtimeRows" :key="item.key" class="runtime-check" :class="item.tone">
              <div class="runtime-check-copy">
                <strong>{{ item.label }}</strong>
                <span>{{ item.value }}</span>
                <small>{{ item.desc }}</small>
              </div>
              <router-link class="runtime-check-link" :to="item.to">处理</router-link>
            </article>
          </div>
        </AsyncState>
      </section>

      <section class="ops-card voice-quality-card" aria-label="语音体验质量">
        <div class="ops-card-head">
          <div>
            <h3>语音体验</h3>
            <span>只读汇总，不会自动打开设备或发起网络测试</span>
          </div>
          <el-button plain size="small" :loading="voiceRequest.loading" @click="loadVoiceDiagnostics">刷新语音数据</el-button>
        </div>
        <AsyncState :loading="voiceRequest.loading" :error="voiceRequest.error" @retry="loadVoiceDiagnostics">
          <div v-if="voiceSnapshot" class="voice-quality-grid">
            <div class="voice-quality-metric">
              <strong>{{ voiceEvidenceLabel }}</strong>
              <span>证据类型</span>
            </div>
            <div class="voice-quality-metric">
              <strong>{{ voiceSnapshot.sample_count }}</strong>
              <span>采样数</span>
            </div>
            <div class="voice-quality-metric">
              <strong>{{ voiceP95Label(voiceSnapshot.stages.first_audio) }}</strong>
              <span>首包 p95</span>
            </div>
            <div class="voice-quality-metric">
              <strong>{{ voiceP95Label(voiceSnapshot.stages.interruption) }}</strong>
              <span>打断 p95</span>
            </div>
          </div>
          <div v-if="voiceRecommendations.length" class="voice-quality-notes">
            <span v-for="recommendation in voiceRecommendations.slice(0, 2)" :key="recommendation">{{ recommendation }}</span>
          </div>
          <el-empty v-if="voiceSnapshot && voiceSnapshot.sample_count === 0" description="暂无语音体验采样；可在语音设置中开始使用" :image-size="48" />
        </AsyncState>
      </section>

      <section class="ops-card platform-card" aria-label="跨平台能力">
        <div class="ops-card-head">
          <div>
            <h3>平台能力</h3>
            <span v-if="platformSnapshot">宿主：{{ platformHostLabel }}</span>
          </div>
          <el-button plain size="small" :loading="platformRequest.loading" @click="loadPlatformMatrix">刷新能力</el-button>
        </div>
        <AsyncState :loading="platformRequest.loading" :error="platformRequest.error" @retry="loadPlatformMatrix">
          <div v-if="platformRows.length" class="platform-table-wrap">
            <table class="platform-table">
              <thead>
                <tr>
                  <th>平台</th>
                  <th>桌面壳</th>
                  <th>Live2D / VRM</th>
                  <th>文字 / 语音</th>
                  <th>桌面动作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in platformRows" :key="row.id" :class="{ host: row.host }">
                  <th scope="row"><strong>{{ row.name }}</strong><small v-if="row.host">当前宿主</small></th>
                  <td v-for="capability in platformCapabilityKeys" :key="`${row.id}-${capability}`">
                    <el-tag size="small" :type="platformTagType(row.capabilities[capability].status)">
                      {{ platformStatusLabel(row.capabilities[capability].status) }}
                    </el-tag>
                    <span class="platform-detail">{{ row.capabilities[capability].detail }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <el-empty v-else description="暂无平台能力数据" :image-size="56" />
        </AsyncState>
      </section>

      <section class="ops-grid">
        <article class="ops-card governance-card">
          <div class="ops-card-head">
            <div>
              <h3>摘要统计</h3>
            </div>
            <div class="action-row">
              <el-button type="primary" size="small" @click="exportGovernanceJson">JSON</el-button>
              <el-button type="primary" size="small" @click="exportGovernanceCsv">CSV</el-button>
            </div>
          </div>

          <div v-if="governanceData" class="metric-grid">
            <div v-for="stat in governanceStats" :key="stat.label" class="metric-tile" :class="stat.tone">
              <strong>{{ stat.value }}</strong>
              <span>{{ stat.label }}</span>
            </div>
          </div>
            <el-empty v-else description="暂无摘要状态" :image-size="56" />

          <div v-if="governanceData?.alerts?.length" class="alert-stack">
            <div v-for="alert in governanceData.alerts.slice(0, 3)" :key="alert.key" class="alert-item">
              <el-tag :type="alert.severity === 'high' ? 'danger' : 'warning'" size="small">{{ alert.type }}</el-tag>
              <span>{{ alert.message }}</span>
            </div>
          </div>
        </article>

        <article class="ops-card summary-watch-card">
          <div class="ops-card-head">
            <div>
              <h3>会话摘要操作</h3>
            </div>
            <div class="action-row">
              <el-button
                type="primary"
                :loading="rewriteReq.loading"
                :disabled="!selectedSummarySessionId || !summaryReady"
                @click="rewriteSummary"
              >
                立即重写
              </el-button>
            </div>
          </div>

          <div class="summary-selector-block">
            <label>会话</label>
            <el-select
              v-model="selectedSummarySessionId"
              class="field"
              placeholder="请选择会话"
              :disabled="summarySessions.length === 0"
              @change="() => loadSummaryDetail()"
            >
              <el-option
                v-for="session in summarySessions"
                :key="session.session_id"
                :label="session.session_id"
                :value="session.session_id"
              />
            </el-select>
            <div class="summary-footnote">
              <span>共 {{ summarySessions.length }} 个会话</span>
              <el-tag :type="summaryReady ? 'success' : 'warning'">
                摘要服务{{ summaryReady ? '就绪' : '未就绪' }}
              </el-tag>
            </div>
          </div>

          <AsyncState
            :loading="summaryDetailReq.loading"
            :error="summaryDetailReq.error"
            :empty="!selectedSummaryDetail?.summary"
            empty-text="未选择会话"
            class="summary-detail-state"
            @retry="loadSummaryDetail"
          >
            <div class="summary-detail-card">
              <div class="summary-detail-meta">
                <el-tag type="info">长度 {{ selectedSummaryDetail?.stats?.summary_length ?? 0 }}</el-tag>
                <el-tag type="success">重写 {{ selectedSummaryDetail?.stats?.rewrite_count ?? 0 }}</el-tag>
                <el-tag type="warning">质量 {{ selectedSummaryDetail?.stats?.quality_band || 'unknown' }}</el-tag>
              </div>
              <pre>{{ selectedSummaryDetail?.summary }}</pre>
            </div>
          </AsyncState>
        </article>
      </section>

      <section class="ops-card pet-ops-card">
        <div class="ops-card-head pet-head">
          <div>
            <h3>桌宠控制</h3>
          </div>
          <div class="pet-chip-row">
            <span v-for="chip in petChips" :key="chip.label" :class="chip.tone">{{ chip.label }}</span>
          </div>
        </div>

        <div class="pet-control-grid">
          <div class="control-block model-block">
            <label>当前模型</label>
            <el-select
              v-model="selectedModelId"
              class="field"
              placeholder="选择可用模型"
              :disabled="petCatalog.models.length === 0"
            >
              <el-option
                v-for="model in petCatalog.models"
                :key="model.id"
                :label="model.name"
                :value="model.id"
              />
            </el-select>
            <div class="row action-row compact-actions">
              <el-button type="primary" :disabled="!selectedModelId" @click="applyModel">
                应用模型
              </el-button>
            </div>
          </div>

          <div class="control-block scale-block">
            <label>缩放比例 · {{ scaleDraft.toFixed(2) }}</label>
            <el-slider
              v-model="scaleDraft"
              :min="0.12"
              :max="0.6"
              :step="0.01"
              @change="applyScale"
            />
          </div>

          <div class="control-block scale-block">
            <label>透明度 · {{ Math.round(opacityDraft * 100) }}%</label>
            <el-slider
              v-model="opacityDraft"
              :min="0.1"
              :max="1"
              :step="0.05"
              @change="applyOpacity"
            />
          </div>

          <div class="control-block">
            <label>允许拖动</label>
            <div class="row">
              <el-switch
                :model-value="petState.interactMode"
                active-text="允许"
                inactive-text="禁止"
                @change="setInteractMode"
              />
            </div>
          </div>

          <div class="control-block emphasis-block">
            <label>桌宠可见性</label>
            <div class="row">
              <el-switch
                :model-value="petState.visible"
                active-text="显示"
                inactive-text="隐藏"
                @change="setPetVisible"
              />
            </div>
          </div>

          <div class="control-block emphasis-block">
            <label>免打扰模式</label>
            <div class="row">
              <el-switch
                :model-value="petState.doNotDisturb"
                active-text="开启"
                inactive-text="关闭"
                @change="setDoNotDisturb"
              />
            </div>
          </div>

          <div class="control-block emphasis-block">
            <label>鼠标事件</label>
            <div class="row">
              <el-switch
                :model-value="petState.clickThrough"
                active-text="穿透"
                inactive-text="接收"
                @change="setClickThrough"
              />
            </div>
          </div>

          <div class="control-block emphasis-block">
            <label>位置锁定</label>
            <div class="row">
              <el-switch
                :model-value="petState.locked"
                active-text="锁定"
                inactive-text="解锁"
                @change="setLocked"
              />
            </div>
          </div>

          <div class="control-block dock-block">
            <label>位置 · {{ petState.placement === 'bottom-right' ? '右下角' : '自由定位' }}</label>
            <el-button type="primary" @click="dockBottomRight">定位到右下角</el-button>
          </div>
        </div>

        <div v-if="avatarCapabilities" class="pet-capability-summary" aria-label="桌宠能力">
          <div class="pet-capability-item">
            <strong>{{ avatarCapabilities.expressions.length }}</strong>
            <span>表情</span>
          </div>
          <div class="pet-capability-item">
            <strong>{{ avatarCapabilities.motions.length }}</strong>
            <span>动作</span>
          </div>
          <div class="pet-capability-item">
            <strong>{{ avatarCapabilities.actions.gaze ? '可用' : '无' }}</strong>
            <span>注视</span>
          </div>
          <div class="pet-capability-item">
            <strong>{{ avatarCapabilities.actions.viseme ? '可用' : '无' }}</strong>
            <span>口型同步</span>
          </div>
        </div>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, reactive, ref } from 'vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { useSystemOverview } from '../composables/useSystemOverview'
import { summaryClient } from '@/api/clients/summary-client'
import { useSettingsStore } from '@/state/settingsStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { inferLlmProviderPreset } from '@/domains/settings/llmProviders'
import { normalizeOpenAiBaseUrl } from '@/domains/settings/llmDiscovery'
import { useI18n } from '@/i18n'
import { openOnboarding } from '@/domains/onboarding/onboardingEvents'
import { systemClient } from '@/api/client'
import { petControl } from '@/utils/petControl'
import type {
  AvatarCapabilitySnapshot,
  ConnectorRegistrySnapshot,
  PlatformCapabilitySnapshot,
  PlatformCapabilityState,
  ProviderRegistrySnapshot,
  VoiceDiagnosticsSnapshot,
} from '@/../shared/agent'

const governanceData = ref<any>(null)
const governanceReq = reactive({ loading: false, error: '' })
const platformSnapshot = ref<PlatformCapabilitySnapshot | null>(null)
const platformRequest = reactive({ loading: false, error: '' })
const providerSnapshot = ref<ProviderRegistrySnapshot | null>(null)
const connectorSnapshot = ref<ConnectorRegistrySnapshot | null>(null)
const avatarCapabilities = ref<AvatarCapabilitySnapshot | null>(null)
const voiceSnapshot = ref<VoiceDiagnosticsSnapshot | null>(null)
const runtimeRequest = reactive({ loading: false, error: '' })
const voiceRequest = reactive({ loading: false, error: '' })
const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const { t } = useI18n()
const canonicalPath = (moduleId: string) => `/w/${workspaceStore.activeWorkspaceId}/${moduleId}`

const loadGovernance = async () => {
  governanceReq.loading = true
  try {
    governanceData.value = await summaryClient.getGovernanceReport(7)
  } catch (e: any) { governanceReq.error = e?.message || '加载失败' }
  finally { governanceReq.loading = false }
}

const loadPlatformMatrix = async () => {
  platformRequest.loading = true
  platformRequest.error = ''
  try {
    platformSnapshot.value = await systemClient.platforms()
  } catch (error: any) {
    platformRequest.error = error?.message || '平台能力读取失败'
  } finally {
    platformRequest.loading = false
  }
}

const loadRuntimeDependencies = async () => {
  runtimeRequest.loading = true
  runtimeRequest.error = ''
  try {
    const [providers, connectors] = await Promise.all([
      systemClient.providers(),
      systemClient.connectors(),
    ])
    providerSnapshot.value = providers
    connectorSnapshot.value = connectors
  } catch (error: any) {
    runtimeRequest.error = error?.message || '运行依赖读取失败'
  } finally {
    runtimeRequest.loading = false
  }
}

const loadVoiceDiagnostics = async () => {
  voiceRequest.loading = true
  voiceRequest.error = ''
  try {
    voiceSnapshot.value = await systemClient.voiceDiagnostics()
  } catch (error: any) {
    voiceRequest.error = error?.message || '语音体验数据读取失败'
  } finally {
    voiceRequest.loading = false
  }
}

const loadAvatarCapabilities = async () => {
  try {
    const result = await petControl.getAvatarCapabilities()
    avatarCapabilities.value = result.success ? result.capabilities : null
  } catch {
    // Capability reporting is optional; keep the rest of the pet controls usable.
    avatarCapabilities.value = null
  }
}

const voiceEvidenceLabel = computed(() => {
  const kinds = voiceSnapshot.value?.evidence_kinds ?? []
  if (!kinds.length) return '暂无'
  if (kinds.includes('real_device')) return '真实设备'
  return '本地 fixture'
})
const voiceP95Label = (stage: Record<string, unknown> | undefined): string => {
  const value = stage?.p95_ms
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)} ms` : '暂无'
}
const voiceRecommendations = computed(() => voiceSnapshot.value?.recommendations ?? [])

const platformRows = computed(() => platformSnapshot.value?.platforms ?? [])
const platformHostLabel = computed(() => {
  const host = platformSnapshot.value?.host
  if (!host) return ''
  return `${host.system} · ${host.displayServer}`
})
const platformCapabilityKeys = ['desktop', 'live2d_vrm', 'text_voice', 'native_actions'] as const
const platformStatusLabel = (status: PlatformCapabilityState) => ({
  available: '可用',
  needs_config: '需配置',
  experimental: '实验性',
  planned: '规划中',
  unsupported: '不支持',
}[status] || status)
const platformTagType = (status: PlatformCapabilityState) => ({
  available: 'success',
  needs_config: 'warning',
  experimental: 'warning',
  planned: 'info',
  unsupported: 'danger',
}[status] || 'info') as 'success' | 'warning' | 'info' | 'danger'

const runtimeRows = computed(() => {
  const providers = providerSnapshot.value?.providers ?? []
  const connectors = connectorSnapshot.value?.connectors ?? []
  const providerFailures = providers.filter((item) => item.configured && !item.healthy)
  const requiredProviders = providers.filter((item) => !item.optional)
  const requiredHealthy = requiredProviders.length === 0 || requiredProviders.every((item) => item.healthy)
  const runningConnectors = connectors.filter((item) => item.state === 'running')
  const connectorFailures = connectors.filter((item) => item.state === 'failure')
  return [
    {
      key: 'providers',
      label: '模型与语音服务',
      value: !providers.length ? '暂无 provider' : requiredHealthy ? `${providers.filter((item) => item.healthy).length}/${providers.length} 健康` : '有必需服务异常',
      desc: providerFailures[0]?.message || (providers.length ? 'LLM、ASR、TTS 和视觉 provider' : '尚未读取 provider 状态'),
      tone: !providers.length ? 'warning' : requiredHealthy ? 'online' : 'offline',
      to: canonicalPath('infrastructure'),
    },
    {
      key: 'connectors',
      label: '连接器',
      value: connectorFailures.length ? `${connectorFailures.length} 项故障` : `${runningConnectors.length} 项运行中`,
      desc: connectorFailures[0]?.lastError || '外部消息与工具连接器默认可停用',
      tone: connectorFailures.length ? 'warning' : 'online',
      to: canonicalPath('agent-governance'),
    },
    {
      key: 'pet',
      label: '桌宠资源',
      value: currentModel.value ? '已加载' : '待配置',
      desc: currentModel.value?.name || '选择 Live2D 或 VRM 模型',
      tone: currentModel.value ? 'online' : 'warning',
      to: canonicalPath('pet'),
    },
    {
      key: 'platform',
      label: '当前平台',
      value: platformHostLabel.value || '待检测',
      desc: '能力矩阵显示已验证和实验性边界',
      tone: platformSnapshot.value ? 'online' : 'warning',
      to: canonicalPath('deploy'),
    },
  ] as Array<{ key: string; label: string; value: string; desc: string; tone: CheckTone; to: string }>
})

const downloadBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

const exportGovernanceReport = async (format: 'json' | 'csv') => {
  governanceReq.loading = true
  governanceReq.error = ''
  try {
    const blob = await summaryClient.exportGovernanceReport(format, 7)
    downloadBlob(blob, `yuizaki-governance-7d.${format}`)
  } catch (e: any) {
    governanceReq.error = e?.message || '导出失败'
  } finally {
    governanceReq.loading = false
  }
}

const exportGovernanceJson = () => exportGovernanceReport('json')
const exportGovernanceCsv = () => exportGovernanceReport('csv')

const {
  systemStore,
  petState,
  petCatalog,
  scaleDraft,
  opacityDraft,
  selectedModelId,
  summarySessions,
  selectedSummaryDetail,
  summaryReady,
  readinessMessage,
  selectedSummarySessionId,
  summarySessionsReq,
  summaryDetailReq,
  readinessReq,
  rewriteReq,
  loadSummarySessions,
  loadSummaryDetail,
  refreshReadiness,
  rewriteSummary,
  syncPetData,
  applyModel,
  applyScale,
  applyOpacity,
  setPetVisible,
  setDoNotDisturb,
  setInteractMode,
  setClickThrough,
  setLocked,
  dockBottomRight
} = useSystemOverview()

const currentModel = computed(() => {
  const activeModelId = petState.value.modelId ?? petCatalog.value.activeModelId
  return (
    petCatalog.value.models.find((model: any) => model.id === activeModelId) ?? petCatalog.value.models[0] ?? null
  )
})

type CheckTone = 'online' | 'warning' | 'offline'
type ChainIssue = { key: string; title: string; desc: string; tone: CheckTone }

const llmProviderPreset = computed(() => inferLlmProviderPreset(settingsStore.state.llm.base_url))
const canAssessConfiguredServices = computed(() => systemStore.controlRunning && !settingsStore.state.error)
const isLocalLlmProvider = computed(() => ['ollama', 'lmstudio'].includes(llmProviderPreset.value))
const hasLlmEndpoint = computed(() => Boolean(normalizeOpenAiBaseUrl(settingsStore.state.llm.base_url)))
const hasLlmModel = computed(() => Boolean(settingsStore.state.llm.model.trim()))
const hasLlmKey = computed(() => Boolean(settingsStore.state.llm.api_key.trim()))
const llmReady = computed(() => {
  if (!canAssessConfiguredServices.value) return false
  if (!hasLlmEndpoint.value || !hasLlmModel.value) return false
  return isLocalLlmProvider.value || hasLlmKey.value
})
const llmStatusText = computed(() => {
  if (!canAssessConfiguredServices.value) return '待检测'
  if (!hasLlmEndpoint.value) return '缺少地址'
  if (!hasLlmModel.value) return '待选模型'
  if (!isLocalLlmProvider.value && !hasLlmKey.value) return '缺少 Key'
  return '已配置'
})

const asrReady = computed(() => {
  if (!canAssessConfiguredServices.value) return false
  const provider = settingsStore.state.asr.provider
  if (provider === 'disabled') return false
  if (provider === 'sensevoice-local' || provider === 'sherpa-onnx' || provider === 'sherpa-onnx-online') return true
  return Boolean(settingsStore.state.asr.base_url.trim())
})
const asrStatusText = computed(() => {
  if (!canAssessConfiguredServices.value) return '待检测'
  if (settingsStore.state.asr.provider === 'disabled') return '已关闭'
  return asrReady.value ? '已配置' : '缺少地址'
})

const ttsConfigured = computed(() => settingsStore.state.tts.provider === 'genie-tts')
const ttsReady = computed(() => Boolean(canAssessConfiguredServices.value && systemStore.pythonRunning && ttsConfigured.value))
const ttsStatusText = computed(() => {
  if (!canAssessConfiguredServices.value) return '待检测'
  if (!ttsConfigured.value) return '冲突'
  return systemStore.pythonRunning ? '已配置' : '待后端'
})
const promptModeLabel = computed(() => {
  const mode = workspaceStore.activeWorkspace.context.promptMode || 'auto'
  if (mode === 'work') return '工作'
  if (mode === 'daily') return '日常'
  return workspaceStore.activeWorkspaceId === 'default' ? '自动·日常' : '自动·工作'
})
const promptContextReady = computed(() => {
  const context = workspaceStore.activeWorkspace.context
  return Boolean(context.promptEngineering?.workPrompt && context.promptEngineering?.dailyPrompt)
})
const petLinkReady = computed(() => Boolean(systemStore.sioConnected && currentModel.value && petState.value.visible))
const chatChainReady = computed(() => Boolean(systemStore.pythonRunning && systemStore.sioConnected && llmReady.value))
const voiceChainReady = computed(() => Boolean(chatChainReady.value && asrReady.value && ttsReady.value))

const chainIssues = computed<ChainIssue[]>(() => {
  const issues: ChainIssue[] = []

  if (!systemStore.controlRunning) {
    issues.push({
      key: 'control',
      title: '控制服务未连接',
      desc: systemStore.controlHealthError || '设置、摘要和桌宠状态暂不可读',
      tone: 'offline',
    })
  }

  if (!systemStore.pythonRunning) {
    issues.push({
      key: 'python',
      title: 'Python 后端未连接',
      desc: systemStore.pythonHealthError || 'LLM、ASR、TTS 暂不可用',
      tone: 'offline',
    })
  }

  if (!systemStore.sioConnected) {
    issues.push({
      key: 'socket',
      title: 'Socket.IO 未连接',
      desc: '对话流、TTS 回传和桌宠联动会中断',
      tone: 'warning',
    })
  }

  if (canAssessConfiguredServices.value) {
    if (!hasLlmEndpoint.value) {
      issues.push({ key: 'llm-url', title: 'LLM 缺少地址', desc: '请在模型与语音中填写服务地址', tone: 'offline' })
    } else if (!hasLlmModel.value) {
      issues.push({ key: 'llm-model', title: 'LLM 未选择模型', desc: '请选择当前提供商的模型', tone: 'offline' })
    } else if (!isLocalLlmProvider.value && !hasLlmKey.value) {
      issues.push({ key: 'llm-key', title: 'LLM 缺少 Key', desc: 'Ollama 和 LM Studio 不需要 Key，其他提供商需要填写', tone: 'offline' })
    }

    if (settingsStore.state.asr.provider === 'disabled') {
      issues.push({ key: 'asr-disabled', title: 'ASR 已关闭', desc: '语音输入不会进入对话链路', tone: 'warning' })
    } else if (!asrReady.value) {
      issues.push({ key: 'asr-url', title: 'ASR 缺少地址', desc: '当前提供商需要填写服务地址', tone: 'warning' })
    }

    if (!ttsConfigured.value) {
      issues.push({ key: 'tts-provider', title: 'TTS 配置冲突', desc: '当前只保留 Genie TTS，请切回 Genie', tone: 'offline' })
    }

    if (readinessReq.error) {
      issues.push({ key: 'readiness-error', title: '摘要检测失败', desc: readinessReq.error, tone: 'warning' })
    } else if (readinessReq.data && !summaryReady.value) {
      issues.push({ key: 'summary-ready', title: '摘要服务未就绪', desc: readinessMessage || '请检查 LLM、TTS 和数据库', tone: 'warning' })
    }
  }

  if (!currentModel.value) {
    issues.push({ key: 'pet-model', title: '桌宠模型未加载', desc: '请选择 Live2D 或 VRM 模型', tone: 'warning' })
  } else if (!petState.value.visible) {
    issues.push({ key: 'pet-hidden', title: '桌宠已隐藏', desc: '桌宠动作和表情不会显示', tone: 'warning' })
  }

  return issues
})

const chainChecks = computed<Array<{ label: string; value: string; desc: string; tone: CheckTone }>>(() => [
  {
    label: '对话链路',
    value: chatChainReady.value ? '已配置' : '待连接',
    desc: chatChainReady.value ? settingsStore.state.llm.model : '后端 / Socket.IO / LLM',
    tone: chatChainReady.value ? 'online' : 'warning',
  },
  {
    label: '提示词',
    value: promptModeLabel.value,
    desc: promptContextReady.value ? '工作/日常提示词已配置' : '提示词未完整',
    tone: promptContextReady.value ? 'online' : 'offline',
  },
  {
    label: 'LLM',
    value: llmStatusText.value,
    desc: settingsStore.state.llm.model || llmProviderPreset.value.toUpperCase(),
    tone: llmReady.value ? 'online' : 'offline',
  },
  {
    label: 'ASR',
    value: asrStatusText.value,
    desc: settingsStore.state.asr.provider,
    tone: asrReady.value ? 'online' : 'warning',
  },
  {
    label: 'TTS',
    value: ttsStatusText.value,
    desc: ttsConfigured.value ? '仅使用 Genie TTS' : '请切回 Genie',
    tone: ttsReady.value ? 'online' : 'offline',
  },
  {
    label: '桌宠联动',
    value: petLinkReady.value ? '可用' : '待检查',
    desc: currentModel.value?.name || '未加载模型',
    tone: petLinkReady.value ? 'online' : 'warning',
  },
  {
    label: '语音对话',
    value: voiceChainReady.value ? '已配置' : '待配置',
    desc: 'ASR / LLM / TTS',
    tone: voiceChainReady.value ? 'online' : 'warning',
  },
])

const refreshChainStatus = async () => {
  await Promise.all([
    settingsStore.fetchSettings(),
    refreshReadiness(),
    syncPetData(false),
  ])
}

const overviewRefreshLoading = computed(() => (
  settingsStore.state.loading
  || readinessReq.loading
  || summarySessionsReq.loading
  || governanceReq.loading
  || platformRequest.loading
  || runtimeRequest.loading
  || voiceRequest.loading
))

const refreshOverview = async () => {
  await Promise.all([
    refreshChainStatus(),
    loadSummarySessions(),
    loadGovernance(),
    loadPlatformMatrix(),
    loadRuntimeDependencies(),
    loadVoiceDiagnostics(),
    loadAvatarCapabilities(),
  ])
}

const connectionCards = computed(() => [
  {
    label: 'Control Server',
    value: systemStore.controlRunning ? 'OK' : 'WAIT',
    desc: systemStore.controlRunning ? 'Control HTTP ready' : systemStore.controlHealthError || 'Checking control service',
    tone: systemStore.controlRunning ? 'online' : 'offline',
  },
  {
    label: 'Python 后端',
    value: systemStore.pythonRunning ? '在线' : '离线',
    desc: systemStore.pythonRunning ? 'FastAPI 服务可达' : systemStore.pythonHealthError || '等待后端健康检查',
    tone: systemStore.pythonRunning ? 'online' : 'offline',
  },
  {
    label: 'Socket.IO',
    value: systemStore.sioConnected ? '已连接' : '等待中',
    desc: systemStore.sioConnected ? '双向运行时通道正常' : '等待 Socket.IO 握手',
    tone: systemStore.sioConnected ? 'online' : 'warning',
  },
])

const governanceStats = computed(() => {
  const summary = governanceData.value?.summary ?? {}
  return [
    { label: '审计总数', value: summary.audit_total || 0, tone: 'neutral' },
    { label: '成功率', value: `${summary.ok_rate || 0}%`, tone: 'ok' },
    { label: '跳过率', value: `${summary.guard_skip_rate || 0}%`, tone: 'warn' },
    { label: '回退率', value: `${summary.fallback_rate || 0}%`, tone: 'err' },
  ]
})

const petChips = computed(() => [
  { label: currentModel.value?.name ?? '未发现模型', tone: 'ok' },
  { label: petState.value.ready ? '已加载' : '加载中', tone: petState.value.ready ? 'ok' : 'warn' },
  { label: petState.value.interactMode ? '可拖动' : '鼠标穿透', tone: petState.value.interactMode ? 'warn' : 'info' },
  { label: petState.value.clickThrough ? '完全穿透' : '可交互', tone: petState.value.clickThrough ? 'ok' : 'warn' },
  { label: petState.value.locked ? '位置锁定' : '位置可调', tone: petState.value.locked ? 'err' : 'info' },
])

let syncTimer: number | null = null
let panelActive = true
const PET_STATUS_REFRESH_INTERVAL_MS = 60_000

const pageIsVisible = () => document.visibilityState !== 'hidden'

const stopPetSync = () => {
  if (syncTimer !== null) {
    window.clearInterval(syncTimer)
    syncTimer = null
  }
}

const startPetSync = (refresh = false) => {
  if (!panelActive || !pageIsVisible() || syncTimer !== null) return
  if (refresh) void syncPetData(false)
  syncTimer = window.setInterval(() => {
    if (panelActive && pageIsVisible()) void syncPetData(true, false)
  }, PET_STATUS_REFRESH_INTERVAL_MS)
}

const handleVisibilityChange = () => {
  if (pageIsVisible()) {
    startPetSync(true)
  } else {
    stopPetSync()
  }
}

onMounted(() => {
  void refreshOverview()

  document.addEventListener('visibilitychange', handleVisibilityChange)
  startPetSync()
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  stopPetSync()
})

onActivated(() => {
  panelActive = true
  startPetSync(true)
})

onDeactivated(() => {
  panelActive = false
  stopPetSync()
})
</script>

<style scoped>
.overview-console {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ops-hero {
  display: block;
}

.ops-status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.ops-status-card,
.ops-card,
.control-block {
  border: 1px solid var(--yui-panel-outline, var(--yui-border));
  background: var(--yui-panel-surface, var(--yui-surface-raised));
  background-clip: padding-box;
  box-shadow: var(--yui-panel-shadow, var(--yui-shadow-card));
}

.ops-status-card {
  min-height: 88px;
  border-radius: var(--yui-radius-card);
  padding: 16px;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.ops-status-card:hover,
.ops-card:hover,
.control-block:hover {
  border-color: var(--yui-panel-outline-strong, var(--yui-border-strong));
  box-shadow: var(--yui-shadow-hover);
}

.ops-card:focus-within,
.control-block:focus-within {
  border-color: var(--yui-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--yui-accent) 16%, transparent), var(--yui-shadow-hover);
}

.ops-status-card span,
.ops-status-card small {
  display: block;
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 700;
}

.ops-status-card strong {
  display: block;
  margin: 10px 0 0;
  color: var(--yui-text);
  font-size: 22px;
  font-weight: 950;
  letter-spacing: 0;
}

.ops-status-card.online { background: var(--yui-success-soft); }
.ops-status-card.warning { background: var(--yui-warning-soft); }
.ops-status-card.offline { background: var(--yui-danger-soft); }

.ops-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
  gap: 16px;
}

.chain-card {
  padding: 18px;
}

.voice-quality-card {
  padding: 18px;
}

.voice-quality-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.voice-quality-metric {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-control);
  background: var(--yui-surface);
}

.voice-quality-metric strong,
.voice-quality-metric span {
  display: block;
}

.voice-quality-metric strong {
  overflow: hidden;
  color: var(--yui-text);
  font-size: 17px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.voice-quality-metric span {
  margin-top: 4px;
  color: var(--yui-muted);
  font-size: 12px;
}

.voice-quality-notes {
  display: grid;
  gap: 4px;
  margin-top: 10px;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
}

.pet-capability-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.pet-capability-item {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-control);
  background: var(--yui-surface);
}

.pet-capability-item strong,
.pet-capability-item span {
  display: block;
}

.pet-capability-item strong {
  color: var(--yui-text);
  font-size: 15px;
}

.pet-capability-item span {
  margin-top: 3px;
  color: var(--yui-muted);
  font-size: 12px;
}

.chain-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
}

.chain-check {
  display: flex;
  min-height: 72px;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  gap: 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 12px;
}

.chain-check strong,
.chain-check span,
.chain-check small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chain-check strong {
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 900;
}

.chain-check span {
  margin-top: 6px;
  color: var(--yui-text);
  font-size: 18px;
  font-weight: 950;
}

.chain-check small {
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 700;
}

.chain-check.online { background: var(--yui-success-soft); }
.chain-check.warning { background: var(--yui-warning-soft); }
.chain-check.offline { background: var(--yui-danger-soft); }

.chain-issues {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.chain-issue {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 10px 12px;
}

.chain-issue strong,
.chain-issue span {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chain-issue strong {
  color: var(--yui-text);
  font-size: 12px;
  font-weight: 900;
}

.chain-issue span {
  margin-top: 4px;
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 650;
  overflow: visible;
  overflow-wrap: anywhere;
  text-overflow: clip;
  white-space: normal;
}

.chain-issue.online { background: var(--yui-success-soft); }
.chain-issue.warning { background: var(--yui-warning-soft); }
.chain-issue.offline { background: var(--yui-danger-soft); }

.ops-card {
  border-radius: var(--yui-radius-card);
  padding: 20px;
}

.ops-card-head,
.pet-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 16px;
}

.ops-card-head h3 {
  margin: 4px 0 4px;
  color: var(--yui-text);
  font-size: 16px;
  font-weight: 900;
}

.action-row,
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.metric-tile {
  min-height: 92px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  padding: 14px;
  text-align: center;
}

.metric-tile.neutral { background: var(--yui-surface-muted); }
.metric-tile.ok { background: var(--yui-success-soft); }
.metric-tile.warn { background: var(--yui-warning-soft); }
.metric-tile.err { background: var(--yui-danger-soft); }

.metric-tile strong {
  display: block;
  color: var(--yui-text);
  font-size: 24px;
  font-weight: 950;
  letter-spacing: 0;
}

.metric-tile span {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.alert-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 14px;
}

.alert-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.alert-item span:last-child {
  color: #475569;
  font-size: 12px;
}

.summary-selector-block {
  padding: 16px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.summary-selector-block label,
.control-block label {
  display: block;
  margin-bottom: 10px;
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 800;
}

.summary-footnote {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 12px;
  color: var(--yui-muted);
  font-size: 12px;
}

.summary-detail-state {
  margin-top: 12px;
}

.summary-detail-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 12px;
}

.summary-detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.summary-detail-card pre {
  max-height: 160px;
  overflow: auto;
  margin: 0;
  color: var(--yui-text);
  font-family: var(--yui-font-sans);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.pet-ops-card {
  overflow: hidden;
  background: var(--yui-panel-surface, var(--yui-surface-raised));
}

.pet-chip-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  max-width: 520px;
}

.pet-chip-row span {
  border-radius: 999px;
  border: 1px solid transparent;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 800;
}

.pet-chip-row .ok { background: #ecfdf5; color: #047857; }
.pet-chip-row .warn { background: #fffbeb; color: #b45309; }
.pet-chip-row .info { background: #eff6ff; color: #2563eb; }
.pet-chip-row .err { background: #fef2f2; color: #dc2626; }

.pet-control-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.control-block {
  min-height: 150px;
  border-radius: var(--yui-radius-card);
  padding: 16px;
}

.model-block,
.scale-block {
  grid-column: span 1;
}

.emphasis-block {
  border-color: rgba(37, 99, 235, 0.28);
  background: var(--yui-accent-soft);
}

.dock-block {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.field {
  width: 100%;
}

.compact-actions {
  margin-top: 12px;
}

.canonical-links {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-bottom: 14px;
  color: var(--yui-muted);
  font-size: 12px;
}

.canonical-links span {
  font-weight: 700;
}

.canonical-links a {
  color: var(--yui-accent);
  font-weight: 700;
  text-underline-offset: 3px;
}

.canonical-links a:focus-visible {
  border-radius: 4px;
  outline: 3px solid var(--yui-accent);
  outline-offset: 2px;
}

.ops-card-head > div:first-child > span {
  color: var(--yui-muted);
  font-size: 12px;
}

.runtime-checklist {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.runtime-check {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-left: 3px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  padding: 12px;
  background: var(--yui-surface-muted);
}

.runtime-check.online { border-left-color: var(--yui-success); }
.runtime-check.warning { border-left-color: var(--yui-warning); }
.runtime-check.offline { border-left-color: var(--yui-danger); }

.runtime-check-copy {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.runtime-check-copy strong,
.runtime-check-copy span,
.runtime-check-copy small {
  overflow-wrap: anywhere;
}

.runtime-check-copy strong { color: var(--yui-text); font-size: 13px; }
.runtime-check-copy span { color: var(--yui-text); font-size: 12px; font-weight: 700; }
.runtime-check-copy small { color: var(--yui-muted); font-size: 11px; }

.runtime-check-link {
  flex: 0 0 auto;
  color: var(--yui-accent);
  font-size: 12px;
  font-weight: 700;
  text-underline-offset: 3px;
}

.platform-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.platform-table {
  width: 100%;
  min-width: 820px;
  border-collapse: collapse;
  table-layout: fixed;
}

.platform-table th,
.platform-table td {
  border-bottom: 1px solid var(--yui-border);
  padding: 12px;
  color: var(--yui-text);
  text-align: left;
  vertical-align: top;
}

.platform-table thead th {
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 800;
}

.platform-table thead th:first-child,
.platform-table tbody th {
  width: 132px;
}

.platform-table tbody th strong,
.platform-table tbody th small,
.platform-detail {
  display: block;
}

.platform-table tbody th small {
  margin-top: 5px;
  color: var(--yui-accent);
  font-size: 11px;
}

.platform-table tbody tr.host {
  background: var(--yui-accent-soft);
}

.platform-detail {
  margin-top: 7px;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

@media (max-width: 1180px) {
  .ops-hero,
  .ops-grid {
    grid-template-columns: 1fr;
  }

  .ops-status-grid,
  .pet-control-grid,
  .chain-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .ops-hero,
  .ops-card {
    padding: 18px;
  }

  .ops-status-grid,
  .metric-grid,
  .pet-control-grid,
  .chain-grid,
  .runtime-checklist,
  .voice-quality-grid,
  .pet-capability-summary {
    grid-template-columns: 1fr;
  }

  .ops-card-head,
  .pet-head,
  .summary-footnote {
    align-items: flex-start;
    flex-direction: column;
  }

  .platform-table-wrap {
    overflow: visible;
  }

  .platform-table,
  .platform-table tbody,
  .platform-table tr,
  .platform-table th,
  .platform-table td {
    display: block;
    width: 100%;
  }

  .platform-table {
    min-width: 0;
  }

  .platform-table thead {
    display: none;
  }

  .platform-table tbody tr {
    margin-bottom: 12px;
    border: 1px solid var(--yui-border);
    border-radius: var(--yui-radius-card);
    background: var(--yui-surface-muted);
  }

  .platform-table tbody tr.host {
    background: var(--yui-accent-soft);
  }

  .platform-table tbody th,
  .platform-table tbody td {
    border-bottom: 1px solid var(--yui-border);
  }

  .platform-table tbody td:last-child {
    border-bottom: 0;
  }
}
</style>
