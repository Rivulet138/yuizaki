<template>
  <section class="companion-hero" :class="`is-${presentationState}`" aria-labelledby="companion-name">
    <div class="avatar-stage" aria-label="companion avatar">
      <img v-if="avatar" :src="avatar" :alt="companionName" />
      <div v-else class="model-avatar" role="img" :aria-label="`${modelType} ${modelId}`">
        <span>{{ companionInitial }}</span>
        <small>{{ modelType.toUpperCase() }}</small>
      </div>
      <span class="activity-indicator" aria-hidden="true"></span>
    </div>

    <div class="hero-copy">
      <p class="eyebrow">{{ modelId }}</p>
      <h2 id="companion-name">{{ companionName }}</h2>
      <div class="semantic-state" role="status" aria-live="polite">
        <strong>{{ stateLabel }}</strong>
        <span>{{ stateDetail }}</span>
      </div>
      <dl class="state-facts">
        <div>
          <dt>{{ availabilityTitle }}</dt>
          <dd>{{ availabilityLabel }}</dd>
        </div>
        <div>
          <dt>{{ permissionTitle }}</dt>
          <dd>{{ permissionLabel }}</dd>
        </div>
        <div>
          <dt>{{ dndTitle }}</dt>
          <dd>{{ dndLabel }}</dd>
        </div>
      </dl>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CompanionPresentationState } from '@/app/runtime/companionRuntime'

const props = defineProps<{
  companionName: string
  avatar?: string | null
  modelType: string
  modelId: string
  presentationState: CompanionPresentationState
  stateLabel: string
  stateDetail: string
  availabilityTitle: string
  availabilityLabel: string
  permissionTitle: string
  permissionLabel: string
  dndTitle: string
  dndLabel: string
}>()

const companionInitial = computed(() => props.companionName.trim().slice(0, 1).toUpperCase() || 'Y')
</script>

<style scoped>
.companion-hero {
  display: grid;
  grid-template-columns: minmax(220px, 0.82fr) minmax(280px, 1.18fr);
  min-height: 340px;
  overflow: hidden;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
}

.avatar-stage {
  position: relative;
  display: grid;
  min-width: 0;
  place-items: center;
  overflow: hidden;
  background: var(--yui-surface-muted);
}

.avatar-stage img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.model-avatar {
  display: grid;
  width: min(68%, 260px);
  aspect-ratio: 1;
  place-items: center;
  border: 1px solid var(--yui-border-strong);
  border-radius: 50%;
  background: var(--yui-surface-raised);
  color: var(--yui-text);
  box-shadow: var(--yui-shadow-card);
}

.model-avatar span {
  align-self: end;
  font-size: clamp(72px, 8vw, 120px);
  font-weight: 800;
  line-height: 1;
}

.model-avatar small {
  align-self: start;
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 760;
}

.activity-indicator {
  position: absolute;
  right: 18px;
  bottom: 18px;
  width: 14px;
  height: 14px;
  border: 3px solid var(--yui-surface-muted);
  border-radius: 50%;
  background: #16a34a;
}

.is-offline .activity-indicator,
.is-interrupted .activity-indicator {
  background: #64748b;
}

.is-error .activity-indicator {
  background: #dc2626;
}

.is-waiting-for-permission .activity-indicator,
.is-thinking .activity-indicator,
.is-executing .activity-indicator {
  background: #d97706;
}

.hero-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  padding: 32px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 720;
  overflow-wrap: anywhere;
}

h2 {
  margin: 0;
  color: var(--yui-text);
  font-size: 34px;
  font-weight: 850;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}

.semantic-state {
  display: grid;
  gap: 5px;
  margin-top: 24px;
}

.semantic-state strong {
  color: var(--yui-text);
  font-size: 18px;
}

.semantic-state span {
  color: var(--yui-muted);
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.state-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 24px 0 0;
}

.state-facts div {
  min-width: 0;
  border-left: 2px solid var(--yui-border-strong);
  padding-left: 10px;
}

.state-facts dt,
.state-facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.state-facts dt {
  color: var(--yui-muted);
  font-size: 11px;
}

.state-facts dd {
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 740;
}

@media (max-width: 760px) {
  .companion-hero {
    grid-template-columns: 1fr;
  }

  .avatar-stage {
    min-height: 220px;
  }

  .hero-copy {
    padding: 22px;
  }

  h2 {
    font-size: 28px;
  }

  .state-facts {
    grid-template-columns: 1fr;
  }
}
</style>
