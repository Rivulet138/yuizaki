<template>
  <section class="activity-summary" :aria-label="summaryTitle">
    <div class="summary-heading">
      <div>
        <h3>{{ summaryTitle }}</h3>
        <p>{{ summarySubtitle }}</p>
      </div>
      <router-link class="text-link" :to="memoryPath">{{ openMemoryLabel }}</router-link>
    </div>

    <div class="summary-grid">
      <article class="summary-section">
        <header>
          <h4>{{ memoryTitle }}</h4>
          <strong>{{ memoryTotal }}</strong>
        </header>
        <p v-if="!recentSignals.length" class="empty-copy">{{ memoryEmptyLabel }}</p>
        <ul v-else>
          <li v-for="signal in recentSignals" :key="`${signal.kind}-${signal.timestamp}-${signal.text}`">
            <span>{{ signal.kind }}</span>
            <p>{{ signal.text }}</p>
          </li>
        </ul>
      </article>

      <article class="summary-section">
        <header>
          <h4>{{ taskTitle }}</h4>
          <span class="task-status">{{ taskStatus }}</span>
        </header>
        <p>{{ taskSummary }}</p>
        <div class="inline-links">
          <router-link :to="taskPath">{{ openTaskLabel }}</router-link>
          <router-link :to="receiptPath">{{ openReceiptLabel }}</router-link>
        </div>
      </article>
    </div>

    <details v-if="relationshipSummary" class="relationship-disclosure">
      <summary>{{ relationshipTitle }}</summary>
      <p>{{ relationshipSummary }}</p>
    </details>
  </section>
</template>

<script setup lang="ts">
interface RecentSignal {
  kind: string
  text: string
  timestamp?: string | null
}

defineProps<{
  summaryTitle: string
  summarySubtitle: string
  memoryTitle: string
  memoryTotal: number
  recentSignals: RecentSignal[]
  memoryEmptyLabel: string
  memoryPath: string
  openMemoryLabel: string
  taskTitle: string
  taskStatus: string
  taskSummary: string
  taskPath: string
  openTaskLabel: string
  receiptPath: string
  openReceiptLabel: string
  relationshipTitle: string
  relationshipSummary?: string
}>()
</script>

<style scoped>
.activity-summary {
  display: grid;
  gap: 14px;
  border-top: 1px solid var(--yui-border);
  padding-top: 20px;
}

.summary-heading,
.summary-section header,
.inline-links {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

h3,
h4,
p {
  margin: 0;
  letter-spacing: 0;
}

h3 {
  color: var(--yui-text);
  font-size: 16px;
}

.summary-heading p,
.empty-copy {
  margin-top: 4px;
  color: var(--yui-muted);
  font-size: 12px;
}

.text-link,
.inline-links a {
  color: var(--yui-accent);
  font-size: 12px;
  font-weight: 740;
  text-decoration: none;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.summary-section {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  padding: 14px;
}

.summary-section h4 {
  color: var(--yui-text);
  font-size: 14px;
}

.summary-section > p {
  margin-top: 14px;
  color: var(--yui-muted);
  font-size: 13px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.summary-section ul {
  display: grid;
  gap: 10px;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}

.summary-section li span,
.task-status {
  color: var(--yui-muted);
  font-size: 11px;
}

.summary-section li p {
  margin-top: 3px;
  color: var(--yui-text);
  font-size: 13px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.inline-links {
  justify-content: flex-start;
  margin-top: 14px;
}

.relationship-disclosure {
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  padding: 10px 12px;
}

.relationship-disclosure summary {
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 760;
  cursor: pointer;
}

.relationship-disclosure p {
  margin-top: 10px;
  color: var(--yui-muted);
  font-size: 13px;
  line-height: 1.55;
}

a:focus-visible,
summary:focus-visible {
  outline: 3px solid var(--yui-accent);
  outline-offset: 2px;
}

@media (max-width: 760px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .summary-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
