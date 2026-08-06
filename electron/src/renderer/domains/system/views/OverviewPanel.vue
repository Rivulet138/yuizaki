<template>
  <PanelShell title="运行总览" tone="admin">
    <div class="overview-console">
      <section class="ops-hero">
        <div class="ops-status-grid">
          <article v-for="card in connectionCards" :key="card.label" class="ops-status-card" :class="card.tone">
            <span>{{ card.label }}</span>
            <strong>{{ card.value }}</strong>
            <small>{{ card.desc }}</small>
          </article>
        </div>
      </section>
      <nav class="canonical-links" :aria-label="t('canonical.system.aria')">
        <span>{{ t('canonical.system.label') }}</span>
        <router-link :to="canonicalPath('infrastructure')">{{ t('canonical.system.diagnostics') }}</router-link>
        <router-link :to="canonicalPath('deploy')">{{ t('canonical.system.legacyRuntime') }}</router-link>
      </nav>

      <section class="ops-card chain-card">
        <div class="ops-card-head">
          <div>
            <h3>链路自检</h3>
          </div>
          <div class="action-row">
            <el-button plain :loading="settingsStore.state.loading || readinessReq.loading" @click="refreshChainStatus">刷新</el-button>
          </div>
        </div>
        <div class="chain-grid">
          <article v-for="item in chainChecks" :key="item.label" class="chain-check" :class="item.tone">
            <div>
              <strong>{{ item.label }}</strong>
              <span>{{ item.value }}</span>
            </div>
            <small>{{ item.desc }}</small>
          </article>
        </div>
        <div v-if="chainIssues.length" class="chain-issues" aria-label="链路问题">
          <div v-for="issue in chainIssues" :key="issue.key" class="chain-issue" :class="issue.tone">
            <strong>{{ issue.title }}</strong>
            <span>{{ issue.desc }}</span>
          </div>
        </div>
      </section>

      <section class="ops-grid">
        <article class="ops-card governance-card">
          <div class="ops-card-head">
            <div>
              <h3>摘要状态</h3>
            </div>
            <div class="action-row">
              <el-button plain :loading="governanceReq.loading" @click="loadGovernance">刷新审计</el-button>
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
              <h3>会话摘要</h3>
            </div>
            <div class="action-row">
              <el-button plain :loading="summarySessionsReq.loading" @click="loadSummarySessions">刷新</el-button>
              <el-button
                type="primary"
                :loading="rewriteReq.loading"
                :disabled="!selectedSummarySessionId || !summaryReady"
                @click="rewriteSummary"
              >
                重写摘要
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
            <label>模型</label>
            <el-select
              v-model="selectedModelId"
              class="field"
              placeholder="选择 Live2D / VRM 模型"
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
                切换模型
              </el-button>
              <el-button plain @click="syncPetData(false)">刷新清单</el-button>
            </div>
          </div>

          <div class="control-block scale-block">
            <label>大小 · {{ scaleDraft.toFixed(2) }}</label>
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
            <label>拖动模式</label>
            <div class="row">
              <el-switch
                :model-value="petState.interactMode"
                active-text="开启"
                inactive-text="关闭"
                @change="setInteractMode"
              />
              <el-button plain @click="syncPetData(false)">刷新状态</el-button>
            </div>
          </div>

          <div class="control-block emphasis-block">
            <label>显示状态</label>
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
            <label>免打扰</label>
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
            <label>鼠标穿透</label>
            <div class="row">
              <el-switch
                :model-value="petState.clickThrough"
                active-text="穿透"
                inactive-text="交互"
                @change="setClickThrough"
              />
            </div>
          </div>

          <div class="control-block emphasis-block">
            <label>锁定位置</label>
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
            <label>位置 · {{ petState.placement === 'bottom-right' ? '右下角' : '自由' }}</label>
            <el-button type="primary" @click="dockBottomRight">贴到右下角</el-button>
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

const governanceData = ref<any>(null)
const governanceReq = reactive({ loading: false, error: '' })
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
  loadHeartbeat,
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
    if (panelActive && pageIsVisible()) void syncPetData(true)
  }, 5000)
}

const handleVisibilityChange = () => {
  if (pageIsVisible()) {
    startPetSync(true)
  } else {
    stopPetSync()
  }
}

onMounted(() => {
  if (pageIsVisible()) void syncPetData(false)
  void Promise.all([
    settingsStore.fetchSettings(),
    loadSummarySessions(),
    refreshReadiness(),
    loadHeartbeat(),
    loadGovernance(),
  ])

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
  border: 1px solid var(--yui-border);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
}

.ops-status-card {
  min-height: 116px;
  border-radius: var(--yui-radius-card);
  padding: 16px;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.ops-status-card:hover,
.ops-card:hover,
.control-block:hover {
  border-color: var(--yui-border-strong);
  box-shadow: var(--yui-shadow-hover);
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
  margin: 12px 0 4px;
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

.chain-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
}

.chain-check {
  display: flex;
  min-height: 96px;
  min-width: 0;
  flex-direction: column;
  justify-content: space-between;
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
  background: var(--yui-surface-raised);
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
  .chain-grid {
    grid-template-columns: 1fr;
  }

  .ops-card-head,
  .pet-head,
  .summary-footnote {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
