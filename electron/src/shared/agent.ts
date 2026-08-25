import type { CapabilitiesSnapshot } from './capability'
import type { PetControlState } from './pet-control'

/** Versioned identity shared by ASR, generation and TTS events. */
export interface GenerationEnvelope {
  version: 1
  /** Stable conversation identity shared across turns and background jobs. */
  conversationId?: string
  /** Logical Agent operation containing one or more steps/jobs. */
  operationId?: string
  /** Zero-based or one-based step position supplied by the producer. */
  stepIndex?: number
  generationId?: string
  turnId?: string
  sequence?: number
  interruptionEpoch?: number
  requestId?: string
}

export interface VoiceTurnEnvelope extends GenerationEnvelope {
  workspaceId: string
  sessionId: string
}

export type CharacterActionType = 'reply' | 'pet_control' | 'tool_trace'

export interface CharacterAction {
  type: CharacterActionType
  content?: string
  payload?: unknown
  schema_version?: string
  source?: string
}

export interface ActionEnvelope {
  version: number
  schema_version?: string
  request_id: string
  source: string
  reply: string
  actions: CharacterAction[]
}

export interface ActionEnvelopeWithTrace extends ActionEnvelope {
  received_at?: string
}

export interface StepChainGroup {
  requestId: string
  envelopeSteps: StepResultRecord[]
  traceSteps: StepExecutionRecord[]
}

export interface StepConditionRecord {
  source_step_id: string
  mode: 'continue_if' | 'skip_if' | string
  status_in: string[]
  status_not_in?: string[]
  content_contains?: string[]
  error_contains?: string[]
  all_of?: StepConditionRecord[]
  any_of?: StepConditionRecord[]
  none_of?: StepConditionRecord[]
}

export interface PlannerTrace {
  timestamp: string
  session_id: string
  goal: string
  mode: string
  steps: Array<{ id?: string; title: string; kind: string; description: string; depends_on?: string[]; condition?: StepConditionRecord | null }>
  request_id?: string | null
  conversation_id?: string | null
  operation_id?: string | null
  turn_id?: string | null
  run_id?: string | null
  step_index?: number | null
}

export interface ToolTrace {
  timestamp: string
  tool: string
  args: Record<string, unknown>
  success: boolean
  content?: string | null
  error?: string | null
}

export interface StepResultRecord {
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
  content?: string | null
  error?: string | null
  task_id?: string | null
  mode?: string | null
  reply_preview?: string | null
  tool_calls_count?: number | null
  has_pet_control?: boolean | null
  retry_count?: number | null
  rollback_status?: string | null
  rollback_target?: string | null
  owner_agent_id?: string | null
  owner_agent_role?: string | null
  route_reason?: string | null
  capability_id?: string | null
  capability_type?: string | null
  capability_kind?: string | null
}

export interface ExecutionSummary {
  status: 'completed' | 'partial' | 'failed' | 'empty' | string
  total_steps: number
  completed_steps: number
  failed_steps: number
  skipped_steps: number
  pending_steps: Array<{ step_id: string; title: string; kind: string }>
  stopped_reason?: string | null
}

export interface StepExecutionRecord {
  timestamp: string
  step_id?: string | null
  kind: string
  status: string
  title?: string | null
  depends_on?: string[] | null
  condition?: StepConditionRecord | null
  prompt?: string | null
  tool?: string | null
  args?: Record<string, unknown> | null
  success?: boolean | null
  error?: string | null
  task_id?: string | null
  mode?: string | null
  reply_preview?: string | null
  tool_calls_count?: number | null
  has_pet_control?: boolean | null
  retry_count?: number | null
  rollback_status?: string | null
  rollback_target?: string | null
  request_id?: string | null
  owner_agent_id?: string | null
  owner_agent_role?: string | null
  route_reason?: string | null
  capability_id?: string | null
  capability_type?: string | null
  capability_kind?: string | null
}

export interface PermissionAuditRecord {
  timestamp: string
  tool_name?: string | null
   capability_id?: string | null
   capability_type?: string | null
   capability_kind?: string | null
  remember_scope?: string | null
  decision: string
  risk_level?: string | null
  request_id?: string | null
  remember?: boolean | null
  requires_approval?: boolean | null
}

export interface SchedulerRunRecord {
  timestamp: string
  task_id: string
  task_name: string
  mode: string
  status: string
  run_id?: string | null
  job_id?: string | null
  summary?: string | null
  request_id?: string | null
  owner_agent_id?: string | null
  owner_agent_role?: string | null
  route_reason?: string | null
  conversation_id?: string | null
  operation_id?: string | null
  turn_id?: string | null
  step_index?: number | null
}

export interface RuntimeLoopRecord {
  timestamp: string
  session_id: string
  request_id?: string | null
  stage: string
  status: string
  summary: string
  agent_id?: string | null
  agent_role?: string | null
  data?: Record<string, unknown> | null
  conversation_id?: string | null
  operation_id?: string | null
  turn_id?: string | null
  run_id?: string | null
  step_index?: number | null
}

export interface ScheduleTask {
  id: string
  name: string
  source: string
  prompt: string
  enabled: boolean
  mode: 'once' | 'interval'
  created_at: number
  run_after_seconds?: number | null
  interval_seconds?: number | null
  next_run_at?: number | null
  last_run_at?: number | null
  last_status?: string | null
  last_run_id?: string | null
  last_job_id?: string | null
  last_request_id?: string | null
  last_run_summary?: string | null
  owner_agent_id?: string | null
  owner_agent_role?: string | null
  route_reason?: string | null
}

export interface PluginSnapshot {
  id: string
  name: string
  version?: string | null
  enabled: boolean
  loaded: boolean
  error: string | null
  config?: Record<string, unknown>
  config_schema?: Record<string, unknown>
}

export interface PluginTraceRecord {
  timestamp: string
  plugin_id: string
  hook: string
  status: string
  detail?: string
}

export interface RuntimeContributionSummary {
  category: 'ui' | 'capability' | 'event' | 'policy'
  count: number
  items: string[]
}

export interface AgentPluginsSnapshot {
  plugins: PluginSnapshot[]
  trace: PluginTraceRecord[]
  contributionSummary?: RuntimeContributionSummary[]
}

export interface MCPServerConfigSnapshot {
  name: string
  base_url: string
  transport: string
  enabled: boolean
  command?: string | null
  args?: string[] | null
  env_keys?: string[] | null
  header_keys?: string[] | null
}

export interface MCPServerPresetSnapshot {
  id: string
  name: string
  description: string
  category: string
  transport: string
  base_url: string
  command?: string | null
  args?: string[] | null
  env_keys?: string[] | null
  header_keys?: string[] | null
  enabled: boolean
  installed: boolean
}

export interface MCPHistoryEntry {
  timestamp: string
  event: string
  status: string
  detail?: string
  transport?: string | null
  tool?: string | null
  request_id?: string | null
  duration_ms?: number | null
  error?: string | null
  session_id?: string | null
  pending_requests?: number | null
  total_calls?: number | null
  total_failures?: number | null
  args_keys?: string[] | null
  output_chars?: number | null
}

export interface MCPInventoryItem {
  name: string
  description?: string
  input_schema?: Record<string, unknown> | null
}

export interface MCPServerStatusSnapshot {
  enabled: boolean
  ok: boolean
  status_code?: number | null
  message?: string | null
  transport?: string | null
  connected?: boolean | null
  pending_requests?: number | null
  total_calls?: number | null
  total_failures?: number | null
  reconnect_count?: number | null
  last_error?: string | null
  session_id?: string | null
  history?: MCPHistoryEntry[] | null
  tools_count?: number | null
  resources_count?: number | null
  prompts_count?: number | null
  tools?: MCPInventoryItem[] | null
  resources?: MCPInventoryItem[] | null
  prompts?: MCPInventoryItem[] | null
  inventory_error?: string | null
}

export interface MCPSnapshot {
  servers: Record<string, MCPServerConfigSnapshot>
  status: Record<string, MCPServerStatusSnapshot>
  contributionSummary?: RuntimeContributionSummary[]
  presets?: MCPServerPresetSnapshot[]
}

export interface AgentTraceSnapshot {
  planner: PlannerTrace[]
  steps: StepExecutionRecord[]
  scheduler: SchedulerRunRecord[]
  runtime_loop?: RuntimeLoopRecord[]
}

export interface ExperienceLatencySummary {
  samples: number
  latest_ms: number | null
  p50_ms: number | null
  p95_ms: number | null
}

export interface ExperienceMetricsSnapshot {
  generated_at: string
  window: {
    max_entries: number
    generation_samples: number
    asr_samples: number
    voice_journey_samples: number
    voice_playback_journey_samples: number
    visual_analysis_samples: number
  }
  latency: Record<string, ExperienceLatencySummary>
  interrupts: {
    requests: number
    hits: number
    hit_rate: number | null
    by_source: Record<string, {
      requests: number
      hits: number
      hit_rate: number | null
    }>
  }
  tools: {
    calls: number
    successes: number
    failures: number
    success_rate: number | null
  }
  visual: {
    frames: number
    analysis_requests: number
    analysis_skipped: number
    analysis_rate: number | null
    completed: number
    usable: number
    usable_rate: number | null
    outcomes: Record<'ready' | 'empty' | 'error' | 'stale', number>
    decision_reasons: Record<string, number>
    capture_reasons: Record<string, number>
    latest_change_score: number | null
  }
}

export interface DiagnosticsEnvCheck {
  electronRoot: string
  pythonAppExists: boolean
  pythonVenvExists: boolean
  pythonVenvPath: string
  rendererDistExists: boolean
  pluginDirExists: boolean
  backupDirExists: boolean
}

export interface RuntimeExceptionRecord {
  timestamp: string
  type: string
  detail: string
}

export interface DiagnosticsSnapshot {
  status: string
  panelUrl?: string
  petWindowVisible: boolean
  petOverlayVisible: boolean
  petBounds: Record<string, unknown>
  petState: PetControlState
  pluginCount: number
  pluginErrorCount: number
  activePluginExecutions: number
  runtimeExceptions: RuntimeExceptionRecord[]
  envCheck: DiagnosticsEnvCheck
}

export interface SystemLogsSnapshot {
  logs: {
    renderer: string | null
    python: string | null
    electron: string | null
  }
}

export interface BackupTarget {
  path: string
  exists: boolean
  type: string
}

export interface BackupTargetsSnapshot {
  targets: BackupTarget[]
}

export interface BackupRestorePlanItem {
  path: string
  currentlyExists: boolean
  backedUpAtSnapshot: boolean
  restored: boolean
  skippedReason?: string
}

export interface BackupRestoreResponse {
  ok: boolean
  dryRun: boolean
  backupDir: string
  manifest?: {
    createdAt?: string
    targets?: Array<{
      path: string
      exists: boolean
      type?: string
      skippedReason?: string
    }>
  }
  restorePlan: BackupRestorePlanItem[]
}

export interface PermissionStateSnapshot {
  remembered: Record<string, boolean>
  audit: PermissionAuditRecord[]
}

export interface PermissionMutationSnapshot extends PermissionStateSnapshot {
  ok: boolean
  cleared?: number
}

export interface MCPMutationResponse {
  ok: boolean
  server: MCPServerConfigSnapshot | null
}

export interface MCPRefreshResponse {
  ok: boolean
  status: MCPServerStatusSnapshot | null
}

export interface AgentPluginMutationResponse {
  ok: boolean
  plugin: PluginSnapshot | null
}

export interface SchedulesSnapshot {
  tasks: ScheduleTask[]
}

export interface ScheduleMutationResponse {
  ok: boolean
  task: ScheduleTask | null
  run?: ScheduleRunIdentity | null
}

export interface ScheduleRunIdentity {
  taskId: string
  runId: string
  jobId: string
  requestId: string
  workspaceId: string
  sessionId: string
  turnId: string
  status: string
  createdAt: number
  finishedAt?: number | null
}

export interface ScheduleCancellationResponse {
  ok: boolean
  run: ScheduleRunIdentity | null
}

export interface HeartbeatSnapshot {
  running: boolean
  interval_seconds?: number
  tick_count: number
  last_tick_at?: string | null
  persona: HeartbeatPersona
  events: HeartbeatTickEvent[]
  behavior_events: HeartbeatBehaviorEvent[]
  goals?: HeartbeatGoalSnapshot[]
  proactive_state?: {
    can_proactively_reach_out: boolean
    suppression_reasons?: string[]
    trigger_reason?: string
    readiness_band?: string
  } | null
  behavior_profile?: {
    tone_bucket?: string
    closeness_bucket?: string
    expression_bucket?: string
    initiative_bucket?: string
  } | null
  active_workspace_id?: string
  active_companion?: {
    id: string
    name: string
    model_type?: string | null
    model_id?: string | null
    persona_prompt?: string | null
    emotion_state?: string | null
    affinity_state?: number | null
    energy_state?: number | null
  } | null
}

export interface HeartbeatGoalSnapshot {
  goal_id: string
  kind: string
  due_at: number
  priority: number
  cooldown_seconds: number
  expires_at?: number | null
  state: 'pending' | 'completed' | 'suppressed' | 'cancelled' | 'expired' | 'failed' | string
  created_at: number
  updated_at: number
  reason?: string
  payload?: Record<string, unknown>
}

export interface RelationshipSummarySnapshot {
  event_count: number
  high_importance_count: number
  global_count: number
  workspace_count: number
  milestone_count: number
  recent_trust_shift_count: number
  recent_gratitude_count: number
  relationship_stage: string
  proactive_budget: number
  relationship_trend: string
  milestone_salience?: string
  milestone_reasoning?: string
}

export interface RelationshipEventSnapshot {
  kind?: string
  mood?: string
  affinity?: number
  energy?: number
  text?: string
  timestamp?: string | null
  workspace_id?: string | null
  scope?: string | null
  importance?: number | null
  milestone?: boolean
}

export interface CompanionRuntimeSnapshot {
  active_workspace_id?: string
  active_companion?: HeartbeatSnapshot['active_companion']
  heartbeat: Omit<HeartbeatSnapshot, 'active_workspace_id' | 'active_companion'>
  jobs?: {
    events: import('./companion-event').CompanionEventEnvelope[]
    active_job_ids: string[]
  }
  companion_state?: {
    mood: string
    energy: number
    trust: number
    intimacy: number
    interruptibility: number
    fatigue: number
    stage: string
    proactive_state?: {
      can_proactively_reach_out: boolean
      suppression_reasons?: string[]
      trigger_reason?: string
      readiness_band?: string
    } | null
    behavior_profile?: {
      tone_bucket?: string
      closeness_bucket?: string
      expression_bucket?: string
      initiative_bucket?: string
    } | null
  }
  memory_state?: {
    profile_count: number
    semantic_count?: number
    episodic_count: number
    relationship_count: number
    working_count: number
    reflective_count: number
    recent_signals?: Array<{
      kind: string
      layer: string
      source: string
      importance: number
      text: string
      timestamp: string
    }>
    signal_summary?: Record<string, number>
  }
  retrieval_strategy?: {
    label: string
    layers: string[]
    reasoning: string
  }
  relationship: {
    events: RelationshipEventSnapshot[]
    grouped: Record<string, Record<string, RelationshipEventSnapshot[]>>
    milestones: RelationshipEventSnapshot[]
    summary: RelationshipSummarySnapshot
  }
}

export type { CapabilitiesSnapshot }

export interface HeartbeatPersona {
  mood: 'neutral' | 'tired' | 'gentle' | 'warm' | 'curious' | string
  energy: number
  affinity: number
}

export interface HeartbeatTickEvent {
  tick: number
  at: string
  persona: HeartbeatPersona
}

export interface HeartbeatBehaviorEvent {
  type: 'suggestion' | 'idle_prompt' | 'reminder' | string
  message: string
  emotion: string
  emotion_id: string
  motion_group: string
  prompt: string
  tick: number
  at: string
  job_id?: string
  request_id?: string
  goal_id?: string
  expires_at?: number
  trigger_reason?: string
  content_code?: string
  sourceKind?: import('./proactive').ProactiveSource
  source_kind?: import('./proactive').ProactiveSource
  sourceId?: string
  source_id?: string
  frame_id?: string
  frameId?: string
  activity_frame_id?: string
  proactive_state?: {
    can_proactively_reach_out: boolean
    suppression_reasons?: string[]
    trigger_reason?: string
    readiness_band?: string
  }
  behavior_profile?: {
    tone_bucket?: string
    closeness_bucket?: string
    expression_bucket?: string
    initiative_bucket?: string
  }
  trace_layers?: string[]
  trace_recall_count?: number
}
