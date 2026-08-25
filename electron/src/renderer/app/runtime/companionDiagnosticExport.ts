const REDACTED = '[redacted]'
const OMITTED = '[omitted:sensitive-payload]'
const MAX_STRING_LENGTH = 2_000
const MAX_ARRAY_LENGTH = 200
const MAX_OBJECT_KEYS = 200

const secretKeyPattern = /(authorization|cookie|credential|password|secret|token|api.?key|client.?key)/i
const omittedPayloadKeyPattern = /^(args|messages|content|reply|reply_preview|description|goal|summary|message|error|title|reason|resultSummary|result_summary|cancellationReason|cancellation_reason|screenshot|image|imageData|image_data|imageUrl|image_url|frame|frameData|frame_data|pcm|audio|audioData|audio_data|rawMemory|raw_memory|memoryText|memory_text|memoryContent|memory_content|clipboardText|clipboard_text|fileText|file_text|query|prompt|input|transcript|user_text|userText|raw_user_text|rawUserText)$/i
const allowedContainerKeyPattern = /^(trace|jobs|entries|stepChain|runtimeLoopEntries|schedulerEntries|data|failure|recovery|condition|configuredBudget|consumedUsage)$/i
const allowedMetadataKeyPattern = /^(traceType|timestamp|type|kind|status|stage|mode|source|version|schemaVersion|workspaceId|workspace_id|sessionId|session_id|turnId|turn_id|jobId|job_id|requestId|request_id|conversationId|conversation_id|operationId|operation_id|runId|run_id|taskId|task_id|stepId|step_id|failedStep|failed_step|failedStepId|failed_step_id|revision|interruptionEpoch|interruption_epoch|sequence|stepIndex|step_index|planner|steps|scheduler|runtimeLoop|runtime_loop|progress|retryable|available|action|scope|singleUse|single_use|ttlSeconds|ttl_seconds|completedSteps|completed_steps|failureCategory|failure_category|category|tool|dependsOn|depends_on|success|firstTimestamp|lastTimestamp|ownerAgentId|owner_agent_id|ownerAgentRole|owner_agent_role|agentId|agent_id|agentRole|agent_role|autonomyMode|autonomy_mode|urgency|turnStage|idempotencyKey|semanticFingerprint|generationId|maxIterations|max_iterations|outputTokens|output_tokens|retryBudget|retry_budget|toolBudget|tool_budget|iterations|retries|toolCalls|tool_calls|attempts)$/i
const identifierKeyPattern = /^(workspaceId|workspace_id|sessionId|session_id|turnId|turn_id|jobId|job_id|requestId|request_id|conversationId|conversation_id|operationId|operation_id|runId|run_id|taskId|task_id|stepId|step_id|failedStep|failed_step|failedStepId|failed_step_id|ownerAgentId|owner_agent_id|agentId|agent_id|idempotencyKey|semanticFingerprint|generationId|tool)$/i
const identifierListKeyPattern = /^(completedSteps|completed_steps|dependsOn|depends_on)$/i
const timestampKeyPattern = /^(timestamp|firstTimestamp|lastTimestamp)$/i
const enumKeyPattern = /^(traceType|type|kind|status|stage|mode|source|schemaVersion|action|scope|failureCategory|failure_category|category|ownerAgentRole|owner_agent_role|agentRole|agent_role|autonomyMode|autonomy_mode|urgency|turnStage)$/i
const safeEnumValues = new Set([
  'all', 'planner', 'steps', 'scheduler', 'runtime_loop',
  'created', 'running', 'progress', 'completed', 'failed', 'cancelled', 'interrupted',
  'unknown_effect', 'ok', 'error', 'skipped', 'pending', 'partial', 'queued', 'rolled_back',
  'agentjobcreated', 'agentjobrunning', 'agentjobprogress', 'agentjobcompleted',
  'agentjobfailed', 'agentjobcancelled', 'agentjobinterrupted', 'agentjobunknowneffect',
  'chat', 'voice', 'heartbeat', 'permission', 'health', 'vision', 'builtin', 'mcp', 'plugin',
  'tool', 'agent', 'analysis', 'join', 'schedule', 'validation', 'policy', 'timeout',
  'cancel', 'provider', 'internal', 'verification', 'resume_failed_step', 'inspect_effect',
  'turn', 'workspace', 'session', 'immediate', 'interval', 'once', 'silent', 'assistant',
  'companion', 'observe', 'interpret', 'recall', 'decide', 'ask_act', 'reflect',
  'update_relationship', 'turn_commit', 'committed', 'yuizaki.companion-event.v2',
])

export const redactDiagnosticText = (value: string): string => {
  const bounded = value.slice(0, MAX_STRING_LENGTH)
  return bounded
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, REDACTED)
    .replace(/\bsk-[A-Za-z0-9._-]+/gi, REDACTED)
    .replace(/\bgh[pousr]_[A-Za-z0-9]{20,}\b/g, REDACTED)
    .replace(/\bAKIA[A-Z0-9]{16}\b/g, REDACTED)
    .replace(/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g, REDACTED)
    .replace(/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/g, REDACTED)
    .replace(/\b(api[_-]?key|access[_-]?token|authorization|password|secret|token)\s*[:=]\s*[^\s,;]+/gi, `$1=${REDACTED}`)
    .replace(/\b(api\s+key|access\s+token|authorization|password|secret|token|credential)\s+(?:is|are)\s+[^\s,;.]+/gi, `$1 ${REDACTED}`)
    .replace(/([?&](?:api[_-]?key|access[_-]?token|authorization|password|secret|token)=)[^&#\s]+/gi, `$1${REDACTED}`)
}

interface SanitizeContext {
  seen: WeakSet<object>
  aliases: Map<string, string>
}

const identifierAlias = (value: string, context: SanitizeContext): string => {
  const bounded = value.slice(0, MAX_STRING_LENGTH)
  const existing = context.aliases.get(bounded)
  if (existing) return existing
  const alias = `[id:${context.aliases.size + 1}]`
  context.aliases.set(bounded, alias)
  return alias
}

const sanitize = (value: unknown, context: SanitizeContext, key = ''): unknown => {
  if (typeof value === 'string') {
    if (identifierKeyPattern.test(key)) return identifierAlias(value, context)
    if (timestampKeyPattern.test(key)) {
      return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(value)
        ? value
        : OMITTED
    }
    if (enumKeyPattern.test(key)) {
      const normalized = value.trim().toLowerCase().replace(/[\s-]+/g, '_')
      return safeEnumValues.has(normalized) ? normalized : OMITTED
    }
    return OMITTED
  }
  if (typeof value === 'number') return Number.isFinite(value) ? value : OMITTED
  if (typeof value === 'boolean' || value === null) return value
  if (typeof value !== 'object') return OMITTED
  if (context.seen.has(value)) return '[omitted:circular]'
  context.seen.add(value)
  if (Array.isArray(value)) {
    if (identifierListKeyPattern.test(key)) {
      return value.slice(0, 20).map(item => typeof item === 'string' ? identifierAlias(item, context) : OMITTED)
    }
    if (!allowedContainerKeyPattern.test(key)) return OMITTED
    return value.slice(0, MAX_ARRAY_LENGTH).map(item => sanitize(item, context))
  }

  const result: Record<string, unknown> = {}
  for (const [key, child] of Object.entries(value).slice(0, MAX_OBJECT_KEYS)) {
    if (secretKeyPattern.test(key)) {
      result[key] = REDACTED
    } else if (omittedPayloadKeyPattern.test(key)) {
      result[key] = OMITTED
    } else if (allowedContainerKeyPattern.test(key) || allowedMetadataKeyPattern.test(key)) {
      result[key] = sanitize(child, context, key)
    } else {
      result[key] = OMITTED
    }
  }
  return result
}

export interface CompanionDiagnosticBundle {
  schemaVersion: 1
  generatedAt: string
  diagnostics: unknown
}

export type CompanionDiagnosticSerializationResult =
  | { ok: true; json: string }
  | { ok: false; reason: 'diagnostic_secret_scan_failed' | 'diagnostic_serialization_failed' }

const serializedLeakPatterns = [
  /\bBearer\s+[A-Za-z0-9._~+/=-]+/i,
  /\bsk-[A-Za-z0-9._-]+/i,
  /\bgh[pousr]_[A-Za-z0-9]{20,}\b/,
  /\bAKIA[A-Z0-9]{16}\b/,
  /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /data:(?:image|audio|video)\//i,
  /"[^"]*(?:authorization|cookie|credential|password|secret|token|api.?key|client.?key)[^"]*"\s*:\s*"(?!\[redacted\])[^"\\]+"/i,
  /"(?:args|messages|content|reply|reply_preview|description|goal|summary|message|error|title|reason|resultSummary|result_summary|cancellationReason|cancellation_reason|screenshot|image|frame|pcm|audio|rawMemory|memoryText|memoryContent|clipboardText|fileText|query|prompt|input|transcript|user_text|userText|raw_user_text|rawUserText)"\s*:\s*"(?!\[omitted:sensitive-payload\])[^"\\]+"/i,
  /\b(?:api\s+key|access\s+token|authorization|password|secret|token|credential)\s+(?:is|are)\s+[^\s,;.]+/i,
]

export const createRedactedDiagnosticBundle = (
  diagnostics: Record<string, unknown>,
  now: () => Date = () => new Date(),
): CompanionDiagnosticBundle => ({
  schemaVersion: 1,
  generatedAt: now().toISOString(),
  diagnostics: sanitize(diagnostics, { seen: new WeakSet<object>(), aliases: new Map<string, string>() }),
})

export const serializeRedactedDiagnosticBundle = (
  bundle: CompanionDiagnosticBundle,
): CompanionDiagnosticSerializationResult => {
  let json: string
  try {
    json = `${JSON.stringify(bundle, null, 2)}\n`
  } catch {
    return { ok: false, reason: 'diagnostic_serialization_failed' }
  }
  return serializedLeakPatterns.some(pattern => pattern.test(json))
    ? { ok: false, reason: 'diagnostic_secret_scan_failed' }
    : { ok: true, json }
}
