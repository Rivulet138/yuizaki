<template>
  <PanelShell title="桌宠 Agent" tone="companion">
    <div class="companion-home">
      <section v-if="companionStore.loading && !activeCompanion" class="empty-home">
        <div class="empty-card">
          <strong>正在加载桌宠档案</strong>
        </div>
      </section>

      <section v-else-if="!activeCompanion" class="empty-home">
        <el-alert v-if="companionLoadError" class="empty-alert" type="warning" :closable="false" show-icon>
          <div class="empty-alert-row">
            <span>{{ companionLoadError }}</span>
            <el-button size="small" text @click.stop="loadCompanionHome">重试</el-button>
          </div>
        </el-alert>
        <el-empty :description="companionLoadError ? '桌宠档案加载失败' : '暂无可用桌宠档案'" />
        <div class="empty-actions">
          <el-button type="primary" @click="showCreateDialog = true">新建桌宠档案</el-button>
          <el-button v-if="companionLoadError" plain @click="loadCompanionHome">重新加载</el-button>
        </div>
      </section>

      <template v-else>
        <section class="status-strip" aria-label="桌宠联动状态">
          <article
            v-for="item in readinessItems"
            :key="item.key"
            class="status-pill"
            :class="`is-${item.state}`"
          >
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </article>
        </section>

        <section class="panel-card pet-quick-card" aria-label="桌宠 Agent 状态">
          <header class="card-header">
            <div>
              <h3>桌宠 Agent 状态</h3>
            </div>
            <el-button size="small" plain :loading="petOperationKey === 'refresh'" @click="refreshPetStateFromClick">刷新状态</el-button>
          </header>

          <div v-if="petQuickError" class="pet-warning">{{ petQuickError }}</div>

          <div class="pet-state-grid">
            <article>
              <span>桌面可见</span>
              <strong>{{ petRuntimeState.visible ? '已显示' : '已隐藏' }}</strong>
            </article>
            <article>
              <span>鼠标策略</span>
              <strong>{{ petRuntimeState.clickThrough ? '鼠标穿透' : '可交互' }}</strong>
            </article>
            <article>
              <span>停靠位置</span>
              <strong>{{ petPlacementLabel }}</strong>
            </article>
            <article>
              <span>角色模型</span>
              <strong>{{ petModelLabel }}</strong>
            </article>
          </div>

          <div class="pet-control-row">
            <el-button
              size="small"
              type="primary"
              plain
              :loading="petOperationKey === 'visible'"
              @click="setPetVisible(!petRuntimeState.visible)"
            >
              <el-icon><component :is="petRuntimeState.visible ? Hide : View" /></el-icon>
              <span>{{ petRuntimeState.visible ? '隐藏桌宠' : '显示桌宠' }}</span>
            </el-button>
            <el-button size="small" plain :loading="petOperationKey === 'dock'" @click="dockPetBottomRight">
              <el-icon><Position /></el-icon>
              <span>贴到右下角</span>
            </el-button>
            <el-button size="small" plain :loading="petOperationKey === 'sync-profile' || applyingRuntime" @click="syncDesktopPetProfile">
              <el-icon><RefreshRight /></el-icon>
              <span>同步人格到桌宠</span>
            </el-button>
          </div>

          <div class="pet-toggle-row">
            <label class="pet-toggle-item">
              <span>鼠标穿透</span>
              <el-switch
                :model-value="petRuntimeState.clickThrough"
                inline-prompt
                active-text="开"
                inactive-text="关"
                :loading="petOperationKey === 'click-through'"
                @change="setPetClickThrough"
              />
            </label>
            <label class="pet-toggle-item">
              <span>免打扰</span>
              <el-switch
                :model-value="petRuntimeState.doNotDisturb"
                inline-prompt
                active-text="开"
                inactive-text="关"
                :loading="petOperationKey === 'dnd'"
                @change="setPetDoNotDisturb"
              />
            </label>
          </div>
        </section>

        <section class="panel-card vision-card" aria-label="实时视觉设置">
          <header class="card-header">
            <div>
              <h3>实时视觉</h3>
              <p>{{ visualPerceptionSummary }}</p>
            </div>
            <el-switch
              :model-value="visionSettings.enabled"
              inline-prompt
              active-text="开"
              inactive-text="关"
              @change="setVisionEnabled"
            />
          </header>

          <div class="vision-control-grid">
            <label>
              <span>观察显示器</span>
              <el-select
                :model-value="visionSettings.displayIndex"
                size="small"
                :disabled="!visionSettings.enabled"
                @change="setVisionDisplay"
              >
                <el-option
                  v-for="display in visionDisplays"
                  :key="display.id"
                  :label="display.label"
                  :value="display.index"
                />
              </el-select>
            </label>
            <label>
              <span>采集范围</span>
              <el-select
                :model-value="visionSettings.captureMode"
                size="small"
                :disabled="!visionSettings.enabled"
                @change="setVisionCaptureMode"
              >
                <el-option label="整个显示器" value="display" />
                <el-option label="指定区域" value="region" />
              </el-select>
            </label>
            <label>
              <span>画面采样</span>
              <el-select
                :model-value="visionSettings.intervalMs"
                size="small"
                :disabled="!visionSettings.enabled"
                @change="setVisionInterval"
              >
                <el-option v-for="option in visionIntervalOptions" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
            </label>
            <label class="vision-switch-field">
              <span>面板隐藏时暂停</span>
              <el-switch
                :model-value="visionSettings.pauseWhenAppHidden"
                :disabled="!visionSettings.enabled"
                @change="setVisionPauseWhenHidden"
              />
            </label>
          </div>

          <div v-if="visionSettings.captureMode === 'region'" class="vision-region-grid">
            <label v-for="field in visionRegionFields" :key="field.key">
              <span>{{ field.label }}</span>
              <el-input-number
                :model-value="visionSettings.region[field.key]"
                :min="field.min"
                :max="100000"
                :step="field.step"
                size="small"
                controls-position="right"
                :disabled="!visionSettings.enabled"
                @change="setVisionRegionValue(field.key, $event)"
              />
            </label>
            <div class="vision-region-actions">
              <VisionRegionSelector
                :disabled="!visionSettings.enabled"
                :display-index="visionSettings.displayIndex"
                :display-width="activeVisionDisplay.width"
                :display-height="activeVisionDisplay.height"
                :region="visionSettings.region"
                @apply="setVisionRegion"
              />
            </div>
          </div>

          <div class="vision-privacy-settings">
            <div class="vision-privacy-header">
              <div>
                <strong>隐私遮挡</strong>
                <el-tag size="small" type="danger" effect="plain">发送前本地处理</el-tag>
              </div>
              <span>{{ visionSettings.privacyMasks.length }} / 8</span>
            </div>
            <div class="vision-privacy-actions">
              <VisionRegionSelector
                v-if="visionSettings.privacyMasks.length < 8"
                :disabled="!visionSettings.enabled"
                :display-index="visionSettings.displayIndex"
                :display-width="activeVisionDisplay.width"
                :display-height="activeVisionDisplay.height"
                :region="privacyMaskDraft"
                :context-regions="visionSettings.privacyMasks"
                button-label="添加遮挡区域"
                dialog-title="选择隐私遮挡区域"
                apply-label="添加遮挡"
                tone="privacy"
                @apply="addVisionPrivacyMask"
              />
              <el-button
                v-if="visionSettings.privacyMasks.length"
                plain
                :disabled="!visionSettings.enabled"
                @click="clearVisionPrivacyMasks"
              >
                清除全部
              </el-button>
            </div>
            <div v-if="visionSettings.privacyMasks.length" class="vision-privacy-list">
              <div v-for="(mask, index) in visionSettings.privacyMasks" :key="`${mask.x}-${mask.y}-${index}`">
                <span>区域 {{ index + 1 }} · {{ mask.width }}×{{ mask.height }} · {{ mask.x }}, {{ mask.y }}</span>
                <el-button
                  text
                  circle
                  :icon="Delete"
                  :disabled="!visionSettings.enabled"
                  title="删除遮挡区域"
                  aria-label="删除遮挡区域"
                  @click="removeVisionPrivacyMask(index)"
                />
              </div>
            </div>
          </div>

          <div class="vision-status-row" :class="`is-${systemStore.visualPerceptionPhase}`">
            <span class="status-dot"></span>
            <strong>{{ visualPerceptionPhaseLabel }}</strong>
            <span>{{ visualPerceptionLastFrameLabel }}</span>
          </div>
        </section>

        <section class="quick-grid" aria-label="桌宠功能入口">
          <router-link
            v-for="action in companionActionLinks"
            :key="action.id"
            class="quick-action"
            :to="modulePath(action.module)"
          >
            <el-icon><component :is="action.icon" /></el-icon>
            <span>{{ action.label }}</span>
          </router-link>
        </section>

        <div class="home-layout">
          <div class="left-column">
            <section class="panel-card">
              <header class="card-header">
                <div>
                  <h3>桌宠 agent 档案</h3>
                </div>
                <div class="header-actions">
                  <el-button size="small" plain :disabled="switchingCompanion || deletingCompanion" @click="showCreateDialog = true">新建</el-button>
                  <el-button size="small" type="primary" :loading="saving" :disabled="switchingCompanion || deletingCompanion" @click="saveCompanion">保存修改</el-button>
                </div>
              </header>

              <el-select
                :model-value="companionStore.activeCompanionId"
                class="full-width companion-select"
                :loading="switchingCompanion"
                :disabled="switchingCompanion || deletingCompanion"
                @change="switchCompanion"
              >
                <el-option v-for="c in companionStore.companions" :key="c.id" :label="c.name" :value="c.id">
                  <span>{{ c.name }}</span>
                  <span class="option-meta">{{ c.model_type || 'live2d' }}</span>
                </el-option>
              </el-select>

              <el-form v-if="editForm" class="profile-form" label-position="top" @submit.prevent>
                <el-form-item label="称呼">
                  <el-input v-model="editForm.name" />
                </el-form-item>

                <div class="form-grid">
                  <el-form-item label="模型类型">
                    <el-select v-model="editForm.model_type" class="full-width">
                      <el-option label="Live2D" value="live2d" />
                      <el-option label="VRM" value="vrm" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="角色模型 ID">
                    <el-input v-model="editForm.model_id" placeholder="例如 hiyori 或 local:vrm/..." />
                  </el-form-item>
                </div>

                <div class="form-grid">
                  <el-form-item label="陪伴气质">
                    <el-select v-model="editForm.temperament" class="full-width">
                      <el-option label="温暖" value="warm" />
                      <el-option label="活泼" value="playful" />
                      <el-option label="克制" value="reserved" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="相处距离">
                    <el-select v-model="editForm.attachment_style" class="full-width">
                      <el-option label="安全型" value="secure" />
                      <el-option label="贴近型" value="attached" />
                      <el-option label="独立型" value="independent" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="回应风格">
                    <el-select v-model="editForm.support_style" class="full-width">
                      <el-option label="温柔" value="gentle" />
                      <el-option label="分析型" value="analytical" />
                      <el-option label="明朗型" value="cheerful" />
                    </el-select>
                  </el-form-item>
                </div>
              </el-form>
            </section>

            <section v-if="editForm" class="panel-card state-editor-card">
              <header class="card-header">
                <div>
                  <h3>陪伴状态</h3>
                </div>
              </header>

              <el-form class="profile-form" label-position="top" @submit.prevent>
                <el-form-item label="当前情绪">
                  <el-select v-model="editForm.emotion_state" class="full-width" filterable allow-create default-first-option>
                    <el-option v-for="option in emotionOptions" :key="option.value" :label="option.label" :value="option.value" />
                  </el-select>
                </el-form-item>

                <div class="state-slider-list">
                  <label v-for="field in stateTuningFields" :key="field.key" class="state-slider-item">
                    <span class="state-slider-heading">
                      <span>{{ field.label }}</span>
                      <strong>{{ formatStatePercent(editForm[field.key]) }}</strong>
                    </span>
                    <el-slider v-model="editForm[field.key]" :min="0" :max="1" :step="0.05" />
                  </label>
                </div>
              </el-form>
            </section>

            <section class="panel-card danger-zone">
              <header class="card-header">
                <div>
                  <h3>桌宠档案操作</h3>
                </div>
              </header>
              <el-button
                type="danger"
                plain
                :loading="deletingCompanion"
                :disabled="activeCompanion.id === 'default' || deletingCompanion || switchingCompanion"
                @click="handleDelete"
              >
                删除此档案
              </el-button>
            </section>
          </div>

          <div class="right-column">
            <section class="panel-card">
              <header class="card-header">
                <div>
                  <h3>陪伴关系</h3>
                  <p>{{ relationshipSummary }}</p>
                </div>
              </header>

              <div class="gauge-list">
                <div v-for="gauge in gaugeList" :key="gauge.key" class="gauge-row">
                  <div class="gauge-label">
                    <span>{{ gauge.label }}</span>
                    <strong>{{ gauge.display }}</strong>
                  </div>
                  <el-progress :percentage="gauge.percent" :stroke-width="8" :show-text="false" />
                </div>
              </div>

              <div class="relationship-stat-grid">
                <article v-for="item in relationshipStats" :key="item.label">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </article>
              </div>

            </section>

            <section class="panel-card">
              <header class="card-header">
                <div>
                  <h3>桌宠心跳</h3>
                  <p>{{ heartbeatSummary }}</p>
                </div>
              </header>

              <div class="state-grid">
                <article>
                  <span>心跳状态</span>
                  <strong>{{ heartbeatState?.running ? '运行中' : '未运行' }}</strong>
                </article>
                <article>
                  <span>触发次数</span>
                  <strong>{{ heartbeatState?.tick_count ?? 0 }}</strong>
                </article>
                <article>
                  <span>行为事件</span>
                  <strong>{{ heartbeatState?.behavior_events?.length ?? 0 }}</strong>
                </article>
                <article>
                  <span>间隔</span>
                  <strong>{{ heartbeatState?.interval_seconds ? `${heartbeatState.interval_seconds}s` : '-' }}</strong>
                </article>
                <article>
                  <span>待机心情</span>
                  <strong>{{ heartbeatState?.persona?.mood || '-' }}</strong>
                </article>
                <article>
                  <span>待机精力</span>
                  <strong>{{ formatOptionalPercent(heartbeatState?.persona?.energy) }}</strong>
                </article>
                <article>
                  <span>最近行为</span>
                  <strong>{{ heartbeatLatestBehavior?.emotion || '-' }}</strong>
                </article>
              </div>
            </section>

            <section class="panel-card memory-card">
              <header class="card-header">
                <div>
                  <h3>她记住了什么</h3>
                  <p>偏好、事件与关系线索共 {{ memoryTotal }} 条</p>
                </div>
                <router-link class="text-link" :to="modulePath('memory')">查看全部</router-link>
              </header>

              <div class="memory-grid">
                <article v-for="layer in memoryLayers" :key="layer.key" class="memory-item">
                  <strong>{{ memoryLayerCount(layer.key) }}</strong>
                  <span>{{ layer.label }}</span>
                </article>
              </div>

              <div v-if="signalSummaryItems.length" class="tag-row">
                <el-tag v-for="item in signalSummaryItems" :key="item.kind" type="info">
                  {{ item.kind }} × {{ item.count }}
                </el-tag>
              </div>
            </section>

            <section class="panel-card">
              <header class="card-header">
                <div>
                  <h3>最近记住的事</h3>
                </div>
              </header>

              <el-empty v-if="!recentSignals.length" description="还没有近期记忆" :image-size="56" />
              <div v-else class="signal-list">
                <article v-for="signal in recentSignals" :key="`${signal.kind}-${signal.timestamp}-${signal.text}`" class="signal-item">
                  <div>
                    <strong>{{ signal.kind }}</strong>
                    <span>{{ signal.layer }} / {{ signal.source }}</span>
                  </div>
                  <p>{{ signal.text }}</p>
                </article>
              </div>
            </section>

            <section v-if="proactiveState || behaviorProfile" class="panel-card">
              <header class="card-header">
                <div>
                  <h3>主动陪伴</h3>
                  <p>{{ proactiveSummary }}</p>
                </div>
              </header>

              <div class="state-grid">
                <article>
                  <span>主动回应</span>
                  <strong>{{ proactiveState?.can_proactively_reach_out ? '可触发' : '暂不触发' }}</strong>
                </article>
                <article>
                  <span>准备度</span>
                  <strong>{{ proactiveState?.readiness_band || '-' }}</strong>
                </article>
                <article>
                  <span>语气</span>
                  <strong>{{ behaviorProfile?.tone_bucket || '-' }}</strong>
                </article>
                <article>
                  <span>主动性</span>
                  <strong>{{ behaviorProfile?.initiative_bucket || '-' }}</strong>
                </article>
              </div>

              <div v-if="proactiveState?.suppression_reasons?.length" class="tag-row">
                <el-tag v-for="reason in proactiveState.suppression_reasons" :key="reason" type="warning">
                  {{ reason }}
                </el-tag>
              </div>
            </section>

          </div>
        </div>
      </template>
    </div>

    <el-dialog v-model="showCreateDialog" title="新建桌宠档案" width="420px">
      <el-form label-position="top">
        <el-form-item label="称呼">
          <el-input v-model="createForm.name" />
        </el-form-item>
        <el-form-item label="模型类型">
          <el-select v-model="createForm.model_type" class="full-width">
            <el-option label="Live2D" value="live2d" />
            <el-option label="VRM" value="vrm" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色模型 ID">
          <el-input v-model="createForm.model_id" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" :disabled="creating || !createForm.name.trim()" @click="handleCreate">创建桌宠档案</el-button>
      </template>
    </el-dialog>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Collection, Delete, Hide, Position, RefreshRight, Setting, StarFilled, Tickets, View } from '@element-plus/icons-vue'
import { useCompanionRuntimeBridge } from '@/app/composables/useCompanionRuntimeBridge'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import VisionRegionSelector from '../components/VisionRegionSelector.vue'
import { useCompanionStore } from '@/stores/companionStore'
import { useSystemStore } from '@/stores/systemStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { petControlClient, systemClient } from '@/api/client'
import { workspaceClient } from '@/api/clients/workspace-client'
import type { CompanionRuntimeSnapshot, RelationshipSummarySnapshot } from '@/../shared/agent'
import { DEFAULT_PET_CONTROL_STATE, type PetControlState, type PetPlacement } from '@/../shared/pet-control'
import type { CompanionRecord } from '@/api/clients/companion-client'
import type { WorkspaceVisionSettings } from '@/../shared/workspace'

type MemoryState = NonNullable<CompanionRuntimeSnapshot['memory_state']>
type RecentSignal = NonNullable<MemoryState['recent_signals']>[number]
type ProactiveState = NonNullable<NonNullable<CompanionRuntimeSnapshot['companion_state']>['proactive_state']>
type BehaviorProfile = NonNullable<NonNullable<CompanionRuntimeSnapshot['companion_state']>['behavior_profile']>
type ReadinessState = 'ready' | 'warn' | 'idle'
type CompanionStateNumberKey = 'affinity_state' | 'trust_state' | 'energy_state' | 'intimacy_state' | 'interruptibility_state' | 'fatigue_state'
type PetOperationKey = 'refresh' | 'visible' | 'dock' | 'click-through' | 'dnd' | 'sync-profile'

const companionStore = useCompanionStore()
const systemStore = useSystemStore()
const workspaceStore = useWorkspaceStore()
const { applyActiveCompanionRuntime, buildIdleProfileFromCompanion } = useCompanionRuntimeBridge()

const activeCompanion = computed(() => companionStore.activeCompanion)
const activeWorkspaceId = computed(() => workspaceStore.activeWorkspaceId)
const defaultVisionSettings: WorkspaceVisionSettings = {
  enabled: true,
  displayIndex: 0,
  intervalMs: 2000,
  pauseWhenAppHidden: true,
  captureMode: 'display',
  region: { x: 0, y: 0, width: 1280, height: 720 },
  privacyMasks: [],
}
const visionSettings = computed(() => workspaceStore.activeWorkspace.context.vision ?? defaultVisionSettings)
const visionDisplays = ref<Array<{
  index: number
  id: number
  label: string
  width: number
  height: number
  scaleFactor: number
  isPrimary: boolean
}>>([{ index: 0, id: 0, label: '主显示器', width: 0, height: 0, scaleFactor: 1, isPrimary: true }])
const activeVisionDisplay = computed(() => {
  const display = visionDisplays.value.find((item) => item.index === visionSettings.value.displayIndex)
    ?? visionDisplays.value[0]
  return {
    width: Math.max(1, display?.width || visionSettings.value.region.width || 1),
    height: Math.max(1, display?.height || visionSettings.value.region.height || 1),
  }
})
const privacyMaskDraft = computed<WorkspaceVisionSettings['region']>(() => ({
  x: Math.round(activeVisionDisplay.value.width * 0.35),
  y: Math.round(activeVisionDisplay.value.height * 0.35),
  width: Math.max(64, Math.round(activeVisionDisplay.value.width * 0.3)),
  height: Math.max(64, Math.round(activeVisionDisplay.value.height * 0.3)),
}))
const visionIntervalOptions = [
  { value: 1000, label: '每 1 秒' },
  { value: 2000, label: '每 2 秒' },
  { value: 5000, label: '每 5 秒' },
  { value: 10000, label: '每 10 秒' },
]
const visionRegionFields = [
  { key: 'x', label: 'X', min: 0, step: 10 },
  { key: 'y', label: 'Y', min: 0, step: 10 },
  { key: 'width', label: '宽度', min: 64, step: 20 },
  { key: 'height', label: '高度', min: 64, step: 20 },
] as const

const runtime = ref({ retrieval_strategy_label: '', retrieval_strategy_layers: [] as string[] })
const petRuntimeState = reactive<PetControlState>({ ...DEFAULT_PET_CONTROL_STATE })
const heartbeatState = ref<CompanionRuntimeSnapshot['heartbeat'] | null>(null)
const memoryState = ref<MemoryState | null>(null)
const signalSummary = ref<Record<string, number>>({})
const proactiveState = ref<ProactiveState | null>(null)
const behaviorProfile = ref<BehaviorProfile | null>(null)
const relationshipStage = ref<string | null>(null)
const relationshipSummaryState = ref<RelationshipSummarySnapshot | null>(null)
const runtimeMood = ref<string | null>(null)

const saving = ref(false)
const creating = ref(false)
const switchingCompanion = ref(false)
const deletingCompanion = ref(false)
const applyingRuntime = ref(false)
const runtimeSyncError = ref('')
const companionLoadError = ref('')
const petQuickError = ref('')
const lastRuntimeSyncAt = ref('')
const showCreateDialog = ref(false)
const createForm = reactive({ name: '', model_type: 'live2d', model_id: '' })
const petOperationKey = ref<PetOperationKey | null>(null)
let runtimeRefreshTimer: number | null = null
let runtimeLoadSequence = 0
let runtimeSyncSequence = 0

const companionActionLinks = [
  { id: 'chat', label: '桌宠对话', module: 'chat', icon: ChatDotRound },
  { id: 'prompt', label: '人格提示词', module: 'prompt', icon: Tickets },
  { id: 'pet', label: '桌宠模型', module: 'pet', icon: StarFilled },
  { id: 'memory', label: '她记住了什么', module: 'memory', icon: Collection },
  { id: 'settings', label: '模型与语音', module: 'settings', icon: Setting },
] as const

const emotionOptions = [
  { label: '平静 neutral', value: 'neutral' },
  { label: '温暖 warm', value: 'warm' },
  { label: '开心 happy', value: 'happy' },
  { label: '专注 focused', value: 'focused' },
  { label: '疲惫 tired', value: 'tired' },
  { label: '好奇 curious', value: 'curious' },
]

const stateTuningFields: Array<{ key: CompanionStateNumberKey; label: string }> = [
  { key: 'affinity_state', label: '亲密度' },
  { key: 'trust_state', label: '信任度' },
  { key: 'energy_state', label: '精力' },
  { key: 'intimacy_state', label: '相处深度' },
  { key: 'interruptibility_state', label: '可打断性' },
  { key: 'fatigue_state', label: '疲劳度' },
]

const memoryLayers = [
  { key: 'profile_count', label: '偏好与称呼' },
  { key: 'working_count', label: '当下任务' },
  { key: 'episodic_count', label: '最近事件' },
  { key: 'relationship_count', label: '关系线索' },
  { key: 'reflective_count', label: '她的反思' },
  { key: 'semantic_count', label: '长期事实' },
]

const modulePath = (moduleId: string) => `/w/${activeWorkspaceId.value}/${moduleId}`

const stageLabel = computed(() => relationshipStage.value || 'warming')

const stageName = computed(() => {
  const names: Record<string, string> = {
    close: '亲密期',
    stable: '稳定期',
    warming: '升温期',
    new: '初识期',
  }
  return names[stageLabel.value] || stageLabel.value
})

const petPlacementLabel = computed(() => {
  const labels: Record<PetPlacement, string> = {
    'bottom-right': '右下角',
    'bottom-left': '左下角',
    'top-right': '右上角',
    'top-left': '左上角',
    center: '居中',
    free: '自由位置',
  }
  return labels[petRuntimeState.placement] || petRuntimeState.placement
})

const petModelLabel = computed(() => petRuntimeState.modelId || '未绑定模型')

const runtimeSyncLabel = computed(() => {
  if (runtimeSyncError.value) return '同步异常'
  return lastRuntimeSyncAt.value ? `最近同步 ${lastRuntimeSyncAt.value}` : '等待同步'
})

const relationshipSummary = computed(() => {
  if (runtime.value.retrieval_strategy_label) {
    return runtime.value.retrieval_strategy_label
  }
  return stageName.value
})

const relationshipStats = computed(() => {
  const summary = relationshipSummaryState.value
  return [
    { label: '关系趋势', value: summary?.relationship_trend || '-' },
    { label: '主动预算', value: String(summary?.proactive_budget ?? 0) },
    { label: '全局事件', value: String(summary?.global_count ?? 0) },
    { label: '场景事件', value: String(summary?.workspace_count ?? 0) },
    { label: '高重要', value: String(summary?.high_importance_count ?? 0) },
    { label: '信任变化', value: String(summary?.recent_trust_shift_count ?? 0) },
    { label: '感谢信号', value: String(summary?.recent_gratitude_count ?? 0) },
  ]
})

const heartbeatSummary = computed(() => {
  if (!heartbeatState.value) return '等待后端运行态返回心跳信息'
  if (!heartbeatState.value.running) return '后端心跳未运行'
  return heartbeatState.value.last_tick_at ? `最近心跳 ${formatDate(heartbeatState.value.last_tick_at)}` : '心跳运行中'
})

const heartbeatLatestBehavior = computed(() => {
  const events = heartbeatState.value?.behavior_events ?? []
  return events.length ? events[events.length - 1] : null
})

const proactiveSummary = computed(() => {
  if (proactiveState.value?.trigger_reason) return proactiveState.value.trigger_reason
  if (proactiveState.value?.can_proactively_reach_out) return '可主动回应'
  return '当前保持安静'
})

const gaugeList = computed(() => {
  const companion = activeCompanion.value
  if (!companion) return []
  return [
    { key: 'affinity', label: '亲密度', value: companion.affinity_state ?? 0.5 },
    { key: 'trust', label: '信任度', value: companion.trust_state ?? 0.5 },
    { key: 'energy', label: '精力', value: companion.energy_state ?? 1 },
    { key: 'intimacy', label: '相处深度', value: companion.intimacy_state ?? 0.5 },
    { key: 'interruptibility', label: '可打断性', value: companion.interruptibility_state ?? 0.75 },
    { key: 'fatigue', label: '疲劳度', value: companion.fatigue_state ?? 0 },
  ].map((item) => ({
    ...item,
    percent: Math.round(Math.min(100, Math.max(0, item.value * 100))),
    display: `${Math.round(Math.min(100, Math.max(0, item.value * 100)))}%`,
  }))
})

const editForm = ref<{
  name: string
  model_type: string
  model_id: string
  persona_prompt: string
  temperament: string
  attachment_style: string
  support_style: string
  emotion_state: string
  affinity_state: number
  trust_state: number
  energy_state: number
  intimacy_state: number
  interruptibility_state: number
  fatigue_state: number
} | null>(null)

const memoryLayerCount = (key: string) => {
  const value = memoryState.value?.[key as keyof MemoryState]
  return typeof value === 'number' ? value : 0
}

const memoryTotal = computed(() => memoryLayers.reduce((sum, layer) => sum + memoryLayerCount(layer.key), 0))

const signalSummaryItems = computed(() =>
  Object.entries(signalSummary.value)
    .filter(([, count]) => Number(count) > 0)
    .map(([kind, count]) => ({ kind, count })),
)

const recentSignals = computed<RecentSignal[]>(() => (memoryState.value?.recent_signals ?? []).slice(0, 4))

const updateVisionSettings = (patch: Partial<WorkspaceVisionSettings>) => {
  workspaceStore.updateWorkspaceContext(activeWorkspaceId.value, {
    vision: { ...visionSettings.value, ...patch },
  })
}

const setVisionEnabled = (value: boolean) => updateVisionSettings({ enabled: Boolean(value) })
const setVisionDisplay = (value: number) => updateVisionSettings({ displayIndex: Number(value) || 0 })
const setVisionInterval = (value: number) => updateVisionSettings({ intervalMs: Number(value) || 5000 })
const setVisionPauseWhenHidden = (value: boolean) => updateVisionSettings({ pauseWhenAppHidden: Boolean(value) })
const setVisionCaptureMode = (value: 'display' | 'region') => updateVisionSettings({
  captureMode: value === 'region' ? 'region' : 'display',
})
const setVisionRegionValue = (key: keyof WorkspaceVisionSettings['region'], value: number | undefined) => {
  const minimum = key === 'width' || key === 'height' ? 64 : 0
  updateVisionSettings({
    region: {
      ...visionSettings.value.region,
      [key]: Math.max(minimum, Math.round(Number(value) || minimum)),
    },
  })
}
const setVisionRegion = (region: WorkspaceVisionSettings['region']) => updateVisionSettings({ region })
const addVisionPrivacyMask = (region: WorkspaceVisionSettings['region']) => updateVisionSettings({
  privacyMasks: [...visionSettings.value.privacyMasks, region].slice(0, 8),
})
const removeVisionPrivacyMask = (index: number) => updateVisionSettings({
  privacyMasks: visionSettings.value.privacyMasks.filter((_, itemIndex) => itemIndex !== index),
})
const clearVisionPrivacyMasks = () => updateVisionSettings({ privacyMasks: [] })

const loadVisionDisplays = async () => {
  const displayApi = window.petApi?.screen?.listDisplays
  if (!displayApi) return
  try {
    const displays = await displayApi()
    if (Array.isArray(displays) && displays.length) {
      visionDisplays.value = displays.map((display) => ({
        ...display,
        label: `${display.label}${display.isPrimary ? '（主显示器）' : ''} · ${display.width}×${display.height}`,
      }))
      if (!displays.some((display) => display.index === visionSettings.value.displayIndex)) {
        updateVisionSettings({ displayIndex: displays.find((display) => display.isPrimary)?.index ?? 0 })
      }
    }
  } catch {
    visionDisplays.value = [{ index: 0, id: 0, label: '主显示器', width: 0, height: 0, scaleFactor: 1, isPrimary: true }]
  }
}

const visualPerceptionPhaseLabel = computed(() => ({
  disabled: '已关闭',
  waiting: '等待连接',
  capturing: '正在采样',
  ready: '后端已接收',
  error: '视觉不可用',
}[systemStore.visualPerceptionPhase] || '等待连接'))

const visualPerceptionLastFrameLabel = computed(() => {
  if (systemStore.visualPerceptionError) return systemStore.visualPerceptionError
  if (!systemStore.visualPerceptionLastFrameAt) return '尚无已确认画面'
  return `最近确认 ${new Date(systemStore.visualPerceptionLastFrameAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`
})

const visualPerceptionSummary = computed(() => {
  if (!visionSettings.value.enabled) return '画面输入已停止'
  const display = visionDisplays.value.find((item) => item.index === visionSettings.value.displayIndex)
  return `${display?.label || `显示器 ${visionSettings.value.displayIndex + 1}`} · ${visionSettings.value.intervalMs / 1000}s`
})

const readinessItems = computed<Array<{ key: string; label: string; value: string; state: ReadinessState }>>(() => [
  {
    key: 'runtime',
    label: 'Agent 联动',
    value: runtimeSyncLabel.value,
    state: runtimeSyncError.value ? 'warn' : lastRuntimeSyncAt.value ? 'ready' : 'idle',
  },
  {
    key: 'persona',
    label: '人格提示词',
    value: activeCompanion.value?.persona_prompt ? '已注入' : '未设置',
    state: activeCompanion.value?.persona_prompt ? 'ready' : 'idle',
  },
  {
    key: 'pet',
    label: '角色模型',
    value: activeCompanion.value?.model_id || '未绑定',
    state: activeCompanion.value?.model_id ? 'ready' : 'idle',
  },
  {
    key: 'memory',
    label: '长期记忆',
    value: `${memoryTotal.value} 条`,
    state: memoryTotal.value > 0 ? 'ready' : 'idle',
  },
  {
    key: 'vision',
    label: '实时视觉',
    value: visualPerceptionPhaseLabel.value,
    state: systemStore.visualPerceptionPhase === 'ready'
      ? 'ready'
      : systemStore.visualPerceptionPhase === 'error'
        ? 'warn'
        : 'idle',
  },
])

const formatDate = (value?: string | null) => {
  if (!value) return '-'
  return value.split('T')[0] || value
}

const normalizeStateValue = (value: unknown, fallback: number) => {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  return Math.min(1, Math.max(0, number))
}

const formatStatePercent = (value: number) => `${Math.round(normalizeStateValue(value, 0) * 100)}%`

const formatOptionalPercent = (value?: number | null) => (value == null ? '-' : formatStatePercent(value))

const isPetControlState = (value: unknown): value is PetControlState =>
  Boolean(value && typeof value === 'object' && 'modelType' in value && 'visible' in value)

const applyPetControlState = (value: unknown) => {
  if (isPetControlState(value)) Object.assign(petRuntimeState, value)
}

const petActionErrorMessage = (error: unknown, fallback: string) => error instanceof Error && error.message ? error.message : fallback

const syncEditForm = () => {
  const companion = activeCompanion.value
  if (!companion) {
    editForm.value = null
    return
  }
  editForm.value = {
    name: companion.name,
    model_type: companion.model_type || 'live2d',
    model_id: companion.model_id || '',
    persona_prompt: companion.persona_prompt || '',
    temperament: companion.temperament || 'warm',
    attachment_style: companion.attachment_style || 'secure',
    support_style: companion.support_style || 'gentle',
    emotion_state: companion.emotion_state || 'neutral',
    affinity_state: normalizeStateValue(companion.affinity_state, 0.5),
    trust_state: normalizeStateValue(companion.trust_state, 0.5),
    energy_state: normalizeStateValue(companion.energy_state, 1),
    intimacy_state: normalizeStateValue(companion.intimacy_state, 0.5),
    interruptibility_state: normalizeStateValue(companion.interruptibility_state, 0.75),
    fatigue_state: normalizeStateValue(companion.fatigue_state, 0),
  }
}

const refreshPetState = async () => {
  if (typeof petControlClient.getState !== 'function') return true
  try {
    applyPetControlState(await petControlClient.getState())
    petQuickError.value = ''
    return true
  } catch (error) {
    petQuickError.value = petActionErrorMessage(error, '无法读取桌宠状态')
    console.warn('读取桌宠状态失败', error)
    return false
  }
}

const runPetQuickAction = async (
  key: PetOperationKey,
  task: () => Promise<unknown>,
  successMessage: string,
) => {
  if (petOperationKey.value) return false
  petOperationKey.value = key
  petQuickError.value = ''
  try {
    applyPetControlState(await task())
    if (!await refreshPetState()) {
      throw new Error(petQuickError.value || '桌宠操作完成，但无法读取最新状态')
    }
    ElMessage.success(successMessage)
    return true
  } catch (error) {
    petQuickError.value = petActionErrorMessage(error, '桌宠操作失败')
    ElMessage.error(petQuickError.value)
    return false
  } finally {
    petOperationKey.value = null
  }
}

const refreshPetStateFromClick = async () => {
  await runPetQuickAction('refresh', async () => {
    if (!await refreshPetState()) {
      throw new Error(petQuickError.value || '无法读取桌宠状态')
    }
  }, '桌宠状态已刷新')
}

const setPetVisible = async (visible: boolean) => {
  await runPetQuickAction('visible', async () => {
    await petControlClient.setVisible(visible)
    petRuntimeState.visible = visible
  }, visible ? '桌宠已显示' : '桌宠已隐藏')
}

const dockPetBottomRight = async () => {
  await runPetQuickAction('dock', () => petControlClient.snapBottomRight(), '桌宠已贴到右下角')
}

const setPetClickThrough = async (enabled: string | number | boolean) => {
  const isEnabled = Boolean(enabled)
  await runPetQuickAction('click-through', () => petControlClient.setClickThrough(isEnabled), isEnabled ? '鼠标穿透已开启' : '鼠标穿透已关闭')
}

const setPetDoNotDisturb = async (enabled: string | number | boolean) => {
  const isEnabled = Boolean(enabled)
  await runPetQuickAction('dnd', () => petControlClient.setDoNotDisturb(isEnabled), isEnabled ? '免打扰已开启' : '免打扰已关闭')
}

const buildRuntimeIdleProfile = () => {
  const profile = buildIdleProfileFromCompanion()
  if (!profile) return null
  return {
    ...profile,
    mood: runtimeMood.value ?? profile.mood,
    relationshipStage: relationshipStage.value ?? profile.relationshipStage,
  }
}

const syncDesktopPetProfile = async () => {
  if (applyingRuntime.value) return
  const syncId = ++runtimeSyncSequence
  applyingRuntime.value = true
  try {
    const ok = await runPetQuickAction('sync-profile', async () => {
      const profile = buildRuntimeIdleProfile()
      if (!profile) throw new Error('没有可同步的桌宠档案')
      await petControlClient.setCompanionIdleProfile(profile)
    }, '桌宠待机画像已同步')
    if (!ok || syncId !== runtimeSyncSequence) return
    runtimeSyncError.value = ''
    lastRuntimeSyncAt.value = new Date().toLocaleTimeString()
    await loadRuntime()
  } finally {
    if (syncId === runtimeSyncSequence) applyingRuntime.value = false
  }
}

const loadRuntime = async () => {
  const companionId = activeCompanion.value?.id
  const requestId = ++runtimeLoadSequence
  if (!companionId) {
    runtime.value = { retrieval_strategy_label: '', retrieval_strategy_layers: [] }
    memoryState.value = null
    signalSummary.value = {}
    proactiveState.value = null
    behaviorProfile.value = null
    relationshipStage.value = null
    relationshipSummaryState.value = null
    heartbeatState.value = null
    runtimeMood.value = null
    return
  }

  try {
    const payload = await systemClient.companionRuntime(12)
    if (requestId !== runtimeLoadSequence || activeCompanion.value?.id !== companionId) return
    runtime.value = {
      retrieval_strategy_label: payload.retrieval_strategy?.label || '',
      retrieval_strategy_layers: payload.retrieval_strategy?.layers || [],
    }
    memoryState.value = payload.memory_state || null
    signalSummary.value = payload.memory_state?.signal_summary ?? {}
    relationshipStage.value = payload.relationship?.summary?.relationship_stage || payload.companion_state?.stage || null
    relationshipSummaryState.value = payload.relationship?.summary || null
    heartbeatState.value = payload.heartbeat || null
    runtimeMood.value = payload.companion_state?.mood || null
    proactiveState.value = payload.companion_state?.proactive_state || null
    behaviorProfile.value = payload.companion_state?.behavior_profile || null
    runtimeSyncError.value = ''
    lastRuntimeSyncAt.value = new Date().toLocaleTimeString()
  } catch (error) {
    if (requestId !== runtimeLoadSequence || activeCompanion.value?.id !== companionId) return
    runtimeSyncError.value = error instanceof Error ? error.message : 'runtime_load_failed'
    console.warn('加载桌宠运行态失败', error)
  }
}

const syncActiveCompanion = async (showMessage = false) => {
  const syncId = ++runtimeSyncSequence
  applyingRuntime.value = true
  try {
    await applyActiveCompanionRuntime()
    if (syncId !== runtimeSyncSequence) return
    runtimeSyncError.value = ''
    lastRuntimeSyncAt.value = new Date().toLocaleTimeString()
    if (showMessage) ElMessage.success('桌宠联动已同步')
  } catch (error) {
    if (syncId !== runtimeSyncSequence) return
    runtimeSyncError.value = error instanceof Error ? error.message : 'runtime_sync_failed'
    console.warn('同步桌宠联动失败', error)
    if (showMessage) ElMessage.error('同步失败')
  } finally {
    if (syncId === runtimeSyncSequence) applyingRuntime.value = false
  }
}

const bindCompanionToWorkspace = async (id: string) => {
  await workspaceClient.update(workspaceStore.activeWorkspaceId, { companion_profile_id: id })
  await workspaceStore.syncFromBackend()
  companionStore.setActiveCompanion(id)
  syncEditForm()
  await syncActiveCompanion()
  await loadRuntime()
}

const switchCompanion = async (id: string) => {
  if (switchingCompanion.value) return
  const alreadyActive = id === companionStore.activeCompanionId
  const alreadyBound = workspaceStore.activeWorkspace.companion_profile_id === id
  if (alreadyActive && alreadyBound) return
  switchingCompanion.value = true
  try {
    await bindCompanionToWorkspace(id)
  } catch (error) {
    console.warn('切换桌宠绑定失败', error)
    ElMessage.error('切换桌宠失败')
  } finally {
    switchingCompanion.value = false
  }
}

const saveCompanion = async () => {
  if (saving.value || !editForm.value || !activeCompanion.value) return
  saving.value = true
  try {
    await companionStore.updateCompanion(activeCompanion.value.id, {
      name: editForm.value.name,
      model_type: editForm.value.model_type,
      model_id: editForm.value.model_id || null,
      persona_prompt: editForm.value.persona_prompt || null,
      temperament: editForm.value.temperament,
      attachment_style: editForm.value.attachment_style,
      support_style: editForm.value.support_style,
      emotion_state: editForm.value.emotion_state || null,
      affinity_state: normalizeStateValue(editForm.value.affinity_state, 0.5),
      trust_state: normalizeStateValue(editForm.value.trust_state, 0.5),
      energy_state: normalizeStateValue(editForm.value.energy_state, 1),
      intimacy_state: normalizeStateValue(editForm.value.intimacy_state, 0.5),
      interruptibility_state: normalizeStateValue(editForm.value.interruptibility_state, 0.75),
      fatigue_state: normalizeStateValue(editForm.value.fatigue_state, 0),
    } satisfies Partial<Omit<CompanionRecord, 'id' | 'created_at' | 'updated_at'>>)
    syncEditForm()
    await syncActiveCompanion()
    await loadRuntime()
    await refreshPetState()
    ElMessage.success('桌宠档案已保存')
  } catch (error) {
    console.warn('保存桌宠档案失败', error)
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const handleCreate = async () => {
  if (creating.value || !createForm.name.trim()) return
  creating.value = true
  try {
    const companion = await companionStore.createCompanion({
      name: createForm.name.trim(),
      model_type: createForm.model_type,
      model_id: createForm.model_id || undefined,
    })
    showCreateDialog.value = false
    Object.assign(createForm, { name: '', model_type: 'live2d', model_id: '' })
    await bindCompanionToWorkspace(companion.id)
    ElMessage.success('桌宠档案已创建')
  } catch (error) {
    console.warn('创建桌宠档案失败', error)
    ElMessage.error('创建失败')
  } finally {
    creating.value = false
  }
}

const handleDelete = async () => {
  if (deletingCompanion.value || !activeCompanion.value || activeCompanion.value.id === 'default') return
  try {
    await ElMessageBox.confirm(`确认删除桌宠档案「${activeCompanion.value.name}」？`, '删除确认', { type: 'warning' })
    deletingCompanion.value = true
    await companionStore.deleteCompanion(activeCompanion.value.id)
    await workspaceStore.syncFromBackend()
    companionStore.setActiveCompanion(workspaceStore.activeWorkspace.companion_profile_id || 'default')
    syncEditForm()
    await syncActiveCompanion()
    await loadRuntime()
    await refreshPetState()
    ElMessage.success('已删除')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    console.warn('删除桌宠档案失败', error)
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  } finally {
    deletingCompanion.value = false
  }
}

const loadCompanionHome = async () => {
  companionLoadError.value = ''
  try {
    await companionStore.loadCompanions()
  } catch (error) {
    companionLoadError.value = error instanceof Error ? error.message : '桌宠档案加载失败'
    runtimeSyncError.value = companionLoadError.value
    console.warn('加载桌宠档案失败', error)
  }

  syncEditForm()
  await syncActiveCompanion()
  await loadRuntime()
  await refreshPetState()
}

watch(activeCompanion, () => {
  syncEditForm()
  void loadRuntime()
  void refreshPetState()
})

onMounted(async () => {
  await loadVisionDisplays()
  await loadCompanionHome()
  runtimeRefreshTimer = window.setInterval(() => {
    void loadRuntime()
  }, 10000)
})

onUnmounted(() => {
  if (runtimeRefreshTimer) window.clearInterval(runtimeRefreshTimer)
})
</script>

<style scoped>
.companion-home {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  color: var(--yui-text);
}

.vision-card {
  display: grid;
  gap: 12px;
}

.vision-control-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: end;
  gap: 12px;
}

.vision-control-grid > label {
  display: grid;
  min-width: 0;
  gap: 6px;
}

.vision-control-grid > label > span {
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 720;
}

.vision-region-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.vision-region-grid > label {
  display: grid;
  min-width: 0;
  gap: 6px;
}

.vision-region-grid > label > span {
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 720;
}

.vision-region-grid :deep(.el-input-number) {
  width: 100%;
}

.vision-region-actions {
  display: flex;
  grid-column: 1 / -1;
  justify-content: flex-end;
}

.vision-privacy-settings {
  display: grid;
  gap: 10px;
  border-top: 1px solid var(--yui-border);
  padding-top: 12px;
}

.vision-privacy-header,
.vision-privacy-header > div,
.vision-privacy-actions,
.vision-privacy-list > div {
  display: flex;
  min-width: 0;
  align-items: center;
}

.vision-privacy-header {
  justify-content: space-between;
  gap: 12px;
}

.vision-privacy-header > div,
.vision-privacy-actions {
  flex-wrap: wrap;
  gap: 8px;
}

.vision-privacy-header > span {
  color: var(--yui-muted);
  font-size: 12px;
}

.vision-privacy-list {
  display: grid;
  gap: 6px;
}

.vision-privacy-list > div {
  min-height: 32px;
  justify-content: space-between;
  gap: 8px;
  border-radius: 6px;
  background: var(--yui-surface-muted);
  padding: 3px 4px 3px 10px;
}

.vision-privacy-list span {
  min-width: 0;
  overflow: hidden;
  color: var(--yui-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vision-switch-field {
  min-height: 56px;
  align-content: end;
  justify-items: start;
}

.vision-status-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  color: var(--yui-muted);
  font-size: 12px;
}

.vision-status-row strong {
  color: var(--yui-text);
}

.vision-status-row > span:last-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vision-status-row .status-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--yui-muted);
}

.vision-status-row.is-ready .status-dot {
  background: #16a34a;
}

.vision-status-row.is-capturing .status-dot {
  background: #2563eb;
}

.vision-status-row.is-error .status-dot {
  background: #dc2626;
}

@media (max-width: 760px) {
  .vision-control-grid,
  .vision-region-grid {
    grid-template-columns: 1fr;
  }
}

.empty-home {
  display: flex;
  min-height: 360px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
}

.empty-card {
  display: flex;
  min-width: min(360px, 100%);
  flex-direction: column;
  gap: 6px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 18px;
  text-align: center;
}

.empty-card strong {
  color: var(--yui-text);
  font-size: 15px;
  font-weight: 850;
}

.empty-card span,
.empty-alert-row span {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.55;
}

.empty-alert {
  width: min(560px, 100%);
}

.empty-alert-row,
.empty-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.empty-alert-row {
  justify-content: space-between;
}

.empty-actions {
  flex-wrap: wrap;
}

.home-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
  gap: 16px;
  min-width: 0;
}

.panel-card,
.quick-action,
.status-pill {
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
}

.card-header,
.gauge-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.card-header h3 {
  margin: 0;
  color: var(--yui-text);
  font-weight: 820;
  letter-spacing: 0;
}

.card-header h3 {
  font-size: 16px;
}

.card-header p,
.status-pill span,
.pet-state-grid span,
.pet-toggle-item span,
.state-grid span,
.signal-item span {
  margin: 0;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.5;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.text-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--yui-accent);
  font-size: 13px;
  font-weight: 760;
  text-decoration: none;
}

.status-strip,
.quick-grid,
.memory-grid,
.pet-state-grid,
.relationship-stat-grid,
.state-grid {
  display: grid;
  gap: 10px;
}

.status-strip {
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
}

.status-pill {
  min-width: 0;
  padding: 11px 12px;
  background: var(--yui-surface-muted);
}

.status-pill strong {
  display: block;
  overflow: hidden;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-pill.is-ready {
  border-color: rgba(34, 197, 94, 0.28);
  background: var(--yui-success-soft);
}

.status-pill.is-warn {
  border-color: rgba(245, 158, 11, 0.34);
  background: var(--yui-warning-soft);
}

.quick-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.pet-quick-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pet-warning {
  border: 1px solid rgba(245, 158, 11, 0.34);
  border-radius: 8px;
  background: var(--yui-warning-soft);
  color: var(--yui-text);
  font-size: 12px;
  line-height: 1.5;
  padding: 9px 10px;
  overflow-wrap: anywhere;
}

.pet-state-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.relationship-stat-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 14px;
}

.relationship-stat-grid article {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface-muted);
  padding: 10px;
}

.relationship-stat-grid span {
  display: block;
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.4;
}

.relationship-stat-grid strong {
  display: block;
  overflow: hidden;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pet-state-grid article {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface-muted);
  padding: 11px 12px;
}

.pet-state-grid strong {
  display: block;
  overflow: hidden;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pet-control-row,
.pet-toggle-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.pet-toggle-row {
  justify-content: space-between;
}

.pet-toggle-item {
  display: inline-flex;
  min-height: 34px;
  min-width: 190px;
  flex: 1 1 190px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
  padding: 7px 10px;
}

.quick-action {
  display: flex;
  min-height: 88px;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  padding: 14px;
  color: var(--yui-text);
  text-decoration: none;
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}

.quick-action:hover {
  border-color: var(--yui-border-strong);
  box-shadow: var(--yui-shadow-hover);
  transform: translateY(-1px);
}

.quick-action .el-icon {
  color: var(--yui-accent);
  font-size: 18px;
}

.quick-action span {
  font-size: 14px;
  font-weight: 800;
}

.left-column,
.right-column {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 16px;
}

.panel-card {
  padding: 16px;
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.companion-select,
.profile-form {
  margin-top: 14px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.state-slider-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.state-slider-item {
  display: block;
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface-muted);
  padding: 10px 12px;
}

.state-slider-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 760;
}

.state-slider-heading strong {
  color: var(--yui-accent);
  font-size: 12px;
}

.full-width {
  width: 100%;
}

.option-meta {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.gauge-list,
.signal-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.gauge-row {
  min-width: 0;
}

.gauge-label {
  margin-bottom: 5px;
  color: var(--yui-text);
  font-size: 13px;
}

.memory-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 14px;
}

.memory-item,
.pet-state-grid article,
.state-grid article {
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface-muted);
  padding: 12px;
}

.memory-item {
  text-align: center;
}

.memory-item strong {
  display: block;
  color: var(--yui-text);
  font-size: 21px;
}

.memory-item span {
  color: var(--yui-muted);
  font-size: 12px;
}

.tag-row {
  margin-top: 12px;
}

.signal-item {
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface-muted);
  padding: 12px;
}

.signal-item div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.signal-item strong,
.state-grid strong {
  color: var(--yui-text);
}

.signal-item p {
  margin: 8px 0 0;
  color: var(--yui-text);
  font-size: 13px;
  line-height: 1.55;
}

.state-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 14px;
}

.state-grid strong {
  display: block;
  margin-top: 4px;
  font-size: 14px;
}

.danger-zone {
  background: var(--yui-danger-soft);
}

@media (max-width: 1180px) {
  .home-layout {
    grid-template-columns: 1fr;
  }

  .quick-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .card-header,
  .gauge-label {
    align-items: flex-start;
    flex-direction: column;
  }

  .status-strip,
  .quick-grid,
  .form-grid,
  .memory-grid,
  .pet-state-grid,
  .relationship-stat-grid,
  .state-grid {
    grid-template-columns: 1fr;
  }

  .pet-toggle-item {
    width: 100%;
  }

}
</style>
