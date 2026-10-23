<template>
  <PanelShell :title="t('overview.title')" tone="admin">
    <template #actions>
      <el-button plain :loading="overviewRefreshLoading" @click="refreshOverview">{{ t('overview.refresh') }}</el-button>
    </template>
    <div class="overview-console">
      <nav class="overview-view-nav" :aria-label="t('overview.viewNavAria')" role="tablist">
        <button
          v-for="view in overviewViews"
          :key="view.id"
          type="button"
          role="tab"
          class="overview-view-button"
          :class="{ active: activeOverviewView === view.id }"
          :aria-selected="activeOverviewView === view.id"
          @click="activeOverviewView = view.id"
        >
          {{ view.label }}
        </button>
      </nav>

      <section v-show="activeOverviewView === 'status'" class="ops-card runtime-readiness-card" :aria-label="t('overview.readinessAria')">
        <div class="ops-card-head">
          <div>
            <h3>{{ runtimeActionItems.length ? t('overview.readinessPending', { count: runtimeActionItems.length }) : t('overview.readinessReady') }}</h3>
          </div>
        </div>
        <el-alert
          v-if="runtimeRequest.error"
          class="runtime-readiness-alert"
          type="warning"
          :closable="false"
          show-icon
          :title="runtimeRequest.error"
        />
        <div v-if="runtimeActionItems.length" class="runtime-action-list">
          <article v-for="item in runtimeActionItems" :key="item.key" class="runtime-action-item" :class="item.tone">
            <span class="runtime-action-dot" aria-hidden="true"></span>
            <div>
              <strong>{{ item.title }}</strong>
              <span>{{ item.desc }}</span>
            </div>
            <router-link :to="item.to">{{ item.actionLabel }}</router-link>
          </article>
        </div>
        <div v-else class="runtime-ready-state">
          <strong>{{ t('overview.readinessCanChat') }}</strong>
        </div>
        <div class="runtime-chain" :aria-label="t('overview.chainAria')">
          <span v-for="item in chainChecks" :key="item.label" class="runtime-chain-item" :class="item.tone" :title="item.desc">
            <i aria-hidden="true"></i>
            <strong>{{ item.label }}</strong>
            <small>{{ item.value }}</small>
          </span>
        </div>
      </section>

      <section v-show="activeOverviewView === 'voice'" class="ops-card voice-quality-card" :aria-label="t('overview.voice.aria')">
        <div class="ops-card-head">
          <div>
            <h3>{{ t('overview.voice.title') }}</h3>
          </div>
        </div>
        <AsyncState :loading="voiceRequest.loading" :error="voiceRequest.error" :show-retry="false">
          <div v-if="voiceSnapshot" class="voice-quality-grid">
            <div class="voice-quality-metric">
              <strong>{{ voiceSnapshot.sample_count > 0 ? t('overview.voice.recorded') : t('overview.voice.noData') }}</strong>
              <span>{{ t('overview.voice.metric.response') }}</span>
            </div>
            <div class="voice-quality-metric">
              <strong>{{ voiceComfortLabel }}</strong>
              <span>{{ t('overview.voice.metric.comfort') }}</span>
            </div>
            <div class="voice-quality-metric">
              <strong>{{ voiceQualificationLabel }}</strong>
              <span>{{ t('overview.voice.metric.device') }}</span>
            </div>
          </div>
          <details v-if="voiceSnapshot" class="voice-diagnostics-details">
            <summary>{{ t('overview.voice.details') }}</summary>
            <div class="voice-quality-grid">
              <div class="voice-quality-metric">
                <strong>{{ voiceEvidenceLabel }}</strong>
                <span>{{ t('overview.voice.metric.evidence') }}</span>
              </div>
              <div class="voice-quality-metric">
                <strong>{{ voiceSnapshot.sample_count }}</strong>
                <span>{{ t('overview.voice.metric.samples') }}</span>
              </div>
              <div class="voice-quality-metric">
                <strong>{{ voiceP95Label(voiceSnapshot.stages.first_audio) }}</strong>
                <span>{{ t('overview.voice.metric.firstAudio') }}</span>
              </div>
              <div class="voice-quality-metric">
                <strong>{{ voiceP95Label(voiceSnapshot.stages.interruption) }}</strong>
                <span>{{ t('overview.voice.metric.interruption') }}</span>
              </div>
            </div>
          </details>
          <div v-if="voiceComfortSummary" class="voice-quality-notes">
            <span>{{ voiceComfortSummary }}</span>
          </div>
          <div v-if="voiceComfortSignalSummary" class="voice-quality-notes">
            <span>{{ voiceComfortSignalSummary }}</span>
          </div>
          <div v-if="voiceQualificationSummary" class="voice-quality-notes">
            <span>{{ voiceQualificationSummary }}</span>
          </div>
          <div v-if="voiceRecommendations.length" class="voice-quality-notes">
            <span v-for="recommendation in voiceRecommendations.slice(0, 2)" :key="recommendation">{{ recommendation }}</span>
          </div>
          <el-empty v-if="voiceSnapshot && voiceSnapshot.sample_count === 0" :description="t('overview.voice.empty')" :image-size="48" />
        </AsyncState>
      </section>

      <section v-show="activeOverviewView === 'platform'" class="ops-card platform-card" :aria-label="t('overview.platform.aria')">
        <div class="ops-card-head">
          <div>
            <h3>{{ t('overview.platform.title') }}</h3>
            <span v-if="platformSnapshot">{{ t('overview.platform.host', { host: platformHostLabel }) }}</span>
          </div>
        </div>
        <AsyncState :loading="platformRequest.loading" :error="platformRequest.error" :show-retry="false">
          <div v-if="platformRows.length" class="platform-table-wrap">
            <table class="platform-table">
              <thead>
                <tr>
                  <th>{{ t('overview.platform.columnPlatform') }}</th>
                  <th>{{ t('overview.platform.columnDesktop') }}</th>
                  <th>Live2D / VRM</th>
                  <th>{{ t('overview.platform.columnTextVoice') }}</th>
                  <th>{{ t('overview.platform.columnActions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in platformRows" :key="row.id" :class="{ host: row.host }">
                  <th scope="row"><strong>{{ row.name }}</strong><small v-if="row.host">{{ t('overview.platform.currentHost') }}</small></th>
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
          <el-empty v-else :description="t('overview.platform.empty')" :image-size="56" />
        </AsyncState>
      </section>

      <section v-show="activeOverviewView === 'runtime'" class="ops-grid">
        <article class="ops-card context-card" :aria-label="t('overview.activeApp.title')">
          <div class="ops-card-head">
            <div>
              <h3>{{ t('overview.activeApp.title') }}</h3>
              <span>{{ t('overview.activeApp.foreground') }}</span>
            </div>
            <el-tag :type="activeApplication ? 'success' : 'info'">
              {{ activeApplication ? t('overview.status.read') : t('overview.status.unavailable') }}
            </el-tag>
          </div>
          <div v-if="activeApplicationRequest.loading" class="compact-status">{{ t('overview.status.reading') }}</div>
          <dl v-else-if="activeApplication" class="context-list">
            <div><dt>{{ t('overview.activeApp.process') }}</dt><dd>{{ activeApplication.name }}</dd></div>
            <div><dt>{{ t('overview.activeApp.window') }}</dt><dd :title="activeApplication.title">{{ activeApplication.title || t('overview.activeApp.untitled') }}</dd></div>
            <div><dt>{{ t('overview.activeApp.pid') }}</dt><dd>{{ activeApplication.process_id }}</dd></div>
          </dl>
          <div v-else class="compact-status">{{ activeApplicationRequest.error || t('overview.activeApp.browserUnavailable') }}</div>
        </article>

        <article class="ops-card orchestration-card" :aria-label="t('overview.orchestration.title')">
          <div class="ops-card-head">
            <div>
              <h3>{{ t('overview.orchestration.title') }}</h3>
            </div>
            <el-tag :type="orchestrationSnapshot ? 'success' : 'info'">
              {{ orchestrationSnapshot ? t('overview.status.read') : t('overview.status.unavailable') }}
            </el-tag>
          </div>
          <div v-if="orchestrationRequest.loading" class="compact-status">{{ t('overview.status.reading') }}</div>
          <template v-else-if="orchestrationSnapshot">
            <div class="orchestration-counts">
              <span>{{ t('overview.orchestration.agents') }} <strong>{{ orchestrationSnapshot.summary?.agents ?? orchestrationSnapshot.agents?.length ?? 0 }}</strong></span>
              <span>{{ t('overview.orchestration.skills') }} <strong>{{ orchestrationSnapshot.summary?.skills ?? orchestrationSnapshot.skills.length }}</strong></span>
              <span>{{ t('overview.orchestration.commands') }} <strong>{{ orchestrationSnapshot.summary?.commands ?? orchestrationSnapshot.commands.length }}</strong></span>
              <span>{{ t('overview.orchestration.hooks') }} <strong>{{ orchestrationSnapshot.summary?.hooks ?? orchestrationSnapshot.hooks.length }}</strong></span>
            </div>
            <details class="orchestration-details">
              <summary>{{ t('overview.orchestration.details') }}</summary>
              <ul>
                <li v-for="item in orchestrationEntries" :key="`${item.kind}:${item.id}`">
                  <strong>{{ item.name }}</strong><span>{{ item.kind }}</span>
                </li>
              </ul>
            </details>
          </template>
          <div v-else class="compact-status">{{ orchestrationRequest.error || t('overview.orchestration.empty') }}</div>
        </article>
      </section>

      <section v-show="activeOverviewView === 'pet'" class="ops-card pet-ops-card">
        <div class="ops-card-head pet-head">
          <div>
            <h3>{{ t('overview.pet.title') }}</h3>
          </div>
          <div class="pet-chip-row">
            <span v-for="chip in petChips" :key="chip.label" :class="chip.tone">{{ chip.label }}</span>
          </div>
        </div>

        <div class="pet-control-grid">
          <div class="control-block model-block">
            <label>{{ t('overview.pet.model') }}</label>
            <el-select
              v-model="selectedModelId"
              class="field"
              :placeholder="t('overview.pet.modelPlaceholder')"
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
                {{ t('overview.pet.applyModel') }}
              </el-button>
            </div>
          </div>

          <div class="control-block scale-block">
            <label>{{ t('overview.pet.scale', { value: scaleDraft.toFixed(2) }) }}</label>
            <el-slider
              v-model="scaleDraft"
              :min="0.12"
              :max="0.6"
              :step="0.01"
              @change="applyScale"
            />
          </div>

          <div class="control-block scale-block">
            <label>{{ t('overview.pet.opacity', { value: Math.round(opacityDraft * 100) }) }}</label>
            <el-slider
              v-model="opacityDraft"
              :min="0.1"
              :max="1"
              :step="0.05"
              @change="applyOpacity"
            />
          </div>

          <div class="control-block">
            <label>{{ t('overview.pet.allowDrag') }}</label>
            <div class="row">
              <el-switch
                :model-value="petState.interactMode"
                :active-text="t('overview.pet.toggle.allow')"
                :inactive-text="t('overview.pet.toggle.forbid')"
                @change="setInteractMode"
              />
            </div>
          </div>

          <div class="control-block emphasis-block">
            <label>{{ t('overview.pet.visibility') }}</label>
            <div class="row">
              <el-switch
                :model-value="petState.visible"
                :active-text="t('overview.pet.toggle.show')"
                :inactive-text="t('overview.pet.toggle.hide')"
                @change="setPetVisible"
              />
            </div>
          </div>

          <div class="control-block emphasis-block">
            <label>{{ t('overview.pet.dnd') }}</label>
            <div class="row">
              <el-switch
                :model-value="petState.doNotDisturb"
                :active-text="t('overview.pet.toggle.on')"
                :inactive-text="t('overview.pet.toggle.off')"
                @change="setDoNotDisturb"
              />
            </div>
          </div>

          <div class="control-block emphasis-block">
            <label>{{ t('overview.pet.mouseEvents') }}</label>
            <div class="row">
              <el-switch
                :model-value="petState.clickThrough"
                :active-text="t('overview.pet.toggle.clickThrough')"
                :inactive-text="t('overview.pet.toggle.receive')"
                @change="setClickThrough"
              />
            </div>
          </div>

          <div class="control-block emphasis-block">
            <label>{{ t('overview.pet.positionLock') }}</label>
            <div class="row">
              <el-switch
                :model-value="petState.locked"
                :active-text="t('overview.pet.toggle.lock')"
                :inactive-text="t('overview.pet.toggle.unlock')"
                @change="setLocked"
              />
            </div>
          </div>

          <div class="control-block dock-block">
            <label>{{ t('overview.pet.position', { value: petState.placement === 'bottom-right' ? t('overview.pet.placement.bottomRight') : t('overview.pet.placement.free') }) }}</label>
            <el-button type="primary" @click="dockBottomRight">{{ t('overview.pet.dock') }}</el-button>
          </div>
        </div>

        <div v-if="avatarCapabilities" class="pet-capability-summary" :aria-label="t('overview.pet.capabilityAria')">
          <div class="pet-capability-item">
            <strong>{{ avatarCapabilities.expressions.length }}</strong>
            <span>{{ t('overview.pet.expressions') }}</span>
          </div>
          <div class="pet-capability-item">
            <strong>{{ avatarCapabilities.motions.length }}</strong>
            <span>{{ t('overview.pet.motions') }}</span>
          </div>
          <div class="pet-capability-item">
            <strong>{{ avatarCapabilities.actions.gaze ? t('overview.status.available') : t('overview.pet.capability.none') }}</strong>
            <span>{{ t('overview.pet.gaze') }}</span>
          </div>
          <div class="pet-capability-item">
            <strong>{{ avatarCapabilities.actions.viseme ? t('overview.status.available') : t('overview.pet.capability.none') }}</strong>
            <span>{{ t('overview.pet.viseme') }}</span>
          </div>
        </div>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { ElEmpty } from 'element-plus'
import 'element-plus/es/components/empty/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElAlert } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import { ElSlider, ElSwitch } from 'element-plus'
import 'element-plus/es/components/slider/style/css'
import 'element-plus/es/components/switch/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, reactive, ref } from 'vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { t } from '@/i18n'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { useSystemOverview } from '../composables/useSystemOverview'
import { useSettingsStore } from '@/state/settingsStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { inferLlmProviderPreset } from '@/domains/settings/llmProviders'
import { normalizeOpenAiBaseUrl } from '@/domains/settings/llmDiscovery'
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
import type { OrchestrationSnapshot } from '@/../shared/orchestration'

type ActiveApplicationSnapshot = {
  ok: boolean
  name: string
  title: string
  process_id: number
}

type OverviewView = 'status' | 'voice' | 'platform' | 'runtime' | 'pet'

const overviewViews = computed<Array<{ id: OverviewView; label: string }>>(() => [
  { id: 'status', label: t('overview.view.status') },
  { id: 'voice', label: t('overview.view.voice') },
  { id: 'platform', label: t('overview.view.platform') },
  { id: 'runtime', label: t('overview.view.runtime') },
  { id: 'pet', label: t('overview.view.pet') },
])
const activeOverviewView = ref<OverviewView>('status')

const platformSnapshot = ref<PlatformCapabilitySnapshot | null>(null)
const platformRequest = reactive({ loading: false, error: '' })
const providerSnapshot = ref<ProviderRegistrySnapshot | null>(null)
const connectorSnapshot = ref<ConnectorRegistrySnapshot | null>(null)
const avatarCapabilities = ref<AvatarCapabilitySnapshot | null>(null)
const voiceSnapshot = ref<VoiceDiagnosticsSnapshot | null>(null)
const runtimeRequest = reactive({ loading: false, error: '' })
const voiceRequest = reactive({ loading: false, error: '' })
const activeApplication = ref<ActiveApplicationSnapshot | null>(null)
const activeApplicationRequest = reactive({ loading: false, error: '' })
const orchestrationSnapshot = ref<OrchestrationSnapshot | null>(null)
const orchestrationRequest = reactive({ loading: false, error: '' })
const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const canonicalPath = (moduleId: string) => `/w/${workspaceStore.activeWorkspaceId}/${moduleId}`

const loadPlatformMatrix = async () => {
  platformRequest.loading = true
  platformRequest.error = ''
  try {
    platformSnapshot.value = await systemClient.platforms()
  } catch (error: any) {
    platformRequest.error = error?.message || t('overview.error.platform')
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
    runtimeRequest.error = error?.message || t('overview.error.runtime')
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
    voiceRequest.error = error?.message || t('overview.error.voice')
  } finally {
    voiceRequest.loading = false
  }
}

const loadActiveApplication = async () => {
  activeApplicationRequest.loading = true
  activeApplicationRequest.error = ''
  try {
    activeApplication.value = await systemClient.activeApplication()
  } catch (error: any) {
    activeApplication.value = null
    activeApplicationRequest.error = error?.message || t('overview.error.activeApp')
  } finally {
    activeApplicationRequest.loading = false
  }
}

const loadOrchestration = async () => {
  orchestrationRequest.loading = true
  orchestrationRequest.error = ''
  try {
    orchestrationSnapshot.value = await systemClient.orchestration()
  } catch (error: any) {
    orchestrationSnapshot.value = null
    orchestrationRequest.error = error?.message || t('overview.error.orchestration')
  } finally {
    orchestrationRequest.loading = false
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
  if (!kinds.length) return t('overview.none')
  if (kinds.includes('real_device')) return t('overview.voice.evidence.realDevice')
  return t('overview.voice.evidence.fixture')
})
const voiceP95Label = (stage: Record<string, unknown> | undefined): string => {
  const value = stage?.p95_ms
  return typeof value === 'number' && Number.isFinite(value) ? t('overview.voice.p95', { ms: Math.round(value) }) : t('overview.none')
}
const voiceComfortLabel = computed(() => {
  const comfort = voiceSnapshot.value?.comfort
  const gate = comfort && typeof comfort === 'object' ? comfort.comfort_gate : null
  const status = gate && typeof gate === 'object' ? (gate as Record<string, unknown>).status : null
  if (status === 'pass') return t('overview.voice.comfort.pass')
  if (status === 'needs_attention') return t('overview.voice.comfort.needsAttention')
  return t('overview.voice.comfort.insufficient')
})
const voiceComfortSummary = computed(() => {
  const comfort = voiceSnapshot.value?.comfort
  if (!comfort || typeof comfort !== 'object') return ''
  const sampleCount = comfort.sample_count
  if (typeof sampleCount !== 'number' || sampleCount <= 0) return t('overview.voice.comfort.noneRecorded')
  const gate = comfort.comfort_gate
  if (!gate || typeof gate !== 'object') return t('overview.voice.comfort.samples', { count: sampleCount })
  const failures = (gate as Record<string, unknown>).failures
  if (Array.isArray(failures) && failures.length > 0) return String(failures[0])
  return t('overview.voice.comfort.samplesNoRegression', { count: sampleCount })
})
const voiceComfortSignalSummary = computed(() => {
  const comfort = voiceSnapshot.value?.comfort
  if (!comfort || typeof comfort !== 'object') return ''
  const signals = comfort.comfort_signals
  if (!signals || typeof signals !== 'object') return t('overview.voice.signal.noClassifier')
  const report = signals as Record<string, unknown>
  const count = typeof report.sample_count === 'number' ? report.sample_count : 0
  const missing = Array.isArray(report.missing_signals)
    ? report.missing_signals.map(item => String(item)).filter(Boolean)
    : []
  if (count <= 0) return t('overview.voice.signal.noneRecorded')
  if (missing.length) return t('overview.voice.signal.missing', { count, missing: missing.join(t('overview.listSeparator')) })
  return t('overview.voice.signal.ok', { count })
})
const voiceQualificationLabel = computed(() => {
  const status = voiceSnapshot.value?.release_gate?.status
  if (status === 'pass') return t('overview.voice.qualification.pass')
  if (status === 'fail') return t('overview.voice.qualification.fail')
  return t('overview.none')
})
const voiceQualificationSummary = computed(() => {
  const qualification = voiceSnapshot.value?.qualification
  if (!qualification) return ''
  if (qualification.status === 'qualified') return t('overview.voice.qualification.ok')
  const gaps = Array.isArray(qualification.gaps)
    ? qualification.gaps
      .map((gap) => typeof gap?.kind === 'string' ? gap.kind : '')
      .filter(Boolean)
      .slice(0, 2)
    : []
  return gaps.length ? t('overview.voice.qualification.gaps', { gaps: gaps.join(t('overview.listSeparator')) }) : t('overview.voice.qualification.incomplete')
})
const voiceRecommendations = computed(() => voiceSnapshot.value?.recommendations ?? [])

const orchestrationEntries = computed(() => {
  const snapshot = orchestrationSnapshot.value
  if (!snapshot) return []
  return [
    ...(snapshot.agents ?? []).map(item => ({ id: item.id, name: item.name, kind: t('overview.orchestration.agents') })),
    ...snapshot.skills.map(item => ({ id: item.id, name: item.name, kind: t('overview.orchestration.skills') })),
    ...snapshot.commands.map(item => ({ id: item.id, name: item.name, kind: t('overview.orchestration.commands') })),
    ...snapshot.hooks.map(item => ({ id: item.id, name: item.name, kind: t('overview.orchestration.hooks') })),
  ].slice(0, 12)
})

const platformRows = computed(() => platformSnapshot.value?.platforms ?? [])
const platformHostLabel = computed(() => {
  const host = platformSnapshot.value?.host
  if (!host) return ''
  return `${host.system} · ${host.displayServer}`
})
const platformCapabilityKeys = ['desktop', 'live2d_vrm', 'text_voice', 'native_actions'] as const
const platformStatusLabel = (status: PlatformCapabilityState) => ({
  available: t('overview.status.available'),
  needs_config: t('overview.platform.status.needsConfig'),
  experimental: t('overview.platform.status.experimental'),
  planned: t('overview.platform.status.planned'),
  unsupported: t('overview.platform.status.unsupported'),
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
      label: t('overview.row.providers'),
      value: !providers.length ? t('overview.value.noProvider') : requiredHealthy ? t('overview.value.providerHealth', { healthy: providers.filter((item) => item.healthy).length, total: providers.length }) : t('overview.value.providerRequiredFailure'),
      desc: providerFailures[0]?.message || (providers.length ? t('overview.desc.providers') : t('overview.desc.providersUnread')),
      tone: !providers.length ? 'warning' : requiredHealthy ? 'online' : 'offline',
      to: canonicalPath('infrastructure'),
    },
    {
      key: 'connectors',
      label: t('overview.row.connectors'),
      value: connectorFailures.length ? t('overview.value.connectorFailures', { count: connectorFailures.length }) : t('overview.value.connectorRunning', { count: runningConnectors.length }),
      desc: connectorFailures[0]?.lastError || t('overview.desc.connectors'),
      tone: connectorFailures.length ? 'warning' : 'online',
      to: canonicalPath('agent-governance'),
    },
    {
      key: 'pet',
      label: t('overview.row.pet'),
      value: currentModel.value ? t('overview.status.loaded') : t('overview.status.pendingConfigure'),
      desc: currentModel.value?.name || t('overview.desc.petModel'),
      tone: currentModel.value ? 'online' : 'warning',
      to: canonicalPath('pet'),
    },
    {
      key: 'platform',
      label: t('overview.row.platform'),
      value: platformHostLabel.value || t('overview.status.pendingCheck'),
      desc: t('overview.desc.platform'),
      tone: platformSnapshot.value ? 'online' : 'warning',
      to: canonicalPath('deploy'),
    },
  ] as Array<{ key: string; label: string; value: string; desc: string; tone: CheckTone; to: string }>
})

const {
  systemStore,
  petState,
  petCatalog,
  scaleDraft,
  opacityDraft,
  selectedModelId,
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
type RuntimeActionItem = ChainIssue & { to: string; actionLabel: string }

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
  if (!canAssessConfiguredServices.value) return t('overview.status.pendingCheck')
  if (!hasLlmEndpoint.value) return t('overview.status.endpointMissing')
  if (!hasLlmModel.value) return t('overview.status.modelMissing')
  if (!isLocalLlmProvider.value && !hasLlmKey.value) return t('overview.status.keyMissing')
  return t('overview.status.configured')
})

const asrReady = computed(() => {
  if (!canAssessConfiguredServices.value) return false
  const provider = settingsStore.state.asr.provider
  if (provider === 'disabled') return false
  if (provider === 'sensevoice-local' || provider === 'sherpa-onnx' || provider === 'sherpa-onnx-online') return true
  return Boolean(settingsStore.state.asr.base_url.trim())
})
const asrStatusText = computed(() => {
  if (!canAssessConfiguredServices.value) return t('overview.status.pendingCheck')
  if (settingsStore.state.asr.provider === 'disabled') return t('overview.status.disabled')
  return asrReady.value ? t('overview.status.configured') : t('overview.status.endpointMissing')
})

const ttsConfigured = computed(() => ['genie-tts', 'openai-compatible'].includes(settingsStore.state.tts.provider))
const ttsReady = computed(() => Boolean(canAssessConfiguredServices.value && systemStore.pythonRunning && ttsConfigured.value))
const ttsStatusText = computed(() => {
  if (!canAssessConfiguredServices.value) return t('overview.status.pendingCheck')
  if (!ttsConfigured.value) return t('overview.status.conflict')
  return systemStore.pythonRunning ? t('overview.status.configured') : t('overview.status.waitingBackend')
})
const promptModeLabel = computed(() => {
  const mode = workspaceStore.activeWorkspace.context.promptMode || 'auto'
  if (mode === 'work') return t('overview.prompt.work')
  if (mode === 'daily') return t('overview.prompt.daily')
  return workspaceStore.activeWorkspaceId === 'default' ? t('overview.prompt.autoDaily') : t('overview.prompt.autoWork')
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
      title: t('overview.issue.controlTitle'),
      desc: systemStore.controlHealthError || t('overview.issue.controlDesc'),
      tone: 'offline',
    })
  }

  if (!systemStore.pythonRunning) {
    issues.push({
      key: 'python',
      title: t('overview.issue.pythonTitle'),
      desc: systemStore.pythonHealthError || t('overview.issue.pythonDesc'),
      tone: 'offline',
    })
  }

  if (!systemStore.sioConnected) {
    issues.push({
      key: 'socket',
      title: t('overview.issue.socketTitle'),
      desc: t('overview.issue.socketDesc'),
      tone: 'warning',
    })
  }

  if (canAssessConfiguredServices.value) {
    if (!hasLlmEndpoint.value) {
      issues.push({ key: 'llm-url', title: t('overview.issue.llmUrlTitle'), desc: t('overview.issue.llmUrlDesc'), tone: 'offline' })
    } else if (!hasLlmModel.value) {
      issues.push({ key: 'llm-model', title: t('overview.issue.llmModelTitle'), desc: t('overview.issue.llmModelDesc'), tone: 'offline' })
    } else if (!isLocalLlmProvider.value && !hasLlmKey.value) {
      issues.push({ key: 'llm-key', title: t('overview.issue.llmKeyTitle'), desc: t('overview.issue.llmKeyDesc'), tone: 'offline' })
    }

    if (settingsStore.state.asr.provider === 'disabled') {
      issues.push({ key: 'asr-disabled', title: t('overview.issue.asrDisabledTitle'), desc: t('overview.issue.asrDisabledDesc'), tone: 'warning' })
    } else if (!asrReady.value) {
      issues.push({ key: 'asr-url', title: t('overview.issue.asrUrlTitle'), desc: t('overview.issue.asrUrlDesc'), tone: 'warning' })
    }

    if (!ttsConfigured.value) {
      issues.push({ key: 'tts-provider', title: t('overview.issue.ttsConflictTitle'), desc: t('overview.issue.ttsProviderDesc'), tone: 'offline' })
    }

  }

  if (!currentModel.value) {
    issues.push({ key: 'pet-model', title: t('overview.issue.petModelTitle'), desc: t('overview.desc.petModel'), tone: 'warning' })
  } else if (!petState.value.visible) {
    issues.push({ key: 'pet-hidden', title: t('overview.issue.petHiddenTitle'), desc: t('overview.issue.petHiddenDesc'), tone: 'warning' })
  }

  return issues
})

const issueTarget = (key: string): string => {
  if (key === 'control' || key === 'python' || key === 'socket' || key === 'providers') return canonicalPath('infrastructure')
  if (key === 'connectors') return canonicalPath('agent-governance')
  if (key === 'pet' || key.startsWith('pet-')) return canonicalPath('pet')
  if (key === 'platform') return canonicalPath('deploy')
  return canonicalPath('settings')
}

const runtimeActionItems = computed<RuntimeActionItem[]>(() => {
  const localIssues = chainIssues.value.map((item) => ({
    ...item,
    to: issueTarget(item.key),
    actionLabel: ['control', 'python', 'socket'].includes(item.key) ? t('overview.action.viewDiagnostics') : t('overview.action.goSettings'),
  }))
  const remoteIssues = runtimeRows.value
    .filter((item) => item.tone !== 'online')
    .filter((item) => item.key !== 'providers' || providerSnapshot.value)
    .filter((item) => item.key !== 'platform' || platformSnapshot.value)
    .map((item) => ({
      key: item.key,
      title: t('overview.runtimeActionTitle', { label: item.label, value: item.value }),
      desc: item.desc,
      tone: item.tone,
      to: item.to,
      actionLabel: t('overview.action.viewDetail'),
    }))

  const seen = new Set<string>()
  return [...localIssues, ...remoteIssues]
    .sort((left, right) => Number(left.tone !== 'offline') - Number(right.tone !== 'offline'))
    .filter((item) => {
      if (seen.has(item.key)) return false
      seen.add(item.key)
      return true
    })
    .slice(0, 6)
})

const chainChecks = computed<Array<{ label: string; value: string; desc: string; tone: CheckTone }>>(() => [
  {
    label: t('overview.chain.chat'),
    value: chatChainReady.value ? t('overview.status.configured') : t('overview.chain.pendingConnection'),
    desc: chatChainReady.value ? settingsStore.state.llm.model : t('overview.chain.backendChain'),
    tone: chatChainReady.value ? 'online' : 'warning',
  },
  {
    label: t('overview.chain.prompt'),
    value: promptModeLabel.value,
    desc: promptContextReady.value ? t('overview.chain.promptReady') : t('overview.chain.promptIncomplete'),
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
    desc: ttsConfigured.value ? t('overview.chain.ttsConfigured', { provider: settingsStore.state.tts.provider }) : t('overview.issue.ttsProviderDesc'),
    tone: ttsReady.value ? 'online' : 'offline',
  },
  {
    label: t('overview.chain.petLink'),
    value: petLinkReady.value ? t('overview.status.available') : t('overview.chain.pendingCheck'),
    desc: currentModel.value?.name || t('overview.chain.noModel'),
    tone: petLinkReady.value ? 'online' : 'warning',
  },
  {
    label: t('overview.chain.voice'),
    value: voiceChainReady.value ? t('overview.status.configured') : t('overview.status.pendingConfigure'),
    desc: 'ASR / LLM / TTS',
    tone: voiceChainReady.value ? 'online' : 'warning',
  },
])

const refreshChainStatus = async () => {
  await Promise.all([
    settingsStore.fetchSettings(),
    syncPetData(false),
  ])
}

const overviewRefreshLoading = computed(() => (
  settingsStore.state.loading
  || platformRequest.loading
  || runtimeRequest.loading
  || voiceRequest.loading
  || activeApplicationRequest.loading
  || orchestrationRequest.loading
))

const refreshOverview = async () => {
  await Promise.all([
    refreshChainStatus(),
    loadPlatformMatrix(),
    loadRuntimeDependencies(),
    loadVoiceDiagnostics(),
    loadAvatarCapabilities(),
    loadActiveApplication(),
    loadOrchestration(),
  ])
}

const petChips = computed(() => [
  { label: currentModel.value?.name ?? t('overview.pet.chip.noModel'), tone: 'ok' },
  { label: petState.value.ready ? t('overview.status.loaded') : t('overview.status.loading'), tone: petState.value.ready ? 'ok' : 'warn' },
  { label: petState.value.interactMode ? t('overview.pet.chip.draggable') : t('overview.pet.chip.clickThrough'), tone: petState.value.interactMode ? 'warn' : 'info' },
  { label: petState.value.clickThrough ? t('overview.pet.chip.fullClickThrough') : t('overview.pet.chip.interactive'), tone: petState.value.clickThrough ? 'ok' : 'warn' },
  { label: petState.value.locked ? t('overview.pet.positionLock') : t('overview.pet.chip.unlocked'), tone: petState.value.locked ? 'err' : 'info' },
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
  gap: 12px;
}

.overview-view-nav {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  padding: 4px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.overview-view-button {
  min-width: 72px;
  min-height: 34px;
  border: 0;
  border-radius: var(--yui-radius-control);
  padding: 6px 12px;
  background: transparent;
  color: var(--yui-muted);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
}

.overview-view-button:hover {
  color: var(--yui-text);
  background: var(--yui-surface);
}

.overview-view-button.active {
  color: var(--yui-accent);
  background: var(--yui-surface-raised);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.1);
}

.overview-view-button:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--yui-accent) 30%, transparent);
  outline-offset: 1px;
}

.ops-card,
.control-block {
  border: 1px solid var(--yui-panel-outline, var(--yui-border));
  background: var(--yui-panel-surface, var(--yui-surface-raised));
  background-clip: padding-box;
  box-shadow: var(--yui-panel-shadow, var(--yui-shadow-card));
}

.ops-card:hover,
.control-block:hover {
  border-color: var(--yui-panel-outline-strong, var(--yui-border-strong));
  box-shadow: var(--yui-panel-shadow, var(--yui-shadow-card));
}

.ops-card:focus-within,
.control-block:focus-within {
  border-color: var(--yui-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--yui-accent) 16%, transparent), var(--yui-shadow-hover);
}

.ops-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
  gap: 12px;
}

.voice-quality-card {
  padding: 16px;
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

.runtime-readiness-card {
  padding: 16px;
}

.runtime-readiness-alert {
  margin-bottom: 10px;
}

.runtime-action-list {
  display: grid;
  gap: 2px;
  border-top: 1px solid var(--yui-border);
  border-bottom: 1px solid var(--yui-border);
}

.runtime-action-item {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px 2px;
}

.runtime-action-item + .runtime-action-item {
  border-top: 1px solid var(--yui-border);
}

.runtime-action-dot,
.runtime-chain-item i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--yui-muted);
}

.runtime-action-item.warning .runtime-action-dot,
.runtime-chain-item.warning i {
  background: #d97706;
}

.runtime-action-item.offline .runtime-action-dot,
.runtime-chain-item.offline i {
  background: #dc2626;
}

.runtime-chain-item.online i {
  background: #059669;
}

.runtime-action-item div,
.runtime-action-item strong,
.runtime-action-item span {
  min-width: 0;
}

.runtime-action-item strong,
.runtime-action-item span {
  display: block;
}

.runtime-action-item strong {
  color: var(--yui-text);
  font-size: 13px;
}

.runtime-action-item span {
  margin-top: 2px;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.runtime-action-item a {
  color: var(--yui-accent);
  font-size: 12px;
  font-weight: 800;
  text-decoration: none;
}

.runtime-ready-state {
  padding: 10px 0 14px;
}

.runtime-ready-state strong,
.runtime-ready-state span {
  display: block;
}

.runtime-ready-state strong {
  color: var(--yui-text);
  font-size: 13px;
}

.runtime-ready-state span {
  margin-top: 3px;
  color: var(--yui-muted);
  font-size: 12px;
}

.runtime-chain {
  display: flex;
  align-items: center;
  gap: 8px 16px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.runtime-chain-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--yui-muted);
  font-size: 11px;
}

.runtime-chain-item strong {
  color: var(--yui-text);
  font-size: 11px;
}

.runtime-chain-item small {
  overflow: hidden;
  max-width: 100px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops-card {
  border-radius: 8px;
  padding: 16px;
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

.compact-status {
  min-height: 36px;
  display: flex;
  align-items: center;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.context-list {
  display: grid;
  gap: 8px;
  margin: 0;
}

.context-list > div {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr);
  gap: 10px;
  align-items: baseline;
  min-width: 0;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--yui-border);
}

.context-list > div:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.context-list dt {
  color: var(--yui-muted);
  font-size: 12px;
}

.context-list dd {
  min-width: 0;
  margin: 0;
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.orchestration-counts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.orchestration-counts span {
  min-width: 0;
  padding: 8px 6px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-control);
  color: var(--yui-muted);
  font-size: 11px;
  text-align: center;
}

.orchestration-counts strong {
  display: block;
  margin-top: 2px;
  color: var(--yui-text);
  font-size: 16px;
}

.orchestration-details {
  margin-top: 12px;
  color: var(--yui-muted);
  font-size: 12px;
}

.orchestration-details summary {
  cursor: pointer;
  color: var(--yui-accent);
  font-weight: 800;
}

.orchestration-details ul {
  display: grid;
  gap: 6px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.orchestration-details li {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--yui-border);
}

.orchestration-details li strong {
  min-width: 0;
  overflow: hidden;
  color: var(--yui-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.orchestration-details li span {
  flex: 0 0 auto;
  color: var(--yui-muted);
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

.control-block label {
  display: block;
  margin-bottom: 10px;
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 800;
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

.ops-card-head > div:first-child > span {
  color: var(--yui-muted);
  font-size: 12px;
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
  .ops-grid {
    grid-template-columns: 1fr;
  }

  .pet-control-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .ops-card {
    padding: 18px;
  }

  .metric-grid,
  .pet-control-grid,
  .voice-quality-grid,
  .pet-capability-summary,
  .orchestration-counts {
    grid-template-columns: 1fr;
  }

  .ops-card-head,
  .pet-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .runtime-action-item {
    grid-template-columns: 10px minmax(0, 1fr);
  }

  .runtime-action-item a {
    grid-column: 2;
    justify-self: start;
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
