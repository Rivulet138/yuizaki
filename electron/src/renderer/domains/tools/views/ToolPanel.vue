<template>
  <PanelShell
    title="能力与工具"
    subtitle="检查工具权限、MCP、技能和最近调用"
    tone="tool"
  >
    <div class="tool-panel">
      <nav class="canonical-links" :aria-label="t('canonical.capabilities.aria')">
        <span>{{ t('canonical.capabilities.label') }}</span>
        <router-link :to="canonicalPath('plugins')">{{ t('canonical.capabilities.plugins') }}</router-link>
        <router-link :to="canonicalPath('agent-governance')">{{ t('canonical.capabilities.governance') }}</router-link>
      </nav>
      <section class="overview-band">
        <article v-for="item in summaryCards" :key="item.label" class="summary-card" :class="`tone-${item.tone}`">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.desc }}</small>
        </article>
      </section>

      <section class="tool-health panel-card" aria-label="本地能力状态">
        <button
          v-for="item in healthItems"
          :key="item.key"
          type="button"
          class="health-item"
          :class="[`tone-${item.tone}`, { active: activeHealthKey === item.key }]"
          @click="applyHealthAction(item.key)"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.detail }}</small>
        </button>
      </section>

      <section class="capability-map panel-card">
        <div class="section-heading">
          <div>
            <h3>能力清单</h3>
          </div>
          <el-button plain :icon="Refresh" :loading="loadingSnapshots" @click="refreshSnapshots">刷新</el-button>
        </div>
        <div class="source-grid">
          <button
            v-for="item in sourceCards"
            :key="item.kind || 'all'"
            type="button"
            class="source-card"
            :class="{ active: filterKind === item.kind }"
            @click="setKindFilter(item.kind)"
          >
            <span class="source-dot" :style="{ background: item.accent }"></span>
            <strong>{{ item.title }}</strong>
            <em>{{ item.count }}</em>
          </button>
        </div>
      </section>

      <section class="mcp-panel panel-card">
        <div class="section-heading">
          <div>
            <h3>MCP 服务</h3>
            <p>{{ mcpRows.length }} 个服务器，已连接 {{ mcpConnectedCount }}，异常 {{ mcpErrorCount }}，未启用 {{ mcpDisabledCount }}</p>
          </div>
          <el-button plain :icon="Refresh" :loading="loadingMcp" @click="loadMcpServers">刷新</el-button>
        </div>

        <el-alert v-if="mcpLoadError" class="panel-alert" type="warning" :closable="false" show-icon>
          <div class="alert-row">
            <span>{{ mcpLoadError }}</span>
            <el-button size="small" text :loading="loadingMcp" @click.stop="loadMcpServers">重试</el-button>
          </div>
        </el-alert>

        <div v-if="mcpRows.length" class="mcp-filter-row" role="tablist" aria-label="MCP 服务筛选">
          <button
            v-for="option in mcpFilterOptions"
            :key="option.value"
            type="button"
            class="mcp-filter-button"
            :class="{ active: mcpFilter === option.value }"
            @click="mcpFilter = option.value"
          >
            <span>{{ option.label }}</span>
            <strong>{{ option.count }}</strong>
          </button>
        </div>

        <div v-if="filteredMcpRows.length" class="mcp-grid">
          <article
            v-for="server in filteredMcpRows"
            :key="server.name"
            class="mcp-card"
            :class="{ disabled: !server.enabled, connected: server.connected, errored: isMcpErrored(server) }"
          >
            <div class="mcp-main">
              <div>
                <strong>{{ server.name }}</strong>
                <span>{{ mcpEndpointLabel(server) }}</span>
              </div>
              <el-tag size="small" :type="mcpStatusTagType(server)">{{ mcpStatusLabel(server) }}</el-tag>
            </div>
            <div class="mcp-meta">
              <span>{{ transportLabel(server.transport) }}</span>
              <span>工具 {{ server.tools_count }}</span>
              <span>资源 {{ server.resources_count }}</span>
              <span>Prompt {{ server.prompts_count }}</span>
              <span v-if="server.env_keys?.length">环境变量 {{ server.env_keys.join(', ') }}</span>
              <span v-if="server.header_keys?.length">请求头 {{ server.header_keys.join(', ') }}</span>
            </div>
            <div v-if="server.last_error || server.inventory_error" class="mcp-error">
              {{ server.last_error || server.inventory_error }}
            </div>
            <div class="mcp-actions">
              <el-switch
                :model-value="server.enabled"
                size="small"
                :loading="mcpActionNames.has(server.name)"
                @change="(value) => toggleMcpServer(server.name, Boolean(value))"
              />
              <el-button
                size="small"
                link
                type="primary"
                :loading="mcpActionNames.has(`${server.name}:refresh`)"
                @click="refreshMcpServer(server.name)"
              >
                重连
              </el-button>
            </div>
          </article>
        </div>
        <el-empty v-else :description="mcpEmptyDescription" :image-size="64" />
      </section>

      <section class="capability-workspace panel-card">
        <div class="capability-list-pane">
          <div class="section-heading compact">
            <div>
              <h3>{{ activeFilterLabel }}</h3>
            </div>
          </div>

          <div class="toolbar">
            <el-input v-model="searchText" clearable placeholder="搜索能力、范围、标签">
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
            <el-select v-model="filterRisk" clearable placeholder="风险级别" class="toolbar-select">
              <el-option v-for="risk in riskOptions" :key="risk.value" :label="risk.label" :value="risk.value" />
            </el-select>
            <el-select v-model="filterApproval" placeholder="权限确认" class="toolbar-select">
              <el-option label="全部" value="all" />
              <el-option label="需确认" value="required" />
              <el-option label="免确认" value="free" />
            </el-select>
          </div>

          <el-alert v-if="capabilityLoadError" class="panel-alert" type="warning" :closable="false" show-icon>
            <div class="alert-row">
              <span>{{ capabilityLoadError }}</span>
              <el-button size="small" text :loading="loadingCapabilities" @click.stop="loadCapabilities">重试</el-button>
            </div>
          </el-alert>

          <div v-if="filteredCapabilities.length" class="capability-list">
            <button
              v-for="item in filteredCapabilities"
              :key="item.id"
              type="button"
              class="capability-row"
              :class="{ active: selectedCapability?.id === item.id }"
              @click="selectedCapabilityId = item.id"
            >
              <div class="row-title">
                <strong>{{ item.name }}</strong>
                <el-tag size="small" :type="kindTagType(item.kind)" effect="light">{{ kindLabel(item.kind) }}</el-tag>
                <el-tag size="small" :type="riskTagType(item.riskLevel)" effect="plain">{{ riskLabel(item.riskLevel) }}</el-tag>
              </div>
              <p>{{ displayCapabilityDescription(item) }}</p>
              <div class="row-meta">
                <span>{{ executionLabel(item) }}</span>
                <span>{{ item.observability?.trace ? '记录调用' : '未记录调用' }}</span>
                <span>超时 {{ formatTimeout(item.timeoutMs) }}</span>
                <span v-if="item.hasPostcondition" class="completion-meta">完成可验证</span>
                <span v-else-if="item.hasRecheck" class="completion-meta">可复查</span>
              </div>
            </button>
          </div>
          <el-empty v-else description="没有匹配的能力" />
        </div>

        <aside class="detail-pane">
          <template v-if="selectedCapability">
            <div class="detail-heading">
              <el-tag :type="kindTagType(selectedCapability.kind)" effect="light">{{ kindLabel(selectedCapability.kind) }}</el-tag>
              <h3>{{ selectedCapability.name }}</h3>
              <p>{{ displayCapabilityDescription(selectedCapability) }}</p>
            </div>

            <div class="risk-card" :class="`risk-${selectedCapability.riskLevel}`">
              <div>
                <span>风险和权限</span>
                <strong>{{ riskLabel(selectedCapability.riskLevel) }}</strong>
              </div>
              <small>{{ riskHint(selectedCapability) }}</small>
            </div>

            <div class="detail-grid">
              <div>
                <span>ID</span>
                <strong>{{ selectedCapability.id }}</strong>
              </div>
              <div>
                <span>类型</span>
                <strong>{{ kindLabel(selectedCapability.kind) }}</strong>
              </div>
              <div>
                <span>归属</span>
                <strong>{{ ownerLabel(selectedCapability.owner) }}</strong>
              </div>
              <div>
                <span>超时</span>
                <strong>{{ formatTimeout(selectedCapability.timeoutMs) }}</strong>
              </div>
            </div>

            <div class="detail-section">
              <span class="section-label">作用范围</span>
              <div class="token-list">
                <el-tag v-for="scope in selectedCapability.scopes || []" :key="scope" size="small" effect="plain">{{ scope }}</el-tag>
                <span v-if="!(selectedCapability.scopes || []).length" class="muted-text">未声明范围</span>
              </div>
            </div>

            <div class="detail-section">
              <span class="section-label">标签</span>
              <div class="token-list">
                <el-tag v-for="tag in capabilityTags(selectedCapability)" :key="tag" size="small" type="info" effect="plain">{{ tag }}</el-tag>
                <span v-if="!capabilityTags(selectedCapability).length" class="muted-text">暂无标签</span>
              </div>
            </div>

            <div class="detail-section">
              <span class="section-label">输入结构</span>
              <div class="schema-summary">
                <strong>{{ schemaSummary(selectedCapability.inputSchema) }}</strong>
                <details>
                  <summary>查看 JSON schema</summary>
                  <pre>{{ schemaPreview(selectedCapability.inputSchema) }}</pre>
                </details>
              </div>
            </div>
          </template>
          <el-empty v-else description="未选择能力" />
        </aside>
      </section>

      <section class="skill-catalog panel-card">
        <div class="section-heading">
          <div>
            <h3>项目技能</h3>
          </div>
          <div class="section-actions">
            <input
              ref="skillImportInput"
              class="file-input"
              type="file"
              accept=".json,.md,.markdown,application/json,text/markdown,text/plain"
              multiple
              @change="handleSkillFileImport"
            />
            <div class="skill-summary">
              <el-tag type="success" effect="light">内置 {{ builtInSkillCount }}</el-tag>
              <el-tag v-if="importedSkillItems.length" type="info" effect="light">导入 {{ importedSkillItems.length }}</el-tag>
              <el-tag v-if="importedSkillItems.length" :type="skillStorageTagType" effect="light">{{ skillStorageLabel }}</el-tag>
              <el-tag type="primary" effect="light">分类 {{ skillCategoryOptions.length }}</el-tag>
            </div>
            <el-button plain :icon="Upload" :loading="loadingImportedSkills || savingImportedSkills" @click="openSkillImport">导入 Skills</el-button>
          </div>
        </div>

        <div class="toolbar skill-toolbar">
          <el-input v-model="skillSearchText" clearable placeholder="搜索技能、分类、标签">
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-select v-model="skillCategoryFilter" placeholder="分类" class="toolbar-select">
            <el-option label="全部分类" value="all" />
            <el-option v-for="category in skillCategoryOptions" :key="category" :label="skillCategoryLabel(category)" :value="category" />
          </el-select>
        </div>

        <div v-if="importedSkillItems.length" class="skill-bulkbar">
          <div class="skill-bulkbar-main">
            <el-checkbox
              :model-value="allFilteredImportedSelected"
              :indeterminate="filteredImportedIndeterminate"
              :disabled="!hasActiveSkillFilter || !filteredImportedSkillItems.length || savingImportedSkills"
              @change="(value) => toggleFilteredSkillSelection(Boolean(value))"
            >
              筛选结果
            </el-checkbox>
            <span>已选 {{ selectedSkillCount }} 个，自定义 {{ importedSkillItems.length }} 个</span>
            <span v-if="hasActiveSkillFilter">当前匹配 {{ filteredImportedSkillItems.length }} 个</span>
          </div>
          <div class="skill-bulkbar-actions">
            <el-button size="small" plain :icon="Check" :disabled="!hasActiveSkillFilter || !filteredImportedSkillItems.length || savingImportedSkills" @click="selectFilteredImportedSkills">
              选择筛选结果
            </el-button>
            <el-button size="small" plain :icon="Close" :disabled="!selectedSkillCount || savingImportedSkills" @click="clearSkillSelection">
              清除选择
            </el-button>
            <el-button size="small" plain type="danger" :icon="Delete" :disabled="!selectedSkillCount || savingImportedSkills" :loading="savingImportedSkills" @click="deleteSelectedSkills">
              删除选中
            </el-button>
            <el-button size="small" plain type="danger" :icon="Delete" :disabled="!canDeleteFilteredSkills || savingImportedSkills" :loading="savingImportedSkills" @click="deleteFilteredImportedSkills">
              删除筛选结果
            </el-button>
          </div>
        </div>

        <div v-if="filteredSkillItems.length" class="skill-grid">
          <article v-for="skill in filteredSkillItems" :key="skill.id" class="skill-card" :class="{ selected: skill.imported && isSkillSelected(skill.id) }">
            <div class="skill-card-head">
              <div>
                <strong>{{ skill.name }}</strong>
                <span>{{ skillCategoryLabel(skill.category) }}</span>
              </div>
              <el-checkbox
                v-if="skill.imported"
                class="skill-select"
                :model-value="isSkillSelected(skill.id)"
                :disabled="savingImportedSkills"
                @click.stop
                @change="(value) => toggleSkillSelection(skill.id, Boolean(value))"
              />
            </div>
            <p>{{ skill.description }}</p>
            <div class="skill-meta">
              <el-tag v-if="!skill.imported" size="small" type="success" effect="plain">内置</el-tag>
              <el-tag v-else size="small" type="warning" effect="plain">自定义</el-tag>
              <el-tag v-if="skill.fit === 'high'" size="small" type="primary" effect="plain">高适配</el-tag>
              <el-tag v-else-if="skill.fit === 'medium'" size="small" type="info" effect="plain">中适配</el-tag>
            </div>
            <div v-if="skill.imported" class="skill-actions">
              <el-button size="small" plain type="danger" :icon="Delete" :loading="savingImportedSkills" @click="removeImportedSkill(skill.id)">删除</el-button>
            </div>
          </article>
        </div>
        <el-empty v-else description="没有匹配的技能" />
      </section>

      <section class="bottom-grid">
        <article class="panel-card plugin-panel">
          <div class="section-heading compact">
            <div>
              <h3>插件工具</h3>
            </div>
            <el-tag :type="pluginHealthTagType" effect="light">{{ pluginHealthLabel }}</el-tag>
          </div>
          <div v-if="pluginTools.length" class="plugin-list">
            <div v-for="tool in pluginTools" :key="tool.id" class="mini-item">
              <strong>{{ tool.name }}</strong>
              <span>{{ tool.desc || '插件未提供说明' }}</span>
            </div>
          </div>
          <el-empty v-else description="暂无插件工具" :image-size="64" />
        </article>

        <article class="panel-card log-panel">
          <div class="section-heading compact">
            <div>
              <h3>最近调用</h3>
            </div>
            <el-tag effect="plain">{{ recentToolLogs.length }} 条记录</el-tag>
          </div>
          <div v-if="recentToolLogs.length" class="log-list">
            <div v-for="(log, idx) in recentToolLogs" :key="`${log.sortKey}-${idx}`" class="log-item">
              <span>{{ log.time }}</span>
              <el-tag size="small" :title="log.source" :type="toolLogTagType(log.actionStatus || log.status)" effect="plain">{{ toolActionStatusLabel(log.actionStatus || log.status) }}</el-tag>
              <strong>{{ log.text }}</strong>
              <small v-if="log.evidence?.length" class="log-evidence">{{ log.evidence[0] }}</small>
            </div>
          </div>
          <el-empty v-else description="暂无工具调用记录" :image-size="64" />
        </article>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Close, Delete, Refresh, Search, Upload } from '@element-plus/icons-vue'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { pluginClient, systemClient } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useI18n } from '@/i18n'
import { curatedSkillRecommendations } from '../skillRecommendations'
import type { PluginLoadFailure, PluginRuntimeState, PluginToolCapabilityContribution } from '../../../../shared/plugin'
import type { CapabilityDescriptor, CapabilityKind, CapabilityRiskLevel, SkillCatalogItem } from '../../../../shared/capability'
import type { AgentTraceSnapshot, MCPSnapshot, MCPServerConfigSnapshot, MCPServerStatusSnapshot, RuntimeLoopRecord, StepExecutionRecord } from '../../../../shared/agent'
import { projectToolActionStatus, toolActionStatusLabel, toolEvidenceFromRecord, type ToolActionStatus } from '../toolActionProjection'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'
type CapabilityKindFilter = CapabilityKind | ''
type CapabilityRiskFilter = CapabilityRiskLevel | ''
type ApprovalFilter = 'all' | 'required' | 'free'
type MetricTone = 'blue' | 'amber' | 'rose' | 'emerald'
type SkillCategoryFilter = 'all' | string
type ImportedSkillCatalogItem = SkillCatalogItem & { imported?: boolean }
type HealthActionKey = 'ready' | 'approval' | 'mcp-error' | 'plugin-error' | 'trace'
type MCPFilter = 'all' | 'connected' | 'error' | 'disabled'

const IMPORTED_SKILLS_STORAGE_KEY = 'yuizaki.importedSkills'
const IMPORTED_SKILLS_MIGRATION_KEY = 'yuizaki.importedSkills.backendMigrated'
const IMPORTED_SKILLS_DIRTY_KEY = 'yuizaki.importedSkills.localDirty'
const workspaceStore = useWorkspaceStore()
const { t } = useI18n()
const canonicalPath = (moduleId: string) => `/w/${workspaceStore.activeWorkspaceId}/${moduleId}`

interface SourceCard {
  kind: CapabilityKindFilter
  title: string
  description: string
  accent: string
  count: number
}

interface RiskOption {
  value: CapabilityRiskLevel
  label: string
}

interface ToolLogItem {
  time: string
  text: string
  source: string
  status?: string | null
  sortKey: string
  actionStatus?: ToolActionStatus
  evidence?: string[]
}

interface HealthItem {
  key: HealthActionKey
  label: string
  value: number
  detail: string
  tone: MetricTone
}

interface MCPFilterOption {
  value: MCPFilter
  label: string
  count: number
}

type MCPRow = MCPServerConfigSnapshot & MCPServerStatusSnapshot & {
  name: string
  connected: boolean
  tools_count: number
  resources_count: number
  prompts_count: number
}

const logs = ref<ToolLogItem[]>([])
const pluginTools = ref<PluginToolCapabilityContribution[]>([])
const pluginStates = ref<PluginRuntimeState[]>([])
const pluginLoadFailures = ref<PluginLoadFailure[]>([])
const capabilities = ref<CapabilityDescriptor[]>([])
const agentTrace = ref<AgentTraceSnapshot | null>(null)
const mcpSnapshot = ref<MCPSnapshot | null>(null)

const filterKind = ref<CapabilityKindFilter>('')
const filterRisk = ref<CapabilityRiskFilter>('')
const filterApproval = ref<ApprovalFilter>('all')
const searchText = ref('')
const selectedCapabilityId = ref('')
const activeHealthKey = ref<HealthActionKey | ''>('')
const mcpFilter = ref<MCPFilter>('all')
const skillSearchText = ref('')
const skillCategoryFilter = ref<SkillCategoryFilter>('all')
const skillImportInput = ref<HTMLInputElement | null>(null)
const importedSkillItems = ref<ImportedSkillCatalogItem[]>([])
const selectedSkillIds = ref(new Set<string>())

const loadingCapabilities = ref(false)
const loadingPlugins = ref(false)
const loadingMcp = ref(false)
const loadingImportedSkills = ref(false)
const savingImportedSkills = ref(false)
const capabilityLoadError = ref('')
const mcpLoadError = ref('')
const importedSkillStorageError = ref('')
const importedSkillBackendReady = ref(false)
const mcpActionNames = ref(new Set<string>())
let pluginLoadSequence = 0
let capabilityLoadSequence = 0
let toolTraceLoadSequence = 0
let mcpLoadSequence = 0

const riskOptions: RiskOption[] = [
  { value: 'safe', label: '安全' },
  { value: 'low', label: '低风险' },
  { value: 'medium', label: '中风险' },
  { value: 'high', label: '高风险' },
  { value: 'critical', label: '关键风险' },
]

const capabilityDescriptionOverrides: Record<string, string> = {
  open_app: '按名称启动本地桌面应用。',
  open_url: '使用默认浏览器打开链接。',
  read_file: '读取本地文本文件内容。',
  write_file: '将文本内容写入本地文件。',
  web_search: '搜索当前公开网络信息，并返回带链接的简明结果。',
  'browser.open_page': '通过 Playwright MCP 服务打开浏览器页面。',
  'time.now': '获取当前本地时间。',
  mcp_playwright_browser_open_page: '在 Playwright 浏览器上下文中打开 URL，并等待网络空闲。',
  mcp_playwright_browser_click: '打开 URL 后点击指定 CSS 选择器。',
  'yuizaki.observe-recall-loop': '收集运行时输入，召回相关记忆，并送入桌宠 Agent 链路。',
  'yuizaki.capability-routing': '通过统一能力快照选择内置工具、插件工具或 MCP 工具。',
  'yuizaki.create-once-task': '在本地调度器中创建一次性任务。',
  'yuizaki.create-interval-task': '在本地调度器中创建按间隔重复执行的任务。',
  'yuizaki.skill.voice-dialogue-chain': '把麦克风输入整理成文本，交给 LLM 生成回复，再触发 TTS 和桌宠动作。',
  'yuizaki.skill.long-dialogue-summary': '把长聊天、语音转写和会话记录整理成摘要、决定、待办和风险。',
  'yuizaki.skill.companion-reflection': '分析对话里的情绪、沟通模式和可改进点，用于长期桌宠记忆和关系反馈。',
  'yuizaki.skill.memory-capture': '把事实、偏好、项目决定和待办沉淀到可检索记忆。',
  'yuizaki.skill.realtime-screen-vision': '把桌面截图作为短时视觉帧交给桌宠理解，OCR 仅用于需要精确读字的场景。',
  'yuizaki.skill.local-file-organizer': '识别本机文件、素材和导入资源用途，给出整理、重命名和归档建议。',
  'yuizaki.skill.ocr-document-organizer': '读取截图、票据或扫描文档里的关键信息，生成结构化条目并建议归档位置。',
  'yuizaki.skill.webapp-testing': '用 Playwright 检查本地 Electron/Vite 页面、交互、截图和控制台错误。',
  'yuizaki.skill.frontend-design': '优化桌宠面板、设置页、本地能力页和调试页的布局、文案、状态和响应式细节。',
  'yuizaki.skill.interface-hardening': '检查空状态、错误提示、长文本溢出、中文文案、深色模式和失败降级。',
  'yuizaki.skill.code-review': '按缺陷、回归风险、缺失测试和行为变化审查改动。',
  'yuizaki.skill.repo-analysis': '只读梳理代码结构、调用关系和风险点，用于复杂改动前建立事实图。',
  'yuizaki.skill.best-practice-research': '优先查官方文档和上游资料，适合接新模型、TTS、ASR、MCP、Ollama、LM Studio 或 SDK 前使用。',
  'yuizaki.skill.mcp-builder': '把本地工具、资源读取、浏览器控制或外部服务包装成标准 MCP 工具。',
  'yuizaki.skill.skill-authoring': '把常用链路沉淀成可复用 Skill，包括触发条件、输入、流程、校验和失败兜底。',
  'yuizaki.skill.image-generation': '生成或编辑头像、背景、UI 参考图和透明素材。',
  'yuizaki.skill.image-enhancement': '提升截图清晰度和可读性，适合 UI 验收、反馈图和文档插图。',
  'yuizaki.skill.document-export': '把摘要、报告和会话结果导出为 PDF、DOCX、PPTX 或 XLSX。',
  'yuizaki.skill.spreadsheet-helper': '编写和调试 Excel/表格公式，适合导入数据、统计结果和批量整理。',
  'yuizaki.skill.task-triage': '把用户反馈、长对话或问题清单拆成优先级、复现步骤、下一步动作和回复草稿。',
  'yuizaki.skill.agent-trace-debug': '分析 LLM、工具调用、记忆召回和插件钩子的执行轨迹，用于排查输出和耗时问题。',
  'yuizaki.skill.release-notes': '把技术改动整理成用户可读的更新说明。',
  'yuizaki.skill.design-system': '沉淀颜色、间距、组件状态和文案规则，让设置页、桌宠页和能力页保持一致。',
  'yuizaki.skill.web-research': '对需要时效性的模型、插件、依赖和工具信息进行搜索、比对和资料整理。',
  'yuizaki.skill.content-writing': '把调研结果、教程、FAQ 和版本说明写成清晰中文内容。',
  'yuizaki.skill.project-planning': '把模糊需求拆成范围、里程碑、验收标准和风险。',
  'yuizaki.skill.quality-cleanup': '清理重复抽象、冗余 UI 文案、过度包装和不一致命名，保持改动小而可验收。',
}

const capabilityNameDescriptionOverrides: Record<string, string> = {
  open_app: '按名称启动本地桌面应用。',
  open_url: '使用默认浏览器打开链接。',
  read_file: '读取本地文本文件内容。',
  write_file: '将文本内容写入本地文件。',
  web_search: '搜索当前公开网络信息，并返回带链接的简明结果。',
  'browser.open_page': '通过 Playwright MCP 服务打开浏览器页面。',
  'time.now': '获取当前本地时间。',
  mcp_playwright_browser_open_page: '在 Playwright 浏览器上下文中打开 URL，并等待网络空闲。',
  mcp_playwright_browser_click: '打开 URL 后点击指定 CSS 选择器。',
  'Observe / Recall Loop': '收集运行时输入，召回相关记忆，并送入桌宠 Agent 链路。',
  'Capability Routing': '通过统一能力快照选择内置工具、插件工具或 MCP 工具。',
  'Create Once Task': '在本地调度器中创建一次性任务。',
  'Create Interval Task': '在本地调度器中创建按间隔重复执行的任务。',
}

const capabilityRawDescriptionOverrides: Record<string, string> = {
  'launch a desktop application by name': '按名称启动本地桌面应用。',
  'open a url in the default browser': '使用默认浏览器打开链接。',
  'read a local text file': '读取本地文本文件内容。',
  'write text content to a local file': '将文本内容写入本地文件。',
  'search the web for current public information and return concise results with urls': '搜索当前公开网络信息，并返回带链接的简明结果。',
  'open a browser page via playwright mcp server': '通过 Playwright MCP 服务打开浏览器页面。',
  'get the current local time': '获取当前本地时间。',
  'open a url in a playwright browser context and wait for network idle. (mcp: playwright/browser.open_page)': '在 Playwright 浏览器上下文中打开 URL，并等待网络空闲。',
  'open a url and click a css selector with playwright. (mcp: playwright/browser.click)': '打开 URL 后点击指定 CSS 选择器。',
  'collect runtime input, recall memory, and feed the companion agent pipeline.': '收集运行时输入，召回相关记忆，并送入桌宠 Agent 链路。',
  'route builtin, plugin, and mcp capabilities through the unified registry snapshot.': '通过统一能力快照选择内置工具、插件工具或 MCP 工具。',
  'create a one-shot scheduled task in the local scheduler.': '在本地调度器中创建一次性任务。',
  'create a recurring scheduled task in the local scheduler.': '在本地调度器中创建按间隔重复执行的任务。',
}

const normalizedSearch = computed(() => searchText.value.trim().toLowerCase())
const normalizedSkillSearch = computed(() => skillSearchText.value.trim().toLowerCase())
const loadingSnapshots = computed(() => loadingCapabilities.value || loadingPlugins.value || loadingMcp.value)

const readyCapabilityCount = computed(() => capabilities.value.filter(isDirectExecutableCapability).length)
const approvalRequiredCount = computed(() => capabilities.value.filter(item => item.requiresApproval).length)
const highRiskCount = computed(() => capabilities.value.filter(item => ['high', 'critical'].includes(item.riskLevel)).length)
const tracedCapabilityCount = computed(() => capabilities.value.filter(item => item.observability?.trace).length)
const pluginIssueCount = computed(() => (
  pluginLoadFailures.value.length +
  pluginStates.value.filter(item => ['blocked', 'error', 'degraded'].includes(item.status)).length
))
const allSkillItems = computed<ImportedSkillCatalogItem[]>(() => {
  const merged = new Map<string, ImportedSkillCatalogItem>()
  for (const skill of curatedSkillRecommendations) {
    merged.set(skill.id, { ...skill, imported: false })
  }
  for (const skill of importedSkillItems.value) {
    merged.set(skill.id, { ...skill, imported: true })
  }
  return [...merged.values()]
})
const builtInSkillCount = computed(() => allSkillItems.value.filter(item => !item.imported).length)
const mcpRows = computed<MCPRow[]>(() => {
  const snapshot = mcpSnapshot.value
  if (!snapshot) return []
  return Object.entries(snapshot.servers || {})
    .map(([name, server]) => {
      const status = snapshot.status?.[name] || {}
      return {
        ...server,
        ...status,
        name,
        enabled: server.enabled,
        connected: Boolean(status.connected),
        tools_count: status.tools_count ?? 0,
        resources_count: status.resources_count ?? 0,
        prompts_count: status.prompts_count ?? 0,
      }
    })
    .sort((left, right) => Number(right.enabled) - Number(left.enabled) || left.name.localeCompare(right.name, 'zh-CN'))
})
const mcpServerCount = computed(() => mcpRows.value.length)
const mcpEnabledCount = computed(() => mcpRows.value.filter(item => item.enabled).length)
const mcpConnectedCount = computed(() => mcpRows.value.filter(item => item.connected).length)
const mcpErrorCount = computed(() => mcpRows.value.filter(isMcpErrored).length)
const mcpDisabledCount = computed(() => mcpRows.value.filter(item => !item.enabled).length)
const mcpFilterOptions = computed<MCPFilterOption[]>(() => [
  { value: 'all', label: '全部', count: mcpRows.value.length },
  { value: 'connected', label: '已连接', count: mcpConnectedCount.value },
  { value: 'error', label: '异常', count: mcpErrorCount.value },
  { value: 'disabled', label: '未启用', count: mcpDisabledCount.value },
])
const filteredMcpRows = computed(() => mcpRows.value.filter((server) => {
  if (mcpFilter.value === 'connected') return server.connected
  if (mcpFilter.value === 'error') return isMcpErrored(server)
  if (mcpFilter.value === 'disabled') return !server.enabled
  return true
}))
const mcpEmptyDescription = computed(() => {
  if (!mcpRows.value.length) return '暂无 MCP 服务'
  const selected = mcpFilterOptions.value.find(item => item.value === mcpFilter.value)
  return `没有${selected?.label || '当前'} MCP 服务`
})

const skillCategoryOptions = computed(() => (
  [...new Set(allSkillItems.value.map(item => item.category).filter(Boolean))]
    .sort((a, b) => skillCategoryLabel(a).localeCompare(skillCategoryLabel(b), 'zh-CN'))
))

const summaryCards = computed(() => [
  { label: '可见能力', value: capabilities.value.length, desc: '当前运行时已注册', tone: 'blue' as MetricTone },
  { label: 'MCP 服务', value: mcpServerCount.value, desc: `${mcpEnabledCount.value} 个启用，${mcpConnectedCount.value} 个已连接`, tone: 'emerald' as MetricTone },
  { label: '内置确认', value: approvalRequiredCount.value, desc: '仅统计仍需逐次确认的入口', tone: 'amber' as MetricTone },
  { label: '高风险', value: highRiskCount.value, desc: '文件、桌面或外部动作', tone: 'rose' as MetricTone },
  { label: '已追踪', value: tracedCapabilityCount.value, desc: '写入 trace 的入口', tone: 'emerald' as MetricTone },
])

const healthItems = computed<HealthItem[]>(() => [
  { key: 'ready', label: '可直接执行', value: readyCapabilityCount.value, detail: '低风险或已选 MCP/插件', tone: 'emerald' },
  { key: 'approval', label: '内置确认', value: approvalRequiredCount.value, detail: '执行前会提示', tone: 'amber' },
  { key: 'mcp-error', label: 'MCP 异常', value: mcpErrorCount.value, detail: '连接或清单错误', tone: mcpErrorCount.value ? 'rose' : 'emerald' },
  { key: 'plugin-error', label: '插件异常', value: pluginIssueCount.value, detail: '阻断、降级或装载失败', tone: pluginIssueCount.value ? 'rose' : 'emerald' },
  { key: 'trace', label: '有调用记录', value: recentToolLogs.value.length, detail: '最近工具链路', tone: 'blue' },
])

const sourceCards = computed<SourceCard[]>(() => [
  {
    kind: '',
    title: '全部能力',
    description: '查看所有已注册入口。',
    accent: '#64748b',
    count: capabilities.value.length,
  },
  {
    kind: 'builtin-tool',
    title: '内置工具',
    description: '文件、浏览器、桌面、时间和搜索。',
    accent: '#2563eb',
    count: countByKind('builtin-tool'),
  },
  {
    kind: 'mcp-tool',
    title: 'MCP 工具',
    description: '由 MCP 服务提供的外部能力。',
    accent: '#d97706',
    count: countByKind('mcp-tool'),
  },
  {
    kind: 'plugin-tool',
    title: '插件工具',
    description: '由插件注册的轻量扩展。',
    accent: '#059669',
    count: countByKind('plugin-tool'),
  },
  {
    kind: 'skill',
    title: '编排技能',
    description: '可复用的 Agent 流程。',
    accent: '#db2777',
    count: countByKind('skill'),
  },
  {
    kind: 'command',
    title: '本地命令',
    description: '任务创建和调度入口。',
    accent: '#7c3aed',
    count: countByKind('command'),
  },
])

const pluginHealthLabel = computed(() => {
  const blocked = pluginStates.value.filter(item => ['blocked', 'error'].includes(item.status)).length
  const degraded = pluginStates.value.filter(item => item.status === 'degraded').length
  if (pluginLoadFailures.value.length) return `${pluginLoadFailures.value.length} 个加载失败`
  if (blocked) return `${blocked} 个不可用`
  if (degraded) return `${degraded} 个降级`
  if (pluginStates.value.length) return `${pluginStates.value.length} 个已加载`
  return '暂无插件'
})

const pluginHealthTagType = computed<TagType>(() => {
  if (pluginLoadFailures.value.length) return 'danger'
  if (pluginStates.value.some(item => ['blocked', 'error'].includes(item.status))) return 'danger'
  if (pluginStates.value.some(item => item.status === 'degraded')) return 'warning'
  if (pluginStates.value.length) return 'success'
  return 'info'
})

const filteredCapabilities = computed(() => capabilities.value.filter((item) => {
  if (activeHealthKey.value === 'ready' && !isDirectExecutableCapability(item)) return false
  if (activeHealthKey.value === 'trace' && !item.observability?.trace) return false
  if (filterKind.value && item.kind !== filterKind.value) return false
  if (filterRisk.value && item.riskLevel !== filterRisk.value) return false
  if (filterApproval.value === 'required' && !item.requiresApproval) return false
  if (filterApproval.value === 'free' && item.requiresApproval) return false
  const query = normalizedSearch.value
  return !query || searchableText(item).includes(query)
}))

const selectedCapability = computed(() => {
  const selected = filteredCapabilities.value.find(item => item.id === selectedCapabilityId.value)
  return selected ?? filteredCapabilities.value[0] ?? null
})

const filteredSkillItems = computed(() => {
  const query = normalizedSkillSearch.value
  return allSkillItems.value.filter((item) => {
    if (skillCategoryFilter.value !== 'all' && item.category !== skillCategoryFilter.value) return false
    if (!query) return true
    return [
      item.name,
      item.description,
      item.category,
      ...(item.tags || []),
    ].filter(Boolean).join(' ').toLowerCase().includes(query)
  })
})

const hasActiveSkillFilter = computed(() => Boolean(normalizedSkillSearch.value) || skillCategoryFilter.value !== 'all')
const filteredImportedSkillItems = computed(() => filteredSkillItems.value.filter(skill => skill.imported))
const filteredImportedSkillIds = computed(() => filteredImportedSkillItems.value.map(skill => skill.id))
const selectedSkillCount = computed(() => selectedSkillIds.value.size)
const selectedFilteredImportedCount = computed(() => filteredImportedSkillIds.value.filter(id => selectedSkillIds.value.has(id)).length)
const allFilteredImportedSelected = computed(() => (
  filteredImportedSkillIds.value.length > 0 &&
  selectedFilteredImportedCount.value === filteredImportedSkillIds.value.length
))
const filteredImportedIndeterminate = computed(() => (
  selectedFilteredImportedCount.value > 0 &&
  selectedFilteredImportedCount.value < filteredImportedSkillIds.value.length
))
const canDeleteFilteredSkills = computed(() => hasActiveSkillFilter.value && filteredImportedSkillItems.value.length > 0)
const skillStorageLabel = computed(() => {
  if (savingImportedSkills.value) return '保存中'
  if (loadingImportedSkills.value) return '读取中'
  if (importedSkillBackendReady.value) return '后端已保存'
  return '本地暂存'
})
const skillStorageTagType = computed<TagType>(() => {
  if (savingImportedSkills.value || loadingImportedSkills.value) return 'info'
  if (importedSkillBackendReady.value) return 'success'
  return importedSkillStorageError.value ? 'warning' : 'info'
})

const traceToolLogs = computed<ToolLogItem[]>(() => {
  const snapshot = agentTrace.value
  if (!snapshot) return []
  const items: ToolLogItem[] = []
  for (const step of snapshot.steps || []) {
    if (!step.tool && !step.capability_id && !step.capability_kind) continue
    items.push(toolLogFromStep(step))
  }
  for (const loop of snapshot.runtime_loop || []) {
    const entry = toolLogFromRuntimeLoop(loop)
    if (entry) items.push(entry)
  }
  return items
})

const recentToolLogs = computed(() => (
  [...logs.value, ...traceToolLogs.value]
    .sort((a, b) => b.sortKey.localeCompare(a.sortKey))
    .slice(0, 20)
))

const activeFilterLabel = computed(() => {
  const kind = sourceCards.value.find(item => item.kind === filterKind.value)?.title || '全部能力'
  const risk = filterRisk.value ? riskLabel(filterRisk.value) : '全部风险'
  const approval = filterApproval.value === 'required' ? '需确认' : filterApproval.value === 'free' ? '免确认' : '全部权限'
  const preset = healthItems.value.find(item => item.key === activeHealthKey.value)?.label
  return `${preset || kind} · ${risk} · ${approval}`
})

function searchableText(item: CapabilityDescriptor) {
  return [
    item.id,
    item.name,
    displayCapabilityDescription(item),
    item.type,
    item.kind,
    item.source,
    item.owner,
    item.riskLevel,
    ...(item.tags || []),
    ...(item.contributionCategories || []),
    ...(item.scopes || []),
    ...(item.memoryHooks || []),
  ].filter(Boolean).join(' ').toLowerCase()
}

function countByKind(kind: CapabilityKindFilter) {
  if (!kind) return capabilities.value.length
  return capabilities.value.filter(item => item.kind === kind).length
}

function isDirectExecutableCapability(item: CapabilityDescriptor) {
  return !item.requiresApproval && (
    ['safe', 'low'].includes(item.riskLevel)
    || ['mcp-tool', 'plugin-tool'].includes(item.kind)
  )
}

function isMcpErrored(server: MCPRow) {
  return Boolean(server.enabled && !server.connected && (server.last_error || server.inventory_error || server.message))
}

function setKindFilter(kind: CapabilityKindFilter) {
  activeHealthKey.value = ''
  filterKind.value = kind
}

function applyHealthAction(action: HealthActionKey) {
  activeHealthKey.value = action
  if (action === 'ready') {
    filterKind.value = ''
    filterRisk.value = ''
    filterApproval.value = 'all'
    searchText.value = ''
    return
  }
  if (action === 'approval') {
    filterKind.value = ''
    filterRisk.value = ''
    filterApproval.value = 'required'
    searchText.value = ''
    return
  }
  if (action === 'mcp-error') {
    filterKind.value = 'mcp-tool'
    filterRisk.value = ''
    filterApproval.value = 'all'
    mcpFilter.value = 'error'
    searchText.value = ''
    return
  }
  if (action === 'plugin-error') {
    filterKind.value = 'plugin-tool'
    filterRisk.value = ''
    filterApproval.value = 'all'
    searchText.value = ''
    return
  }
  if (action === 'trace') {
    filterKind.value = ''
    filterRisk.value = ''
    filterApproval.value = 'all'
    searchText.value = ''
  }
}

function kindLabel(kind: CapabilityKind) {
  const labels: Record<CapabilityKind, string> = {
    'builtin-tool': '内置',
    'plugin-tool': '插件',
    'mcp-tool': 'MCP',
    skill: 'Skill',
    command: '命令',
  }
  return labels[kind] || kind
}

function kindTagType(kind: CapabilityKind): TagType {
  const map: Record<CapabilityKind, TagType> = {
    'builtin-tool': 'primary',
    'plugin-tool': 'success',
    'mcp-tool': 'warning',
    skill: 'danger',
    command: 'info',
  }
  return map[kind]
}

function kindFallbackDescription(kind: CapabilityKind) {
  const map: Record<CapabilityKind, string> = {
    'builtin-tool': 'Yuizaki 后端内置能力，用于基础动作或本地资源访问。',
    'plugin-tool': '插件贡献能力，是否可用取决于插件加载状态。',
    'mcp-tool': 'MCP 服务暴露的工具，是否可用取决于对应服务连接状态。',
    skill: '编排技能，用来描述一段可复用的 Agent 流程。',
    command: '本地命令入口，用来触发后端任务或调度动作。',
  }
  return map[kind]
}

function normalizeDescriptionKey(value?: string) {
  return String(value || '').trim().replace(/\s+/g, ' ').toLowerCase()
}

function displayCapabilityDescription(item: CapabilityDescriptor) {
  const idOverride = capabilityDescriptionOverrides[item.id]
  if (idOverride) return idOverride

  const nameOverride = capabilityNameDescriptionOverrides[item.name]
  if (nameOverride) return nameOverride

  const rawDescriptionOverride = capabilityRawDescriptionOverrides[normalizeDescriptionKey(item.description)]
  if (rawDescriptionOverride) return rawDescriptionOverride

  return item.description || kindFallbackDescription(item.kind)
}

function transportLabel(transport: string) {
  const labels: Record<string, string> = {
    http: 'HTTP',
    sse: 'SSE',
    stdio: 'STDIO',
    streamable_http: '流式 HTTP',
  }
  return labels[transport] || transport.toUpperCase()
}

function mcpEndpointLabel(server: MCPRow) {
  if (server.transport === 'stdio') {
    return `${server.command || 'stdio'} ${(server.args || []).join(' ')}`.trim()
  }
  return server.base_url || '未配置地址'
}

function mcpStatusLabel(server: MCPRow) {
  if (!server.enabled) return '未启用'
  if (server.connected) return '已连接'
  if (server.last_error || server.inventory_error || server.message) return '异常'
  return '已启用'
}

function mcpStatusTagType(server: MCPRow): TagType {
  if (!server.enabled) return 'info'
  if (server.connected) return 'success'
  if (server.last_error || server.inventory_error || server.message) return 'danger'
  return 'warning'
}

function executionLabel(item: CapabilityDescriptor) {
  if (item.requiresApproval) return '执行前确认'
  if (['mcp-tool', 'plugin-tool'].includes(item.kind)) return '启用即授权'
  if (['high', 'critical'].includes(item.riskLevel)) return '高风险免确认'
  return '可直接执行'
}

function ownerLabel(owner?: string) {
  if (!owner) return '未声明'
  const labels: Record<string, string> = {
    'yuizaki.builtin-tools': '内置工具',
    'yuizaki.companion-orchestrator': '桌宠编排',
    'yuizaki.task-router': '任务路由',
  }
  if (owner.startsWith('plugin:')) return `插件 ${owner.slice('plugin:'.length)}`
  if (owner.startsWith('mcp:')) return `MCP ${owner.slice('mcp:'.length)}`
  return labels[owner] || owner
}

function riskLabel(risk: CapabilityRiskLevel) {
  return riskOptions.find(item => item.value === risk)?.label || risk
}

function riskTagType(risk: CapabilityRiskLevel): TagType {
  const map: Record<CapabilityRiskLevel, TagType> = {
    safe: 'success',
    low: 'info',
    medium: 'warning',
    high: 'danger',
    critical: 'danger',
  }
  return map[risk]
}

function riskHint(item: CapabilityDescriptor) {
  if (item.requiresApproval) return '执行前会弹出确认。'
  if (['mcp-tool', 'plugin-tool'].includes(item.kind)) return '由对应服务或插件的启用开关授权，关闭后停止调用。'
  if (['high', 'critical'].includes(item.riskLevel)) return '会触碰文件、桌面或外部服务，建议保留记录。'
  if (item.riskLevel === 'medium') return '适合按需调用并保留执行记录。'
  return '适合作为常规入口。'
}

function capabilityTags(item: CapabilityDescriptor) {
  return [...(item.tags || []), ...(item.contributionCategories || [])]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function schemaFieldNames(schema?: Record<string, unknown>) {
  if (!schema) return []
  const properties = schema.properties
  if (isRecord(properties)) return Object.keys(properties)
  return Object.keys(schema)
}

function schemaSummary(schema?: Record<string, unknown>) {
  const fields = schemaFieldNames(schema)
  if (!fields.length) return '未声明字段'
  if (fields.length <= 4) return fields.join(', ')
  return `${fields.slice(0, 4).join(', ')} +${fields.length - 4}`
}

function schemaPreview(schema?: Record<string, unknown>) {
  if (!schema || !Object.keys(schema).length) return '{}'
  try {
    return JSON.stringify(schema, null, 2)
  } catch {
    return '{...}'
  }
}

function formatTimeout(timeoutMs?: number) {
  if (!timeoutMs) return '默认'
  if (timeoutMs >= 1000) return `${Math.round(timeoutMs / 1000)}s`
  return `${timeoutMs}ms`
}

function skillCategoryLabel(category: string) {
  const labels: Record<string, string> = {
    companion: '桌宠与记忆',
    perception: '感知能力',
    development: '开发工程',
    frontend: '界面体验',
    research: '资料调研',
    automation: '自动化',
    document: '文档数据',
    mcp: 'MCP 扩展',
    governance: '质量治理',
    media: '图像媒体',
    authoring: '技能编写',
    general: '通用',
  }
  return labels[category] || category
}

function openSkillImport() {
  skillImportInput.value?.click()
}

async function handleSkillFileImport(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) return

  try {
    const imported = await importSkillFiles(files)
    if (!imported.length) {
      ElMessage.warning('没有识别到可导入的 Skill')
      return
    }
    await mergeImportedSkills(imported)
    ElMessage.success(`已导入 ${imported.length} 个 Skill`)
  } catch (error) {
    const message = error instanceof Error ? error.message : '导入 Skills 失败'
    ElMessage.error(message)
  }
}

async function importSkillFiles(files: File[]) {
  const imported: ImportedSkillCatalogItem[] = []
  for (const file of files) {
    const text = await file.text()
    if (file.name.toLowerCase().endsWith('.json')) {
      imported.push(...parseSkillJson(text, file.name))
    } else {
      const skill = parseSkillMarkdown(text, file.name)
      if (skill) imported.push(skill)
    }
  }
  return imported
}

function parseSkillJson(text: string, fileName: string): ImportedSkillCatalogItem[] {
  let payload: unknown
  try {
    payload = JSON.parse(text)
  } catch {
    throw new Error(`${fileName} 不是有效 JSON`)
  }

  const candidates = Array.isArray(payload)
    ? payload
    : isRecord(payload) && Array.isArray(payload.items)
      ? payload.items
      : isRecord(payload) && Array.isArray(payload.skills)
        ? payload.skills
        : [payload]

  return candidates
    .map((candidate, index) => normalizeImportedSkill(candidate, `${fileName}-${index + 1}`))
    .filter((item): item is ImportedSkillCatalogItem => Boolean(item))
}

function parseSkillMarkdown(text: string, fileName: string): ImportedSkillCatalogItem | null {
  const frontmatter = parseFrontmatter(text)
  const body = text.replace(/^---\s*[\s\S]*?\s*---/, '').trim()
  const heading = body.match(/^#\s+(.+)$/m)?.[1]?.trim()
  const firstParagraph = body
    .split(/\r?\n/)
    .map(line => line.trim())
    .find(line => line && !line.startsWith('#') && !line.startsWith('---'))
  const name = frontmatter.name || frontmatter.title || heading || fileName.replace(/\.(md|markdown)$/i, '')
  const description = frontmatter.description || firstParagraph || '导入的本地 Skill'

  return normalizeImportedSkill({
    id: frontmatter.id,
    name,
    description,
    category: frontmatter.category,
    fit: frontmatter.fit,
    tags: frontmatter.tags,
  }, fileName)
}

function parseFrontmatter(text: string): Record<string, string> {
  const match = text.match(/^---\s*\r?\n([\s\S]*?)\r?\n---/)
  if (!match) return {}
  return Object.fromEntries(
    match[1]
      .split(/\r?\n/)
      .map((line) => line.match(/^([A-Za-z0-9_-]+):\s*(.+)$/))
      .filter((item): item is RegExpMatchArray => Boolean(item))
      .map((item) => [item[1], item[2].replace(/^['"]|['"]$/g, '').trim()]),
  )
}

function normalizeImportedSkill(candidate: unknown, fallbackId: string): ImportedSkillCatalogItem | null {
  if (!isRecord(candidate)) return null
  const name = stringField(candidate.name) || stringField(candidate.title) || stringField(candidate.id) || fallbackId
  const description = stringField(candidate.description) || stringField(candidate.desc) || stringField(candidate.summary) || '导入的本地 Skill'
  const tags = normalizeTags(candidate.tags)
  const category = normalizeSkillCategory(stringField(candidate.category), name, description, tags)

  return {
    id: normalizeSkillId(stringField(candidate.id) || name || fallbackId),
    name,
    description,
    category,
    source: 'imported',
    status: 'built-in',
    fit: normalizeSkillFit(stringField(candidate.fit)),
    installed: true,
    enabled_codex: true,
    directory: stringField(candidate.directory) || null,
    tags,
    imported: true,
  }
}

function normalizeTags(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(item => String(item).trim()).filter(Boolean)
  }
  if (typeof value === 'string') {
    return value.split(/[,\s]+/).map(item => item.trim()).filter(Boolean)
  }
  return []
}

function normalizeSkillCategory(category: string, name: string, description: string, tags: string[]) {
  const allowed = new Set(['companion', 'development', 'frontend', 'research', 'automation', 'document', 'mcp', 'governance', 'media', 'authoring', 'general'])
  if (allowed.has(category)) return category
  const haystack = `${name} ${description} ${tags.join(' ')}`.toLowerCase()
  if (haystack.includes('mcp')) return 'mcp'
  if (/(ui|ux|frontend|visual|design|界面)/i.test(haystack)) return 'frontend'
  if (/(memory|dialogue|companion|voice|tts|asr|桌宠|语音|记忆)/i.test(haystack)) return 'companion'
  if (/(doc|pdf|sheet|ppt|document|文档|表格)/i.test(haystack)) return 'document'
  if (/(test|debug|review|code|ci|repo|测试|代码)/i.test(haystack)) return 'development'
  if (/(image|media|audio|video|图像|媒体)/i.test(haystack)) return 'media'
  if (/(research|search|docs|调研|搜索)/i.test(haystack)) return 'research'
  if (/(plan|quality|cleanup|治理)/i.test(haystack)) return 'governance'
  if (/(skill|author|prompt|编写)/i.test(haystack)) return 'authoring'
  if (/(task|file|automation|自动化|任务|文件)/i.test(haystack)) return 'automation'
  return 'general'
}

function normalizeSkillFit(value: string): SkillCatalogItem['fit'] {
  if (value === 'high' || value === 'medium' || value === 'low') return value
  return 'medium'
}

function normalizeSkillId(value: string) {
  const raw = value.trim() || 'skill'
  if (/^[a-z0-9_.:-]+$/i.test(raw)) return raw
  const slug = raw
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `imported.skill.${slug || hashString(raw)}`
}

function hashString(value: string) {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0
  }
  return Math.abs(hash).toString(36)
}

function stringField(value: unknown) {
  return typeof value === 'string' ? value.trim() : ''
}

async function mergeImportedSkills(skills: ImportedSkillCatalogItem[]) {
  importedSkillItems.value = mergeSkillItems(importedSkillItems.value, skills)
  await persistImportedSkills()
}

async function removeImportedSkill(skillId: string) {
  await deleteImportedSkills([skillId], { confirm: false, successMessage: '已删除 Skill' })
}

async function loadImportedSkills() {
  if (typeof window === 'undefined') return
  loadingImportedSkills.value = true
  const localItems = readImportedSkillsFromLocalStorage()
  importedSkillItems.value = localItems
  try {
    const snapshot = await systemClient.importedSkills()
    let backendItems = normalizeImportedSkillList(snapshot.items || [])
    if (localItems.length && (!hasMigratedImportedSkills() || hasDirtyImportedSkills())) {
      backendItems = await saveImportedSkillsToBackend(mergeSkillItems(backendItems, localItems))
    }
    importedSkillItems.value = backendItems
    importedSkillBackendReady.value = true
    importedSkillStorageError.value = ''
    markImportedSkillsMigrated()
    markImportedSkillsDirty(false)
    persistImportedSkillsToLocalStorage()
  } catch (error) {
    importedSkillBackendReady.value = false
    importedSkillStorageError.value = error instanceof Error ? error.message : '后端技能存储不可用'
    importedSkillItems.value = localItems
  } finally {
    loadingImportedSkills.value = false
  }
}

function readImportedSkillsFromLocalStorage() {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(IMPORTED_SKILLS_STORAGE_KEY)
    const payload = raw ? JSON.parse(raw) : []
    const items = Array.isArray(payload) ? payload : []
    return normalizeImportedSkillList(items)
  } catch {
    return []
  }
}

async function persistImportedSkills() {
  persistImportedSkillsToLocalStorage()
  if (!importedSkillBackendReady.value) {
    markImportedSkillsDirty(true)
    return
  }
  savingImportedSkills.value = true
  try {
    const savedItems = await saveImportedSkillsToBackend(importedSkillItems.value)
    importedSkillItems.value = savedItems
    importedSkillStorageError.value = ''
    markImportedSkillsDirty(false)
  } catch (error) {
    importedSkillBackendReady.value = false
    importedSkillStorageError.value = error instanceof Error ? error.message : '后端技能保存失败'
    markImportedSkillsDirty(true)
    ElMessage.warning('后端保存失败，已先保存在本地')
  } finally {
    savingImportedSkills.value = false
  }
}

function persistImportedSkillsToLocalStorage() {
  if (typeof window === 'undefined') return
  const payload = toPersistableSkills(importedSkillItems.value)
  window.localStorage.setItem(IMPORTED_SKILLS_STORAGE_KEY, JSON.stringify(payload))
}

async function saveImportedSkillsToBackend(skills: ImportedSkillCatalogItem[]) {
  const snapshot = await systemClient.saveImportedSkills(toPersistableSkills(skills))
  return normalizeImportedSkillList(snapshot.items || [])
}

function normalizeImportedSkillList(items: unknown[]) {
  return items
    .map((item, index) => normalizeImportedSkill(item, `stored-${index + 1}`))
    .filter((item): item is ImportedSkillCatalogItem => Boolean(item))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
}

function mergeSkillItems(baseItems: ImportedSkillCatalogItem[], nextItems: ImportedSkillCatalogItem[]) {
  const merged = new Map(baseItems.map(skill => [skill.id, skill]))
  for (const skill of nextItems) merged.set(skill.id, { ...skill, imported: true })
  return [...merged.values()].sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
}

function toPersistableSkills(skills: ImportedSkillCatalogItem[]) {
  return skills.map(({ imported: _imported, ...skill }) => ({
    ...skill,
    source: 'imported',
    status: 'built-in',
    installed: true,
    enabled_codex: true,
  }))
}

function hasMigratedImportedSkills() {
  if (typeof window === 'undefined') return true
  return window.localStorage.getItem(IMPORTED_SKILLS_MIGRATION_KEY) === '1'
}

function markImportedSkillsMigrated() {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(IMPORTED_SKILLS_MIGRATION_KEY, '1')
}

function hasDirtyImportedSkills() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(IMPORTED_SKILLS_DIRTY_KEY) === '1'
}

function markImportedSkillsDirty(dirty: boolean) {
  if (typeof window === 'undefined') return
  if (dirty) {
    window.localStorage.setItem(IMPORTED_SKILLS_DIRTY_KEY, '1')
  } else {
    window.localStorage.removeItem(IMPORTED_SKILLS_DIRTY_KEY)
  }
}

function isSkillSelected(skillId: string) {
  return selectedSkillIds.value.has(skillId)
}

function toggleSkillSelection(skillId: string, selected: boolean) {
  if (!importedSkillItems.value.some(skill => skill.id === skillId)) return
  const next = new Set(selectedSkillIds.value)
  if (selected) {
    next.add(skillId)
  } else {
    next.delete(skillId)
  }
  selectedSkillIds.value = next
}

function toggleFilteredSkillSelection(selected: boolean) {
  const next = new Set(selectedSkillIds.value)
  for (const skillId of filteredImportedSkillIds.value) {
    if (selected) {
      next.add(skillId)
    } else {
      next.delete(skillId)
    }
  }
  selectedSkillIds.value = next
}

function selectFilteredImportedSkills() {
  if (!hasActiveSkillFilter.value) return
  toggleFilteredSkillSelection(true)
}

function clearSkillSelection() {
  selectedSkillIds.value = new Set()
}

async function deleteSelectedSkills() {
  await deleteImportedSkills([...selectedSkillIds.value], {
    confirm: true,
    title: '删除选中 Skills',
    successMessage: '已删除选中的 Skill',
  })
}

async function deleteFilteredImportedSkills() {
  if (!canDeleteFilteredSkills.value) return
  await deleteImportedSkills(filteredImportedSkillIds.value, {
    confirm: true,
    title: '删除筛选结果',
    successMessage: '已删除当前筛选结果中的 Skill',
  })
}

async function deleteImportedSkills(skillIds: string[], options: { confirm?: boolean; title?: string; successMessage?: string } = {}) {
  const uniqueIds = [...new Set(skillIds.filter(Boolean))]
  if (!uniqueIds.length) return
  if (options.confirm !== false) {
    try {
      await ElMessageBox.confirm(
        `将直接删除 ${uniqueIds.length} 个自定义 Skill，内置技能不会受影响。`,
        options.title || '删除 Skills',
        {
          confirmButtonText: '删除',
          cancelButtonText: '取消',
          type: 'warning',
        },
      )
    } catch {
      return
    }
  }

  const nextItems = importedSkillItems.value.filter(skill => !uniqueIds.includes(skill.id))
  importedSkillItems.value = nextItems
  pruneSelectedSkillIds()
  persistImportedSkillsToLocalStorage()
  if (!importedSkillBackendReady.value) markImportedSkillsDirty(true)

  if (importedSkillBackendReady.value) {
    savingImportedSkills.value = true
    try {
      const snapshot = await systemClient.removeImportedSkills(uniqueIds)
      importedSkillItems.value = normalizeImportedSkillList(snapshot.items || [])
      persistImportedSkillsToLocalStorage()
      importedSkillStorageError.value = ''
      markImportedSkillsDirty(false)
    } catch {
      try {
        const savedItems = await saveImportedSkillsToBackend(nextItems)
        importedSkillItems.value = savedItems
        persistImportedSkillsToLocalStorage()
        importedSkillStorageError.value = ''
        markImportedSkillsDirty(false)
      } catch (error) {
        importedSkillBackendReady.value = false
        importedSkillStorageError.value = error instanceof Error ? error.message : '后端技能删除失败'
        markImportedSkillsDirty(true)
        ElMessage.warning('后端删除失败，已先更新本地列表')
      }
    } finally {
      savingImportedSkills.value = false
      pruneSelectedSkillIds()
    }
  }

  ElMessage.success(options.successMessage || '已删除 Skill')
}

function pruneSelectedSkillIds() {
  const validIds = new Set(importedSkillItems.value.map(skill => skill.id))
  const next = new Set([...selectedSkillIds.value].filter(skillId => validIds.has(skillId)))
  if (next.size !== selectedSkillIds.value.size) selectedSkillIds.value = next
}

const pushLog = (text: string) => {
  const now = new Date()
  logs.value.unshift({
    time: now.toLocaleTimeString(),
    text,
    source: '本地',
    status: 'ok',
    sortKey: now.toISOString(),
  })
  if (logs.value.length > 20) logs.value.pop()
}

function addMcpAction(name: string) {
  const next = new Set(mcpActionNames.value)
  next.add(name)
  mcpActionNames.value = next
}

function removeMcpAction(name: string) {
  const next = new Set(mcpActionNames.value)
  next.delete(name)
  mcpActionNames.value = next
}

function formatTraceTime(timestamp?: string) {
  if (!timestamp) return '-'
  const parts = timestamp.split('T')
  if (parts.length > 1) return parts[1].replace('Z', '').slice(0, 8)
  return timestamp
}

function toolLogTagType(status?: string | null): TagType {
  const raw = String(status || '').toLowerCase()
  if (raw.includes('error') || raw.includes('fail')) return 'danger'
  if (raw.includes('skip') || raw.includes('partial')) return 'warning'
  if (raw.includes('completed') && !raw.includes('verified')) return 'info'
  if (raw === 'ok' || raw.includes('success') || raw.includes('complete')) return 'success'
  return 'info'
}

function toolLogFromStep(step: StepExecutionRecord): ToolLogItem {
  const capability = step.capability_id || step.tool || step.capability_kind || step.kind
  const result = step.error ? `失败: ${step.error}` : (step.title || step.reply_preview || step.status || '已记录')
  return {
    time: formatTraceTime(step.timestamp),
    text: `${capability} · ${result}`,
    source: 'trace',
    status: step.status,
    sortKey: step.timestamp || '',
    actionStatus: projectToolActionStatus(step.status, undefined),
    evidence: toolEvidenceFromRecord(step),
  }
}

function toolLogFromRuntimeLoop(loop: RuntimeLoopRecord): ToolLogItem | null {
  const data = isRecord(loop.data) ? loop.data : null
  const capability = data && typeof data.capability_id === 'string'
    ? data.capability_id
    : data && typeof data.capability_kind === 'string'
      ? data.capability_kind
      : null
  if (!capability && loop.stage !== 'tool_call') return null
  return {
    time: formatTraceTime(loop.timestamp),
    text: `${capability || loop.stage} · ${loop.summary || loop.status}`,
    source: 'runtime',
    status: loop.status,
    sortKey: loop.timestamp || '',
    actionStatus: projectToolActionStatus(loop.status, data?.verificationStatus ?? data?.verification_status),
    evidence: toolEvidenceFromRecord(data || {}),
  }
}

async function loadPlugins() {
  const requestId = ++pluginLoadSequence
  loadingPlugins.value = true
  try {
    const payload = await pluginClient.list()
    if (requestId !== pluginLoadSequence) return
    pluginTools.value = payload.toolCapabilities ?? []
    pluginStates.value = payload.pluginStates ?? []
    pluginLoadFailures.value = payload.loadFailures ?? []
  } catch (error) {
    if (requestId !== pluginLoadSequence) return
    const message = error instanceof Error ? error.message : '未知错误'
    pushLog(`插件工具加载失败: ${message}`)
  } finally {
    if (requestId === pluginLoadSequence) loadingPlugins.value = false
  }
}

async function loadCapabilities() {
  const requestId = ++capabilityLoadSequence
  loadingCapabilities.value = true
  capabilityLoadError.value = ''
  try {
    const snapshot = await systemClient.capabilities()
    if (requestId !== capabilityLoadSequence) return
    capabilities.value = snapshot.capabilities ?? []
    if (!capabilities.value.some(item => item.id === selectedCapabilityId.value) && capabilities.value[0]) {
      selectedCapabilityId.value = capabilities.value[0].id
    }
  } catch (error) {
    if (requestId !== capabilityLoadSequence) return
    const message = error instanceof Error ? error.message : '未知错误'
    capabilityLoadError.value = `能力快照加载失败: ${message}`
  } finally {
    if (requestId === capabilityLoadSequence) loadingCapabilities.value = false
  }
}

async function loadToolTrace() {
  const requestId = ++toolTraceLoadSequence
  try {
    const snapshot = await systemClient.agentTrace()
    if (requestId !== toolTraceLoadSequence) return
    agentTrace.value = snapshot
  } catch (error) {
    if (requestId !== toolTraceLoadSequence) return
    const message = error instanceof Error ? error.message : '未知错误'
    pushLog(`后端工具记录加载失败: ${message}`)
  }
}

async function loadMcpServers() {
  const requestId = ++mcpLoadSequence
  loadingMcp.value = true
  mcpLoadError.value = ''
  try {
    const snapshot = await systemClient.mcp()
    if (requestId !== mcpLoadSequence) return
    mcpSnapshot.value = snapshot
  } catch (error) {
    if (requestId !== mcpLoadSequence) return
    const message = error instanceof Error ? error.message : '未知错误'
    mcpLoadError.value = `MCP 服务加载失败: ${message}`
  } finally {
    if (requestId === mcpLoadSequence) loadingMcp.value = false
  }
}

async function toggleMcpServer(serverName: string, enabled: boolean) {
  addMcpAction(serverName)
  try {
    await systemClient.toggleMcp(serverName, enabled)
    await loadMcpServers()
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    pushLog(`MCP ${serverName} ${enabled ? '启用' : '停用'}失败: ${message}`)
    await loadMcpServers()
  } finally {
    removeMcpAction(serverName)
  }
}

async function refreshMcpServer(serverName: string) {
  const actionName = `${serverName}:refresh`
  addMcpAction(actionName)
  try {
    await systemClient.refreshMcp(serverName)
    await loadMcpServers()
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    pushLog(`MCP ${serverName} 重连失败: ${message}`)
  } finally {
    removeMcpAction(actionName)
  }
}

async function refreshSnapshots() {
  await Promise.all([loadPlugins(), loadCapabilities(), loadToolTrace(), loadMcpServers()])
}

watch(importedSkillItems, pruneSelectedSkillIds)

onMounted(async () => {
  await loadImportedSkills()
  await refreshSnapshots()
})
</script>

<style scoped>
.tool-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-card,
.summary-card {
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
}

.overview-band {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}

.summary-card {
  min-height: 88px;
  padding: 14px;
}

.summary-card span,
.summary-card small,
.detail-grid span,
.risk-card span,
.section-label {
  display: block;
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 700;
}

.summary-card strong {
  display: block;
  margin: 6px 0;
  color: var(--yui-text);
  font-size: 28px;
  line-height: 1;
  font-weight: 900;
}

.tone-blue strong { color: #2563eb; }
.tone-amber strong { color: #d97706; }
.tone-rose strong { color: #e11d48; }
.tone-emerald strong { color: #059669; }

.capability-map,
.mcp-panel,
.skill-catalog,
.plugin-panel,
.log-panel {
  padding: 16px;
}

.tool-health {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  padding: 10px;
}

.health-item {
  min-width: 0;
  border: 1px solid transparent;
  border-radius: 10px;
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  cursor: pointer;
  padding: 10px 12px;
  text-align: left;
  transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}

.health-item:hover,
.health-item:focus-visible,
.health-item.active {
  border-color: var(--yui-border-strong);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-hover);
  outline: none;
}

.health-item span,
.health-item small {
  display: block;
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 700;
}

.health-item strong {
  display: block;
  margin: 5px 0;
  color: var(--yui-text);
  font-size: 22px;
  line-height: 1;
  font-weight: 900;
}

.health-item.tone-blue strong { color: #2563eb; }
.health-item.tone-amber strong { color: #d97706; }
.health-item.tone-rose strong { color: #e11d48; }
.health-item.tone-emerald strong { color: #059669; }

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.section-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.file-input {
  display: none;
}

.section-heading.compact {
  margin-bottom: 10px;
}

.section-heading h3 {
  margin: 0;
  color: var(--yui-text);
  font-size: 16px;
  font-weight: 850;
}

.section-heading p,
.capability-row p,
.detail-heading p,
.skill-card p,
.mini-item span {
  margin: 5px 0 0;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.55;
}

.source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}

.source-card {
  min-height: 64px;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 8px;
  align-items: center;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  cursor: pointer;
  padding: 12px;
  text-align: left;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.source-card:hover,
.source-card.active,
.capability-row:hover,
.capability-row.active,
.skill-card:hover {
  transform: translateY(-1px);
  border-color: var(--yui-border-strong);
  box-shadow: var(--yui-shadow-hover);
}

.source-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
}

.source-card strong,
.skill-card strong,
.mini-item strong {
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 850;
}

.source-card em {
  color: var(--yui-text);
  font-size: 16px;
  font-style: normal;
  font-weight: 900;
}

.source-card small {
  grid-column: 1 / -1;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
}

.mcp-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.mcp-filter-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--yui-border);
  border-radius: 999px;
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  cursor: pointer;
  padding: 6px 10px;
  transition: border-color 0.18s ease, background 0.18s ease;
}

.mcp-filter-button:hover,
.mcp-filter-button:focus-visible,
.mcp-filter-button.active {
  border-color: var(--yui-border-strong);
  background: var(--yui-surface-raised);
  outline: none;
}

.mcp-filter-button span {
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 700;
}

.mcp-filter-button strong {
  color: var(--yui-text);
  font-size: 12px;
}

.mcp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 10px;
}

.mcp-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  padding: 13px;
}

.mcp-card.connected {
  border-color: rgba(34, 197, 94, 0.24);
  background: var(--yui-success-soft);
}

.mcp-card.errored {
  border-color: rgba(244, 63, 94, 0.35);
  background: var(--yui-danger-soft);
}

.mcp-card.disabled {
  background: var(--yui-surface-muted);
}

.mcp-main,
.mcp-actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.mcp-main > div {
  min-width: 0;
}

.mcp-main strong {
  display: block;
  color: var(--yui-text);
  font-size: 14px;
  font-weight: 850;
}

.mcp-main span {
  display: block;
  margin-top: 4px;
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.mcp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mcp-meta span {
  border-radius: 999px;
  background: var(--yui-surface-muted);
  color: #64748b;
  padding: 3px 8px;
  font-size: 11px;
}

.mcp-error {
  border-radius: 6px;
  background: var(--yui-danger-soft);
  color: #be123c;
  padding: 7px 9px;
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.mcp-actions {
  align-items: center;
}

.capability-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  min-height: 620px;
  overflow: hidden;
}

.capability-list-pane {
  min-width: 0;
  padding: 16px;
  border-right: 1px solid var(--yui-border);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.toolbar-select {
  width: 142px;
  flex-shrink: 0;
}

.skill-toolbar .toolbar-select {
  width: 132px;
}

.panel-alert {
  margin-bottom: 12px;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.capability-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 458px;
  overflow-y: auto;
  padding-right: 4px;
}

.capability-row {
  width: 100%;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  cursor: pointer;
  padding: 13px;
  text-align: left;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.row-title,
.row-meta,
.skill-summary,
.skill-meta,
.skill-actions,
.token-list {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.row-title strong {
  color: var(--yui-text);
  font-size: 14px;
  font-weight: 850;
}

.row-meta {
  margin-top: 10px;
}

.row-meta span,
.skill-meta span {
  border-radius: 999px;
  background: var(--yui-surface-muted);
  color: #64748b;
  padding: 3px 8px;
  font-size: 11px;
}

.detail-pane {
  min-width: 0;
  padding: 16px;
  background: var(--yui-surface-muted);
}

.detail-heading {
  margin-bottom: 14px;
}

.detail-heading h3 {
  margin: 9px 0 0;
  color: var(--yui-text);
  font-size: 20px;
  font-weight: 900;
}

.risk-card {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  padding: 13px;
}

.risk-card strong {
  display: block;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 19px;
}

.risk-card small {
  max-width: 188px;
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.5;
}

.risk-high,
.risk-critical {
  background: var(--yui-danger-soft);
  border-color: rgba(244, 63, 94, 0.22);
}

.risk-medium {
  background: var(--yui-warning-soft);
  border-color: rgba(245, 158, 11, 0.24);
}

.risk-safe,
.risk-low {
  background: var(--yui-success-soft);
  border-color: rgba(34, 197, 94, 0.2);
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.detail-grid > div,
.schema-summary {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  padding: 10px;
}

.detail-grid strong,
.schema-summary strong {
  display: block;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.detail-section {
  margin-top: 14px;
}

.token-list {
  margin-top: 7px;
}

.muted-text {
  color: #94a3b8;
  font-size: 12px;
}

.schema-summary details {
  margin-top: 8px;
}

.schema-summary summary {
  color: #475569;
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}

.schema-summary pre {
  max-height: 190px;
  overflow: auto;
  margin: 8px 0 0;
  color: #334155;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.skill-toolbar {
  margin-bottom: 14px;
}

.skill-bulkbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: -2px 0 14px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 9px 10px;
}

.skill-bulkbar-main,
.skill-bulkbar-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.skill-bulkbar-main span {
  color: var(--yui-muted);
  font-size: 12px;
}

.skill-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  max-height: 560px;
  overflow-y: auto;
  padding-right: 4px;
}

.skill-card {
  display: flex;
  min-height: 166px;
  flex-direction: column;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  padding: 13px;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.skill-card.selected {
  border-color: rgba(37, 99, 235, 0.42);
  background: color-mix(in srgb, var(--yui-surface-raised) 84%, rgba(37, 99, 235, 0.16));
}

.skill-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.skill-card-head > div {
  min-width: 0;
}

.skill-select {
  flex-shrink: 0;
}

.skill-card-head span {
  display: block;
  margin-top: 4px;
  color: var(--yui-muted);
  font-size: 11px;
}

.skill-card p {
  flex: 1;
}

.skill-actions {
  justify-content: flex-end;
  min-height: 28px;
  margin-top: 10px;
}

.bottom-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 16px;
}

.plugin-list,
.log-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mini-item,
.log-item {
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 10px;
}

.mini-item strong,
.mini-item span {
  display: block;
}

.log-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.log-item span {
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.log-item strong {
  min-width: 0;
  color: var(--yui-text);
  overflow-wrap: anywhere;
}

.log-evidence {
  min-width: 0;
  color: #047857;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.el-input__wrapper),
:deep(.el-select__wrapper) {
  border-radius: 10px;
}

.canonical-links {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-bottom: 14px;
  color: var(--yui-muted);
  font-size: 12px;
}

.canonical-links span {
  font-weight: 700;
}

.canonical-links a {
  color: var(--yui-accent);
  font-weight: 700;
  text-underline-offset: 3px;
}

.canonical-links a:focus-visible {
  border-radius: 4px;
  outline: 3px solid var(--yui-accent);
  outline-offset: 2px;
}

@media (max-width: 1180px) {
  .overview-band,
  .source-grid,
  .skill-grid,
  .bottom-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .capability-workspace {
    grid-template-columns: 1fr;
  }

  .capability-list-pane {
    border-right: none;
    border-bottom: 1px solid var(--yui-border);
  }
}

@media (max-width: 760px) {
  .overview-band,
  .source-grid,
  .skill-grid,
  .bottom-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .section-heading,
  .section-actions,
  .skill-bulkbar,
  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .toolbar-select,
  .skill-toolbar .toolbar-select {
    width: 100%;
  }
}
</style>
