<template>
  <ol class="readiness-rail" :aria-label="t('onboarding.readiness.aria')">
    <li
      v-for="probe in probes"
      :key="probe.id"
      class="readiness-item"
      :data-status="probe.status"
      :data-required="probe.requiredForText"
      :role="isBlockingFailure(probe) ? 'alert' : undefined"
    >
      <span class="readiness-marker" aria-hidden="true">
        <el-icon v-if="probe.status === 'ready'"><CircleCheckFilled /></el-icon>
        <el-icon v-else-if="probe.status === 'running'"><Loading /></el-icon>
        <el-icon v-else-if="probe.status === 'failed'"><CircleCloseFilled /></el-icon>
        <el-icon v-else-if="probe.status === 'cancelled' || probe.status === 'unavailable'"><RemoveFilled /></el-icon>
        <el-icon v-else-if="probe.status === 'needs_user' || probe.status === 'degraded'"><WarningFilled /></el-icon>
        <el-icon v-else><Clock /></el-icon>
      </span>
      <div class="readiness-copy">
        <div class="readiness-heading">
          <strong>{{ probeLabel(probe) }}</strong>
          <span>{{ statusLabel(probe) }}</span>
        </div>
        <p>{{ probeMessage(probe) }}</p>
        <div v-if="repairAction(probe) || settingsAction(probe)" class="readiness-item-actions">
          <el-button
            v-if="repairAction(probe)"
            class="repair-button"
            size="small"
            text
            @click="emit('repair', repairAction(probe)!)"
          >
            {{ t('onboarding.repair') }}
          </el-button>
          <el-button
            v-if="settingsAction(probe)"
            class="repair-button"
            size="small"
            text
            @click="emit('repair', settingsAction(probe)!)"
          >
            {{ t(settingsAction(probe) === 'navigate:pet' ? 'onboarding.openPetSettings' : 'onboarding.openSettings') }}
          </el-button>
        </div>
      </div>
    </li>
  </ol>
</template>

<script setup lang="ts">
import { CircleCheckFilled, CircleCloseFilled, Clock, Loading, RemoveFilled, WarningFilled } from '@element-plus/icons-vue'
import { isOnboardingProbeMessageKey, isOnboardingRepairActionId, type OnboardingProbeResult, type OnboardingRepairActionId } from '@/../shared/onboarding-readiness'
import { currentLocale, t } from '@/i18n'

defineProps<{ probes: OnboardingProbeResult[] }>()
const emit = defineEmits<{ repair: [actionId: OnboardingRepairActionId] }>()

const SETTINGS_PROBES = new Set<OnboardingProbeResult['id']>([
  'llm.provider',
  'llm.model_chat',
  'tts.status',
  'asr.runtime',
  'database.status',
  'memory.status',
  'mcp.snapshot',
])

const needsAction = (probe: OnboardingProbeResult): boolean => (
  ['degraded', 'unavailable', 'failed', 'cancelled', 'needs_user'].includes(probe.status)
)

const repairAction = (probe: OnboardingProbeResult): OnboardingRepairActionId | null => (
  isOnboardingRepairActionId(probe.repairActionId) ? probe.repairActionId : null
)

const settingsAction = (probe: OnboardingProbeResult): OnboardingRepairActionId | null => {
  if (!needsAction(probe)) return null
  if (probe.id === 'host.avatar') return 'navigate:pet'
  if (SETTINGS_PROBES.has(probe.id)) return 'navigate:settings'
  return null
}

const isBlockingFailure = (probe: OnboardingProbeResult): boolean => (
  probe.requiredForText && (probe.status === 'failed' || probe.status === 'unavailable')
)

const statusLabel = (probe: OnboardingProbeResult): string => {
  if (!probe.requiredForText && probe.status === 'failed') return t('onboarding.status.optionalUnavailable')
  return t(`onboarding.status.${probe.status}`)
}
const probeLabel = (probe: OnboardingProbeResult): string => {
  const key = `onboarding.probe.${probe.id}`
  const translated = t(key)
  return translated === key ? probe.label : translated
}
const GENERIC_EVIDENCE_CATEGORIES = new Set(['transport', 'timeout', 'blocked_by_dependency'])
const probeMessage = (probe: OnboardingProbeResult): string => {
  if (isOnboardingProbeMessageKey(probe.messageKey)) return t(probe.messageKey)
  if (currentLocale.value === 'en-US' && probe.message.trim()) return probe.message.trim().slice(0, 500)
  const category = typeof probe.evidence?.['category'] === 'string' ? probe.evidence['category'] : ''
  if (GENERIC_EVIDENCE_CATEGORIES.has(category)) return t(`onboarding.message.category.${category}`)
  return t(`onboarding.message.status.${probe.status}`)
}
</script>

<style scoped>
.readiness-rail {
  list-style: none;
  margin: 0;
  padding: 0;
}

.readiness-item {
  position: relative;
  box-sizing: border-box;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 12px;
  min-height: 42px;
  padding: 3px 0 8px;
}

.readiness-item:not(:last-child)::after {
  position: absolute;
  top: 25px;
  bottom: 0;
  left: 11px;
  width: 1px;
  background: var(--yui-border, #d9e1ea);
  content: '';
}

.readiness-marker {
  position: relative;
  z-index: 1;
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border: 1px solid var(--yui-border, #d9e1ea);
  border-radius: 50%;
  background: var(--yui-surface, #fff);
  color: #64748b;
}

.readiness-item[data-status='ready'] .readiness-marker { color: #15803d; }
.readiness-item[data-status='failed'] .readiness-marker { color: #b91c1c; }
.readiness-item[data-status='needs_user'] .readiness-marker,
.readiness-item[data-status='degraded'] .readiness-marker { color: #a16207; }
.readiness-item[data-status='unavailable'] .readiness-marker,
.readiness-item[data-status='failed'][data-required='false'] .readiness-marker { color: #64748b; }
.readiness-item[data-status='running'] .readiness-marker { color: var(--el-color-primary); }

.readiness-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.readiness-heading strong {
  overflow-wrap: anywhere;
  color: var(--yui-text, #172033);
  font-size: 14px;
  font-weight: 650;
}

.readiness-heading span {
  flex: 0 0 auto;
  color: var(--yui-text-muted, #526176);
  font-size: 12px;
}

.readiness-copy p {
  max-width: 68ch;
  margin: 4px 0 0;
  overflow-wrap: anywhere;
  color: var(--yui-text-muted, #526176);
  font-size: 12px;
  line-height: 1.45;
}
.readiness-item-actions { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.repair-button { margin: 4px 0 0; padding-inline: 0; }

@media (max-width: 520px) {
  .readiness-heading { align-items: flex-start; flex-direction: column; gap: 2px; }
}
</style>
