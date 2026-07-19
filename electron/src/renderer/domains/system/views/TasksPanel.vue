<template>
  <PanelShell
    title="编排对象"
    tone="admin"
  >
    <div class="tasks-panel">
      <div class="panel-toolbar">
        <div>
          <h3>命令、技能、Agent、钩子</h3>
        </div>
        <div class="toolbar-actions">
          <el-input
            v-model="searchQuery"
            class="search-input"
            clearable
            size="small"
            placeholder="搜索名称或说明"
          />
          <el-button type="primary" plain :loading="orchestrationRequest.loading" @click="loadOrchestration">刷新</el-button>
        </div>
      </div>

      <div class="summary-grid">
        <div v-for="item in summaryCards" :key="item.label" class="summary-card" :class="`tone-${item.tone}`">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>

      <el-card class="orchestration-card" shadow="never">
        <template #header>
          <div class="card-header">
            <span>编排对象</span>
            <div class="tag-row">
              <el-tag size="small">{{ orchestration.commands?.length || 0 }} 命令</el-tag>
              <el-tag size="small" type="success">{{ orchestration.skills?.length || 0 }} 技能</el-tag>
              <el-tag size="small" type="danger">{{ orchestration.agents?.length || 0 }} Agent</el-tag>
              <el-tag size="small" type="warning">{{ orchestration.hooks?.length || 0 }} 钩子</el-tag>
            </div>
          </div>
        </template>

        <AsyncState :loading="orchestrationRequest.loading" :error="orchestrationRequest.error" @retry="loadOrchestration">
          <el-tabs v-model="activeTab" class="object-tabs">
            <el-tab-pane label="命令">
              <el-empty v-if="!filteredCommands.length" :description="emptyText('命令')" />
              <div v-else class="object-list">
                <div v-for="item in filteredCommands" :key="item.id" class="object-item">
                  <div class="object-title">
                    <strong>{{ item.name }}</strong>
                    <el-tag size="small" type="info">{{ item.audience }}</el-tag>
                  </div>
                  <span>{{ item.description }}</span>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane label="技能">
              <el-empty v-if="!filteredSkills.length" :description="emptyText('技能')" />
              <div v-else class="object-list">
                <div v-for="item in filteredSkills" :key="item.id" class="object-item">
                  <div class="object-title">
                    <strong>{{ item.name }}</strong>
                    <el-tag size="small" type="success">{{ item.audience }}</el-tag>
                  </div>
                  <span>{{ item.description }}</span>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane label="Agent">
              <el-empty v-if="!filteredAgents.length" :description="emptyText('Agent')" />
              <div v-else class="object-list">
                <div v-for="item in filteredAgents" :key="item.id" class="object-item">
                  <div class="object-title">
                    <strong>{{ item.name }}</strong>
                    <el-tag size="small" type="danger">{{ item.role }}</el-tag>
                    <el-tag size="small" type="info">{{ item.audience }}</el-tag>
                  </div>
                  <span>{{ item.description }}</span>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane label="钩子">
              <el-empty v-if="!filteredHooks.length" :description="emptyText('钩子')" />
              <div v-else class="object-list">
                <div v-for="item in filteredHooks" :key="item.id" class="object-item">
                  <div class="object-title">
                    <strong>{{ item.name }}</strong>
                    <el-tag size="small" type="warning">{{ item.audience }}</el-tag>
                    <el-tag v-if="item.stage" size="small" type="info">{{ item.stage }}</el-tag>
                  </div>
                  <span>{{ item.description }}</span>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </AsyncState>
      </el-card>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { useDomainRequest } from '@/shared/composables/useDomainRequest'
import { systemClient } from '@/api/client'
import type { OrchestrationSnapshot } from '@/../shared/orchestration'

type SummaryTone = 'blue' | 'emerald' | 'rose' | 'amber'

const orchestration = ref<OrchestrationSnapshot>({
  agents: [],
  skills: [],
  commands: [],
  hooks: [],
  summary: { agents: 0, skills: 0, commands: 0, hooks: 0 },
})
const orchestrationRequest = useDomainRequest<OrchestrationSnapshot>()
const activeTab = ref('0')
const searchQuery = ref('')

type SearchableOrchestrationItem = {
  id: string
  name: string
  description?: string
  audience?: string
  role?: string
  stage?: string
}

const normalizedSearchQuery = computed(() => searchQuery.value.trim().toLowerCase())
const filterItems = <T extends SearchableOrchestrationItem>(items: T[] | undefined): T[] => {
  const query = normalizedSearchQuery.value
  const source = items || []
  if (!query) return source
  return source.filter((item) => [
    item.id,
    item.name,
    item.description,
    item.audience,
    item.role,
    item.stage,
  ].filter(Boolean).join(' ').toLowerCase().includes(query))
}

const filteredCommands = computed(() => filterItems(orchestration.value.commands || []))
const filteredSkills = computed(() => filterItems(orchestration.value.skills || []))
const filteredAgents = computed(() => filterItems(orchestration.value.agents || []))
const filteredHooks = computed(() => filterItems(orchestration.value.hooks || []))

const emptyText = (label: string) => normalizedSearchQuery.value ? `没有匹配的${label}` : `暂无${label}对象`

const summaryCards = computed(() => [
  { label: '命令', value: orchestration.value.commands?.length || 0, tone: 'blue' as SummaryTone },
  { label: '技能', value: orchestration.value.skills?.length || 0, tone: 'emerald' as SummaryTone },
  { label: 'Agent', value: orchestration.value.agents?.length || 0, tone: 'rose' as SummaryTone },
  { label: '钩子', value: orchestration.value.hooks?.length || 0, tone: 'amber' as SummaryTone },
])

const loadOrchestration = async () => {
  const result = await orchestrationRequest.execute(() => systemClient.orchestration())
  if (result) orchestration.value = result
}

onMounted(() => {
  void loadOrchestration()
})
</script>

<style scoped>
.tasks-panel,
.object-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.panel-toolbar,
.card-header,
.tag-row,
.toolbar-actions,
.object-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.panel-toolbar,
.card-header {
  justify-content: space-between;
}

.toolbar-actions {
  flex: 0 1 420px;
  justify-content: flex-end;
}

.search-input {
  min-width: 180px;
  max-width: 280px;
}

.panel-toolbar {
  padding: 14px 16px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
}

.panel-toolbar h3 {
  margin: 0 0 4px;
  color: var(--yui-text);
  font-size: 16px;
}

.panel-toolbar p,
.object-item span,
.summary-card small {
  margin: 0;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.5;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.summary-card {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.summary-card span,
.summary-card small {
  display: block;
}

.summary-card span {
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 750;
}

.summary-card strong {
  display: block;
  margin: 6px 0 3px;
  color: var(--yui-text);
  font-size: 28px;
  line-height: 1;
}

.tone-blue strong { color: #2563eb; }
.tone-emerald strong { color: #059669; }
.tone-rose strong { color: #e11d48; }
.tone-amber strong { color: #d97706; }

.orchestration-card {
  min-width: 0;
}

.object-tabs {
  min-width: 0;
}

.tag-row {
  flex-wrap: wrap;
}

.object-item {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface-muted);
}

.object-title {
  flex-wrap: wrap;
}

.object-title strong {
  color: var(--yui-text);
}

@media (max-width: 960px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .panel-toolbar,
  .card-header,
  .toolbar-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar-actions,
  .search-input {
    width: 100%;
    max-width: none;
  }
}

@media (max-width: 640px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
