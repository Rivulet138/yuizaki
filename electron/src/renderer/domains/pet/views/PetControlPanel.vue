<template>
  <PanelShell :title="t('petControl.title')" tone="companion">
    <template #actions>
      <el-button :icon="Clock" plain @click="relationshipHistoryVisible = true">{{ t('petControl.relationshipHistory') }}</el-button>
    </template>
    <div class="pet-console">
      <section class="status-strip" :aria-label="t('petControl.statusAria')">
        <article v-for="item in statusCards" :key="item.label" class="status-card">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.detail }}</small>
        </article>
      </section>
      <el-alert v-if="operationMessage" :title="operationMessage" :type="operationAlertType" show-icon @close="operationMessage = ''" />

      <section class="pet-workspace">
        <PetModelManager
          v-model:selected-model-id="selectedModelId"
          v-model:local-model-type="localModelType"
          v-model:source-path="localModelSourcePath"
          :models="catalog.models"
          :current-model="currentModel"
          :source-label="currentModelSourceLabel"
          :capabilities="avatarCapabilities"
          :sync-hint="modelSyncHint"
          :source-placeholder="localModelPlaceholder"
          :loading="operationLoading"
          :pending-action="pendingAction"
          :refreshing="refreshingPet"
          :option-label="modelOptionLabel"
          @apply="applyModel"
          @refresh="refresh"
          @import-picker="oneClickImportModelFolder"
          @browse="pickAndImportLocalModel"
          @import-path="importLocalModel"
          @delete="deleteCurrentLocalModel"
        />

        <PetResidenceControls
          :state="state"
          :display-label="activeDisplayLabel"
          :loading="operationLoading"
          :pending-action="pendingAction"
          @begin-adjustment="enterAdjustmentMode"
          @restore-resident="restoreResidentMode"
          @update-click-through="setClickThrough"
          @update-locked="setLocked"
          @update-dnd="setDoNotDisturb"
        />

        <el-card class="control-card appearance-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>{{ t('petControl.appearance.title') }}</span>
              <el-tag size="small" type="info">{{ scaleDraft.toFixed(2) }} × {{ Math.round(opacityDraft * 100) }}%</el-tag>
            </div>
          </template>
          <label class="field-label">{{ t('petControl.appearance.scale', { value: scaleDraft.toFixed(2) }) }}</label>
          <div class="preset-row" :aria-label="t('petControl.appearance.sizePresetAria')">
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
          <label class="field-label">{{ t('petControl.appearance.opacity', { value: ratioPercent(opacityDraft) }) }}</label>
          <el-slider v-model="opacityDraft" :min="0.1" :max="1" :step="0.05" @change="applyOpacity" />
        </el-card>

        <el-card class="control-card capability-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>{{ t('petControl.capability.title') }}</span>
              <el-tag size="small" :type="avatarCapabilities ? 'success' : 'warning'">
                {{ avatarCapabilities ? t('petControl.capability.synced') : t('petControl.capability.pending') }}
              </el-tag>
            </div>
          </template>
          <div class="capability-summary">
            <span>{{ state.modelType.toUpperCase() }} · {{ currentModel?.name ?? t('petControl.capability.noModel') }}</span>
            <span>{{ t('petControl.capability.status', { value: state.ready ? t('petControl.status.ready') : t('petControl.status.notReady') }) }}</span>
          </div>
          <div v-if="avatarCapabilities" class="capability-tags" :aria-label="t('petControl.capability.actionsAria')">
            <el-tag
              v-for="item in capabilityRows"
              :key="item.key"
              size="small"
              :type="item.enabled ? 'success' : 'info'"
              effect="plain"
            >
              {{ item.label }} {{ item.enabled ? t('petControl.capability.available') : t('petControl.capability.unavailable') }}
            </el-tag>
          </div>
          <div class="button-row">
            <el-button
              plain
              :disabled="!avatarCapabilities?.actions.gaze || operationLoading"
              @click="previewGaze"
            >
              {{ t('petControl.capability.gazeCenter') }}
            </el-button>
            <el-button
              plain
              :disabled="!avatarCapabilities?.actions.cancel || operationLoading"
              @click="cancelAvatarActions"
            >
              {{ t('petControl.capability.stopAction') }}
            </el-button>
            <el-button plain :loading="refreshingPet" @click="refresh">{{ t('petControl.capability.sync') }}</el-button>
          </div>
        </el-card>

        <details class="pet-advanced-controls">
          <summary>{{ t('pet.advanced.modelAndLipSync') }}</summary>
        <el-card class="control-card lipsync-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>{{ t('petControl.lipSync.title') }}</span>
              <el-tag size="small" type="info">{{ currentModel?.name ?? t('petControl.lipSync.currentModel') }}</el-tag>
            </div>
          </template>
          <label class="field-label">{{ t('petControl.lipSync.gain', { value: lipSyncDraft.gain.toFixed(1) }) }}</label>
          <el-slider v-model="lipSyncDraft.gain" :min="0.5" :max="12" :step="0.1" />
          <label class="field-label">{{ t('petControl.lipSync.noiseGate', { value: lipSyncDraft.noiseGate.toFixed(3) }) }}</label>
          <el-slider v-model="lipSyncDraft.noiseGate" :min="0" :max="0.1" :step="0.001" />
          <label class="field-label">{{ t('petControl.lipSync.maxOpen', { value: lipSyncDraft.maxOpen.toFixed(2) }) }}</label>
          <el-slider v-model="lipSyncDraft.maxOpen" :min="0.1" :max="1" :step="0.05" />
          <label class="field-label">{{ t('petControl.lipSync.attack', { value: lipSyncDraft.attack.toFixed(2) }) }}</label>
          <el-slider v-model="lipSyncDraft.attack" :min="0.05" :max="1" :step="0.05" />
          <label class="field-label">{{ t('petControl.lipSync.release', { value: lipSyncDraft.release.toFixed(2) }) }}</label>
          <el-slider v-model="lipSyncDraft.release" :min="0.05" :max="1" :step="0.05" />
          <div class="button-row">
            <el-button type="primary" plain :loading="operationLoading" @click="applyLipSyncProfile">{{ t('petControl.lipSync.apply') }}</el-button>
            <el-button plain :disabled="operationLoading" @click="resetLipSyncProfile">{{ t('petControl.lipSync.reset') }}</el-button>
          </div>
        </el-card>


        <el-card class="control-card manifest-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>{{ t('petControl.manifest.title') }}</span>
              <el-tag size="small" type="info">{{ currentModel?.type.toUpperCase() ?? t('petControl.manifest.modelFallback') }}</el-tag>
            </div>
          </template>
          <div class="model-meta">
            <span>{{ t('petControl.manifest.expressions', { count: currentManifest?.expressions.length ?? 0 }) }}</span>
            <span>{{ t('petControl.manifest.parameters', { count: currentManifest?.parameterControls.length ?? 0 }) }}</span>
            <span>{{ t('petControl.manifest.motionGroups', { count: Object.keys(currentManifest?.motions ?? {}).length }) }}</span>
          </div>
          <el-input
            :model-value="currentModel?.promptContext ?? ''"
            type="textarea"
            :rows="5"
            readonly
            :placeholder="t('petControl.manifest.emptyContext')"
          />
          <div class="button-row">
            <el-button plain :disabled="!currentModel?.promptContext" @click="copyPromptContext">{{ t('petControl.manifest.copy') }}</el-button>
          </div>
        </el-card>

        <el-card class="control-card expression-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>{{ t('petControl.expression.title') }}</span>
            </div>
          </template>
          <label class="field-label">{{ t('petControl.expression.emotionPreset') }}</label>
          <el-select v-model="selectedEmotionId" class="full-field" filterable :placeholder="t('petControl.expression.emptyEmotionPreset')" :disabled="emotionOptions.length === 0">
            <el-option
              v-for="emotion in emotionOptions"
              :key="emotion.id"
              :label="emotionOptionLabel(emotion)"
              :value="emotion.id"
            />
          </el-select>
          <div class="button-row">
            <el-button type="primary" plain :disabled="!selectedEmotionId" @click="previewEmotionPreset">{{ t('petControl.expression.playEmotionPreset') }}</el-button>
          </div>

          <label class="field-label">{{ t('petControl.expression.mix') }}</label>
          <el-select v-model="selectedExpressionId" class="full-field" filterable :placeholder="t('petControl.selectPlaceholder')">
            <el-option
              v-for="expression in expressionOptions"
              :key="expression.id"
              :label="expression.label"
              :value="expression.id"
            />
          </el-select>
          <label class="field-label">{{ t('petControl.expression.weight', { value: ratioPercent(expressionWeight) }) }}</label>
          <el-slider v-model="expressionWeight" :min="0" :max="1" :step="0.05" />
          <div class="button-row">
            <el-button type="primary" :disabled="!selectedExpressionId" @click="previewExpressionMix">{{ t('petControl.expression.preview') }}</el-button>
          </div>

          <label class="field-label">{{ t('petControl.expression.parameterOverride') }}</label>
          <el-select v-model="selectedParameterId" class="full-field" filterable :placeholder="t('petControl.selectPlaceholder')">
            <el-option
              v-for="parameter in parameterOptions"
              :key="parameter.id"
              :label="parameter.label"
              :value="parameter.id"
            />
          </el-select>
          <label class="field-label">{{ t('petControl.expression.parameterValue', { value: parameterValue.toFixed(2) }) }}</label>
          <el-slider v-model="parameterValue" :min="selectedParameterRange.min" :max="selectedParameterRange.max" :step="selectedParameterStep" />
          <div class="button-row">
            <el-button plain :disabled="!selectedParameterId" @click="previewParameterOverride">{{ t('petControl.expression.previewParameter') }}</el-button>
          </div>
        </el-card>
        </details>

        <el-card class="control-card motion-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>{{ t('petControl.motion.title') }}</span>
              <el-tag size="small" type="info">{{ state.placement === 'free' ? t('petControl.motion.free') : placementLabel(state.placement) }}</el-tag>
            </div>
          </template>
          <label class="field-label">{{ t('petControl.motion.preview') }}</label>
          <el-select v-model="selectedMotionId" class="full-field" filterable :placeholder="t('petControl.selectPlaceholder')">
            <el-option
              v-for="motion in motionOptions"
              :key="motion.id"
              :label="motion.label"
              :value="motion.id"
            />
          </el-select>
          <div class="button-row">
            <el-button plain :disabled="!selectedMotionId" @click="previewMotion">{{ t('petControl.motion.play') }}</el-button>
          </div>

          <label class="field-label">{{ t('petControl.motion.anchor') }}</label>
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
            <el-button plain :disabled="state.locked" @click="applyPosition">{{ t('petControl.motion.saveAnchor') }}</el-button>
            <el-button plain :loading="refreshingPet" :disabled="refreshingPet" @click="refresh">{{ t('petControl.motion.refresh') }}</el-button>
          </div>
          <label class="field-label">{{ t('petControl.motion.screenDock') }}</label>
          <div class="form-grid compact-grid">
            <el-select v-model="selectedDisplayId" class="full-field" :placeholder="t('petControl.motion.selectDisplay')">
              <el-option :label="defaultDisplayLabel" :value="null" />
              <el-option v-for="display in displayOptions" :key="display.id" :label="displayOptionLabel(display)" :value="display.id" />
            </el-select>
            <el-select v-model="selectedPlacement" class="full-field" :placeholder="t('petControl.motion.selectPlacement')">
              <el-option v-for="option in placementOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </div>
          <div class="button-row">
            <el-button type="primary" plain @click="applyPlacement">{{ t('petControl.motion.applyPlacement') }}</el-button>
          </div>
        </el-card>

        <details class="pet-advanced-controls">
          <summary>{{ t('pet.advanced.behaviorAndRecovery') }}</summary>
        <el-card class="control-card behavior-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>{{ t('petControl.behavior.title') }}</span>
            </div>
          </template>
          <label class="field-label">{{ t('petControl.behavior.state') }}</label>
          <el-select v-model="selectedBehaviorState" class="full-field" :placeholder="t('petControl.behavior.selectState')">
            <el-option v-for="option in behaviorStateOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <div class="button-row">
            <el-button plain @click="applyBehaviorState">{{ t('petControl.behavior.save') }}</el-button>
          </div>
          <div class="form-grid compact-grid">
            <el-input v-model="idleProfileDraft.mood" :placeholder="t('petControl.behavior.moodPlaceholder')" clearable />
            <el-input v-model="idleProfileDraft.supportStyle" :placeholder="t('petControl.behavior.supportStylePlaceholder')" clearable />
            <el-input v-model="idleProfileDraft.relationshipStage" :placeholder="t('petControl.behavior.relationshipStagePlaceholder')" clearable />
            <el-input v-model="idleProfileDraft.relationshipTrend" :placeholder="t('petControl.behavior.relationshipTrendPlaceholder')" clearable />
          </div>
          <div class="form-grid compact-grid">
            <label class="field-label">{{ t('petControl.behavior.energy', { value: ratioPercent(idleProfileDraft.energy) }) }}</label>
            <el-slider v-model="idleProfileDraft.energy" :min="0" :max="1" :step="0.05" />
            <label class="field-label">{{ t('petControl.behavior.affinity', { value: ratioPercent(idleProfileDraft.affinity) }) }}</label>
            <el-slider v-model="idleProfileDraft.affinity" :min="0" :max="1" :step="0.05" />
            <label class="field-label">{{ t('petControl.behavior.trust', { value: ratioPercent(idleProfileDraft.trust) }) }}</label>
            <el-slider v-model="idleProfileDraft.trust" :min="0" :max="1" :step="0.05" />
            <label class="field-label">{{ t('petControl.behavior.intimacy', { value: ratioPercent(idleProfileDraft.intimacy) }) }}</label>
            <el-slider v-model="idleProfileDraft.intimacy" :min="0" :max="1" :step="0.05" />
          </div>
          <div class="button-row">
            <el-button type="primary" plain @click="applyIdleProfile">{{ t('petControl.behavior.saveProfile') }}</el-button>
          </div>
        </el-card>
        <el-card class="control-card recovery-card" shadow="never">
          <template #header>
            <div class="card-heading">
              <span>{{ t('petControl.recovery.title') }}</span>
              <el-tag size="small" :type="state.ready ? 'success' : 'warning'">{{ state.ready ? t('petControl.status.loaded') : t('petControl.status.notReady') }}</el-tag>
            </div>
          </template>
          <div class="recovery-actions">
            <el-button type="primary" plain @click="dockBottomRight">{{ t('petControl.recovery.dockBottomRight') }}</el-button>
            <el-button plain @click="reloadRenderer">{{ t('petControl.recovery.reloadRenderer') }}</el-button>
            <el-button plain @click="showPet">{{ t('petControl.recovery.show') }}</el-button>
            <el-button plain @click="hidePet">{{ t('petControl.recovery.hide') }}</el-button>
          </div>
          <label class="field-label">{{ t('petControl.recovery.audioUrl') }}</label>
          <div class="model-import-row">
            <el-input v-model="lipSyncAudioUrl" :placeholder="t('petControl.recovery.audioUrlPlaceholder')" clearable />
            <el-button plain :disabled="!lipSyncAudioUrl.trim()" @click="startLipSync">{{ t('petControl.recovery.startLipSync') }}</el-button>
            <el-button plain @click="stopLipSync">{{ t('petControl.recovery.stopLipSync') }}</el-button>
          </div>
        </el-card>
        </details>
      </section>
    </div>
  </PanelShell>
  <RelationshipHistoryDrawer v-model="relationshipHistoryVisible" />
</template>

<script setup lang="ts">
import { ElAlert } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElSlider } from 'element-plus'
import 'element-plus/es/components/slider/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import { ElCard } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Clock } from '@element-plus/icons-vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import PetModelManager from '../components/PetModelManager.vue'
import PetResidenceControls from '../components/PetResidenceControls.vue'
import RelationshipHistoryDrawer from '../components/RelationshipHistoryDrawer.vue'
import { t } from '@/i18n'
import { petControl, type PetBehaviorState } from '@/utils/petControl'
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
import { AVATAR_COMMAND_VERSION, type AvatarAction, type AvatarCapabilitySnapshot, type AvatarCommand } from '../../../../shared/avatar-command'

type PlacementPreset = Exclude<PetPlacement, 'free'>

const state = reactive<PetControlState>({ ...DEFAULT_PET_CONTROL_STATE })
const catalog = reactive<PetModelCatalogPayload>({ activeModelId: null, models: [] })
const avatarCapabilities = ref<AvatarCapabilitySnapshot | null>(null)
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
const pendingAction = ref<string | null>(null)
const refreshingPet = ref(false)
const hasLoadedState = ref(false)
const operationMessage = ref('')
const operationAlertType = ref<'success' | 'warning' | 'info' | 'error'>('info')
const relationshipHistoryVisible = ref(false)
const modelSourceLabels = {
  bundled: 'petControl.modelSource.bundled',
  local: 'petControl.modelSource.local',
  plugin: 'petControl.modelSource.plugin',
} as const
const ratioPercent = (value: number) => `${Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 100)}%`
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
    ? t('petControl.model.placeholderLive2d')
    : t('petControl.model.placeholderVrm')
))
const modelSourceLabel = (model: Pick<PetModelDefinition, 'source'>): string =>
  t(model.source ? modelSourceLabels[model.source] : 'petControl.modelSource.bundled')
const modelOptionLabel = (model: PetModelDefinition): string =>
  `${model.name} · ${model.type.toUpperCase()} · ${modelSourceLabel(model)}`
const currentModelSourceLabel = computed(() => currentModel.value ? modelSourceLabel(currentModel.value) : t('petControl.modelSource.none'))
const modelSyncHint = computed(() => {
  if (!state.modelId || !currentModel.value || state.modelId === currentModel.value.id) {
    return ''
  }
  return t('petControl.model.syncFallback', { name: currentModel.value.name })
})

const currentManifest = computed(() => currentModel.value?.manifest ?? null)
const expressionOptions = computed(() => currentManifest.value?.expressions ?? [])
const parameterOptions = computed(() => currentManifest.value?.parameterControls ?? [])
const motionOptions = computed(() => currentModel.value?.motions ?? [])
const emotionOptions = computed(() => currentModel.value?.emotions ?? [])
const displayOptions = computed(() => displays.items)
const defaultDisplayLabel = computed(() => {
  const activeDisplay = displays.items.find((display) => display.id === displays.activeDisplayId)
  return activeDisplay
    ? t('petControl.display.defaultWithLabel', { label: displayOptionLabel(activeDisplay) })
    : t('petControl.display.default')
})
const behaviorStateOptions = computed<Array<{ label: string; value: PetBehaviorState }>>(() => [
  { label: t('petControl.behaviorState.idle'), value: 'idle' },
  { label: t('petControl.behaviorState.sleepy'), value: 'sleepy' },
  { label: t('petControl.behaviorState.waiting'), value: 'waiting' },
  { label: t('petControl.behaviorState.curious'), value: 'curious' },
  { label: t('petControl.behaviorState.focused'), value: 'focused' },
  { label: t('petControl.behaviorState.thinking'), value: 'thinking' },
  { label: t('petControl.behaviorState.speaking'), value: 'speaking' },
  { label: t('petControl.behaviorState.reacting'), value: 'reacting' },
  { label: t('petControl.behaviorState.interrupted'), value: 'interrupted' },
])
const capabilityRows = computed(() => {
  const actions = avatarCapabilities.value?.actions
  return [
    { key: 'behavior', label: t('petControl.capabilityRow.behavior'), enabled: Boolean(actions?.behavior) },
    { key: 'affect', label: t('petControl.capabilityRow.affect'), enabled: Boolean(actions?.affect) },
    { key: 'gaze', label: t('petControl.capabilityRow.gaze'), enabled: Boolean(actions?.gaze) },
    { key: 'motion', label: t('petControl.capabilityRow.motion'), enabled: Boolean(actions?.motion) },
    { key: 'expression', label: t('petControl.capabilityRow.expression'), enabled: Boolean(actions?.expression) },
    { key: 'parameterPatch', label: t('petControl.capabilityRow.parameterPatch'), enabled: Boolean(actions?.parameterPatch) },
    { key: 'viseme', label: t('petControl.capabilityRow.viseme'), enabled: Boolean(actions?.viseme) },
  ]
})
const sizePresetOptions = [
  { label: 'S', value: 'small', scale: 0.2 },
  { label: 'M', value: 'medium', scale: 0.42 },
  { label: 'L', value: 'large', scale: 0.5 },
  { label: 'XL', value: 'xlarge', scale: 0.58 },
]
const fallbackPlacementOptions = computed<Array<{ label: string; value: PlacementPreset }>>(() => [
  { label: t('petControl.placement.bottomRight'), value: 'bottom-right' },
  { label: t('petControl.placement.bottomLeft'), value: 'bottom-left' },
  { label: t('petControl.placement.topRight'), value: 'top-right' },
  { label: t('petControl.placement.topLeft'), value: 'top-left' },
  { label: t('petControl.placement.center'), value: 'center' },
])
const placementOptions = computed(() => (
  placementPresets.value.length
    ? placementPresets.value.map((preset) => ({ label: preset.name, value: preset.placement }))
    : fallbackPlacementOptions.value
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
      label: t('petControl.interaction.waitingLabel'),
      strategy: t('petControl.interaction.waitingStrategy'),
      detail: t('petControl.interaction.waitingDetail'),
    }
  }

  if (state.locked) {
    return {
      label: state.clickThrough ? t('petControl.interaction.focusLabel') : t('petControl.interaction.lockedLabel'),
      strategy: state.clickThrough ? t('petControl.interaction.clickThroughStrategy') : t('petControl.interaction.lockedStrategy'),
      detail: state.interactMode ? t('petControl.interaction.lockedDetailInteract') : t('petControl.interaction.lockedDetail'),
    }
  }

  if (state.clickThrough) {
    return {
      label: t('petControl.interaction.passiveLabel'),
      strategy: t('petControl.interaction.clickThroughStrategy'),
      detail: state.interactMode ? t('petControl.interaction.passiveDetailInteract') : t('petControl.interaction.passiveDetail'),
    }
  }

  if (state.interactMode) {
    return {
      label: t('petControl.interaction.adjustLabel'),
      strategy: t('petControl.interaction.adjustStrategy'),
      detail: t('petControl.interaction.adjustDetail'),
    }
  }

  return {
    label: t('petControl.interaction.interactiveLabel'),
    strategy: t('petControl.interaction.interactiveStrategy'),
    detail: t('petControl.interaction.interactiveDetail'),
  }
})

const formatCoordinate = (value: number | null) => (typeof value === 'number' ? Math.round(value).toString() : t('petControl.status.auto'))

const placementLabel = (value: PetPlacement) => placementOptions.value.find((option) => option.value === value)?.label ?? t('petControl.placement.freePosition')

const displayOptionLabel = (display: PetDisplayInfo) => {
  const size = `${Math.round(display.workArea.width)}×${Math.round(display.workArea.height)}`
  const index = displays.items.findIndex((item) => item.id === display.id)
  const label = index >= 0
    ? t('petControl.display.screen', { index: index + 1 })
    : display.label.replace(/\s*Primary\s*/i, '').replace(/\s*\([^)]*\)\s*$/, '').trim() || t('petControl.display.screenFallback')
  return `${label}${display.primary ? t('petControl.display.primary') : ''} · ${size}`
}

const activeDisplayLabel = computed(() => {
  const displayId = state.displayId ?? displays.activeDisplayId
  const display = displays.items.find((item) => item.id === displayId)
  return display ? displayOptionLabel(display) : t('petControl.display.default')
})

const emotionOptionLabel = (emotion: PetEmotionPreset) =>
  t('petControl.expression.emotionOption', { label: emotion.label, motions: emotion.motions.length, expressions: emotion.expressions.length })

const statusCards = computed(() => [
  {
    label: t('petControl.card.layer'),
    value: state.ready ? t('petControl.status.loaded') : hasLoadedState.value ? t('petControl.status.notReady') : t('petControl.status.loading'),
    detail: currentModel.value?.name ?? t('petControl.card.waitingManifest'),
  },
  {
    label: t('petControl.card.mouseStrategy'),
    value: effectiveInteraction.value.strategy,
    detail: effectiveInteraction.value.detail,
  },
  {
    label: t('petControl.appearance.title'),
    value: `${state.scale.toFixed(2)} × ${Math.round(state.opacity * 100)}%`,
    detail: t('petControl.card.anchorDetail', { x: formatCoordinate(state.positionX), y: formatCoordinate(state.positionY) }),
  },
  {
    label: t('petControl.card.dockPosition'),
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
  if (message.includes('Local model not found') || message.includes('Local VRM asset not found') || message.includes('Local model asset not found')) {
    return t('petControl.error.modelNotFoundSuffix', { message, hint: t('petControl.model.refreshHint') })
  }
  if (message.includes('FileReferences.Moc')) {
    return t('petControl.error.live2dMissingMoc')
  }
  if (message.includes('FileReferences.Textures')) {
    return t('petControl.error.live2dMissingTextures')
  }
  if (message.includes('missing or unsafe referenced assets')) {
    return message.replace(
      'Live2D model has missing or unsafe referenced assets:',
      t('petControl.error.live2dUnsafeAssets'),
    )
  }
  if (message.includes('model directory is outside the model library')) {
    return t('petControl.error.live2dOutsideLibrary')
  }
  if (message.includes('No .model3.json file found')) {
    return t('petControl.error.noModel3Json')
  }
  if (message.includes('Choose a Live2D .model3.json file')) {
    return t('petControl.error.chooseModel3Json')
  }
  if (message.includes('Local model path does not exist')) {
    return t('petControl.error.localModelMissing')
  }
  if (message.includes('Imported model was copied, but it could not be indexed')) {
    return t('petControl.error.importIndexFailed')
  }
  return message
}

const runPetOperation = async <T,>(
  task: () => Promise<T>,
  successMessage?: string,
  failureMessage = t('petControl.error.operationFailed'),
  action = 'other',
): Promise<T | null> => {
  if (operationLoading.value) return null
  operationLoading.value = true
  pendingAction.value = action
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
    pendingAction.value = null
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

const showPetLayerAfterModelChange = async (failureMessage = t('petControl.error.showLayerFailed')) => {
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
    const [nextState, nextCatalog, nextDisplays, nextPresets, nextCapabilities] = await Promise.all([
      petControl.getState(),
      petControl.getCatalog(),
      petControl.getDisplays(),
      typeof petControl.getPlacementPresets === 'function'
        ? petControl.getPlacementPresets().catch((error) => {
            console.warn(t('petControl.log.loadPresetsFailed'), error)
            return null
          })
        : Promise.resolve(null),
      typeof petControl.getAvatarCapabilities === 'function'
        ? petControl.getAvatarCapabilities().catch(() => null)
        : Promise.resolve(null),
    ])
    if (requestId !== refreshSequence) return
    Object.assign(state, nextState)
    catalog.activeModelId = nextCatalog.activeModelId
    catalog.models = nextCatalog.models
    displays.activeDisplayId = nextDisplays.activeDisplayId
    displays.items = nextDisplays.displays
    avatarCapabilities.value = nextCapabilities?.capabilities ?? null
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
    operationMessage.value = errorMessage(error, t('petControl.error.stateReadFailed'))
    ElMessage.error(operationMessage.value)
  } finally {
    if (requestId === refreshSequence) refreshingPet.value = false
  }
}

const applyModel = async () => {
  if (!selectedModelId.value) return
  const result = await runPetOperation(
    () => petControl.setModel(selectedModelId.value),
    t('petControl.success.modelSwitched'),
    t('petControl.error.modelSwitchFailed'),
    'model-apply',
  )
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
    t('petControl.success.lipSyncApplied'),
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
  applyState(await runPetOperation(() => petControl.setScale(scale), t('petControl.success.sizePresetApplied')))
}

const setDoNotDisturb = async (enabled: string | number | boolean) => {
  const isEnabled = Boolean(enabled)
  applyState(await runPetOperation(
    () => petControl.setDoNotDisturb(isEnabled),
    // eslint-disable-next-line no-extra-boolean-cast -- keep the status branch tied to the normalized boolean value.
    Boolean(enabled) ? t('petControl.success.dndOn') : t('petControl.success.dndOff'),
    t('petControl.error.dndFailed'),
    'dnd',
  ))
}

const importLocalModel = async (sourceOverride?: string, modelTypeOverride?: PetImportableModelType) => {
  const sourcePath = (sourceOverride ?? localModelSourcePath.value).trim()
  const modelType = modelTypeOverride ?? localModelType.value
  if (!sourcePath) {
    ElMessage.warning(
      modelType === 'live2d'
        ? t('petControl.warning.live2dPathRequired')
        : t('petControl.warning.vrmPathRequired'),
    )
    return
  }
  const result = await runPetOperation(
    () => petControl.importLocalModel(sourcePath, modelType),
    modelType === 'live2d' ? t('petControl.success.live2dImported') : t('petControl.success.vrmImported'),
    t('petControl.error.modelImportFailed'),
    'model-import',
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
    t('petControl.error.modelFolderImportFailed'),
    'model-import',
  )
  if (!result || result.canceled) return
  applyModelImportResult(result)
  await showPetLayerAfterModelChange()
  await refresh()
  operationAlertType.value = 'success'
  operationMessage.value = result.modelType === 'vrm'
    ? t('petControl.success.vrmImportedAndShown')
    : t('petControl.success.live2dImportedAndShown')
  ElMessage.success(operationMessage.value)
}

const pickAndImportLocalModel = async () => {
  const picked = await runPetOperation(
    () => petControl.pickLocalModel(localModelType.value),
    undefined,
    t('petControl.error.pickerFailed'),
    'model-browse',
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
      t('petControl.model.deleteConfirm', { name: model.name }),
      t('petControl.model.deleteTitle'),
      {
        confirmButtonText: t('petControl.model.deleteConfirmButton'),
        cancelButtonText: t('petControl.action.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const result = await runPetOperation(
    () => petControl.deleteLocalModel(model.id),
    t('petControl.success.modelDeleted'),
    t('petControl.error.modelDeleteFailed'),
    'model-delete',
  )
  if (!result) return
  applyState(result.state)
  catalog.activeModelId = result.catalog.activeModelId
  catalog.models = result.catalog.models
  syncDrafts()
  await showPetLayerAfterModelChange(t('petControl.error.modelDeletedShowFailed'))
  await refresh()
}

const previewExpressionMix = async () => {
  if (!selectedExpressionId.value) return
  await runPetOperation(() => petControl.triggerExpressionMix({
    expressions: [{ expression: selectedExpressionId.value, weight: expressionWeight.value }],
    intensity: expressionWeight.value,
    durationMs: 1800,
  }), t('petControl.success.expressionMixSent'))
}

const previewEmotionPreset = async () => {
  if (!selectedEmotionId.value) return
  await runPetOperation(() => petControl.triggerEmotion(selectedEmotionId.value), t('petControl.success.emotionPresetSent'))
}

const previewParameterOverride = async () => {
  if (!selectedParameterId.value) return
  await runPetOperation(() => petControl.triggerParameterOverrides({
    expressions: [],
    parameterOverrides: [{ id: selectedParameterId.value, value: parameterValue.value, weight: 1 }],
    intensity: 1,
    durationMs: 1800,
  }), t('petControl.success.parameterOverrideSent'))
}

const previewMotion = async () => {
  const motion = motionOptions.value.find((item) => item.id === selectedMotionId.value)
  if (!motion) return
  await runPetOperation(() => petControl.triggerMotion(motion.group, motion.index), t('petControl.success.motionSent'))
}

const buildAvatarCommand = (action: AvatarAction): AvatarCommand => {
  const now = Date.now()
  const randomId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${now}-${Math.random().toString(16).slice(2)}`
  return {
    version: AVATAR_COMMAND_VERSION,
    id: `ui-${randomId}`,
    streamId: 'ui-pet-control',
    sequence: now,
    issuedAt: now,
    priority: 60,
    interrupt: 'replace',
    ...(avatarCapabilities.value?.revision ? { capabilityRevision: avatarCapabilities.value.revision } : {}),
    actions: [action],
  }
}

const sendAvatarAction = async (action: AvatarAction, successMessage: string) => {
  const capability = avatarCapabilities.value?.actions[action.type]
  if (!capability) {
    ElMessage.info(t('petControl.error.capabilityUnsupported'))
    return
  }
  const result = await runPetOperation(
    () => petControl.triggerAvatarCommand(buildAvatarCommand(action)),
    successMessage,
    t('petControl.error.avatarActionFailed'),
    `avatar-${action.type}`,
  )
  if (result && result.status !== 'completed' && result.status !== 'started' && result.status !== 'accepted') {
    operationAlertType.value = 'warning'
    operationMessage.value = result.message ?? t('petControl.avatar.status', { status: result.status })
  }
}

const previewGaze = async () => {
  await sendAvatarAction({ type: 'gaze', target: { x: 0, y: 0, z: 0 }, strength: 0.8, holdMs: 1800 }, t('petControl.success.gazeSent'))
}

const cancelAvatarActions = async () => {
  await sendAvatarAction({ type: 'cancel' }, t('petControl.success.avatarCancelSent'))
}

const applyPosition = async () => {
  applyState(await runPetOperation(() => petControl.move(positionXDraft.value, positionYDraft.value), t('petControl.success.positionApplied')))
  await refresh()
}

const applyPlacement = async () => {
  applyState(await runPetOperation(() => petControl.place(selectedPlacement.value, selectedDisplayId.value), t('petControl.success.placementApplied')))
  await refresh()
}

const applyBehaviorState = async () => {
  await runPetOperation(() => petControl.setBehaviorState(selectedBehaviorState.value, 1800), t('petControl.success.behaviorStateApplied'))
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
  }), t('petControl.success.idleProfileApplied'))
}

const copyPromptContext = async () => {
  const prompt = currentModel.value?.promptContext
  if (!prompt) return
  await navigator.clipboard.writeText(prompt)
  ElMessage.success(t('petControl.success.promptCopied'))
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
  }, undefined, t('petControl.error.clickThroughFailed'), 'click-through')
  applyState(result)
  if (result !== null) await refresh()
}

const setLocked = async (enabled: string | number | boolean) => {
  applyState(await runPetOperation(
    () => petControl.setLocked(Boolean(enabled)),
    undefined,
    t('petControl.error.lockFailed'),
    'lock',
  ))
}

const enterAdjustmentMode = async () => {
  const result = await runPetOperation(
    () => petControl.beginAdjustment(),
    t('petControl.success.adjustmentEntered'),
    t('petControl.error.adjustmentFailed'),
    'adjustment',
  )
  applyState(result)
  if (result !== null) await refresh()
}

const restoreResidentMode = async () => {
  const result = await runPetOperation(async () => {
    if (state.interactMode) {
      await petControl.completeAdjustment()
    }
    await petControl.setVisible(true)
    await petControl.setLocked(false)
    await petControl.setClickThrough(true)
    return petControl.snapBottomRight()
  }, t('petControl.success.restoreResident'), t('petControl.error.restoreFailed'), 'restore')
  applyState(result)
  if (result !== null) await refresh()
}

const dockBottomRight = async () => {
  applyState(await runPetOperation(() => petControl.snapBottomRight(), t('petControl.success.dockedBottomRight')))
  await refresh()
}

const reloadRenderer = async () => {
  await runPetOperation(() => petControl.reloadRenderer(), t('petControl.success.rendererReloaded'))
  readyRetryCount = 0
  scheduleReadyRetry()
}

const startLipSync = async () => {
  const audioUrl = lipSyncAudioUrl.value.trim()
  if (!audioUrl) {
    ElMessage.warning(t('petControl.warning.audioUrlRequired'))
    return
  }
  await runPetOperation(() => petControl.startLipSync(audioUrl), t('petControl.success.lipSyncStarted'))
}

const stopLipSync = async () => {
  await runPetOperation(() => petControl.stopLipSync(), t('petControl.success.lipSyncStopped'))
}

const showPet = async () => {
  const result = await runPetOperation(() => petControl.setVisible(true), t('petControl.success.petShown'))
  if (result !== null) await refresh()
}

const hidePet = async () => {
  const result = await runPetOperation(() => petControl.setVisible(false), t('petControl.success.petHidden'))
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

.pet-advanced-controls {
  min-width: 0;
}

.pet-advanced-controls > summary {
  cursor: pointer;
  padding: 12px 14px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  color: var(--yui-text);
  font-weight: 760;
}

.pet-advanced-controls[open] > summary {
  margin-bottom: 10px;
}

.pet-advanced-controls > .control-card + .control-card {
  margin-top: 10px;
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

.capability-card {
  background: var(--yui-surface-raised);
}

.capability-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  color: var(--yui-muted);
  font-size: 12px;
}

.capability-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
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
