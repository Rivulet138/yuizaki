<template>
  <section class="proactive-settings" :aria-label="t('proactive.title')">
    <div class="section-heading">
      <h3>{{ t('proactive.title') }}</h3>
      <button v-if="controls.policyClosed.value" type="button" class="text-action" @click="load">
        {{ t('proactive.retry') }}
      </button>
    </div>

    <p v-if="controls.loading.value || controls.saving.value" class="policy-status" role="status" aria-live="polite">
      {{ t(controls.saving.value ? 'proactive.status.saving' : 'proactive.status.loading') }}
    </p>
    <p v-else-if="controls.policyClosed.value" class="policy-status policy-status--error" role="alert">
      {{ t('proactive.status.closed') }}
    </p>
    <p v-else class="policy-status" role="status">{{ t('proactive.status.ready') }}</p>

    <label class="control-row">
      <span><strong>{{ t('proactive.enabled') }}</strong><small>{{ t('proactive.enabledHint') }}</small></span>
      <input data-testid="proactive-enabled" type="checkbox" :checked="settings.enabled" :disabled="busy" @change="setBoolean('enabled', $event)" />
    </label>
    <label class="control-row">
      <span><strong>{{ t('proactive.dnd') }}</strong><small>{{ t('proactive.dndHint') }}</small></span>
      <input data-testid="proactive-dnd" type="checkbox" :checked="settings.dnd" :disabled="busy" @change="setBoolean('dnd', $event)" />
    </label>
    <label class="control-row">
      <span><strong>{{ t('proactive.source.completed_turn_followup') }}</strong><small>{{ t('proactive.sourceHint') }}</small></span>
      <input data-testid="proactive-source-completed-turn" type="checkbox" :checked="settings.sourceEnabled.completed_turn_followup" :disabled="busy" @change="setSource($event)" />
    </label>

    <fieldset class="quiet-hours">
      <legend>{{ t('proactive.quiet.enabled') }}</legend>
      <label class="compact-toggle">
        <input data-testid="proactive-quiet-enabled" type="checkbox" :checked="settings.quietHours.enabled" :disabled="busy" @change="setQuietEnabled($event)" />
        <span>{{ t('proactive.quiet.enabled') }}</span>
      </label>
      <div class="field-grid">
        <label><span>{{ t('proactive.quiet.start') }}</span><input data-testid="proactive-quiet-start" type="time" :value="settings.quietHours.start" :disabled="busy" @change="setQuietText('start', $event)" /></label>
        <label><span>{{ t('proactive.quiet.end') }}</span><input data-testid="proactive-quiet-end" type="time" :value="settings.quietHours.end" :disabled="busy" @change="setQuietText('end', $event)" /></label>
      </div>
      <label class="field"><span>{{ t('proactive.quiet.timezone') }}</span><input data-testid="proactive-timezone" type="text" :value="settings.quietHours.timezone" :disabled="busy" @change="setQuietText('timezone', $event)" /></label>
    </fieldset>

    <div class="field-grid numeric-grid">
      <label><span>{{ t('proactive.dailyBudget') }}</span><input data-testid="proactive-daily-budget" type="number" :min="limits.dailyBudget.min" :max="limits.dailyBudget.max" :value="settings.dailyBudget" :disabled="busy" @change="setNumber('dailyBudget', $event)" /></label>
      <label><span>{{ t('proactive.cooldown') }}</span><input data-testid="proactive-cooldown" type="number" :min="limits.cooldownSeconds.min" :max="limits.cooldownSeconds.max" :value="settings.cooldownSeconds" :disabled="busy" @change="setNumber('cooldownSeconds', $event)" /></label>
      <label><span>{{ t('proactive.retention') }}</span><input data-testid="proactive-retention" type="number" :min="limits.retentionDays.min" :max="limits.retentionDays.max" :value="settings.retentionDays" :disabled="busy" @change="setNumber('retentionDays', $event)" /></label>
    </div>

    <div class="opportunity" data-testid="proactive-opportunity">
      <h4>{{ t('proactive.opportunity.title') }}</h4>
      <p v-if="!opportunity" class="empty">{{ t('proactive.opportunity.empty') }}</p>
      <template v-else>
        <dl>
          <div><dt>{{ t('proactive.opportunity.source') }}</dt><dd>{{ sourceLabel(opportunity.sourceKind) }}</dd></div>
          <div><dt>{{ t('proactive.opportunity.reason') }}</dt><dd>{{ reasonLabel(opportunity.triggerReason) }}</dd></div>
          <div><dt>{{ t('proactive.opportunity.expires') }}</dt><dd>{{ formatDate(opportunity.expiresAt) }}</dd></div>
        </dl>
        <div class="feedback-actions" role="group" :aria-label="t('proactive.opportunity.title')">
          <button v-for="kind in feedbackKinds" :key="kind" :ref="kind === 'never_source' ? setNeverButton : undefined" type="button" :data-testid="`proactive-feedback-${kind}`" :disabled="feedbackPending" @click="sendFeedback(kind)">
            {{ t(`proactive.feedback.${kind}`) }}
          </button>
        </div>
      </template>
    </div>

    <div class="frames">
      <div class="section-heading">
        <h4>{{ t('proactive.frames.title') }}</h4>
        <button
          type="button"
          class="text-action"
          data-testid="proactive-frames-rebuild"
          :disabled="controls.rebuilding.value"
          @click="rebuildFrames"
        >
          {{ t(controls.rebuilding.value ? 'proactive.frames.rebuilding' : 'proactive.frames.rebuild') }}
        </button>
      </div>
      <p v-if="!controls.visibleFrames.value.length" class="empty">{{ t('proactive.frames.empty') }}</p>
      <div v-for="frame in controls.visibleFrames.value" :key="frame.frameId" class="frame-row">
        <span><strong>{{ sourceLabel(frame.sourceKind) }}</strong><small>{{ t('proactive.frames.expires') }} {{ formatDate(frame.expiresAt) }}</small></span>
        <button type="button" class="icon-action" :aria-label="t('proactive.frames.delete')" :title="t('proactive.frames.delete')" @click="controls.deleteFrame(frame.frameId)">
          <el-icon aria-hidden="true"><Delete /></el-icon>
        </button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import {
  PROACTIVE_FEEDBACK_KINDS,
  PROACTIVE_SETTINGS_LIMITS,
  type ProactiveFeedbackKind,
  type ProactiveOpportunityIdentity,
  type ProactiveSettingsPatch,
  type ProactiveSource,
} from '@/../shared/proactive'
import { useI18n } from '@/i18n'
import { useProactiveControls } from '../composables/useProactiveControls'

const props = defineProps<{
  visible: boolean
  workspaceId: string
  opportunity: ProactiveOpportunityIdentity | null
}>()

const controls = useProactiveControls()
const { locale, t } = useI18n()
const settings = computed(() => controls.settings.value)
const busy = computed(() => controls.loading.value || controls.saving.value)
const feedbackKinds = PROACTIVE_FEEDBACK_KINDS
const limits = PROACTIVE_SETTINGS_LIMITS
const feedbackPending = computed(() => props.opportunity ? controls.isFeedbackPending(props.opportunity) : false)
let neverButton: HTMLElement | null = null

const setNeverButton = (value: unknown) => {
  neverButton = value instanceof HTMLElement ? value : null
}

const load = () => controls.load()
const checked = (event: Event) => (event.target as HTMLInputElement).checked
const textValue = (event: Event) => (event.target as HTMLInputElement).value
const setBoolean = (field: 'enabled' | 'dnd', event: Event) => controls.updateSettings({ [field]: checked(event) })
const setSource = (event: Event) => controls.updateSettings({ sourceEnabled: { completed_turn_followup: checked(event) } })
const setQuietEnabled = (event: Event) => controls.updateSettings({ quietHours: { enabled: checked(event) } })
const setQuietText = (field: 'start' | 'end' | 'timezone', event: Event) => controls.updateSettings({ quietHours: { [field]: textValue(event) } })
const setNumber = (field: keyof typeof PROACTIVE_SETTINGS_LIMITS, event: Event) => {
  const range = PROACTIVE_SETTINGS_LIMITS[field]
  const value = Math.min(range.max, Math.max(range.min, Math.trunc(Number(textValue(event)))))
  return controls.updateSettings({ [field]: value } as ProactiveSettingsPatch)
}

const sourceLabel = (source: ProactiveSource) => t(`proactive.source.${source}`)
const reasonLabel = (reason: string) => t(reason === 'completed_turn_followup'
  ? 'proactive.reason.completed_turn_followup'
  : 'proactive.reason.unknown')
const formatDate = (value: number) => new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value * 1_000))

const sendFeedback = async (kind: ProactiveFeedbackKind) => {
  const opportunity = props.opportunity
  if (!opportunity || feedbackPending.value) return
  if (kind === 'never_source') {
    try {
      await ElMessageBox.confirm(
        t('proactive.feedback.confirmBody'),
        t('proactive.feedback.confirmTitle'),
        { confirmButtonText: t('proactive.feedback.confirm'), cancelButtonText: t('common.cancel'), type: 'warning', autofocus: true },
      )
    } catch {
      await nextTick()
      neverButton?.focus()
      return
    }
  }
  const saved = await controls.submitFeedback(opportunity, kind)
  if (saved) ElMessage.success(t('proactive.feedback.saved'))
  await nextTick()
  if (kind === 'never_source') neverButton?.focus()
}

const rebuildFrames = async () => {
  const rebuilt = await controls.rebuildFrames()
  if (rebuilt) ElMessage.success(t('proactive.frames.rebuilt'))
  else ElMessage.error(t('proactive.frames.rebuildFailed'))
}

watch(() => [props.visible, props.workspaceId] as const, ([visible], previous) => {
  if (!visible) return
  if (previous && previous[1] !== props.workspaceId) controls.invalidate()
  void load()
}, { immediate: true })

onBeforeUnmount(() => controls.invalidate())
</script>

<style scoped>
.proactive-settings { display: grid; min-width: 0; gap: 12px; }
.section-heading, .control-row, .frame-row { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 12px; }
h3, h4, p { margin: 0; }
h4 { font-size: 13px; }
.control-row { padding: 8px 0; }
.control-row > span, .frame-row > span { display: grid; min-width: 0; gap: 3px; }
small, .empty, .policy-status { color: var(--yui-muted); font-size: 12px; line-height: 1.45; }
.policy-status--error { color: #b91c1c; }
input[type='checkbox'] { width: 18px; height: 18px; flex: 0 0 auto; accent-color: var(--yui-primary); }
.quiet-hours { display: grid; gap: 10px; margin: 0; padding: 12px; border: 1px solid var(--yui-border); border-radius: 6px; }
.quiet-hours legend { padding: 0 4px; font-size: 12px; font-weight: 700; }
.compact-toggle { display: flex; align-items: center; gap: 8px; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.numeric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.field, .field-grid label { display: grid; min-width: 0; gap: 5px; color: var(--yui-muted); font-size: 12px; }
input[type='text'], input[type='time'], input[type='number'] { width: 100%; min-width: 0; min-height: 34px; box-sizing: border-box; padding: 5px 7px; border: 1px solid var(--yui-border-strong); border-radius: 5px; background: var(--yui-surface); color: var(--yui-text); }
.opportunity, .frames { display: grid; gap: 10px; padding-top: 4px; }
dl { display: grid; gap: 6px; margin: 0; }
dl div { display: grid; grid-template-columns: minmax(88px, auto) minmax(0, 1fr); gap: 10px; }
dt { color: var(--yui-muted); font-size: 12px; }
dd { min-width: 0; margin: 0; overflow-wrap: anywhere; text-align: right; font-size: 12px; }
.feedback-actions { display: flex; flex-wrap: wrap; gap: 6px; }
button { min-height: 34px; border: 1px solid var(--yui-border-strong); border-radius: 6px; padding: 0 9px; background: var(--yui-surface); color: var(--yui-text); cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .58; }
button:focus-visible, input:focus-visible { outline: 2px solid var(--yui-primary); outline-offset: 2px; }
.text-action { border: 0; color: var(--yui-primary); background: transparent; }
.icon-action { width: 34px; padding: 0; font-size: 20px; }
.frame-row { padding: 8px 0; border-bottom: 1px solid var(--yui-border); }
@media (max-width: 760px) { .numeric-grid { grid-template-columns: 1fr; } }
@media (max-width: 520px) { .field-grid { grid-template-columns: 1fr; } dl div { grid-template-columns: 1fr; gap: 2px; } dd { text-align: left; } }
</style>
