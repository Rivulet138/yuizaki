export type CapabilityKind = 'builtin-tool' | 'plugin-tool' | 'mcp-tool' | 'skill' | 'command'

export type CapabilityType = 'tool' | 'skill' | 'command'

export type CapabilityRiskLevel = 'safe' | 'low' | 'medium' | 'high' | 'critical'

export type CapabilityEffectKind = 'read' | 'write' | 'unknown'

export interface CapabilityDescriptor {
  id: string
  name: string
  description: string
  type: CapabilityType
  kind: CapabilityKind
  source: string
  riskLevel: CapabilityRiskLevel
  requiresApproval: boolean
  owner?: string
  tags?: string[]
  contributionCategories?: string[]
  scopes?: string[]
  inputSchema?: Record<string, unknown>
  outputSchema?: Record<string, unknown>
  timeoutMs?: number
  memoryHooks?: string[]
  observability?: {
    trace?: boolean
    audit?: boolean
    stage?: string
  }
  parameters?: Record<string, unknown>
  effectKind?: CapabilityEffectKind
  hasPostcondition?: boolean
  hasRecheck?: boolean
}

export interface CapabilitiesSnapshot {
  capabilities: CapabilityDescriptor[]
  summary?: {
    total: number
    builtin: number
    plugin: number
    mcp: number
    skill: number
    command: number
    approval_required: number
  }
}

export type StreamState = 'disconnected' | 'ready' | 'preview' | 'live' | 'ending' | 'ended' | 'error' | string

export interface StreamCapabilityDescriptor {
  id: string
  name: string
  riskLevel?: CapabilityRiskLevel | string
  requiresApproval?: boolean
  available?: boolean
  executionReady?: boolean
  needsConfig?: boolean
}

export interface StreamPreview {
  requestId?: string
  kind: string
  action?: string
  params?: Record<string, unknown>
  riskLevel?: CapabilityRiskLevel | string
  summary?: string
  steps?: string[]
  expiresAt?: number | string | null
}

export interface StreamExecuteResponse {
  schemaVersion?: string
  ok: boolean
  executed?: boolean
  requestId?: string
  action?: string
  result?: Record<string, unknown> | null
  outcome?: string
  verificationStatus?: string
  auditEvent?: Record<string, unknown> | string | null
  audit?: Record<string, unknown> | string | null
  externalSideEffects?: boolean
  state?: StreamState
  message?: string
  error?: string
}

export interface StreamRuntimeSnapshot {
  schemaVersion?: string
  state: StreamState
  connection?: {
    status?: StreamState
    adapter?: string | null
    configured?: boolean
  }
  platforms?: {
    twitch?: {
      eventsubConfigured?: boolean
      eventsubPath?: string
      ircIngressPath?: string
      inboundRateLimitPerMinute?: number
      throttledEvents?: number
      revoked?: boolean
      revocationCount?: number
      outboundActions?: boolean
      chatConfigured?: boolean
      connectionStatus?: 'configured' | 'revoked' | 'unconfigured' | string
      lastEventAt?: string | null
      subscriptionPlan?: {
        status?: 'unconfigured' | 'not_planned' | 'planned' | 'synced' | 'revoked' | string
        management?: 'local_only' | string
        remoteSyncAvailable?: boolean
        desired?: string[]
        active?: string[]
        lastSyncAt?: string | null
        lastError?: string | null
        externalSideEffects?: boolean
      }
      ircConnection?: {
        status?: string
        configured?: boolean
        desired?: boolean
        attempt?: number
        nextRetryInSeconds?: number | null
        backoffSeconds?: number | null
        lastError?: string | null
      }
    }
  }
  adapter?: {
    id?: string
    name?: string
    connected?: boolean
    configured?: boolean
    endpoint?: string
    remoteAllowed?: boolean
    passwordConfigured?: boolean
  } | null
  capabilities?: StreamCapabilityDescriptor[]
  policy?: {
    mode?: string
    externalSideEffects?: boolean
    confirmationRequired?: boolean
    humanTakeover?: boolean
    automaticActions?: boolean
    humanApprovalRequired?: boolean
    moderation?: StreamModerationPolicySnapshot
  } | null
  lastAction?: {
    id?: string
    kind?: string
    status?: string
    at?: number | string | null
    sideEffect?: boolean
  } | null
  preview?: StreamPreview | null
}

export interface StreamModerationPolicySnapshot {
  schemaVersion?: string
  enabled?: boolean
  blockedTerms?: string[]
  slowModeSeconds?: number
  maxMessagesPerMinute?: number
}

export interface StreamPreviewResponse {
  ok: boolean
  preview?: StreamPreview | null
  error?: string
}

/** Read-only adapter discovery result. Probe must not start or change a broadcast. */
export interface StreamProbeResponse {
  ok: boolean
  probe?: Record<string, unknown> | null
  state?: StreamState
  error?: string
}

export interface StreamObsProfile {
  profileName: string
}

export interface StreamObsProfilesResponse {
  schemaVersion?: string
  ok: boolean
  profiles?: StreamObsProfile[]
  currentProfileName?: string | null
  externalSideEffects?: boolean
  error?: string
}

export interface StreamLocalEvent {
  id?: string
  eventId?: string
  kind: string
  text?: string
  author?: string
  createdAt?: number | string | null
  receivedAt?: number | string | null
  delivered?: boolean
  status?: string
  at?: number | string | null
  source?: string
  message?: string
  payload?: Record<string, unknown> | null
}

export interface StreamEventsSnapshot {
  ok?: boolean
  schemaVersion?: string
  events?: StreamLocalEvent[]
  items?: StreamLocalEvent[]
  error?: string
}

export type StreamActionStatus = 'sending' | 'known_success' | 'unknown_effect' | 'failed' | string

export interface StreamActionRecord {
  action: string
  requestId: string
  at: string
  status: StreamActionStatus
  outcome?: string
  confirmed?: boolean
  externalSideEffects?: boolean
  verificationStatus?: string
  errorCode?: string
}

export interface StreamActionsSnapshot {
  ok?: boolean
  schemaVersion?: string
  count?: number
  limit?: number
  actions?: StreamActionRecord[]
  externalSideEffects?: boolean
  error?: string
}

export type StreamDraftStatus = 'generated' | 'failed' | string

export interface StreamReplyDraft {
  draftId: string
  eventId: string
  workspaceId: string
  sessionId: string
  requestId: string
  turnId?: string | null
  source?: string | null
  author?: string | null
  eventText?: string | null
  reply?: string | null
  status: StreamDraftStatus
  outcome?: string | null
  createdAt?: string | null
  updatedAt?: string | null
  externalSideEffects?: boolean
  sent?: boolean
  sendStatus?: 'not_sent' | 'known_success' | 'unknown_effect' | 'failed' | string
  error?: string | null
}

export interface StreamDraftsSnapshot {
  ok?: boolean
  schemaVersion?: string
  count?: number
  limit?: number
  drafts?: StreamReplyDraft[]
  externalSideEffects?: boolean
  error?: string
}

export interface StreamDraftGenerateResponse {
  ok: boolean
  created?: boolean
  draft?: StreamReplyDraft | null
  externalSideEffects?: boolean
  error?: string
}

export interface StreamDraftConsumeResponse {
  ok: boolean
  attempted?: number
  created?: number
  skipped?: number
  drafts?: StreamReplyDraft[]
  errors?: Array<{ eventId: string; code: string; error: string }>
  externalSideEffects?: boolean
  error?: string
}

export interface StreamDraftConsumerSnapshot {
  schemaVersion?: string
  enabled?: boolean
  running?: boolean
  processed?: number
  lastError?: string | null
  maxPerRun?: number
  externalSideEffects?: boolean
}

export interface StreamTakeoverResponse {
  ok: boolean
  enabled?: boolean
  policy?: StreamRuntimeSnapshot['policy']
  state?: StreamState
  snapshot?: StreamRuntimeSnapshot | null
  error?: string
}

export interface CapabilityCategorySummary {
  kind: CapabilityKind
  count: number
}

export interface SkillCatalogItem {
  id: string
  name: string
  description: string
  category: string
  source: string
  status: string
  fit: 'high' | 'medium' | 'low' | string
  installed: boolean
  enabled_codex: boolean
  /** True only when a trusted runtime executor is bound to this entry. */
  executionReady?: boolean
  /** `catalog_only` means metadata is present but no executable binding exists. */
  runtimeBinding?: 'catalog_only' | 'bound' | 'unavailable' | string
  directory?: string | null
  repo?: string | null
  url?: string | null
  tags?: string[] | null
}

export interface SkillCatalogSnapshot {
  schemaVersion?: 'yuizaki.skill-catalog.v1' | string
  items: SkillCatalogItem[]
  summary: {
    total: number
    built_in: number
    ready: number
    planned: number
    high_fit: number
    medium_fit: number
    recommended: number
    execution_ready?: number
    catalog_only?: number
    categories?: Record<string, number>
  }
  notes?: string[]
}
