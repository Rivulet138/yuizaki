import type { HttpClientError } from '@/api/clients/http-client'
import { currentLocale, t } from '@/i18n'
import { errorMessages } from '@/i18n/errorMessages'

/**
 * Turn a backend error into one sentence a user can act on.
 *
 * The backend returns stable machine codes (`qq_bridge_hash_mismatch`,
 * `dsh_empty_output`, `rate_limited`, ...). Panels used to show those codes, or a
 * bare HTTP status, straight to the user. This module owns the mapping from code
 * to message key in one place, so every surface explains the same failure the
 * same way and keeps the raw code available for support; the sentences
 * themselves live in `i18n/errorMessages.ts`, which makes them translatable
 * without touching this logic.
 */

export interface ErrorExplanation {
  /** Short, user-facing sentence. */
  title: string
  /** Optional concrete next step. */
  action?: string
  /** Machine code when the backend supplied one. */
  code?: string
  /** HTTP status when the failure came from a response. */
  status?: number
  /** Request id for support, when present. */
  requestId?: string
}

/**
 * Message keys for one code. Keeping keys rather than text here is what lets the
 * catalogue be re-translated as data; a missing key would render as its own name,
 * so every entry must name the keys that `i18n/errorMessages.ts` defines.
 */
type Entry = { title: string; action?: string }

const CODE_TABLE: Record<string, Entry> = {
  // ---- transport / local service ----
  service_unavailable: { title: 'error.service_unavailable.title', action: 'error.service_unavailable.action' },
  request_timeout: { title: 'error.request_timeout.title', action: 'error.request_timeout.action' },
  backend_auth_missing: { title: 'error.backend_auth_missing.title', action: 'error.backend_auth_missing.action' },

  // ---- model provider ----
  llm_not_initialized: { title: 'error.llm_not_initialized.title', action: 'error.llm_not_initialized.action' },
  llm_key_missing: { title: 'error.llm_key_missing.title', action: 'error.llm_key_missing.action' },
  provider_rejected: { title: 'error.provider_rejected.title', action: 'error.provider_rejected.action' },
  empty_reply: { title: 'error.empty_reply.title', action: 'error.empty_reply.action' },
  turn_runner_exception: { title: 'error.turn_runner_exception.title', action: 'error.turn_runner_exception.action' },

  // ---- DSH delegation ----
  dsh_invalid_task: { title: 'error.dsh_invalid_task.title', action: 'error.dsh_invalid_task.action' },
  dsh_invalid_config: { title: 'error.dsh_invalid_config.title', action: 'error.dsh_invalid_config.action' },
  dsh_not_found: { title: 'error.dsh_not_found.title', action: 'error.dsh_not_found.action' },
  dsh_busy: { title: 'error.dsh_busy.title', action: 'error.dsh_busy.action' },
  dsh_timeout: { title: 'error.dsh_timeout.title', action: 'error.dsh_timeout.action' },
  dsh_nonzero_exit: { title: 'error.dsh_nonzero_exit.title', action: 'error.dsh_nonzero_exit.action' },
  dsh_output_too_large: { title: 'error.dsh_output_too_large.title', action: 'error.dsh_output_too_large.action' },
  dsh_empty_output: { title: 'error.dsh_empty_output.title', action: 'error.dsh_empty_output.action' },
  dsh_execution_context_required: { title: 'error.dsh_execution_context_required.title', action: 'error.dsh_execution_context_required.action' },

  // ---- QQ managed bridge ----
  qq_bridge_unavailable: { title: 'error.qq_bridge_unavailable.title', action: 'error.qq_bridge_unavailable.action' },
  qq_bridge_risk_not_accepted: { title: 'error.qq_bridge_risk_not_accepted.title', action: 'error.qq_bridge_risk_not_accepted.action' },
  qq_bridge_no_source: { title: 'error.qq_bridge_no_source.title', action: 'error.qq_bridge_no_source.action' },
  qq_bridge_hash_mismatch: { title: 'error.qq_bridge_hash_mismatch.title', action: 'error.qq_bridge_hash_mismatch.action' },
  qq_bridge_install_failed: { title: 'error.qq_bridge_install_failed.title', action: 'error.qq_bridge_install_failed.action' },
  qq_bridge_install_incomplete: { title: 'error.qq_bridge_install_incomplete.title', action: 'error.qq_bridge_install_incomplete.action' },
  qq_bridge_not_installed: { title: 'error.qq_bridge_not_installed.title', action: 'error.qq_bridge_not_installed.action' },
  qq_bridge_spawn_failed: { title: 'error.qq_bridge_spawn_failed.title', action: 'error.qq_bridge_spawn_failed.action' },

  // ---- connector admission ----
  missing_bridge_url: { title: 'error.missing_bridge_url.title', action: 'error.missing_bridge_url.action' },
  missing_bridge_token: { title: 'error.missing_bridge_token.title', action: 'error.missing_bridge_token.action' },
  invalid_bridge_url: { title: 'error.invalid_bridge_url.title', action: 'error.invalid_bridge_url.action' },
  personal_bridge_only: { title: 'error.personal_bridge_only.title', action: 'error.personal_bridge_only.action' },
  official_connector_removed: { title: 'error.official_connector_removed.title', action: 'error.official_connector_removed.action' },
  invalid_webhook_auth: { title: 'error.invalid_webhook_auth.title', action: 'error.invalid_webhook_auth.action' },
  connector_disabled: { title: 'error.connector_disabled.title', action: 'error.connector_disabled.action' },
  not_allowlisted: { title: 'error.not_allowlisted.title', action: 'error.not_allowlisted.action' },
  rate_limited: { title: 'error.rate_limited.title', action: 'error.rate_limited.action' },
  connector_event_in_progress: { title: 'error.connector_event_in_progress.title', action: 'error.connector_event_in_progress.action' },

  // ---- workspace / settings ----
  workspace_mismatch: { title: 'error.workspace_mismatch.title', action: 'error.workspace_mismatch.action' },
  context_revision_conflict: { title: 'error.context_revision_conflict.title', action: 'error.context_revision_conflict.action' },
  permission_required: { title: 'error.permission_required.title', action: 'error.permission_required.action' },
  MEMORY_RECALL_FAILED: { title: 'error.MEMORY_RECALL_FAILED.title', action: 'error.MEMORY_RECALL_FAILED.action' },
  invalid_json: { title: 'error.invalid_json.title', action: 'error.invalid_json.action' },
  payload_too_large: { title: 'error.payload_too_large.title', action: 'error.payload_too_large.action' },
  text_required: { title: 'error.text_required.title', action: 'error.text_required.action' },
  file_too_large: { title: 'error.file_too_large.title', action: 'error.file_too_large.action' },

  // ---- tools / agent runtime ----
  tool_timeout: { title: 'error.tool_timeout.title', action: 'error.tool_timeout.action' },
  tool_not_exposed: { title: 'error.tool_not_exposed.title', action: 'error.tool_not_exposed.action' },
  tool_executor_not_available: { title: 'error.tool_executor_not_available.title', action: 'error.tool_executor_not_available.action' },
  tool_executor_returned_none: { title: 'error.tool_executor_returned_none.title', action: 'error.tool_executor_returned_none.action' },
  permission_denied: { title: 'error.permission_denied.title', action: 'error.permission_denied.action' },
  user_denied: { title: 'error.user_denied.title', action: 'error.user_denied.action' },
  untrusted_mcp_followup_requires_confirmation: { title: 'error.untrusted_mcp_followup_requires_confirmation.title', action: 'error.untrusted_mcp_followup_requires_confirmation.action' },
  generation_manager_unavailable: { title: 'error.generation_manager_unavailable.title', action: 'error.generation_manager_unavailable.action' },
  llm_unavailable: { title: 'error.llm_unavailable.title', action: 'error.llm_unavailable.action' },
  chat_completion_failed: { title: 'error.chat_completion_failed.title', action: 'error.chat_completion_failed.action' },
  chat_error: { title: 'error.chat_error.title', action: 'error.chat_error.action' },
  companion_not_found: { title: 'error.companion_not_found.title', action: 'error.companion_not_found.action' },
  dsh_io_error: { title: 'error.dsh_io_error.title', action: 'error.dsh_io_error.action' },
  translate_error: { title: 'error.translate_error.title', action: 'error.translate_error.action' },

  // ---- storage / index ----
  database_error: { title: 'error.database_error.title', action: 'error.database_error.action' },
  database_not_initialized: { title: 'error.database_not_initialized.title', action: 'error.database_not_initialized.action' },
  memory_search_scan_limit_reached: { title: 'error.memory_search_scan_limit_reached.title', action: 'error.memory_search_scan_limit_reached.action' },
  memory_index_rebuild_cancelled: { title: 'error.memory_index_rebuild_cancelled.title', action: 'error.memory_index_rebuild_cancelled.action' },

  // ---- scheduler / recovery ----
  scheduler_not_available: { title: 'error.scheduler_not_available.title', action: 'error.scheduler_not_available.action' },
  scheduled_task_exception: { title: 'error.scheduled_task_exception.title', action: 'error.scheduled_task_exception.action' },
  unsupported_schedule_mode: { title: 'error.unsupported_schedule_mode.title', action: 'error.unsupported_schedule_mode.action' },
  recovery_not_available: { title: 'error.recovery_not_available.title', action: 'error.recovery_not_available.action' },
  recovery_resume_failed: { title: 'error.recovery_resume_failed.title', action: 'error.recovery_resume_failed.action' },
  recovery_resume_invalid: { title: 'error.recovery_resume_invalid.title', action: 'error.recovery_resume_invalid.action' },

  // ---- voice / bridge transport ----
  svc_error: { title: 'error.svc_error.title', action: 'error.svc_error.action' },
  svc_not_initialized: { title: 'error.svc_not_initialized.title', action: 'error.svc_not_initialized.action' },
  relationship_history_unavailable: { title: 'error.relationship_history_unavailable.title', action: 'error.relationship_history_unavailable.action' },
  connection_closed: { title: 'error.connection_closed.title', action: 'error.connection_closed.action' },
  server_reconnect: { title: 'error.server_reconnect.title', action: 'error.server_reconnect.action' },
  unauthorized: { title: 'error.unauthorized.title', action: 'error.unauthorized.action' },
  auth_failed: { title: 'error.auth_failed.title', action: 'error.auth_failed.action' },
}

const STATUS_FALLBACK: Record<number, Entry> = {
  400: { title: 'error.http_400.title', action: 'error.http_400.action' },
  401: { title: 'error.http_401.title', action: 'error.http_401.action' },
  403: { title: 'error.http_403.title', action: 'error.http_403.action' },
  404: { title: 'error.http_404.title', action: 'error.http_404.action' },
  409: { title: 'error.http_409.title', action: 'error.http_409.action' },
  422: { title: 'error.http_422.title', action: 'error.http_422.action' },
  429: { title: 'error.http_429.title', action: 'error.http_429.action' },
  502: { title: 'error.http_502.title', action: 'error.http_502.action' },
  503: { title: 'error.http_503.title', action: 'error.http_503.action' },
  504: { title: 'error.http_504.title', action: 'error.http_504.action' },
}

/**
 * The catalogue, widened for lookup by locale and key: `definePanelMessages`
 * infers a literal key union, which cannot be indexed with a runtime string.
 */
const catalog: Record<string, Record<string, string>> = errorMessages as unknown as Record<
  string,
  Record<string, string>
>

/**
 * Resolve one catalogue key for the active locale.
 *
 * `t()` is the normal path. It answers with the key itself when the catalogue has
 * not been merged into the shared table yet (that merge lives in `i18n/index.ts`,
 * which this module deliberately does not own), and a toast reading
 * `error.dsh_timeout.title` is worse than any fallback, so the catalogue is asked
 * directly as a second chance. Once the module is registered the second lookup
 * never runs.
 */
const message = (key: string): string => {
  const translated = t(key)
  if (translated !== key) return translated
  return catalog[currentLocale.value]?.[key] ?? key
}

const readField = (value: unknown, key: string): unknown =>
  value && typeof value === 'object' ? (value as Record<string, unknown>)[key] : undefined

const asString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim() ? value.trim() : undefined

const asNumber = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined

/** Split a raw string that is exactly a machine code (e.g. "dsh_timeout"). */
const looksLikeCode = (value: string): boolean => /^[A-Za-z][A-Za-z0-9_]{2,60}$/.test(value)

export function explainError(error: unknown): ErrorExplanation {
  if (error == null) {
    return { title: message('error.unknown.title'), action: message('error.unknown.action') }
  }

  const candidate = error as Partial<HttpClientError> & Record<string, unknown>
  const rawCode = asString(candidate.code) || asString(readField(candidate.payload, 'code'))
  const status = asNumber(candidate.status) ?? asNumber(readField(candidate.payload, 'status'))
  const requestId = asString(candidate.requestId) || asString(readField(candidate.payload, 'request_id'))
  const rawMessage = asString(candidate.message) ?? asString(readField(candidate.payload, 'message')) ?? ''

  // A payload may carry the code inside `error`, e.g. {"error": "rate_limited"}.
  const payloadError = asString(readField(candidate.payload, 'error'))
  const messageCode = looksLikeCode(rawMessage) ? rawMessage : undefined
  const payloadCode = payloadError && looksLikeCode(payloadError) ? payloadError : undefined
  const code = rawCode || messageCode || payloadCode

  const known = code ? CODE_TABLE[code] : undefined
  if (known) {
    return {
      title: message(known.title),
      action: known.action ? message(known.action) : undefined,
      code,
      status,
      requestId,
    }
  }

  const byStatus = status ? STATUS_FALLBACK[status] : undefined
  if (byStatus) {
    const title = message(byStatus.title)
    const action = byStatus.action ? message(byStatus.action) : ''
    const detail = rawMessage && !looksLikeCode(rawMessage) && rawMessage !== title ? rawMessage : undefined
    return {
      title,
      action: detail ? t('error.format.statusDetail', { action, detail }) : action,
      code,
      status,
      requestId,
    }
  }

  // Nothing machine-readable: keep whatever sentence the backend sent, but strip
  // a bare HTTP wrapper so the toast never reads "http_400".
  const readable = rawMessage && !looksLikeCode(rawMessage) ? rawMessage : ''
  return {
    title: readable || message('error.unknown.title'),
    action: readable ? undefined : message('error.unknown.retryAction'),
    code,
    status,
    requestId,
  }
}

/**
 * One-line rendering for toasts and inline alerts. Keeps the machine code in
 * parentheses only when it adds diagnostic value the sentence lacks.
 */
export function describeError(error: unknown): string {
  const { title, action, code } = explainError(error)
  const body = action ? t('error.format.titleAction', { title, action }) : title
  return code && !body.includes(code) ? t('error.format.withCode', { body, code }) : body
}

/** True when the failure carries something the shared table can act on. */
const isIdentifiable = (error: unknown): boolean => {
  const { code, status } = explainError(error)
  if (typeof status === 'number') return true
  return Boolean(code && Object.prototype.hasOwnProperty.call(CODE_TABLE, code))
}

/**
 * Context-first failure text for toasts and inline alerts.
 *
 * Call sites used to repeat `error instanceof Error ? error.message : '上下文'`,
 * which put raw transport strings in front of the user ("Request failed with
 * status code 500", SDK wording, stack hints) and discarded the sentence the
 * caller already had. This keeps the caller's context unless the failure is
 * machine-identifiable, in which case the shared explanation wins because it
 * carries a next step.
 *
 * `context` is expected to be already-localised by the caller, so an
 * i18n-aware panel keeps its own wording for unrecognised failures.
 */
export function describeFailure(error: unknown, context?: string): string {
  if (isIdentifiable(error)) return describeError(error)
  const fallback = context?.trim()
  return fallback || describeError(error)
}
