<template>
  <PanelShell title="任务追踪" subtitle="查看任务执行结果、计划任务和请求链路" tone="admin">
    <template #actions>
      <el-button size="small" plain :disabled="!selectedTrace" @click="downloadDiagnosticBundle">导出诊断</el-button>
      <el-button size="small" plain :loading="refreshLoading" @click="refreshAll">刷新</el-button>
    </template>
    <div class="trace-console">
      <section class="trace-hero panel-card">
        <div class="hero-metrics">
          <div v-for="metric in traceMetrics" :key="metric.label" class="metric-card" :class="`tone-${metric.tone}`" :title="metric.desc">
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
          </div>
        </div>
      </section>

      <section class="experience-panel panel-card">
        <div class="section-header compact">
          <div>
            <h3>运行指标</h3>
          </div>
        </div>
        <div class="experience-grid">
          <div
            v-for="metric in primaryExperienceMetrics"
            :key="metric.key"
            class="experience-metric"
            :title="`${metric.label}：P95 ${formatLatency(metric.p95)}，${metric.samples} 次采样`"
          >
            <span>{{ metric.label }}</span>
            <strong>{{ formatLatency(metric.p50) }}</strong>
          </div>
        </div>
        <details v-if="secondaryExperienceMetrics.length" class="experience-more">
          <summary>更多指标</summary>
          <div class="experience-grid experience-grid--secondary">
            <div
              v-for="metric in secondaryExperienceMetrics"
              :key="metric.key"
              class="experience-metric"
              :title="`${metric.label}：P95 ${formatLatency(metric.p95)}，${metric.samples} 次采样`"
            >
              <span>{{ metric.label }}</span>
              <strong>{{ formatLatency(metric.p50) }}</strong>
            </div>
          </div>
        </details>
            <div class="experience-rates">
          <span :title="`${experienceMetrics?.interrupts.by_source.voice?.hits ?? 0}/${experienceMetrics?.interrupts.by_source.voice?.requests ?? 0}`">语音打断 <strong>{{ formatRate(experienceMetrics?.interrupts.by_source.voice?.hit_rate) }}</strong></span>
          <span :title="`${experienceMetrics?.interrupts.by_source.manual?.hits ?? 0}/${experienceMetrics?.interrupts.by_source.manual?.requests ?? 0}`">手动中断 <strong>{{ formatRate(experienceMetrics?.interrupts.by_source.manual?.hit_rate) }}</strong></span>
          <span :title="`${experienceMetrics?.tools.successes ?? 0}/${experienceMetrics?.tools.calls ?? 0}`">工具成功 <strong>{{ formatRate(experienceMetrics?.tools.success_rate) }}</strong></span>
          <span :title="`分析 ${experienceMetrics?.visual?.analysis_requests ?? 0}/${experienceMetrics?.visual?.frames ?? 0}，复用 ${experienceMetrics?.visual?.analysis_skipped ?? 0} 帧`">视觉调用 <strong>{{ formatRate(experienceMetrics?.visual?.analysis_rate) }}</strong></span>
          <span :title="`${experienceMetrics?.visual?.usable ?? 0}/${experienceMetrics?.visual?.completed ?? 0}`">视觉结论 <strong>{{ formatRate(experienceMetrics?.visual?.usable_rate) }}</strong></span>
        </div>
      </section>

      <section class="jobs-panel panel-card">
        <div class="section-header compact">
          <div>
            <h3>后台任务</h3>
          </div>
          <div class="job-summary">
            <el-tag size="small" type="success" effect="plain">{{ activeCompanionJobs.length }} active</el-tag>
            <el-tag size="small" type="info" effect="plain">{{ companionJobs.length }} recent</el-tag>
          </div>
        </div>
        <AsyncState :loading="companionRuntimeRequest.loading" :error="companionRuntimeRequest.error" @retry="loadCompanionRuntime">
          <div v-if="companionJobs.length" class="job-list">
            <article v-for="job in companionJobs" :key="job.jobId" class="job-card">
              <div class="job-card-main">
                <div class="job-title-row">
                  <strong>{{ companionJobTitle(job) }}</strong>
                  <el-tag size="small" :type="companionJobTagType(job.status)" effect="light">{{ companionJobStatusLabel(job.status) }}</el-tag>
                </div>
                <p class="job-subtitle">{{ job.source }} · {{ job.jobId }}</p>
                <div class="tag-row">
                  <el-tag v-if="job.runId" size="small" type="primary" effect="plain">run {{ job.runId }}</el-tag>
                  <el-tag size="small" type="info" effect="plain">rev {{ job.revision }}</el-tag>
                  <el-tag v-if="job.data?.goalId" size="small" type="success" effect="plain">goal {{ String(job.data.goalId) }}</el-tag>
                  <el-tag v-if="job.data?.phase" size="small" type="warning" effect="plain">{{ String(job.data.phase) }}</el-tag>
                </div>
                <el-progress v-if="companionJobProgress(job) !== null" class="job-progress" :percentage="companionJobProgress(job) || 0" :show-text="false" :status="job.status === 'failed' || job.status === 'unknown_effect' ? 'exception' : undefined" />
                <p v-if="companionJobResultSummary(job)" class="job-result">{{ companionJobResultSummary(job) }}</p>
                <p v-if="companionJobOutcome(job)" class="job-outcome">{{ companionJobOutcome(job) }}</p>
                <ul v-if="failureEvidenceLines(job).length" class="job-failure-evidence" aria-label="失败证据">
                  <li v-for="line in failureEvidenceLines(job)" :key="line">{{ line }}</li>
                </ul>
                <p v-if="companionJobDuration(job)" class="job-meta">耗时 {{ companionJobDuration(job) }}<span v-if="projectCompanionJob(job).artifactCount !== null"> · 产物 {{ projectCompanionJob(job).artifactCount }}</span></p>
              </div>
              <div class="job-card-actions">
                <el-button v-if="canResumeCompanionJob(job)" size="small" type="primary" plain :loading="retryingJobIds.has(job.jobId)" :disabled="retryingJobIds.has(job.jobId)" @click="resumeCompanionJob(job)">从失败步骤继续</el-button>
                <el-button v-if="canRetryCompanionJob(job)" size="small" type="warning" plain :loading="retryingJobIds.has(job.jobId)" :disabled="retryingJobIds.has(job.jobId)" @click="retryCompanionJob(job)">重试</el-button>
                <el-button v-if="canConfirmUnknownEffectRetry(job)" size="small" type="danger" plain :loading="retryingJobIds.has(job.jobId)" :disabled="retryingJobIds.has(job.jobId)" @click="confirmUnknownEffectRetry(job)">检查后重试</el-button>
                <el-button v-if="canCancelCompanionJob(job)" size="small" type="warning" plain :loading="cancellingJobIds.has(job.jobId)" :disabled="cancellingJobIds.has(job.jobId)" @click="cancelCompanionJob(job)">停止</el-button>
              </div>
            </article>
          </div>
          <el-empty v-else description="暂无 Agent Job" :image-size="52" />
        </AsyncState>
      </section>

      <section class="runtime-strip panel-card">
        <div class="section-header compact">
          <div>
                <h3>最近执行阶段</h3>
          </div>
        </div>
        <div class="loop-stages" aria-label="最近运行时循环阶段">
          <div
            v-for="stage in runtimeStageOrder"
            :key="stage"
            class="loop-stage"
            :class="{ active: lastLoopStage === stage, done: loopStagesDone.includes(stage) }"
            :title="stage"
          >
            <span>{{ stageLabels[stage] }}</span>
          </div>
        </div>
      </section>

      <div class="trace-layout">
        <aside class="schedule-panel panel-card">
          <div class="section-header">
            <div>
              <h3>计划任务</h3>
            </div>
          </div>

          <AsyncState :loading="schedulesRequest.loading" :error="schedulesRequest.error" @retry="loadSchedules">
            <div v-if="schedules?.length" class="schedule-list">
              <article v-for="task in schedules" :key="task.id" class="schedule-card">
                <div class="schedule-topline">
                  <strong>{{ task.name }}</strong>
                  <el-switch :model-value="task.enabled" size="small" :disabled="isScheduleBusy(task.id)" @change="toggleScheduleItem(task.id, Boolean($event))" />
                </div>
                <p>{{ task.prompt }}</p>
                <div class="tag-row">
                  <el-tag size="small" type="info" effect="light">{{ task.mode }}</el-tag>
                  <el-tag size="small" :type="statusTagType(task.last_status || 'pending')" effect="light">{{ task.last_status || 'pending' }}</el-tag>
                  <el-tag v-if="task.owner_agent_role" size="small" type="danger" effect="plain">{{ task.owner_agent_role }}</el-tag>
                  <el-tag v-if="task.last_run_id" size="small" type="primary" effect="plain">run {{ task.last_run_id }}</el-tag>
                  <el-tag v-if="task.last_job_id" size="small" type="info" effect="plain">job {{ task.last_job_id }}</el-tag>
                  <el-tag v-if="task.last_request_id" size="small" type="success" effect="plain">{{ task.last_request_id }}</el-tag>
                </div>
                <div class="schedule-times">
                  <span>下次 {{ formatDateTime(task.next_run_at) }}</span>
                  <span>上次 {{ formatDateTime(task.last_run_at) }}</span>
                </div>
                <div v-if="task.route_reason" class="route-note">{{ task.route_reason }}</div>
                <div v-if="task.last_run_summary" class="summary-note">{{ task.last_run_summary }}</div>
                <div class="schedule-actions">
                  <el-button size="small" :type="isScheduleRetryable(task.last_status) ? 'warning' : 'primary'" plain :loading="runningScheduleIds.has(task.id)" :disabled="isScheduleBusy(task.id)" @click="runScheduleItemNow(task.id)">{{ isScheduleRetryable(task.last_status) ? '重试' : '入队运行' }}</el-button>
                  <el-button v-if="isScheduleActive(task.last_status)" size="small" type="warning" plain :loading="cancellingScheduleIds.has(task.id)" :disabled="isScheduleBusy(task.id)" @click="cancelScheduleItem(task.id)">停止</el-button>
                  <el-button size="small" type="danger" plain :loading="removingScheduleIds.has(task.id)" :disabled="isScheduleBusy(task.id)" @click="removeScheduleItem(task.id)">删除</el-button>
                </div>
              </article>
            </div>
            <el-empty v-else description="暂无计划任务" :image-size="56" />
          </AsyncState>

          <div class="create-task-box">
            <el-alert v-if="scheduleMutationError" class="mutation-alert" type="error" :title="scheduleMutationError" show-icon :closable="false" />
            <el-form label-position="top" size="small" @submit.prevent>
              <el-form-item label="任务名称">
                <el-input v-model="scheduleForm.name" placeholder="如：晚间复盘 / 喝水提醒" />
              </el-form-item>
              <el-form-item label="任务提示词 / Prompt">
                <el-input v-model="scheduleForm.prompt" type="textarea" :rows="3" placeholder="描述任务目标、提醒内容或例行工作..." resize="none" />
              </el-form-item>
              <div class="create-controls">
                <el-input-number v-model="scheduleForm.run_after_seconds" :min="5" :max="86400" size="small" />
                <el-input-number v-model="scheduleForm.interval_seconds" :min="30" :max="86400" size="small" />
              </div>
              <div class="create-actions">
                <el-button type="primary" size="small" :loading="createOnceScheduleRequest.loading" :disabled="!scheduleForm.prompt.trim() || createScheduleLoading" @click="submitOnceSchedule">单次</el-button>
                <el-button type="success" size="small" :loading="createIntervalScheduleRequest.loading" :disabled="!scheduleForm.prompt.trim() || createScheduleLoading" @click="submitIntervalSchedule">循环</el-button>
              </div>
            </el-form>
          </div>
        </aside>

        <main class="trace-browser panel-card">
          <div class="browser-main">
            <div class="section-header browser-header">
              <div>
                <h3>{{ activeTraceFilterLabel }}</h3>
              </div>
            </div>

            <div class="trace-toolbar">
              <el-input v-model="traceSearch" placeholder="搜索请求、任务、Agent、工具、摘要..." clearable>
                <template #prefix><span class="search-prefix">⌕</span></template>
              </el-input>
              <el-select v-model="traceFilter" class="toolbar-select" placeholder="事件类型">
                <el-option label="全部事件" value="all" />
                <el-option label="有步骤链" value="steps" />
                <el-option label="运行循环" value="runtime_loop" />
                <el-option label="计划器" value="scheduler" />
                <el-option label="Planner" value="planner" />
              </el-select>
              <el-select v-model="statusFilter" class="toolbar-select" placeholder="状态">
                <el-option label="全部状态" value="all" />
                <el-option label="成功/完成" value="ok" />
                <el-option label="失败" value="error" />
                <el-option label="跳过/部分完成" value="partial" />
              </el-select>
            </div>

            <el-alert v-if="unlinkedTraceCount" class="trace-alert" type="warning" :closable="false" show-icon :title="`${unlinkedTraceCount} 条追踪事件缺少 request_id，已临时分组为未关联运行`" />

            <AsyncState :loading="agentTraceRequest.loading" :error="agentTraceRequest.error" @retry="loadAgentTrace">
              <div v-if="filteredTraceGroups.length" class="run-list">
                <button
                  v-for="group in filteredTraceGroups"
                  :key="group.requestId"
                  type="button"
                  class="run-card"
                  :class="{ active: selectedTrace?.requestId === group.requestId }"
                  @click="selectedTraceId = group.requestId"
                >
                  <div class="run-main">
                    <div class="run-title">
                      <span class="request-id">{{ group.requestId }}</span>
                      <el-tag size="small" :type="statusTagType(group.status)" effect="light">{{ statusLabel(group.status) }}</el-tag>
                    </div>
                    <p>{{ group.summary }}</p>
                    <div class="run-meta">
                      <span>{{ formatTime(group.lastTimestamp) }}</span>
                      <span>{{ group.entries.length }} 条事件</span>
                      <span>{{ group.stepChain.length }} 个步骤</span>
                      <span v-if="group.ownerRoles.length">{{ group.ownerRoles.join(' / ') }}</span>
                    </div>
                    <div v-if="group.operationId || group.conversationId || group.runId" class="run-identity" aria-label="run identity">
                      <span v-if="group.operationId">op {{ group.operationId }}</span>
                      <span v-if="group.conversationId">conversation {{ group.conversationId }}</span>
                      <span v-if="group.runId">run {{ group.runId }}</span>
                    </div>
                  </div>
                  <div class="run-counts">
                    <strong>{{ group.steps }}</strong><span>步骤</span>
                    <strong>{{ group.runtimeLoop }}</strong><span>循环</span>
                  </div>
                </button>
              </div>
              <el-empty v-else description="暂无匹配的追踪记录" :image-size="64" />
            </AsyncState>
          </div>

          <aside class="trace-detail">
            <template v-if="selectedTrace">
              <div class="detail-heading">
                <h3>{{ selectedTrace.requestId }}</h3>
                <p>{{ selectedTrace.summary }}</p>
              </div>

              <div class="detail-grid">
                <div><span>规划器</span><strong>{{ selectedTrace.planner }}</strong></div>
                <div><span>步骤</span><strong>{{ selectedTrace.steps }}</strong></div>
                <div><span>计划器</span><strong>{{ selectedTrace.scheduler }}</strong></div>
                <div><span>循环</span><strong>{{ selectedTrace.runtimeLoop }}</strong></div>
              </div>

              <div v-if="selectedTrace.operationId || selectedTrace.conversationId || selectedTrace.turnId || selectedTrace.runId" class="detail-identity">
                <span v-if="selectedTrace.operationId">operation {{ selectedTrace.operationId }}</span>
                <span v-if="selectedTrace.conversationId">conversation {{ selectedTrace.conversationId }}</span>
                <span v-if="selectedTrace.turnId">turn {{ selectedTrace.turnId }}</span>
                <span v-if="selectedTrace.runId">run {{ selectedTrace.runId }}</span>
              </div>

              <div v-if="selectedTrace.stepChain.length" class="detail-section">
                <div class="detail-section-title">步骤链路</div>
                <div class="step-chain">
                  <article v-for="step in selectedTrace.stepChain" :key="step.step_id" class="step-node" :class="`status-${normalizeStatus(step.status)}`">
                    <div class="step-index">{{ step.step_id }}</div>
                    <div class="step-body">
                      <div class="step-title">
                        <strong>{{ step.title }}</strong>
                        <el-tag size="small" :type="statusTagType(step.status)" effect="light">{{ statusLabel(step.status) }}</el-tag>
                      </div>
                      <p v-if="step.description">{{ step.description }}</p>
                      <div class="tag-row">
                        <el-tag v-if="step.owner_agent_role" size="small" type="danger" effect="plain">{{ step.owner_agent_role }}</el-tag>
                        <el-tag v-if="step.capability_type || step.capability_kind" size="small" type="warning" effect="plain">{{ step.capability_type || '能力' }} / {{ step.capability_kind || '未知' }}</el-tag>
                        <el-tag v-for="dep in step.depends_on" :key="dep" size="small" type="info" effect="plain">依赖：{{ dep }}</el-tag>
                      </div>
                      <div v-if="step.condition" class="route-note">{{ formatStepCondition(step) }}</div>
                      <div v-if="step.tool" class="tool-box">
                        <span>工具</span>
                        <strong>{{ step.tool }}</strong>
                        <code>{{ formatArgs(step.args) }}</code>
                      </div>
                      <div v-if="step.reply_preview" class="reply-preview">{{ step.reply_preview }}</div>
                    </div>
                  </article>
                </div>
              </div>

              <div v-if="selectedTrace.runtimeLoopEntries.length" class="detail-section">
                <div class="detail-section-title">运行循环</div>
                <div class="loop-log-list">
                  <article v-for="(entry, index) in selectedTrace.runtimeLoopEntries" :key="`loop-${index}`" class="loop-log-card">
                    <div class="log-card-title">
                      <el-tag size="small" type="info" effect="light">{{ stageLabels[entry.stage || ''] || entry.stage || entry.traceType }}</el-tag>
                      <el-tag v-if="entry.agent_role" size="small" type="danger" effect="plain">{{ entry.agent_role }}</el-tag>
                      <span>{{ formatTime(entry.timestamp) }}</span>
                    </div>
                    <p>{{ entry.summary || entry.task_name || entry.goal || '-' }}</p>
                    <div v-if="entry.intent || entry.urgency || entry.autonomy_mode" class="tag-row">
                      <el-tag v-if="entry.intent" size="small" type="success" effect="plain">意图：{{ entry.intent }}</el-tag>
                      <el-tag v-if="entry.urgency" size="small" type="info" effect="plain">紧急度：{{ entry.urgency }}</el-tag>
                      <el-tag v-if="entry.autonomy_mode" size="small" type="warning" effect="plain">模式：{{ entry.autonomy_mode }}</el-tag>
                    </div>
                    <div v-if="entry.top_route_reason" class="route-note">{{ entry.top_route_reason }}</div>
                  </article>
                </div>
              </div>

              <div v-if="selectedTrace.schedulerEntries.length" class="detail-section">
                <div class="detail-section-title">计划器运行</div>
                <div class="loop-log-list amber">
                  <article v-for="(entry, index) in selectedTrace.schedulerEntries" :key="`scheduler-${index}`" class="loop-log-card">
                    <div class="log-card-title">
                      <el-tag size="small" type="info" effect="light">{{ entry.mode || 'schedule' }}</el-tag>
                      <el-tag size="small" :type="statusTagType(entry.status || 'pending')" effect="light">{{ entry.status || 'pending' }}</el-tag>
                      <span>{{ formatTime(entry.timestamp) }}</span>
                    </div>
                    <p>{{ entry.task_name || '-' }}</p>
                    <div v-if="entry.run_id || entry.job_id" class="tag-row">
                      <el-tag v-if="entry.run_id" size="small" type="primary" effect="plain">run {{ entry.run_id }}</el-tag>
                      <el-tag v-if="entry.job_id" size="small" type="info" effect="plain">job {{ entry.job_id }}</el-tag>
                    </div>
                    <div v-if="entry.summary" class="summary-note">{{ entry.summary }}</div>
                    <div v-if="entry.route_reason" class="route-note">{{ entry.route_reason }}</div>
                  </article>
                </div>
              </div>

              <details class="detail-section detail-section--raw">
                <summary class="detail-section-title">原始事件</summary>
                <div class="raw-events">
                  <div v-for="(entry, index) in selectedTrace.entries" :key="index" class="raw-line">
                    <span>{{ formatTime(entry.timestamp) }}</span>
                    <strong>{{ entry.traceType }}</strong>
                    <em>{{ entry.kind || entry.status || entry.stage || '-' }}</em>
                    <code>{{ entry.task_name || entry.goal || entry.summary || '' }}</code>
                  </div>
                </div>
              </details>
            </template>
            <el-empty v-else description="未选择运行记录" :image-size="64" />
          </aside>
        </main>
      </div>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { getSocketClient } from '@/net/socketClient'
import { systemClient } from '@/api/client'
import { useSystemDomain } from '../composables/useSystemDomain'
import type { PlannerTrace, RuntimeLoopRecord, ScheduleTask, SchedulerRunRecord, StepConditionRecord, StepExecutionRecord } from '@/../shared/agent'
import type { CompanionEventEnvelope, CompanionJobStatus } from '@/../shared/companion-event'
import {
  canCancelCompanionJob,
  canConfirmUnknownEffectRetry,
  canResumeCompanionJob,
  canRetryCompanionJob,
  companionJobToolArgs,
  isTerminalCompanionJob,
  isToolCompanionJob,
  projectCompanionJob,
} from '@/app/runtime/companionJobProjection'
import { createRedactedDiagnosticBundle, serializeRedactedDiagnosticBundle } from '@/app/runtime/companionDiagnosticExport'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'
type TraceFilter = 'all' | 'planner' | 'steps' | 'scheduler' | 'runtime_loop'
type StatusFilter = 'all' | 'ok' | 'error' | 'partial'
type MetricTone = 'blue' | 'emerald' | 'amber' | 'rose'
interface TraceEntry {
  traceType: TraceFilter
  timestamp: string
  kind?: string
  status?: string
  goal?: string
  task_name?: string
  mode?: string
  stage?: string
  summary?: string
  intent?: string
  urgency?: string
  autonomy_mode?: string
  top_route_reason?: string
  agent_id?: string
  agent_role?: string
  owner_agent_id?: string
  owner_agent_role?: string
  route_reason?: string
  run_id?: string
  job_id?: string
  conversation_id?: string
  operation_id?: string
  turn_id?: string
  step_index?: number
}

interface StepDisplay {
  step_id: string
  kind: string
  status: string
  title: string
  description: string
  depends_on: string[]
  condition?: StepConditionRecord | null
  tool?: string | null
  args?: Record<string, unknown> | null
  success?: boolean | null
  error?: string | null
  reply_preview?: string | null
  owner_agent_id?: string | null
  owner_agent_role?: string | null
  route_reason?: string | null
  capability_id?: string | null
  capability_type?: string | null
  capability_kind?: string | null
}

interface TraceGroup {
  requestId: string
  planner: number
  steps: number
  scheduler: number
  runtimeLoop: number
  entries: TraceEntry[]
  stepChain: StepDisplay[]
  runtimeLoopEntries: TraceEntry[]
  schedulerEntries: TraceEntry[]
  status: string
  summary: string
  firstTimestamp: string
  lastTimestamp: string
  ownerRoles: string[]
  conversationId?: string
  operationId?: string
  turnId?: string
  runId?: string
}

const {
  schedules,
  agentTrace,
  companionRuntime,
  experienceMetrics,
  schedulesRequest,
  agentTraceRequest,
  companionRuntimeRequest,
  experienceMetricsRequest,
  createOnceScheduleRequest,
  createIntervalScheduleRequest,
  removeScheduleRequest,
  toggleScheduleRequest,
  runScheduleNowRequest,
  cancelScheduleRequest,
  loadSchedules,
  createOnceSchedule,
  createIntervalSchedule,
  removeSchedule,
  toggleSchedule,
  runScheduleNow,
  cancelSchedule,
  resolveCompanionOpportunity,
  cancelHeartbeatGoal,
  loadAgentTrace,
  loadCompanionRuntime,
  loadExperienceMetrics,
} = useSystemDomain()

const scheduleForm = reactive({ name: '', prompt: '', run_after_seconds: 60, interval_seconds: 300 })
const traceSearch = ref('')
const traceFilter = ref<TraceFilter>('all')
const statusFilter = ref<StatusFilter>('all')
const selectedTraceId = ref('')
const removingScheduleIds = ref(new Set<string>())
const togglingScheduleIds = ref(new Set<string>())
const runningScheduleIds = ref(new Set<string>())
const cancellingScheduleIds = ref(new Set<string>())
const cancellingJobIds = ref(new Set<string>())
const retryingJobIds = ref(new Set<string>())

const addPending = (setRef: { value: Set<string> }, key: string) => {
  setRef.value = new Set(setRef.value).add(key)
}

const removePending = (setRef: { value: Set<string> }, key: string) => {
  const next = new Set(setRef.value)
  next.delete(key)
  setRef.value = next
}

const isScheduleBusy = (taskId: string) => (
  removingScheduleIds.value.has(taskId)
  || togglingScheduleIds.value.has(taskId)
  || runningScheduleIds.value.has(taskId)
  || cancellingScheduleIds.value.has(taskId)
)

const isScheduleActive = (status?: string | null) => status === 'queued' || status === 'running'
const isScheduleRetryable = (status?: string | null) => Boolean(status && (status.startsWith('error:') || status.startsWith('interrupted:')))

const runtimeStageOrder = ['observe', 'interpret', 'recall', 'decide', 'ask_act', 'reflect', 'update_relationship']
const stageLabels: Record<string, string> = { observe: '观察', interpret: '理解', recall: '回忆', decide: '决策', ask_act: '执行', reflect: '反思', update_relationship: '关系' }

const runtimeLoops = computed<RuntimeLoopRecord[]>(() => {
  const raw = agentTrace.value?.runtime_loop || []
  return Array.isArray(raw) ? raw : []
})

const sortedRuntimeLoops = computed(() => [...runtimeLoops.value].sort((a, b) => (a.timestamp || '').localeCompare(b.timestamp || '')))
const lastLoopStage = computed(() => sortedRuntimeLoops.value.length ? sortedRuntimeLoops.value[sortedRuntimeLoops.value.length - 1].stage : '')
const loopStagesDone = computed(() => Array.from(new Set(runtimeLoops.value.map(loop => loop.stage).filter(Boolean))))

const companionJobs = computed<CompanionEventEnvelope[]>(() => {
  const latest = new Map<string, CompanionEventEnvelope>()
  for (const event of companionRuntime.value?.jobs?.events || []) {
    const previous = latest.get(event.jobId)
    if (!previous || event.revision > previous.revision || (event.revision === previous.revision && event.timestamp > previous.timestamp)) {
      latest.set(event.jobId, event)
    }
  }
  return [...latest.values()].sort((a, b) => b.timestamp - a.timestamp)
})
const activeCompanionJobs = computed(() => companionJobs.value.filter(job => !isTerminalCompanionJob(job.status)))

function companionJobTitle(job: CompanionEventEnvelope) {
  return projectCompanionJob(job).title
}

function companionJobProgress(job: CompanionEventEnvelope) {
  const value = projectCompanionJob(job).progress
  return value === null ? null : Math.round(value * 100)
}

function companionJobResultSummary(job: CompanionEventEnvelope) {
  return projectCompanionJob(job).resultSummary
}

function companionJobDuration(job: CompanionEventEnvelope) {
  const value = projectCompanionJob(job).durationMs
  return value === null ? '' : `${value} ms`
}

function companionJobOutcome(job: CompanionEventEnvelope) {
  return projectCompanionJob(job).error
}

function failureEvidenceLines(job: CompanionEventEnvelope) {
  const projection = projectCompanionJob(job)
  if (!isTerminalCompanionJob(job.status) || job.status === 'completed') return []
  const lines: string[] = []
  if (job.status === 'unknown_effect' || projection.effectOutcome === 'unknown_effect') lines.push('执行结果未知：该工具可能已经产生影响')
  if (projection.failureCategory) lines.push(`失败类型：${projection.failureCategory}`)
  if (projection.failedStep) lines.push(`失败步骤：${projection.failedStep}`)
  if (projection.completedSteps.length) lines.push(`已完成：${projection.completedSteps.join('、')}`)
  return lines
}

function companionJobTagType(status: CompanionJobStatus): TagType {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'unknown_effect') return 'danger'
  if (status === 'interrupted') return 'warning'
  if (status === 'cancelled') return 'info'
  if (status === 'progress') return 'warning'
  return 'primary'
}

function companionJobStatusLabel(status: CompanionJobStatus) {
  const labels: Record<CompanionJobStatus, string> = {
    created: 'created', running: 'running', progress: 'progress', completed: 'completed', failed: 'failed', cancelled: 'cancelled', interrupted: 'interrupted', unknown_effect: 'unknown effect',
  }
  return labels[status]
}

function companionToolName(job: CompanionEventEnvelope) {
  return projectCompanionJob(job).tool
}

const resumeCompanionJob = async (job: CompanionEventEnvelope) => {
  if (!canResumeCompanionJob(job)) return
  const projection = projectCompanionJob(job)
  addPending(retryingJobIds, job.jobId)
  try {
    const result = await systemClient.resumeAgentRecovery({
      recovery_handle: projection.recoveryHandle,
      ...(job.workspaceId ? { workspace_id: job.workspaceId } : {}),
      session_id: job.sessionId,
      turn_id: job.turnId,
      failed_step_id: projection.failedStep,
    })
    if (result.ok === false) {
      ElMessage.error('恢复句柄已失效，请重新执行任务')
      return
    }
    ElMessage.success('已从失败步骤继续')
    await loadCompanionRuntime()
  } catch {
    ElMessage.error('无法从失败步骤继续，请稍后重试')
  } finally {
    removePending(retryingJobIds, job.jobId)
  }
}

const retryCompanionJob = async (job: CompanionEventEnvelope, unknownEffectAcknowledged = false) => {
  if (!canRetryCompanionJob(job) && !(unknownEffectAcknowledged && canConfirmUnknownEffectRetry(job))) return
  addPending(retryingJobIds, job.jobId)
  try {
    if (isToolCompanionJob(job)) {
      const toolName = companionToolName(job)
      const args = companionJobToolArgs(job)
      if (!toolName || !args) return
      const retryRequestId = `${job.requestId}:retry:${Date.now()}`
      getSocketClient().sendToolCall(retryRequestId, toolName, args, {
        requestId: retryRequestId,
        runId: job.runId,
        jobId: job.jobId,
        source: 'desktop',
        retry: true,
      })
      ElMessage.success('Tool retry requested')
      await new Promise(resolve => window.setTimeout(resolve, 80))
      await loadCompanionRuntime()
      return
    }
    const taskId = String(job.data?.taskId || '').trim()
    if (!taskId) return
    const result = await runScheduleNow(taskId)
    if (result?.ok) {
      ElMessage.success('Job 已重新入队')
      await Promise.all([loadCompanionRuntime(), loadSchedules()])
    }
  } finally {
    removePending(retryingJobIds, job.jobId)
  }
}

const confirmUnknownEffectRetry = async (job: CompanionEventEnvelope) => {
  if (!canConfirmUnknownEffectRetry(job)) return
  try {
    await ElMessageBox.confirm(
      '该工具可能已经产生影响。请先检查目标应用或外部系统的当前状态；仅在确认需要再次执行后继续。',
      '确认未知执行结果',
      {
        confirmButtonText: '已检查，仍要重试',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  await retryCompanionJob(job, true)
}

const downloadDiagnosticBundle = () => {
  if (!selectedTrace.value) return
  const relatedJobs = companionJobs.value.filter(job => job.requestId === selectedTrace.value?.requestId)
  const bundle = createRedactedDiagnosticBundle({
    trace: selectedTrace.value,
    jobs: relatedJobs,
  })
  const serialized = serializeRedactedDiagnosticBundle(bundle)
  if (!serialized.ok) {
    ElMessage.error('诊断包含无法安全导出的内容，已阻止下载')
    return
  }
  const blob = new Blob([serialized.json], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `yuizaki-diagnostic-${Date.now()}.json`
  anchor.click()
  URL.revokeObjectURL(url)
  ElMessage.success('脱敏诊断已导出')
}

const cancelCompanionJob = async (job: CompanionEventEnvelope) => {
  if (!canCancelCompanionJob(job)) return
  addPending(cancellingJobIds, job.jobId)
  try {
    if (isToolCompanionJob(job)) {
      getSocketClient().sendInterrupt(job.sessionId, job.requestId, 'manual')
      ElMessage.success('Tool cancellation requested')
      await new Promise(resolve => window.setTimeout(resolve, 80))
      await loadCompanionRuntime()
      return
    }
    const result = job.source === 'heartbeat'
      ? (job.data?.goalId
        ? await cancelHeartbeatGoal(String(job.data.goalId), 'user_cancelled_from_job_panel')
        : await resolveCompanionOpportunity(job.jobId, { request_id: job.requestId, outcome: 'cancelled', reason: 'user_cancelled_from_job_panel' }))
      : await cancelSchedule(job.runId || job.jobId)
    if (result?.ok) {
      ElMessage.success('Job 已停止')
      await loadCompanionRuntime()
    }
  } finally {
    removePending(cancellingJobIds, job.jobId)
  }
}
const unlinkedTraceCount = computed(() => {
  const snapshot = agentTrace.value
  if (!snapshot) return 0
  return [
    ...(snapshot.planner || []),
    ...(snapshot.steps || []),
    ...(snapshot.scheduler || []),
    ...(snapshot.runtime_loop || []),
  ].filter(item => !item.request_id).length
})

const traceGroups = computed<TraceGroup[]>(() => {
  if (!agentTrace.value) return []
  const map = new Map<string, TraceGroup>()
  const ensureGroup = (requestId: string) => {
    if (!map.has(requestId)) {
      map.set(requestId, {
        requestId,
        planner: 0,
        steps: 0,
        scheduler: 0,
        runtimeLoop: 0,
        entries: [],
        stepChain: [],
        runtimeLoopEntries: [],
        schedulerEntries: [],
        status: 'pending',
        summary: '暂无摘要',
        firstTimestamp: '',
        lastTimestamp: '',
        ownerRoles: [],
        conversationId: undefined,
        operationId: undefined,
        turnId: undefined,
        runId: undefined,
      })
    }
    return map.get(requestId)!
  }

  const addEntry = (group: TraceGroup, entry: TraceEntry) => {
    group.entries.push(entry)
    if (!group.firstTimestamp || entry.timestamp < group.firstTimestamp) group.firstTimestamp = entry.timestamp
    if (!group.lastTimestamp || entry.timestamp > group.lastTimestamp) group.lastTimestamp = entry.timestamp
    const role = entry.owner_agent_role || entry.agent_role
    if (role && !group.ownerRoles.includes(role)) group.ownerRoles.push(role)
  }

  for (const [index, item] of (agentTrace.value.planner || []).entries()) {
    const group = ensureGroup(item.request_id || fallbackTraceRequestId('planner', index, item.timestamp, item.goal))
    group.planner += 1
    group.summary = item.goal || group.summary
    addEntry(group, traceEntryFromPlanner(item))
  }

  for (const [index, item] of (agentTrace.value.steps || []).entries()) {
    const group = ensureGroup(item.request_id || fallbackTraceRequestId('steps', index, item.timestamp, item.title || item.step_id))
    group.steps += 1
    const entry = traceEntryFromStep(item)
    addEntry(group, entry)
    if (item.step_id && item.title) group.stepChain.push(stepDisplayFromExecution(item))
  }

  for (const [index, item] of (agentTrace.value.scheduler || []).entries()) {
    const group = ensureGroup(item.request_id || fallbackTraceRequestId('scheduler', index, item.timestamp, item.task_name))
    group.scheduler += 1
    group.summary = item.task_name || item.summary || group.summary
    const entry = traceEntryFromScheduler(item)
    addEntry(group, entry)
    group.schedulerEntries.push(entry)
  }

  for (const [index, item] of (agentTrace.value.runtime_loop || []).entries()) {
    const group = ensureGroup(item.request_id || fallbackTraceRequestId('runtime_loop', index, item.timestamp, item.summary || item.stage))
    group.runtimeLoop += 1
    group.summary = item.summary || group.summary
    const entry = traceEntryFromRuntimeLoop(item)
    addEntry(group, entry)
    group.runtimeLoopEntries.push(entry)
  }

  for (const group of map.values()) {
    const identity = group.entries.find(entry => entry.conversation_id || entry.operation_id || entry.turn_id || entry.run_id)
    group.conversationId = identity?.conversation_id
    group.operationId = identity?.operation_id
    group.turnId = identity?.turn_id
    group.runId = identity?.run_id
    group.status = inferGroupStatus(group)
    group.entries.sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    group.stepChain.sort((a, b) => a.step_id.localeCompare(b.step_id))
  }

  return [...map.values()].sort((a, b) => b.lastTimestamp.localeCompare(a.lastTimestamp))
})

const filteredTraceGroups = computed(() => {
  const query = traceSearch.value.trim().toLowerCase()
  return traceGroups.value.filter((group) => {
    if (traceFilter.value !== 'all' && traceGroupCount(group, traceFilter.value) <= 0) return false
    if (statusFilter.value !== 'all' && normalizeStatus(group.status) !== statusFilter.value) return false
    if (!query) return true
    return groupSearchText(group).includes(query)
  })
})

const selectedTrace = computed(() => {
  const selected = filteredTraceGroups.value.find(group => group.requestId === selectedTraceId.value)
  return selected ?? filteredTraceGroups.value[0] ?? null
})

const activeTraceFilterLabel = computed(() => {
  const typeLabel: Record<TraceFilter, string> = { all: '全部运行', planner: '含 Planner', steps: '含步骤链', scheduler: '含计划器', runtime_loop: '含运行循环' }
  const statusLabelText: Record<StatusFilter, string> = { all: '全部状态', ok: '成功/完成', error: '失败', partial: '跳过/部分完成' }
  const search = traceSearch.value.trim()
  return `${typeLabel[traceFilter.value]} · ${statusLabelText[statusFilter.value]}${search ? ` · 搜索“${search}”` : ''}`
})

const traceMetrics = computed(() => [
  { label: '运行数', value: traceGroups.value.length, desc: `${filteredTraceGroups.value.length} 个匹配`, tone: 'blue' as MetricTone },
  { label: '步骤事件', value: agentTrace.value?.steps?.length || 0, desc: `${failedStepCount.value} 个失败`, tone: failedStepCount.value ? 'rose' as MetricTone : 'emerald' as MetricTone },
  { label: '运行循环', value: runtimeLoops.value.length, desc: lastLoopStage.value ? `最近：${stageLabels[lastLoopStage.value] || lastLoopStage.value}` : '暂无循环', tone: 'amber' as MetricTone },
  { label: '计划任务', value: schedules.value.length, desc: `${enabledScheduleCount.value} 个启用`, tone: 'emerald' as MetricTone },
])

const experienceMetricDefinitions = [
  { key: 'speech_start_confirmed', label: '持续语音确认' },
  { key: 'speech_end', label: '说话结束' },
  { key: 'asr_final', label: '语音识别' },
  { key: 'llm_request', label: '模型请求' },
  { key: 'llm_first_token', label: '首字响应' },
  { key: 'llm_first_sentence', label: '首句可播' },
  { key: 'tts_ready_wait', label: 'TTS 等待' },
  { key: 'tts_first_chunk', label: '首段音频' },
  { key: 'playback_start', label: '实际开播' },
  { key: 'voice_to_playback', label: '麦克风到首播' },
  { key: 'interrupt_ack', label: '打断确认' },
  { key: 'realtime_connect', label: '即时连接' },
  { key: 'realtime_speech_to_response', label: '即时首响应' },
  { key: 'realtime_speech_to_playback', label: '即时首播' },
  { key: 'realtime_interrupt_ack', label: '即时打断' },
  { key: 'visual_analysis', label: '视觉分析' },
] as const

const experienceLatencyMetrics = computed(() => experienceMetricDefinitions.map((definition) => {
  const summary = experienceMetrics.value?.latency[definition.key]
  return {
    ...definition,
    p50: summary?.p50_ms ?? null,
    p95: summary?.p95_ms ?? null,
    samples: summary?.samples ?? 0,
  }
}))
const primaryExperienceMetricKeys = new Set([
  'asr_final',
  'llm_first_token',
  'tts_first_chunk',
  'playback_start',
  'visual_analysis',
])
const primaryExperienceMetrics = computed(() => (
  experienceLatencyMetrics.value.filter(metric => primaryExperienceMetricKeys.has(metric.key))
))
const secondaryExperienceMetrics = computed(() => (
  experienceLatencyMetrics.value.filter(metric => !primaryExperienceMetricKeys.has(metric.key))
))

function formatLatency(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '待采样'
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`
  return `${Math.round(value)} ms`
}

function formatRate(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '待采样'
  return `${Math.round(value * 100)}%`
}

const failedStepCount = computed(() => (agentTrace.value?.steps || []).filter(step => normalizeStatus(step.status) === 'error').length)
const enabledScheduleCount = computed(() => schedules.value.filter(task => task.enabled).length)
const createScheduleLoading = computed(() => (
  createOnceScheduleRequest.loading
  || createIntervalScheduleRequest.loading
))
const refreshLoading = computed(() => (
  schedulesRequest.loading
  || agentTraceRequest.loading
  || experienceMetricsRequest.loading
  || companionRuntimeRequest.loading
))
const refreshAll = async () => {
  await Promise.all([
    loadSchedules(),
    loadAgentTrace(),
    loadExperienceMetrics(),
    loadCompanionRuntime(),
  ])
}
const scheduleMutationError = computed(() => (
  createOnceScheduleRequest.error
  || createIntervalScheduleRequest.error
  || removeScheduleRequest.error
  || toggleScheduleRequest.error
  || runScheduleNowRequest.error
  || cancelScheduleRequest.error
))

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stringField(record: Record<string, unknown> | null | undefined, key: string) {
  const value = record?.[key]
  return typeof value === 'string' && value.trim() ? value : undefined
}

function fallbackTraceRequestId(type: TraceFilter, index: number, timestamp?: string, label?: string | null) {
  const suffix = label?.trim() || timestamp || String(index + 1)
  return `未关联 ${type} #${index + 1} · ${suffix}`
}

function traceEntryFromPlanner(item: PlannerTrace): TraceEntry {
  return {
    traceType: 'planner', timestamp: item.timestamp || '', goal: item.goal, mode: item.mode,
    conversation_id: item.conversation_id || undefined,
    operation_id: item.operation_id || undefined,
    turn_id: item.turn_id || undefined,
    run_id: item.run_id || undefined,
    step_index: item.step_index ?? undefined,
  }
}

function traceGroupCount(group: TraceGroup, filter: TraceFilter) {
  if (filter === 'all') return group.entries.length
  if (filter === 'runtime_loop') return group.runtimeLoop
  return group[filter]
}

function traceEntryFromStep(item: StepExecutionRecord): TraceEntry {
  return {
    traceType: 'steps',
    timestamp: item.timestamp || '',
    kind: item.kind,
    status: item.status,
    goal: item.title || undefined,
    task_name: item.tool || undefined,
    owner_agent_id: item.owner_agent_id || undefined,
    owner_agent_role: item.owner_agent_role || undefined,
    route_reason: item.route_reason || undefined,
  }
}

function traceEntryFromScheduler(item: SchedulerRunRecord): TraceEntry {
  return {
    traceType: 'scheduler',
    timestamp: item.timestamp || '',
    task_name: item.task_name,
    mode: item.mode,
    status: item.status,
    summary: item.summary || undefined,
    run_id: item.run_id || undefined,
    job_id: item.job_id || undefined,
    owner_agent_id: item.owner_agent_id || undefined,
    owner_agent_role: item.owner_agent_role || undefined,
    route_reason: item.route_reason || undefined,
    conversation_id: item.conversation_id || undefined,
    operation_id: item.operation_id || undefined,
    turn_id: item.turn_id || undefined,
    step_index: item.step_index ?? undefined,
  }
}

function traceEntryFromRuntimeLoop(item: RuntimeLoopRecord): TraceEntry {
  const data = isRecord(item.data) ? item.data : null
  return {
    traceType: 'runtime_loop',
    timestamp: item.timestamp || '',
    stage: item.stage,
    status: item.status,
    summary: item.summary,
    intent: stringField(data, 'intent'),
    urgency: stringField(data, 'urgency'),
    autonomy_mode: stringField(data, 'autonomy_mode'),
    top_route_reason: stringField(data, 'top_route_reason'),
    agent_id: item.agent_id || undefined,
    agent_role: item.agent_role || undefined,
    conversation_id: item.conversation_id || undefined,
    operation_id: item.operation_id || undefined,
    turn_id: item.turn_id || undefined,
    run_id: item.run_id || undefined,
    step_index: item.step_index ?? undefined,
  }
}

function stepDisplayFromExecution(item: StepExecutionRecord): StepDisplay {
  return {
    step_id: item.step_id || 'step',
    kind: item.kind,
    status: item.status,
    title: item.title || item.step_id || '未命名步骤',
    description: item.prompt || '',
    depends_on: item.depends_on || [],
    condition: item.condition,
    tool: item.tool,
    args: item.args,
    success: item.success,
    error: item.error,
    reply_preview: item.reply_preview,
    owner_agent_id: item.owner_agent_id,
    owner_agent_role: item.owner_agent_role,
    route_reason: item.route_reason,
    capability_id: item.capability_id,
    capability_type: item.capability_type,
    capability_kind: item.capability_kind,
  }
}

function inferGroupStatus(group: TraceGroup) {
  const statuses = group.entries.map(entry => entry.status || '').filter(Boolean)
  if (statuses.some(status => normalizeStatus(status) === 'error')) return 'error'
  if (statuses.some(status => normalizeStatus(status) === 'partial')) return 'partial'
  if (statuses.some(status => normalizeStatus(status) === 'ok')) return 'ok'
  return 'pending'
}

function normalizeStatus(status?: string | null): StatusFilter | 'pending' {
  const raw = String(status || '').toLowerCase()
  if (raw.includes('error') || raw.includes('fail')) return 'error'
  if (raw.includes('skip') || raw.includes('partial') || raw.includes('empty')) return 'partial'
  if (raw === 'ok' || raw.includes('success') || raw.includes('complete')) return 'ok'
  return 'pending'
}

function statusTagType(status?: string | null): TagType {
  const normalized = normalizeStatus(status)
  if (normalized === 'ok') return 'success'
  if (normalized === 'error') return 'danger'
  if (normalized === 'partial') return 'warning'
  return 'info'
}

function statusLabel(status?: string | null) {
  const normalized = normalizeStatus(status)
  if (normalized === 'ok') return '成功'
  if (normalized === 'error') return '失败'
  if (normalized === 'partial') return '部分/跳过'
  return status || 'pending'
}

function groupSearchText(group: TraceGroup) {
  return [
    group.requestId,
    group.summary,
    group.status,
    ...group.ownerRoles,
    ...group.entries.flatMap(entry => [entry.traceType, entry.kind, entry.status, entry.goal, entry.task_name, entry.stage, entry.summary, entry.agent_id, entry.agent_role, entry.owner_agent_id, entry.owner_agent_role, entry.route_reason]),
    ...group.stepChain.flatMap(step => [step.step_id, step.title, step.description, step.tool, step.owner_agent_id, step.owner_agent_role, step.route_reason, step.capability_id, step.capability_kind]),
  ].filter(Boolean).join(' ').toLowerCase()
}

function formatTime(timestamp?: string) {
  if (!timestamp) return '-'
  const parts = timestamp.split('T')
  if (parts.length > 1) return parts[1].replace('Z', '').slice(0, 8)
  return timestamp
}

function formatDateTime(timestamp?: ScheduleTask['next_run_at']) {
  if (!timestamp) return '-'
  const date = new Date(timestamp * 1000)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString()
}

function formatArgs(args?: Record<string, unknown> | null) {
  if (!args) return '{}'
  try {
    return JSON.stringify(args)
  } catch {
    return '{...}'
  }
}

const formatStepCondition = (step: Pick<StepDisplay, 'condition'>) => {
  const condition = step.condition
  if (!condition) return ''
  return formatConditionRecord(condition)
}

const formatConditionRecord = (condition: StepConditionRecord): string => {
  const source = condition.source_step_id || 'dependency'
  const statusIn = Array.isArray(condition.status_in) ? condition.status_in.map(String) : []
  const statusNotIn = Array.isArray(condition.status_not_in) ? condition.status_not_in.map(String) : []
  const contentContains = Array.isArray(condition.content_contains) ? condition.content_contains.map(String) : []
  const errorContains = Array.isArray(condition.error_contains) ? condition.error_contains.map(String) : []
  const parts: string[] = []
  if (condition.source_step_id) parts.push(source)
  if (statusIn.length) parts.push(`status in [${statusIn.join(', ')}]`)
  if (statusNotIn.length) parts.push(`status not in [${statusNotIn.join(', ')}]`)
  if (contentContains.length) parts.push(`content has [${contentContains.join(', ')}]`)
  if (errorContains.length) parts.push(`error has [${errorContains.join(', ')}]`)
  if (condition.all_of?.length) parts.push(`all(${condition.all_of.map(formatConditionRecord).join('; ')})`)
  if (condition.any_of?.length) parts.push(`any(${condition.any_of.map(formatConditionRecord).join('; ')})`)
  if (condition.none_of?.length) parts.push(`none(${condition.none_of.map(formatConditionRecord).join('; ')})`)
  const prefix = condition.mode === 'skip_if' ? 'skip if' : 'continue if'
  return `${prefix} ${parts.length ? parts.join(' && ') : source}`
}

const submitOnceSchedule = async () => {
  if (!scheduleForm.prompt.trim()) return
  const result = await createOnceSchedule({ name: scheduleForm.name.trim() || 'once-task', prompt: scheduleForm.prompt.trim(), run_after_seconds: scheduleForm.run_after_seconds })
  if (result?.ok) {
    ElMessage.success('单次任务已创建')
  }
}

const submitIntervalSchedule = async () => {
  if (!scheduleForm.prompt.trim()) return
  const result = await createIntervalSchedule({ name: scheduleForm.name.trim() || 'interval-task', prompt: scheduleForm.prompt.trim(), interval_seconds: scheduleForm.interval_seconds })
  if (result?.ok) {
    ElMessage.success('循环任务已创建')
  }
}

const removeScheduleItem = async (taskId: string) => {
  const task = schedules.value.find((item) => item.id === taskId)
  try {
    await ElMessageBox.confirm(
      `将删除计划任务“${task?.name || taskId}”。后续运行会立即停止。`,
      '删除计划任务',
      {
        confirmButtonText: '删除任务',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  addPending(removingScheduleIds, taskId)
  try {
    await removeSchedule(taskId)
    ElMessage.success('计划任务已删除')
  } finally {
    removePending(removingScheduleIds, taskId)
  }
}
const toggleScheduleItem = async (taskId: string, enabled: boolean) => {
  addPending(togglingScheduleIds, taskId)
  try {
    const result = await toggleSchedule(taskId, enabled)
    if (result?.ok) {
      ElMessage.success(enabled ? '计划任务已启用' : '计划任务已停用')
    }
  } finally {
    removePending(togglingScheduleIds, taskId)
  }
}
const runScheduleItemNow = async (taskId: string) => {
  addPending(runningScheduleIds, taskId)
  try {
    const result = await runScheduleNow(taskId)
    if (result?.ok) {
      ElMessage.success('任务已加入执行队列')
      await loadAgentTrace()
    }
  } finally {
    removePending(runningScheduleIds, taskId)
  }
}
const cancelScheduleItem = async (taskId: string) => {
  addPending(cancellingScheduleIds, taskId)
  try {
    const result = await cancelSchedule(taskId)
    if (result?.ok) {
      ElMessage.success('任务已停止')
      await loadAgentTrace()
    }
  } finally {
    removePending(cancellingScheduleIds, taskId)
  }
}

onMounted(() => {
  void loadSchedules()
  void loadAgentTrace()
  void loadExperienceMetrics()
  void loadCompanionRuntime()
})
</script>

<style scoped>
.trace-console {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-card {
  border: 1px solid var(--yui-panel-outline, var(--yui-border));
  border-radius: var(--yui-radius-card);
  background: var(--yui-panel-surface, var(--yui-surface));
  background-clip: padding-box;
  box-shadow: var(--yui-panel-shadow, var(--yui-shadow-card));
}

.trace-hero {
  padding: 16px;
}

.hero-copy,
.hero-metrics {
  position: relative;
  z-index: 1;
}

.hero-eyebrow,
.section-kicker {
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.hero-copy h2 {
  margin: 8px 0;
  color: var(--yui-text);
  font-size: 28px;
  line-height: 1.12;
  font-weight: 950;
}

.hero-copy p,
.section-header p,
.run-card p,
.step-body p,
.loop-log-card p,
.detail-heading p,
.schedule-card p {
  margin: 6px 0 0;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.65;
}

.hero-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.metric-card {
  min-height: 104px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  background-clip: padding-box;
  padding: 14px;
}

.metric-card span,
.metric-card small,
.detail-grid span,
.tool-box span {
  display: block;
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 750;
}

.metric-card strong {
  display: block;
  margin: 5px 0;
  font-size: 26px;
  line-height: 1;
  font-weight: 950;
}

.tone-blue strong { color: #2563eb; }
.tone-emerald strong { color: #059669; }
.tone-amber strong { color: #d97706; }
.tone-rose strong { color: #e11d48; }

.runtime-strip {
  padding: 16px;
}

.experience-panel {
  padding: 16px;
}

.jobs-panel {
  padding: 16px;
}

.job-summary,
.job-title-row,
.job-card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.job-summary {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.job-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
}

.job-card {
  display: flex;
  min-width: 0;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 12px;
}

.job-card-main {
  min-width: 0;
  flex: 1;
}

.job-title-row {
  min-width: 0;
  justify-content: space-between;
}

.job-title-row strong,
.job-subtitle {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-title-row strong {
  color: var(--yui-text);
  font-size: 13px;
}

.job-subtitle {
  margin: 5px 0 8px;
  color: var(--yui-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
}

.job-progress {
  margin-top: 10px;
}

.job-failure-evidence {
  margin: 8px 0 0;
  padding-left: 18px;
  color: var(--yui-text);
  font-size: 11px;
  line-height: 1.55;
}

.experience-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 1px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-border);
  overflow: hidden;
}

.experience-metric {
  min-width: 0;
  padding: 12px;
  background: var(--yui-panel-surface-strong, var(--yui-surface-muted));
}

.experience-metric span,
.experience-metric small {
  display: block;
  color: var(--yui-muted);
  font-size: 11px;
}

.experience-metric strong {
  display: block;
  margin: 5px 0;
  color: var(--yui-text);
  font-size: 18px;
}

.experience-rates {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  color: var(--yui-muted);
  font-size: 11px;
}

.experience-more {
  margin-top: 10px;
}

.experience-more > summary {
  width: fit-content;
  color: var(--yui-muted);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
}

.experience-more[open] > summary {
  margin-bottom: 8px;
  color: var(--yui-text);
}

.experience-grid--secondary {
  grid-template-columns: repeat(auto-fit, minmax(124px, 1fr));
}

.experience-rates > span {
  border: 1px solid var(--yui-border);
  border-radius: 999px;
  background: var(--yui-surface-muted);
  padding: 5px 9px;
}

.experience-rates strong {
  color: var(--yui-text);
}

.section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.section-header.compact {
  margin-bottom: 10px;
}

h3 {
  margin: 3px 0 0;
  color: var(--yui-text);
  font-size: 15px;
  font-weight: 850;
}

.loop-stages {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}

.loop-stage {
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 9px 10px;
  transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.loop-stage span,
.loop-stage small {
  display: block;
}

.loop-stage span {
  color: var(--yui-text);
  font-size: 12px;
  font-weight: 850;
}

.loop-stage small {
  margin-top: 2px;
  color: var(--yui-muted);
  font-size: 10px;
}

.loop-stage.done {
  border-color: rgba(37, 99, 235, 0.22);
  background: var(--yui-accent-soft);
}

.loop-stage.active {
  border-color: rgba(79, 70, 229, 0.55);
  background: #4f46e5;
  box-shadow: 0 12px 30px rgba(79, 70, 229, 0.24);
}

.loop-stage.active span,
.loop-stage.active small {
  color: #fff;
}

.trace-layout {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
  min-height: 660px;
}

.schedule-panel,
.trace-browser {
  min-height: 0;
  overflow: hidden;
}

.schedule-panel {
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.schedule-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 320px;
  overflow-y: auto;
  padding-right: 2px;
}

.schedule-card {
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  padding: 12px;
}

.schedule-topline,
.tag-row,
.schedule-actions,
.trace-toolbar,
.run-title,
.run-meta,
.step-title,
.log-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.schedule-topline {
  justify-content: space-between;
}

.schedule-topline strong {
  min-width: 0;
  color: var(--yui-text);
  font-size: 13px;
}

.tag-row,
.run-meta {
  flex-wrap: wrap;
  margin-top: 8px;
}

.schedule-times {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  color: var(--yui-muted);
  font-size: 11px;
}

.schedule-times span {
  border-radius: 999px;
  background: var(--yui-surface);
  padding: 3px 8px;
}

.route-note,
.summary-note {
  margin-top: 8px;
  border-radius: 10px;
  padding: 7px 9px;
  font-size: 11px;
  line-height: 1.5;
}

.route-note {
  background: var(--yui-accent-soft);
  color: var(--yui-accent);
}

.summary-note {
  background: var(--yui-surface-muted);
  color: var(--yui-muted);
}

.schedule-actions,
.create-actions {
  margin-top: 10px;
}

.create-task-box {
  margin-top: 16px;
  border-top: 1px solid var(--yui-border);
  padding-top: 14px;
}

.mutation-alert {
  margin: 10px 0 12px;
}

.create-controls,
.create-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.trace-browser {
  display: grid;
  grid-template-columns: minmax(0, 0.95fr) minmax(420px, 1.05fr);
}

.browser-main {
  min-width: 0;
  border-right: 1px solid var(--yui-border);
  padding: 16px;
}

.trace-toolbar {
  margin-bottom: 12px;
}

.trace-alert {
  margin-bottom: 12px;
}

.toolbar-select {
  width: 136px;
  flex-shrink: 0;
}

.search-prefix {
  color: var(--yui-muted);
  font-weight: 900;
}

.run-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 510px;
  overflow-y: auto;
  padding-right: 4px;
}

.run-card {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 64px;
  gap: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  cursor: pointer;
  padding: 13px;
  text-align: left;
  transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.run-card:hover,
.run-card.active {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.42);
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
}

.run-card:focus-visible {
  border-color: var(--yui-accent);
  outline: 3px solid color-mix(in srgb, var(--yui-accent) 22%, transparent);
  outline-offset: 2px;
}

.request-id {
  min-width: 0;
  color: var(--yui-accent);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  font-weight: 850;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-meta span {
  border-radius: 999px;
  background: var(--yui-surface);
  color: var(--yui-muted);
  padding: 3px 8px;
  font-size: 11px;
}

.run-counts {
  display: grid;
  grid-template-columns: 1fr;
  place-items: center;
  align-content: center;
  gap: 2px;
  border-left: 1px solid var(--yui-border);
  color: var(--yui-muted);
  font-size: 10px;
  text-transform: uppercase;
}

.run-counts strong {
  color: var(--yui-text);
  font-size: 17px;
}

.trace-detail {
  min-width: 0;
  max-height: 660px;
  overflow-y: auto;
  background: var(--yui-surface-muted);
  padding: 16px;
}

.detail-heading {
  margin-bottom: 14px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.detail-grid > div {
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
  padding: 10px;
}

.detail-grid strong {
  display: block;
  margin-top: 4px;
  color: var(--yui-text);
  font-size: 18px;
}

.detail-section {
  margin-top: 16px;
}

.detail-section-title {
  margin-bottom: 9px;
  color: var(--yui-text);
  font-size: 12px;
  font-weight: 900;
  text-transform: uppercase;
}

.step-chain,
.loop-log-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-node {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
  padding: 12px;
}

.step-index {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: var(--yui-accent-soft);
  color: var(--yui-accent);
  font-size: 11px;
  font-weight: 900;
  overflow: hidden;
}

.step-title {
  justify-content: space-between;
  align-items: flex-start;
}

.step-title strong {
  color: var(--yui-text);
  font-size: 13px;
}

.tool-box,
.reply-preview {
  margin-top: 9px;
  border-radius: 12px;
  padding: 9px;
}

.tool-box {
  border: 1px solid var(--yui-border);
  background: var(--yui-surface-muted);
  color: var(--yui-text);
}

.tool-box strong,
.tool-box code {
  display: block;
  margin-top: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  overflow-wrap: anywhere;
}

.tool-box strong {
  color: var(--yui-accent);
}

.reply-preview {
  background: var(--yui-accent-soft);
  color: var(--yui-accent);
  font-size: 12px;
}

.loop-log-card {
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
  padding: 11px;
}

.loop-log-list.amber .loop-log-card {
  border-color: rgba(253, 230, 138, 0.85);
  background: var(--yui-warning-soft);
}

.log-card-title {
  flex-wrap: wrap;
}

.log-card-title span {
  margin-left: auto;
  color: var(--yui-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
}

.raw-events {
  max-height: 260px;
  overflow: auto;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
  padding: 12px;
}

.raw-line {
  display: grid;
  grid-template-columns: 70px 88px 90px minmax(0, 1fr);
  gap: 8px;
  margin-bottom: 6px;
  color: var(--yui-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
}

.raw-line span { color: var(--yui-muted); }
.raw-line strong { color: var(--yui-accent); }
.raw-line em { color: #059669; font-style: normal; }
.raw-line code { color: var(--yui-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

:deep(.el-input__wrapper),
:deep(.el-select__wrapper) {
  border-radius: 13px;
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

@media (max-width: 1280px) {
  .experience-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .experience-metric:nth-child(3n) {
    border-right: 0;
  }

  .experience-metric:nth-child(-n + 3) {
    border-bottom: 1px solid var(--yui-border);
  }

  .trace-hero,
  .trace-layout,
  .trace-browser {
    grid-template-columns: 1fr;
  }

  .browser-main {
    border-right: none;
    border-bottom: 1px solid rgba(226, 232, 240, 0.78);
  }

  .trace-detail {
    max-height: none;
  }
}

@media (max-width: 820px) {
  .experience-grid {
    grid-template-columns: 1fr;
  }

  .experience-metric,
  .experience-metric:nth-child(3n) {
    border-right: 0;
    border-bottom: 1px solid var(--yui-border);
  }

  .experience-metric:last-child {
    border-bottom: 0;
  }

  .hero-metrics,
  .loop-stages,
  .detail-grid,
  .create-controls,
  .create-actions,
  .run-card,
  .step-node,
  .raw-line {
    grid-template-columns: 1fr;
  }

  .trace-toolbar,
  .section-header {
    align-items: stretch;
    flex-direction: column;
  }

  .toolbar-select {
    width: 100%;
  }

  .run-counts {
    display: none;
  }
}
</style>
