<template>
  <PanelShell title="桌宠模型与动作" tone="companion">
    <div class="pet-console">
      <section class="status-strip" aria-label="桌宠状态">
        <article v-for="item in statusCards" :key="item.label" class="status-card">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.detail }}</small>
        </article>
      </section>
      <el-alert v-if="operationMessage" :title="operationMessage" :type="operationAlertType" show-icon @close="operationMessage = ''" />

      <section class="pet-workspace">
        <el-card class="control-card model-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>角色模型</span>
              <div class="card-heading__actions">
                <el-tag size="small" :type="catalog.models.length > 0 ? 'success' : 'warning'">{{ catalog.models.length }} 个模型</el-tag>
                <el-button size="small" type="primary" :loading="operationLoading" :disabled="operationLoading || refreshingPet" @click="oneClickImportModelFolder">
                  <el-icon><Upload /></el-icon>
                  <span>导入</span>
                </el-button>
              </div>
            </div>
          </template>
          <el-select v-model="selectedModelId" class="full-field" placeholder="选择模型" :disabled="catalog.models.length === 0 || operationLoading || refreshingPet">
            <el-option v-for="model in catalog.models" :key="model.id" :label="modelOptionLabel(model)" :value="model.id" />
          </el-select>
          <div class="model-meta">
            <span>类型：{{ currentModel?.type.toUpperCase() ?? '未知' }} · {{ currentModelSourceLabel }}</span>
            <span>动作 {{ currentModel?.motions.length ?? 0 }} · 表情 {{ currentModel?.expressions.length ?? 0 }}</span>
          </div>
          <small v-if="modelSyncHint" class="field-hint warning-hint">{{ modelSyncHint }}</small>
          <div class="button-row">
            <el-button type="primary" :loading="operationLoading" :disabled="operationLoading || refreshingPet || !selectedModelId" @click="applyModel">切换模型</el-button>
            <el-button plain :loading="refreshingPet" :disabled="refreshingPet" @click="refresh">刷新</el-button>
          </div>
          <div class="import-mode-row compact-import-row">
            <el-radio-group v-model="localModelType" size="small">
              <el-radio-button label="live2d">Live2D</el-radio-button>
              <el-radio-button label="vrm">VRM</el-radio-button>
            </el-radio-group>
          </div>
          <div class="model-import-row">
            <el-input v-model="localModelSourcePath" :placeholder="localModelPlaceholder" clearable />
            <el-button plain :loading="operationLoading" :disabled="operationLoading || refreshingPet" @click="pickAndImportLocalModel">浏览</el-button>
            <el-button plain :loading="operationLoading" :disabled="operationLoading || refreshingPet" @click="importLocalModel()">导入</el-button>
          </div>
          <div class="button-row">
            <el-button plain type="danger" :loading="operationLoading" :disabled="operationLoading || refreshingPet || currentModel?.source !== 'local'" @click="deleteCurrentLocalModel">删除本地模型</el-button>
          </div>
        </el-card>

        <el-card class="control-card safety-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>桌面驻留</span>
              <el-tag size="small" :type="state.clickThrough ? 'success' : 'info'">{{ state.clickThrough ? '不拦截鼠标' : '可直接操作' }}</el-tag>
            </div>
          </template>
          <div class="switch-row primary-switch">
            <div>
              <strong>鼠标穿透</strong>
            </div>
            <el-switch :model-value="state.clickThrough" inline-prompt active-text="开" inactive-text="关" @change="setClickThrough" />
          </div>
          <div class="switch-row">
            <div>
              <strong>锁定位置</strong>
            </div>
            <el-switch :model-value="state.locked" inline-prompt active-text="锁" inactive-text="解" @change="setLocked" />
          </div>
          <div class="switch-row">
            <div>
              <strong>拖动模式</strong>
            </div>
            <el-switch :model-value="state.interactMode" inline-prompt active-text="开" inactive-text="关" @change="setInteractMode" />
          </div>
          <div class="switch-row">
            <div>
              <strong>免打扰</strong>
            </div>
            <el-switch :model-value="state.doNotDisturb" inline-prompt active-text="开" inactive-text="关" @change="setDoNotDisturb" />
          </div>
          <div class="button-row">
            <el-button type="primary" plain :loading="operationLoading" @click="enterAdjustmentMode">拖动调整</el-button>
            <el-button plain :loading="operationLoading" @click="restoreResidentMode">常驻</el-button>
          </div>
        </el-card>

        <el-card class="control-card appearance-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>外观参数</span>
              <el-tag size="small" type="info">{{ scaleDraft.toFixed(2) }} × {{ Math.round(opacityDraft * 100) }}%</el-tag>
            </div>
          </template>
          <label class="field-label">缩放 {{ scaleDraft.toFixed(2) }}</label>
          <div class="preset-row" aria-label="尺寸预设">
            <el-button
              v-for="option in sizePresetOptions"
              :key="option.value"
              size="small"
              :type="activeSizePreset.value === option.value ? 'primary' : 'default'"
              plain
              @click="applySizePreset(option.scale)"
            >
              {{ option.label }}
            </el-button>
          </div>
          <el-slider v-model="scaleDraft" :min="0.12" :max="0.6" :step="0.01" @change="applyScale" />
          <label class="field-label">透明度 {{ opacityDraft.toFixed(2) }}</label>
          <el-slider v-model="opacityDraft" :min="0.1" :max="1" :step="0.05" @change="applyOpacity" />
        </el-card>

        <el-card class="control-card lipsync-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>口型校准</span>
              <el-tag size="small" type="info">{{ currentModel?.name ?? '当前模型' }}</el-tag>
            </div>
          </template>
          <label class="field-label">增益 {{ lipSyncDraft.gain.toFixed(1) }}</label>
          <el-slider v-model="lipSyncDraft.gain" :min="0.5" :max="12" :step="0.1" />
          <label class="field-label">噪声门 {{ lipSyncDraft.noiseGate.toFixed(3) }}</label>
          <el-slider v-model="lipSyncDraft.noiseGate" :min="0" :max="0.1" :step="0.001" />
          <label class="field-label">张嘴上限 {{ lipSyncDraft.maxOpen.toFixed(2) }}</label>
          <el-slider v-model="lipSyncDraft.maxOpen" :min="0.1" :max="1" :step="0.05" />
          <label class="field-label">开启速度 {{ lipSyncDraft.attack.toFixed(2) }}</label>
          <el-slider v-model="lipSyncDraft.attack" :min="0.05" :max="1" :step="0.05" />
          <label class="field-label">闭合速度 {{ lipSyncDraft.release.toFixed(2) }}</label>
          <el-slider v-model="lipSyncDraft.release" :min="0.05" :max="1" :step="0.05" />
          <div class="button-row">
            <el-button type="primary" plain :loading="operationLoading" @click="applyLipSyncProfile">应用</el-button>
            <el-button plain :disabled="operationLoading" @click="resetLipSyncProfile">恢复默认</el-button>
          </div>
        </el-card>


        <el-card class="control-card manifest-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>Agent 可用模型上下文</span>
              <el-tag size="small" type="info">{{ currentModel?.type.toUpperCase() ?? '模型' }}</el-tag>
            </div>
          </template>
          <div class="model-meta">
            <span>表情 {{ currentManifest?.expressions.length ?? 0 }}</span>
            <span>参数 {{ currentManifest?.parameterControls.length ?? 0 }}</span>
            <span>动作组 {{ Object.keys(currentManifest?.motions ?? {}).length }}</span>
          </div>
          <el-input
            :model-value="currentModel?.promptContext ?? ''"
            type="textarea"
            :rows="5"
            readonly
            placeholder="当前模型没有可注入给 agent 的动作上下文"
          />
          <div class="button-row">
            <el-button plain :disabled="!currentModel?.promptContext" @click="copyPromptContext">复制模型上下文</el-button>
          </div>
        </el-card>

        <el-card class="control-card expression-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>表情与参数</span>
            </div>
          </template>
          <label class="field-label">情绪预设</label>
          <el-select v-model="selectedEmotionId" class="full-field" filterable placeholder="当前模型没有情绪预设" :disabled="emotionOptions.length === 0">
            <el-option
              v-for="emotion in emotionOptions"
              :key="emotion.id"
              :label="emotionOptionLabel(emotion)"
              :value="emotion.id"
            />
          </el-select>
          <div class="button-row">
            <el-button type="primary" plain :disabled="!selectedEmotionId" @click="previewEmotionPreset">触发</el-button>
          </div>

          <label class="field-label">表情混合</label>
          <el-select v-model="selectedExpressionId" class="full-field" filterable placeholder="请选择">
            <el-option
              v-for="expression in expressionOptions"
              :key="expression.id"
              :label="`${expression.label} · ${expression.kind}`"
              :value="expression.id"
            />
          </el-select>
          <label class="field-label">权重 {{ expressionWeight.toFixed(2) }}</label>
          <el-slider v-model="expressionWeight" :min="0" :max="1" :step="0.05" />
          <div class="button-row">
            <el-button type="primary" :disabled="!selectedExpressionId" @click="previewExpressionMix">预览</el-button>
          </div>

          <label class="field-label">参数覆盖</label>
          <el-select v-model="selectedParameterId" class="full-field" filterable placeholder="请选择">
            <el-option
              v-for="parameter in parameterOptions"
              :key="parameter.id"
              :label="`${parameter.label} · ${parameter.id}`"
              :value="parameter.id"
            />
          </el-select>
          <label class="field-label">参数值 {{ parameterValue.toFixed(2) }}</label>
          <el-slider v-model="parameterValue" :min="selectedParameterRange.min" :max="selectedParameterRange.max" :step="selectedParameterStep" />
          <div class="button-row">
            <el-button plain :disabled="!selectedParameterId" @click="previewParameterOverride">预览</el-button>
          </div>
        </el-card>

        <el-card class="control-card motion-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>动作与位置</span>
              <el-tag size="small" type="info">{{ state.placement === 'free' ? '自由' : placementLabel(state.placement) }}</el-tag>
            </div>
          </template>
          <label class="field-label">动作预览</label>
          <el-select v-model="selectedMotionId" class="full-field" filterable placeholder="请选择">
            <el-option
              v-for="motion in motionOptions"
              :key="motion.id"
              :label="motion.label"
              :value="motion.id"
            />
          </el-select>
          <div class="button-row">
            <el-button plain :disabled="!selectedMotionId" @click="previewMotion">播放</el-button>
          </div>

          <label class="field-label">模型锚点</label>
          <div class="position-grid position-grid--labeled">
            <label>
              <span>X</span>
              <el-input-number v-model="positionXDraft" :min="0" :step="10" controls-position="right" />
            </label>
            <label>
              <span>Y</span>
              <el-input-number v-model="positionYDraft" :min="0" :step="10" controls-position="right" />
            </label>
          </div>
          <div class="button-row">
            <el-button plain :disabled="state.locked" @click="applyPosition">应用锚点</el-button>
            <el-button plain :loading="refreshingPet" :disabled="refreshingPet" @click="refresh">同步</el-button>
          </div>
          <label class="field-label">屏幕停靠</label>
          <div class="form-grid compact-grid">
            <el-select v-model="selectedDisplayId" class="full-field" placeholder="选择屏幕">
              <el-option :label="defaultDisplayLabel" :value="null" />
              <el-option v-for="display in displayOptions" :key="display.id" :label="displayOptionLabel(display)" :value="display.id" />
            </el-select>
            <el-select v-model="selectedPlacement" class="full-field" placeholder="停靠位置">
              <el-option v-for="option in placementOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </div>
          <div class="button-row">
            <el-button type="primary" plain @click="applyPlacement">应用停靠</el-button>
          </div>
        </el-card>

        <el-card class="control-card behavior-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>待机人格</span>
            </div>
          </template>
          <label class="field-label">桌宠状态</label>
          <el-select v-model="selectedBehaviorState" class="full-field" placeholder="选择行为状态">
            <el-option v-for="option in behaviorStateOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <div class="button-row">
            <el-button plain @click="applyBehaviorState">应用</el-button>
          </div>
          <div class="form-grid compact-grid">
            <el-input v-model="idleProfileDraft.mood" placeholder="心情，例如轻松、专注" clearable />
            <el-input v-model="idleProfileDraft.supportStyle" placeholder="回应方式，例如安静陪伴" clearable />
            <el-input v-model="idleProfileDraft.relationshipStage" placeholder="关系阶段，例如熟悉期" clearable />
            <el-input v-model="idleProfileDraft.relationshipTrend" placeholder="关系变化，例如升温" clearable />
          </div>
          <div class="form-grid compact-grid">
            <label class="field-label">精力 {{ idleProfileDraft.energy.toFixed(2) }}</label>
            <el-slider v-model="idleProfileDraft.energy" :min="0" :max="1" :step="0.05" />
            <label class="field-label">亲近度 {{ idleProfileDraft.affinity.toFixed(2) }}</label>
            <el-slider v-model="idleProfileDraft.affinity" :min="0" :max="1" :step="0.05" />
            <label class="field-label">信任 {{ idleProfileDraft.trust.toFixed(2) }}</label>
            <el-slider v-model="idleProfileDraft.trust" :min="0" :max="1" :step="0.05" />
            <label class="field-label">亲密度 {{ idleProfileDraft.intimacy.toFixed(2) }}</label>
            <el-slider v-model="idleProfileDraft.intimacy" :min="0" :max="1" :step="0.05" />
          </div>
          <div class="button-row">
            <el-button type="primary" plain @click="applyIdleProfile">同步待机人格</el-button>
          </div>
        </el-card>
        <el-card class="control-card recovery-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>快速恢复</span>
              <el-tag size="small" :type="state.ready ? 'success' : 'warning'">{{ state.ready ? '已加载' : '未就绪' }}</el-tag>
            </div>
          </template>
          <div class="recovery-actions">
            <el-button type="primary" plain @click="dockBottomRight">停靠右下角</el-button>
            <el-button plain @click="reloadRenderer">重新加载 Live2D</el-button>
            <el-button plain @click="showPet">显示桌宠</el-button>
            <el-button plain @click="hidePet">隐藏桌宠</el-button>
          </div>
          <label class="field-label">口型同步音频 URL</label>
          <div class="model-import-row">
            <el-input v-model="lipSyncAudioUrl" placeholder="http(s) 音频地址" clearable />
            <el-button plain :disabled="!lipSyncAudioUrl.trim()" @click="startLipSync">开始口型同步</el-button>
            <el-button plain @click="stopLipSync">停止口型同步</el-button>
          </div>
        </el-card>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { petControl, type PetBehaviorState } from '@/utils/petControl'
import { CONTROL_AUTH_MISSING_MESSAGE, isAuthMissingError } from '@/api/clients/http-client'
import {
  DEFAULT_PET_CONTROL_STATE,
  type PetCompanionIdleProfile,
  type PetControlState,
  type PetDisplayInfo,
  type PetEmotionPreset,
  type PetLipSyncProfile,
  type PetModelCatalogPayload,
  type PetModelDefinition,
  type PetPlacement,
  type PetPlacementPreset,
} from '../../../../shared/pet-control'
import type { PetImportableModelType, PetModelImportMode } from '../../../../shared/resource-manager'

type PlacementPreset = Exclude<PetPlacement, 'free'>

const state = reactive<PetControlState>({ ...DEFAULT_PET_CONTROL_STATE })
const catalog = reactive<PetModelCatalogPayload>({ activeModelId: null, models: [] })
const displays = reactive<{ activeDisplayId: number | null; items: PetDisplayInfo[] }>({ activeDisplayId: null, items: [] })
const placementPresets = ref<PetPlacementPreset[]>([])
const selectedModelId = ref<string | null>(null)
const scaleDraft = ref(DEFAULT_PET_CONTROL_STATE.scale)
const opacityDraft = ref(DEFAULT_PET_CONTROL_STATE.opacity)
const lipSyncDraft = reactive<PetLipSyncProfile>({ ...DEFAULT_PET_CONTROL_STATE.lipSyncProfile })
const localModelType = ref<PetImportableModelType>('live2d')
const localModelSourcePath = ref('')
const selectedExpressionId = ref<string | null>(null)
const expressionWeight = ref(1)
const selectedParameterId = ref<string | null>(null)
const parameterValue = ref(0)
const selectedMotionId = ref<string | null>(null)
const selectedEmotionId = ref<string | null>(null)
const selectedPlacement = ref<PlacementPreset>('bottom-right')
const selectedDisplayId = ref<number | null>(null)
const selectedBehaviorState = ref<PetBehaviorState>('idle')
const idleProfileDraft = reactive<Required<Pick<PetCompanionIdleProfile, 'energy' | 'affinity' | 'trust' | 'intimacy'>> & Pick<PetCompanionIdleProfile, 'mood' | 'supportStyle' | 'relationshipStage' | 'relationshipTrend'>>({
  mood: '',
  supportStyle: '',
  relationshipStage: '',
  relationshipTrend: '',
  energy: 0.5,
  affinity: 0.5,
  trust: 0.5,
  intimacy: 0.5,
})
const positionXDraft = ref(100)
const positionYDraft = ref(100)
const lipSyncAudioUrl = ref('')
const operationLoading = ref(false)
const refreshingPet = ref(false)
const hasLoadedState = ref(false)
const operationMessage = ref('')
const operationAlertType = ref<'success' | 'warning' | 'info' | 'error'>('info')
const petAuthRecoveryHint = '请从 Electron 主窗口进入控制面板；浏览器直开 Vite 地址无法操作桌宠。'
const localModelRefreshHint = '如果模型文件是在资源管理器里删除或补齐的，请点击“刷新”同步列表。'
const modelSourceLabels = {
  bundled: '内置',
  local: '本地',
  plugin: '插件',
} as const
let refreshSequence = 0
let readyRetryTimer: number | null = null
let readyRetryCount = 0

const currentModel = computed(() => {
  const activeId = state.modelId ?? catalog.activeModelId
  return catalog.models.find((model) => model.id === activeId) ?? catalog.models[0] ?? null
})
const activeSizePreset = computed(() =>
  sizePresetOptions.reduce((best, option) =>
    Math.abs(option.scale - state.scale) < Math.abs(best.scale - state.scale) ? option : best,
  sizePresetOptions[1]),
)
const localModelPlaceholder = computed(() => (
  localModelType.value === 'live2d'
    ? '.model3.json、文件夹或 .zip 路径'
    : '.vrm 文件或文件夹路径'
))
const modelSourceLabel = (model: Pick<PetModelDefinition, 'source'>): string =>
  model.source ? modelSourceLabels[model.source] : '内置'
const modelOptionLabel = (model: PetModelDefinition): string =>
  `${model.name} · ${model.type.toUpperCase()} · ${modelSourceLabel(model)}`
const currentModelSourceLabel = computed(() => currentModel.value ? modelSourceLabel(currentModel.value) : '未选择')
const modelSyncHint = computed(() => {
  if (!state.modelId || !currentModel.value || state.modelId === currentModel.value.id) {
    return ''
  }
  return `当前模型不可用，已回退到 ${currentModel.value.name}。`
})

const currentManifest = computed(() => currentModel.value?.manifest ?? null)
const expressionOptions = computed(() => currentManifest.value?.expressions ?? [])
const parameterOptions = computed(() => currentManifest.value?.parameterControls ?? [])
const motionOptions = computed(() => currentModel.value?.motions ?? [])
const emotionOptions = computed(() => currentModel.value?.emotions ?? [])
const displayOptions = computed(() => displays.items)
const defaultDisplayLabel = computed(() => {
  const activeDisplay = displays.items.find((display) => display.id === displays.activeDisplayId)
  return activeDisplay ? `默认屏幕 · ${displayOptionLabel(activeDisplay)}` : '默认屏幕'
})
const behaviorStateOptions: Array<{ label: string; value: PetBehaviorState }> = [
  { label: '待机', value: 'idle' },
  { label: '困倦', value: 'sleepy' },
  { label: '等待', value: 'waiting' },
  { label: '好奇', value: 'curious' },
  { label: '专注', value: 'focused' },
  { label: '思考中', value: 'thinking' },
  { label: '说话中', value: 'speaking' },
  { label: '回应中', value: 'reacting' },
  { label: '被打断后停顿', value: 'interrupted' },
]
const sizePresetOptions = [
  { label: 'S', value: 'small', scale: 0.2 },
  { label: 'M', value: 'medium', scale: 0.28 },
  { label: 'L', value: 'large', scale: 0.4 },
  { label: 'XL', value: 'xlarge', scale: 0.52 },
]
const fallbackPlacementOptions: Array<{ label: string; value: PlacementPreset }> = [
  { label: '右下角', value: 'bottom-right' },
  { label: '左下角', value: 'bottom-left' },
  { label: '右上角', value: 'top-right' },
  { label: '左上角', value: 'top-left' },
  { label: '居中', value: 'center' },
]
const placementOptions = computed(() => (
  placementPresets.value.length
    ? placementPresets.value.map((preset) => ({ label: preset.name, value: preset.placement }))
    : fallbackPlacementOptions
))
const selectedParameter = computed(() => parameterOptions.value.find((item) => item.id === selectedParameterId.value) ?? null)
const selectedParameterRange = computed(() => selectedParameter.value
  ? { min: selectedParameter.value.min, max: selectedParameter.value.max }
  : { min: -1, max: 1 })
const selectedParameterStep = computed(() => {
  const range = selectedParameterRange.value.max - selectedParameterRange.value.min
  return range > 10 ? 1 : 0.05
})

const effectiveInteraction = computed(() => {
  if (!state.ready) {
    return {
      label: '等待渲染',
      strategy: '等待模型',
      detail: '渲染未就绪',
    }
  }

  if (state.locked) {
    return {
      label: state.clickThrough ? '专注常驻' : '锁定守护',
      strategy: state.clickThrough ? '鼠标穿透' : '锁定交互',
      detail: state.interactMode ? '拖动模式已挂起，需先解锁' : '位置已锁定',
    }
  }

  if (state.clickThrough) {
    return {
      label: '穿透常驻',
      strategy: '鼠标穿透',
      detail: state.interactMode ? '拖动模式待命，关闭穿透后生效' : '不拦截主屏幕操作',
    }
  }

  if (state.interactMode) {
    return {
      label: '调整位置',
      strategy: '拖动模式',
      detail: '可拖动和滚轮缩放',
    }
  }

  return {
    label: '可交互',
    strategy: '接收交互',
    detail: '常规点击模式',
  }
})

const formatCoordinate = (value: number | null) => (typeof value === 'number' ? Math.round(value).toString() : '自动')

const placementLabel = (value: PetPlacement) => placementOptions.value.find((option) => option.value === value)?.label ?? '自由位置'

const displayOptionLabel = (display: PetDisplayInfo) => {
  const size = `${Math.round(display.workArea.width)}×${Math.round(display.workArea.height)}`
  const index = displays.items.findIndex((item) => item.id === display.id)
  const label = index >= 0 ? `屏幕 ${index + 1}` : display.label.replace(/\s*Primary\s*/i, '').replace(/\s*\([^)]*\)\s*$/, '').trim() || '屏幕'
  return `${label}${display.primary ? ' · 主屏幕' : ''} · ${size}`
}

const activeDisplayLabel = computed(() => {
  const displayId = state.displayId ?? displays.activeDisplayId
  const display = displays.items.find((item) => item.id === displayId)
  return display ? displayOptionLabel(display) : '默认屏幕'
})

const emotionOptionLabel = (emotion: PetEmotionPreset) =>
  `${emotion.label} · 动作 ${emotion.motions.length} · 表情 ${emotion.expressions.length}`

const statusCards = computed(() => [
  {
    label: '桌宠层',
    value: state.ready ? '已加载' : hasLoadedState.value ? '未就绪' : '加载中',
    detail: currentModel.value?.name ?? '等待模型清单',
  },
  {
    label: '鼠标策略',
    value: effectiveInteraction.value.strategy,
    detail: effectiveInteraction.value.detail,
  },
  {
    label: '外观参数',
    value: `${state.scale.toFixed(2)} × ${Math.round(state.opacity * 100)}%`,
    detail: `锚点 X ${formatCoordinate(state.positionX)} · Y ${formatCoordinate(state.positionY)}`,
  },
  {
    label: '停靠位置',
    value: placementLabel(state.placement),
    detail: activeDisplayLabel.value,
  },
])

const syncDrafts = () => {
  const anchor = resolveAnchorDraft()
  selectedModelId.value = currentModel.value?.id ?? state.modelId ?? catalog.activeModelId
  scaleDraft.value = Number(state.scale.toFixed(2))
  opacityDraft.value = Number(state.opacity.toFixed(2))
  Object.assign(lipSyncDraft, state.lipSyncProfile)
  positionXDraft.value = typeof state.positionX === 'number' ? state.positionX : anchor.x
  positionYDraft.value = typeof state.positionY === 'number' ? state.positionY : anchor.y
  selectedExpressionId.value = expressionOptions.value[0]?.id ?? null
  selectedParameterId.value = parameterOptions.value[0]?.id ?? null
  parameterValue.value = selectedParameter.value ? (selectedParameter.value.min + selectedParameter.value.max) / 2 : 0
  selectedMotionId.value = motionOptions.value[0]?.id ?? null
  selectedEmotionId.value = emotionOptions.value.some((item) => item.id === selectedEmotionId.value)
    ? selectedEmotionId.value
    : emotionOptions.value[0]?.id ?? null
  selectedPlacement.value = state.placement === 'free' ? 'bottom-right' : state.placement
  selectedDisplayId.value = state.displayId ?? displays.activeDisplayId
}

const resolveAnchorDraft = () => {
  const displayId = state.displayId ?? displays.activeDisplayId
  const display = displays.items.find((item) => item.id === displayId) ?? displays.items.find((item) => item.primary)
  const viewportWidth = Math.max(1, Math.round(display?.workArea.width ?? window.screen.availWidth ?? 1280))
  const viewportHeight = Math.max(1, Math.round(display?.workArea.height ?? window.screen.availHeight ?? 720))
  const interactionWidth = viewportWidth * 0.28
  const interactionHeight = viewportHeight * 0.72
  const margin = Math.min(32, Math.max(12, Math.min(viewportWidth, viewportHeight) * 0.04))
  const left = Math.round(interactionWidth / 2 + margin)
  const right = Math.round(viewportWidth - interactionWidth / 2 - margin)
  const top = Math.round(interactionHeight + margin)
  const bottom = Math.round(viewportHeight - margin)
  if (state.placement === 'bottom-left') return { x: left, y: bottom }
  if (state.placement === 'top-right') return { x: right, y: top }
  if (state.placement === 'top-left') return { x: left, y: top }
  if (state.placement === 'center') {
    return {
      x: Math.round(viewportWidth / 2),
      y: Math.round(Math.min(bottom, Math.max(top, viewportHeight / 2 + interactionHeight / 2))),
    }
  }
  return { x: right, y: bottom }
}

const clearReadyRetry = () => {
  if (readyRetryTimer !== null) {
    window.clearTimeout(readyRetryTimer)
    readyRetryTimer = null
  }
}

const scheduleReadyRetry = () => {
  clearReadyRetry()
  if (state.ready || readyRetryCount >= 4) return
  readyRetryCount += 1
  readyRetryTimer = window.setTimeout(async () => {
    readyRetryTimer = null
    try {
      applyState(await petControl.getState())
      if (state.ready) {
        readyRetryCount = 0
      } else {
        scheduleReadyRetry()
      }
      syncDrafts()
    } catch {
      // The main refresh path already shows connection errors.
    }
  }, 500)
}

const errorMessage = (error: unknown, fallback: string): string => {
  const message = error instanceof Error && error.message ? error.message : fallback
  if (isAuthMissingError(error)) {
    return `${CONTROL_AUTH_MISSING_MESSAGE} ${petAuthRecoveryHint}`
  }
  if (message.includes('Local model not found') || message.includes('Local VRM asset not found') || message.includes('Local model asset not found')) {
    return `${message}。${localModelRefreshHint}`
  }
  if (message.includes('FileReferences.Moc')) {
    return 'Live2D 模型缺少 Moc 引用。请检查 .model3.json 中的 FileReferences.Moc，并确认对应 .moc3 文件存在。'
  }
  if (message.includes('FileReferences.Textures')) {
    return 'Live2D 模型缺少贴图引用。请检查 .model3.json 中的 FileReferences.Textures，并确认贴图文件存在。'
  }
  if (message.includes('missing or unsafe referenced assets')) {
    return message.replace(
      'Live2D model has missing or unsafe referenced assets:',
      'Live2D 模型资源不完整或引用路径不安全：',
    )
  }
  if (message.includes('model directory is outside the model library')) {
    return 'Live2D 模型目录不在受管理的模型库内，请重新选择模型文件夹。'
  }
  if (message.includes('No .model3.json file found')) {
    return '所选文件夹中未找到 .model3.json 文件。'
  }
  if (message.includes('Choose a Live2D .model3.json file')) {
    return '请选择 Live2D .model3.json 文件、模型文件夹或 .zip 压缩包。'
  }
  if (message.includes('Local model path does not exist')) {
    return '本地模型路径不存在。'
  }
  if (message.includes('Imported model was copied, but it could not be indexed')) {
    return '模型已复制，但后端资源检查未通过。请确认 .model3.json、Moc 和贴图文件完整后再导入。'
  }
  return message
}

const runPetOperation = async <T,>(
  task: () => Promise<T>,
  successMessage?: string,
  failureMessage = '桌宠操作失败',
): Promise<T | null> => {
  if (operationLoading.value) return null
  operationLoading.value = true
  operationMessage.value = ''
  try {
    const result = await task()
    if (successMessage) {
      operationAlertType.value = 'success'
      operationMessage.value = successMessage
    }
    return result
  } catch (error) {
    operationAlertType.value = 'error'
    operationMessage.value = errorMessage(error, failureMessage)
    ElMessage.error(operationMessage.value)
    return null
  } finally {
    operationLoading.value = false
  }
}

const applyState = (nextState: PetControlState | null | undefined) => {
  if (nextState) Object.assign(state, nextState)
}

const applyModelImportResult = (result: {
  state?: PetControlState
  catalog?: PetModelCatalogPayload
  modelType?: PetModelImportMode
}) => {
  applyState(result.state)
  if (result.catalog) {
    catalog.activeModelId = result.catalog.activeModelId
    catalog.models = result.catalog.models
  }
  if (result.modelType && result.modelType !== 'auto') {
    localModelType.value = result.modelType
  }
  localModelSourcePath.value = ''
  syncDrafts()
}

const showPetLayerAfterModelChange = async (failureMessage = '桌宠模型已更新，但显示桌宠层失败') => {
  try {
    await petControl.setVisible(true)
  } catch (error) {
    operationAlertType.value = 'warning'
    operationMessage.value = errorMessage(error, failureMessage)
    ElMessage.warning(operationMessage.value)
  }
}

const refresh = async () => {
  const requestId = ++refreshSequence
  refreshingPet.value = true
  try {
    const [nextState, nextCatalog, nextDisplays, nextPresets] = await Promise.all([
      petControl.getState(),
      petControl.getCatalog(),
      petControl.getDisplays(),
      typeof petControl.getPlacementPresets === 'function'
        ? petControl.getPlacementPresets().catch((error) => {
            console.warn('读取桌宠停靠预设失败', error)
            return null
          })
        : Promise.resolve(null),
    ])
    if (requestId !== refreshSequence) return
    Object.assign(state, nextState)
    catalog.activeModelId = nextCatalog.activeModelId
    catalog.models = nextCatalog.models
    displays.activeDisplayId = nextDisplays.activeDisplayId
    displays.items = nextDisplays.displays
    hasLoadedState.value = true
    if (nextPresets) {
      placementPresets.value = nextPresets.presets
    }
    syncDrafts()
    if (state.ready) {
      readyRetryCount = 0
      clearReadyRetry()
    } else {
      scheduleReadyRetry()
    }
  } catch (error) {
    if (requestId !== refreshSequence) return
    hasLoadedState.value = true
    operationAlertType.value = 'error'
    operationMessage.value = errorMessage(error, '无法读取桌宠状态')
    ElMessage.error(operationMessage.value)
  } finally {
    if (requestId === refreshSequence) refreshingPet.value = false
  }
}

const applyModel = async () => {
  if (!selectedModelId.value) return
  const result = await runPetOperation(() => petControl.setModel(selectedModelId.value), '模型已切换')
  if (!result) return
  applyState(result)
  await showPetLayerAfterModelChange()
  await refresh()
}

const applyScale = async (value: number | number[]) => {
  const scale = Array.isArray(value) ? value[0] : value
  applyState(await runPetOperation(() => petControl.setScale(scale)))
}

const applyOpacity = async (value: number | number[]) => {
  const opacity = Array.isArray(value) ? value[0] : value
  applyState(await runPetOperation(() => petControl.setOpacity(opacity)))
}

const applyLipSyncProfile = async () => {
  const result = await runPetOperation(
    () => petControl.updateConfig({ lipSyncProfile: { ...lipSyncDraft } }),
    '口型校准已应用',
  )
  applyState(result)
  if (result) Object.assign(lipSyncDraft, result.lipSyncProfile)
}

const resetLipSyncProfile = async () => {
  Object.assign(lipSyncDraft, DEFAULT_PET_CONTROL_STATE.lipSyncProfile)
  await applyLipSyncProfile()
}

const applySizePreset = async (scale: number) => {
  scaleDraft.value = scale
  applyState(await runPetOperation(() => petControl.setScale(scale), '尺寸预设已应用'))
}

const setDoNotDisturb = async (enabled: string | number | boolean) => {
  const isEnabled = Boolean(enabled)
  applyState(await runPetOperation(
    () => petControl.setDoNotDisturb(isEnabled),
    // eslint-disable-next-line no-extra-boolean-cast -- keep the status branch tied to the normalized boolean value.
    Boolean(enabled) ? '免打扰已开启' : '免打扰已关闭',
  ))
}

const importLocalModel = async (sourceOverride?: string, modelTypeOverride?: PetImportableModelType) => {
  const sourcePath = (sourceOverride ?? localModelSourcePath.value).trim()
  const modelType = modelTypeOverride ?? localModelType.value
  if (!sourcePath) {
    ElMessage.warning(modelType === 'live2d' ? '请输入 .model3.json 文件或模型文件夹路径' : '请输入 .vrm 文件路径')
    return
  }
  const result = await runPetOperation(
    () => petControl.importLocalModel(sourcePath, modelType),
    modelType === 'live2d' ? 'Live2D 模型已导入' : 'VRM 模型已导入',
  )
  if (!result) return
  applyModelImportResult(result)
  await showPetLayerAfterModelChange()
  await refresh()
}

const oneClickImportModelFolder = async () => {
  const result = await runPetOperation(
    () => petControl.importLocalModelFromPicker('auto'),
    undefined,
    '模型文件夹导入失败',
  )
  if (!result || result.canceled) return
  applyModelImportResult(result)
  await showPetLayerAfterModelChange()
  await refresh()
  operationAlertType.value = 'success'
  operationMessage.value = result.modelType === 'vrm'
    ? '3D/VRM 模型已导入并切换到桌宠层'
    : 'Live2D 模型已导入并切换到桌宠层'
  ElMessage.success(operationMessage.value)
}

const pickAndImportLocalModel = async () => {
  const picked = await runPetOperation(
    () => petControl.pickLocalModel(localModelType.value),
    undefined,
    '打开模型选择器失败',
  )
  if (!picked || picked.canceled || !picked.sourcePath) return
  localModelSourcePath.value = picked.sourcePath
  await importLocalModel(picked.sourcePath, picked.modelType === 'auto' ? localModelType.value : picked.modelType)
}

const deleteCurrentLocalModel = async () => {
  const model = currentModel.value
  if (!model || model.source !== 'local') return
  try {
    await ElMessageBox.confirm(
      `将从本地模型库删除「${model.name}」，此操作会移除该模型文件并切换到可用模型。`,
      '删除本地模型',
      {
        confirmButtonText: '删除模型',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const result = await runPetOperation(() => petControl.deleteLocalModel(model.id), '本地模型已删除')
  if (!result) return
  applyState(result.state)
  catalog.activeModelId = result.catalog.activeModelId
  catalog.models = result.catalog.models
  syncDrafts()
  await showPetLayerAfterModelChange('本地模型已删除，但显示桌宠层失败')
  await refresh()
}

const previewExpressionMix = async () => {
  if (!selectedExpressionId.value) return
  await runPetOperation(() => petControl.triggerExpressionMix({
    expressions: [{ expression: selectedExpressionId.value, weight: expressionWeight.value }],
    intensity: expressionWeight.value,
    durationMs: 1800,
  }), '表情混合已发送')
}

const previewEmotionPreset = async () => {
  if (!selectedEmotionId.value) return
  await runPetOperation(() => petControl.triggerEmotion(selectedEmotionId.value), '情绪预设已发送')
}

const previewParameterOverride = async () => {
  if (!selectedParameterId.value) return
  await runPetOperation(() => petControl.triggerParameterOverrides({
    expressions: [],
    parameterOverrides: [{ id: selectedParameterId.value, value: parameterValue.value, weight: 1 }],
    intensity: 1,
    durationMs: 1800,
  }), '参数覆盖已发送')
}

const previewMotion = async () => {
  const motion = motionOptions.value.find((item) => item.id === selectedMotionId.value)
  if (!motion) return
  await runPetOperation(() => petControl.triggerMotion(motion.group, motion.index), '动作已发送')
}

const applyPosition = async () => {
  applyState(await runPetOperation(() => petControl.move(positionXDraft.value, positionYDraft.value), '位置已应用'))
  await refresh()
}

const applyPlacement = async () => {
  applyState(await runPetOperation(() => petControl.place(selectedPlacement.value, selectedDisplayId.value), '屏幕停靠已应用'))
  await refresh()
}

const applyBehaviorState = async () => {
  await runPetOperation(() => petControl.setBehaviorState(selectedBehaviorState.value, 1800), '行为状态已应用')
}

const normalizeIdleText = (value: string | null | undefined): string | null => {
  const trimmed = value?.trim()
  return trimmed ? trimmed : null
}

const applyIdleProfile = async () => {
  await runPetOperation(() => petControl.setCompanionIdleProfile({
    mood: normalizeIdleText(idleProfileDraft.mood),
    supportStyle: normalizeIdleText(idleProfileDraft.supportStyle),
    relationshipStage: normalizeIdleText(idleProfileDraft.relationshipStage),
    relationshipTrend: normalizeIdleText(idleProfileDraft.relationshipTrend),
    energy: idleProfileDraft.energy,
    affinity: idleProfileDraft.affinity,
    trust: idleProfileDraft.trust,
    intimacy: idleProfileDraft.intimacy,
  }), '待机画像已应用')
}

const copyPromptContext = async () => {
  const prompt = currentModel.value?.promptContext
  if (!prompt) return
  await navigator.clipboard.writeText(prompt)
  ElMessage.success('提示词上下文已复制')
}

const setClickThrough = async (enabled: string | number | boolean) => {
  const clickThrough = Boolean(enabled)
  const result = await runPetOperation(async () => {
    if (clickThrough) {
      applyState(await petControl.setInteractMode(false))
    } else {
      await petControl.setVisible(true)
    }
    return petControl.setClickThrough(clickThrough)
  })
  applyState(result)
  if (result !== null) await refresh()
}

const setLocked = async (enabled: string | number | boolean) => {
  applyState(await runPetOperation(() => petControl.setLocked(Boolean(enabled))))
}

const setInteractMode = async (enabled: string | number | boolean) => {
  const interactMode = Boolean(enabled)
  const result = await runPetOperation(async () => {
    if (interactMode) {
      await petControl.setVisible(true)
      applyState(await petControl.setLocked(false))
      applyState(await petControl.setClickThrough(false))
    }
    return petControl.setInteractMode(interactMode)
  })
  applyState(result)
  if (result !== null) await refresh()
}

const enterAdjustmentMode = async () => {
  const result = await runPetOperation(async () => {
    await petControl.setVisible(true)
    applyState(await petControl.setLocked(false))
    applyState(await petControl.setClickThrough(false))
    applyState(await petControl.setInteractMode(true))
  }, '已进入拖动调整模式')
  if (result !== null) await refresh()
}

const restoreResidentMode = async () => {
  const result = await runPetOperation(async () => {
    await petControl.setVisible(true)
    applyState(await petControl.setInteractMode(false))
    applyState(await petControl.setLocked(false))
    applyState(await petControl.setClickThrough(true))
    applyState(await petControl.snapBottomRight())
  }, '已恢复穿透常驻')
  if (result !== null) await refresh()
}

const dockBottomRight = async () => {
  applyState(await runPetOperation(() => petControl.snapBottomRight(), '已贴到右下角'))
  await refresh()
}

const reloadRenderer = async () => {
  await runPetOperation(() => petControl.reloadRenderer(), 'Live2D 已请求重新加载')
  readyRetryCount = 0
  scheduleReadyRetry()
}

const startLipSync = async () => {
  const audioUrl = lipSyncAudioUrl.value.trim()
  if (!audioUrl) {
    ElMessage.warning('请输入 http(s) 音频地址')
    return
  }
  await runPetOperation(() => petControl.startLipSync(audioUrl), '口型同步已开始')
}

const stopLipSync = async () => {
  await runPetOperation(() => petControl.stopLipSync(), '口型同步已停止')
}

const showPet = async () => {
  const result = await runPetOperation(() => petControl.setVisible(true), '桌宠已显示')
  if (result !== null) await refresh()
}

const hidePet = async () => {
  const result = await runPetOperation(() => petControl.setVisible(false), '桌宠已隐藏')
  if (result !== null) await refresh()
}

onMounted(() => {
  void refresh()
})

onBeforeUnmount(() => {
  clearReadyRetry()
})
</script>

<style scoped>
.pet-console {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.status-card span,
.model-meta,
.control-card small {
  color: #64748b;
  font-size: 12px;
}

.status-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 10px;
}

.status-card {
  display: flex;
  min-height: 82px;
  flex-direction: column;
  justify-content: space-between;
  padding: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.status-card:hover,
.control-card:hover {
  border-color: var(--yui-border-strong);
  box-shadow: var(--yui-shadow-hover);
}

.status-card strong {
  color: var(--yui-text);
  font-size: 18px;
  line-height: 1.25;
}

.status-card small {
  color: #64748b;
}

.pet-workspace {
  display: grid;
  grid-template-columns: minmax(320px, 0.95fr) minmax(360px, 1.05fr);
  gap: 14px;
  align-items: start;
}

.button-row,
.switch-row,
.card-heading,
.model-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.button-row {
  margin-top: 10px;
  flex-wrap: wrap;
}

.import-mode-row {
  margin-top: 12px;
  padding-top: 2px;
}

.model-import-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 10px;
  margin-top: 12px;
}

.control-card {
  border-radius: var(--yui-radius-card);
  border: 1px solid var(--yui-border);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.control-card :deep(.el-card__header) {
  padding: 12px 14px;
}

.control-card :deep(.el-card__body) {
  padding: 14px;
  min-width: 0;
  overflow: hidden;
}

.control-card :deep(.el-slider) {
  width: calc(100% - 18px);
  margin-inline: 9px;
  min-width: 0;
  max-width: 100%;
  overflow: visible;
}

.model-card,
.recovery-card {
  background: var(--yui-surface-raised);
}

.safety-card {
  background: var(--yui-surface-raised);
}

.appearance-card {
  background: var(--yui-surface-raised);
}

.card-heading {
  justify-content: space-between;
  font-weight: 800;
  min-width: 0;
}

.card-heading__actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.card-heading span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.full-field {
  width: 100%;
}

.model-meta {
  justify-content: space-between;
  margin-top: 10px;
  flex-wrap: wrap;
}

.switch-row {
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--yui-border);
  gap: 16px;
}

.switch-row:last-child {
  border-bottom: 0;
}

.switch-row > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.switch-row :deep(.el-switch) {
  flex: 0 0 auto;
  min-width: 46px;
  justify-content: flex-end;
}

.switch-row :deep(.el-switch__label) {
  display: none;
}

.primary-switch {
  padding-top: 0;
}

.field-label {
  display: block;
  margin: 10px 0 4px;
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 700;
}

.field-hint {
  display: block;
  margin-top: 6px;
}

.warning-hint {
  color: #a16207;
}

.preset-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.preset-row .el-button {
  min-width: 48px;
}

.recovery-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.position-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 10px 0;
}

.position-grid--labeled label {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.position-grid--labeled span {
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 760;
}

@media (max-width: 960px) {
  .pet-workspace,
  .status-strip {
    grid-template-columns: 1fr;
  }

  .model-import-row {
    grid-template-columns: 1fr;
  }

  .model-import-row .el-button {
    width: 100%;
  }
}

@media (max-width: 760px) {
  .pet-console {
    gap: 14px;
  }

  .status-card {
    padding: 12px;
  }

  .position-grid {
    grid-template-columns: 1fr;
  }
}
</style>
