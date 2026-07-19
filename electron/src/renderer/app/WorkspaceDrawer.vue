<template>
  <el-drawer
    :model-value="visible"
    title="桌宠场景设置"
    direction="rtl"
    size="400px"
    class="workspace-drawer"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div class="flex flex-col gap-6 px-2">
      <!-- 基本信息 -->
      <section class="flex flex-col gap-4">
        <h3 class="text-sm font-semibold text-slate-800 m-0">场景信息</h3>
        <el-form label-position="top" size="default" class="w-full">
          <el-form-item label="场景名称" class="mb-4">
            <el-input :model-value="workspace.name" placeholder="例如 日常陪伴、学习陪伴" @change="updateField('name', $event)" />
          </el-form-item>
          <el-form-item label="场景描述" class="mb-0">
            <el-input :model-value="workspace.description || ''" type="textarea" :rows="3" placeholder="语气、边界或任务偏好" resize="none" @change="updateField('description', $event)" />
          </el-form-item>
        </el-form>
      </section>

      <el-divider class="my-0" />

      <!-- 模型配置 -->
      <section class="flex flex-col gap-4">
        <h3 class="text-sm font-semibold text-slate-800 m-0">模型配置</h3>
        <el-form label-position="top" size="default">
          <el-form-item label="场景模型" class="mb-1">
            <el-select
              data-testid="workspace-model-select"
              :model-value="selectedModelId"
              class="w-full"
              filterable
              allow-create
              clearable
              default-first-option
              :loading="modelOptionsLoading"
              placeholder="跟随全局模型"
              @change="updateModelSelection"
            >
              <el-option
                v-for="option in modelOptions"
                :key="option.id"
                :label="option.label"
                :value="option.id"
              />
            </el-select>
          </el-form-item>
          <el-alert v-if="modelOptionsError" :title="modelOptionsError" type="error" :closable="false" show-icon />
        </el-form>
      </section>

      <el-divider class="my-0" />

      <!-- 记忆范围 -->
      <section class="flex flex-col gap-4">
        <h3 class="text-sm font-semibold text-slate-800 m-0">记忆范围</h3>
        <el-form label-position="top" size="default" class="mb-0">
          <el-form-item label="默认记忆范围" class="mb-1">
            <el-select :model-value="workspace.memory_scope || 'workspace'" class="w-full" @change="updateField('memory_scope', $event)">
              <el-option label="跨场景长期记忆" value="global" />
              <el-option label="当前场景记忆" value="workspace" />
              <el-option label="当前会话记忆" value="session" />
            </el-select>
          </el-form-item>
        </el-form>
      </section>

      <el-divider class="my-0" />

      <!-- 桌宠档案 -->
      <section class="flex flex-col gap-4">
        <h3 class="text-sm font-semibold text-slate-800 m-0">桌宠档案</h3>
        <el-form label-position="top" size="default" class="mb-0">
          <el-form-item label="绑定桌宠" class="mb-2">
            <el-select :model-value="workspace.companion_profile_id || 'default'" class="w-full" @change="updateField('companion_profile_id', $event)">
              <el-option v-for="c in companions" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>

          <div class="flex flex-wrap gap-2 mb-4">
            <el-button size="small" plain @click="$emit('create-companion')">
              新建
            </el-button>
            <el-button size="small" plain @click="$emit('edit-companion', workspace.companion_profile_id || 'default')">
              编辑
            </el-button>
            <el-button size="small" type="danger" plain :disabled="(workspace.companion_profile_id || 'default') === 'default'" @click="$emit('delete-companion', workspace.companion_profile_id || 'default')">
              删除
            </el-button>
          </div>

          <div v-if="activeCompanion" class="bg-slate-50 rounded-lg p-3 text-sm flex flex-col gap-2 border border-slate-100">
            <div class="flex justify-between"><span class="text-slate-500">模型类型</span><span class="font-medium text-slate-700">{{ activeCompanion.model_type || '-' }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">模型 ID</span><span class="font-medium text-slate-700">{{ activeCompanion.model_id || '-' }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">情绪</span><span class="font-medium text-slate-700">{{ activeCompanion.emotion_state || '-' }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">亲密度</span><span class="font-medium text-slate-700">{{ activeCompanion.affinity_state ?? '-' }}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">能量</span><span class="font-medium text-slate-700">{{ activeCompanion.energy_state ?? '-' }}</span></div>
          </div>
        </el-form>
      </section>

      <el-divider class="my-0" />

      <!-- 工具 / MCP -->
      <section class="flex flex-col gap-4">
        <h3 class="text-sm font-semibold text-slate-800 m-0">扩展能力</h3>
        <el-form label-position="top" size="default">
          <el-form-item label="可用工具" class="mb-4">
            <el-select
              data-testid="workspace-tool-select"
              :model-value="selectedToolIds"
              class="w-full"
              multiple
              filterable
              clearable
              collapse-tags
              :max-collapse-tags="3"
              :loading="extensionOptionsLoading"
              placeholder="全部工具"
              @change="updateToolSelection"
            >
              <el-option
                v-for="option in toolOptions"
                :key="option.id"
                :label="option.label"
                :value="option.id"
                :disabled="!option.available"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="MCP 服务" class="mb-1">
            <el-select
              data-testid="workspace-mcp-select"
              :model-value="selectedMcpServerId"
              class="w-full"
              filterable
              clearable
              :loading="extensionOptionsLoading"
              placeholder="全部已启用服务"
              @change="updateMcpSelection"
            >
              <el-option
                v-for="option in mcpOptions"
                :key="option.id"
                :label="option.label"
                :value="option.id"
                :disabled="!option.available"
              />
            </el-select>
          </el-form-item>
          <el-alert v-if="extensionOptionsError" :title="extensionOptionsError" type="error" :closable="false" show-icon />
        </el-form>
      </section>

      <el-divider class="my-0" />

      <!-- 元信息 -->
      <section class="flex flex-col gap-3">
        <h3 class="text-sm font-semibold text-slate-800 m-0">元信息</h3>
        <div class="flex flex-col gap-2 text-xs">
          <div class="flex justify-between items-center"><span class="text-slate-500">ID</span><code class="bg-slate-100 px-1.5 py-0.5 rounded text-slate-600">{{ workspace.id }}</code></div>
          <div class="flex justify-between items-center"><span class="text-slate-500">创建时间</span><code class="bg-slate-100 px-1.5 py-0.5 rounded text-slate-600">{{ workspace.createdAt }}</code></div>
          <div class="flex justify-between items-center"><span class="text-slate-500">更新时间</span><code class="bg-slate-100 px-1.5 py-0.5 rounded text-slate-600">{{ workspace.updatedAt }}</code></div>
        </div>
      </section>

    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { WorkspaceRecord } from '@/../shared/workspace'
import type { CapabilityDescriptor } from '@/../shared/capability'
import type { CompanionRecord } from '@/api/clients/companion-client'
import { settingsClient } from '@/api/clients/settings-client'
import { systemClient } from '@/api/clients/system-client'

const props = defineProps<{
  visible: boolean
  workspace: WorkspaceRecord
  companions: CompanionRecord[]
  activeCompanion: CompanionRecord | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'update-field', field: string, value: string): void
  (e: 'create-companion'): void
  (e: 'edit-companion', companionId: string): void
  (e: 'delete-companion', companionId: string): void
}>()

const updateField = (field: string, value: string) => {
  emit('update-field', field, value)
}

interface ExtensionOption {
  id: string
  label: string
  available: boolean
}

interface ModelOption {
  id: string
  label: string
}

const modelOptionsLoading = ref(false)
const modelOptionsError = ref('')
const discoveredModelIds = ref<string[]>([])
const configuredModelId = ref('')
const selectedModelId = ref('')
const extensionOptionsLoading = ref(false)
const extensionOptionsError = ref('')
const capabilities = ref<CapabilityDescriptor[]>([])
const mcpServers = ref<Array<{ id: string; enabled: boolean }>>([])
const selectedToolIds = ref<string[]>([])
const selectedMcpServerId = ref('')

const modelOptions = computed<ModelOption[]>(() => {
  const knownIds = new Set([
    ...discoveredModelIds.value,
    configuredModelId.value,
  ].map((id) => id.trim()).filter(Boolean))
  const options = [...knownIds]
    .sort((left, right) => left.localeCompare(right))
    .map((id) => ({ id, label: id }))

  if (selectedModelId.value && !knownIds.has(selectedModelId.value)) {
    options.push({
      id: selectedModelId.value,
      label: `${selectedModelId.value}（当前）`,
    })
  }
  return options
})

const parseToolPreset = (value: string | null | undefined): string[] => {
  if (!value?.trim()) {
    return []
  }
  try {
    const parsed = JSON.parse(value) as unknown
    if (!Array.isArray(parsed)) {
      return []
    }
    return [...new Set(parsed
      .filter((item): item is string => typeof item === 'string')
      .map((item) => item.trim())
      .filter(Boolean))]
  } catch {
    return []
  }
}

const mergeUnavailableOptions = (options: ExtensionOption[], selected: string[]): ExtensionOption[] => {
  const knownIds = new Set(options.map((option) => option.id))
  return [
    ...options,
    ...selected
      .filter((id) => !knownIds.has(id))
      .map((id) => ({ id, label: `${id}（不可用）`, available: false })),
  ]
}

const toolOptions = computed(() => mergeUnavailableOptions(
  capabilities.value
    .filter((capability) => capability.type === 'tool')
    .map((capability) => ({
      id: capability.id,
      label: capability.name || capability.id,
      available: true,
    }))
    .sort((left, right) => left.label.localeCompare(right.label, 'zh-CN')),
  selectedToolIds.value,
))

const mcpOptions = computed(() => mergeUnavailableOptions(
  mcpServers.value.map((server) => ({
    id: server.id,
    label: server.enabled ? server.id : `${server.id}（已停用）`,
    available: server.enabled,
  })),
  selectedMcpServerId.value ? [selectedMcpServerId.value] : [],
))

const syncSelections = () => {
  selectedModelId.value = props.workspace.default_model?.trim() || ''
  selectedToolIds.value = parseToolPreset(props.workspace.tool_preset)
  selectedMcpServerId.value = props.workspace.mcp_preset_id?.trim() || ''
}

const loadModelOptions = async () => {
  modelOptionsLoading.value = true
  modelOptionsError.value = ''
  try {
    const settings = await settingsClient.load()
    const llm = settings.llm
    configuredModelId.value = llm.model?.trim() || ''
    discoveredModelIds.value = configuredModelId.value ? [configuredModelId.value] : []

    if (llm.base_url?.trim()) {
      const result = await settingsClient.listLlmModels({
        provider: llm.provider,
        base_url: llm.base_url,
        api_key: llm.api_key,
        timeout: llm.timeout,
      })
      if (!result.ok) {
        modelOptionsError.value = '模型目录加载失败'
        return
      }
      discoveredModelIds.value = [...new Set([
        ...discoveredModelIds.value,
        ...result.models.map((id) => id.trim()).filter(Boolean),
      ])]
    }
  } catch {
    configuredModelId.value = ''
    discoveredModelIds.value = []
    modelOptionsError.value = '模型目录加载失败'
  } finally {
    modelOptionsLoading.value = false
  }
}

const loadExtensionOptions = async () => {
  extensionOptionsLoading.value = true
  extensionOptionsError.value = ''
  const [capabilityResult, mcpResult] = await Promise.allSettled([
    systemClient.capabilities(),
    systemClient.mcp(),
  ])

  if (capabilityResult.status === 'fulfilled') {
    capabilities.value = capabilityResult.value.capabilities
  } else {
    capabilities.value = []
  }
  if (mcpResult.status === 'fulfilled') {
    mcpServers.value = Object.entries(mcpResult.value.servers).map(([id, server]) => ({
      id,
      enabled: server.enabled,
    }))
  } else {
    mcpServers.value = []
  }

  const failed = [capabilityResult, mcpResult].filter((result) => result.status === 'rejected').length
  if (failed > 0) {
    extensionOptionsError.value = failed === 2 ? '扩展能力加载失败' : '部分扩展能力加载失败'
  }
  extensionOptionsLoading.value = false
}

const updateToolSelection = (value: string[]) => {
  const normalized = [...new Set(value)].sort((left, right) => left.localeCompare(right))
  selectedToolIds.value = normalized
  updateField('tool_preset', normalized.length > 0 ? JSON.stringify(normalized) : '')
}

const updateMcpSelection = (value: string) => {
  selectedMcpServerId.value = value
  updateField('mcp_preset_id', value)
}

const updateModelSelection = (value: string) => {
  selectedModelId.value = value?.trim() || ''
  updateField('default_model', selectedModelId.value)
}

watch(
  () => [props.workspace.id, props.workspace.default_model, props.workspace.tool_preset, props.workspace.mcp_preset_id],
  syncSelections,
  { immediate: true },
)

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      void loadExtensionOptions()
      void loadModelOptions()
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.workspace-drawer :deep(.el-drawer__header) {
  margin-bottom: 0;
  padding-bottom: 16px;
  border-bottom: 1px solid #f1f5f9;
}
.workspace-drawer :deep(.el-drawer__body) {
  padding: 20px;
}
</style>
