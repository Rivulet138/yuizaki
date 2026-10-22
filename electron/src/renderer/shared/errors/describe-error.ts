import type { HttpClientError } from '@/api/clients/http-client'

/**
 * Turn a backend error into one sentence a user can act on.
 *
 * The backend returns stable machine codes (`qq_bridge_hash_mismatch`,
 * `dsh_empty_output`, `rate_limited`, ...). Panels used to show those codes, or a
 * bare HTTP status, straight to the user. This module owns the translation in
 * one place so every surface explains the same failure the same way and keeps
 * the raw code available for support.
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

type Entry = { title: string; action?: string }

const CODE_TABLE: Record<string, Entry> = {
  // ---- transport / local service ----
  service_unavailable: {
    title: '无法连接本地服务',
    action: '确认 Yuizaki 后端与 Electron 控制服务在运行，然后重试。',
  },
  request_timeout: { title: '本地服务响应超时', action: '稍后重试；若持续发生，请重启 Electron 窗口。' },
  backend_auth_missing: { title: '后端服务未授权', action: '刷新控制页，或从 Electron 应用入口重新打开界面。' },

  // ---- model provider ----
  llm_not_initialized: { title: '模型服务尚未就绪', action: '在「设置 → 模型」填写 API Key 后重试。' },
  llm_key_missing: { title: '缺少模型 API Key', action: '在「设置 → 模型」填写密钥；命令行启动时可用 YUIZAKI_PROVIDER_CREDENTIALS_JSON 注入。' },
  provider_rejected: { title: '模型服务拒绝了请求', action: '检查 API Key、余额与模型名是否与该端点匹配。' },
  empty_reply: { title: '模型返回了空回复', action: '重试一次；若持续为空，检查模型名或降低温度。' },
  turn_runner_exception: { title: '本轮处理中断，结果未确认', action: '刷新后检查实际结果，不要直接重试写操作。' },

  // ---- DSH delegation ----
  dsh_invalid_task: { title: '任务描述不合法', action: '任务不能为空、不能以 -- 开头，且不超过 4000 字。' },
  dsh_invalid_config: { title: 'DSH 命令配置无效', action: '检查 YUIZAKI_DSH_COMMAND 是否为 JSON argv 数组（不能是 .cmd）。' },
  dsh_not_found: { title: '找不到 DSH 可执行程序', action: '确认已安装 DSH，或设置 YUIZAKI_DSH_COMMAND 指向入口文件。' },
  dsh_busy: { title: 'DSH 正在处理其它任务', action: '等当前任务结束后再试；同一时间只允许一个 DSH 进程。' },
  dsh_timeout: { title: 'DSH 执行超时', action: '任务可能已改动文件，先核实结果再决定是否重试。' },
  dsh_nonzero_exit: { title: 'DSH 执行失败', action: '查看返回的错误输出；可能已改动文件，不要自动重试。' },
  dsh_output_too_large: { title: 'DSH 输出过长', action: '把任务拆小，或让它只返回结论摘要。' },
  dsh_empty_output: {
    title: 'DSH 没有返回任何内容',
    action: '通常是 DSH 缺少模型凭据：设置 DEEPSEEK_API_KEY 或初始化 headless profile 后重试。',
  },
  dsh_execution_context_required: { title: '缺少执行上下文', action: '本次调用未携带授权上下文，请重新发起请求。' },

  // ---- QQ managed bridge ----
  qq_bridge_unavailable: { title: '内置桥管理器不可用', action: '确认后端已启动且资源锁包含 qq_bridge 条目。' },
  qq_bridge_risk_not_accepted: { title: '尚未确认账号风险', action: '安装前需要勾选确认：个人账号协议存在封禁风险。' },
  qq_bridge_no_source: { title: '缺少桥下载源', action: 'resources.lock.json 中的 qq_bridge 条目缺少 url 或 sha256。' },
  qq_bridge_hash_mismatch: { title: '桥安装包校验失败', action: '已丢弃下载内容。上游 release 可能已更新，需要重新固定 sha256。' },
  qq_bridge_install_failed: { title: '桥安装失败', action: '检查网络与磁盘空间后重试。' },
  qq_bridge_install_incomplete: { title: '安装包内容不完整', action: '压缩包中没有可执行文件，请重新安装。' },
  qq_bridge_not_installed: { title: '内置桥尚未安装', action: '先点击「下载并安装内置桥」。' },
  qq_bridge_spawn_failed: { title: '桥进程启动失败', action: '检查杀毒软件是否拦截，或手动运行该 exe 查看报错。' },

  // ---- connector admission ----
  missing_bridge_url: { title: '缺少桥地址', action: '填写桥地址，或改用内置桥自动配置。' },
  missing_bridge_token: { title: '缺少桥令牌', action: '填写桥令牌，或改用内置桥自动生成。' },
  invalid_bridge_url: { title: '桥地址格式不正确', action: '必须是 http(s):// 的完整地址。' },
  personal_bridge_only: { title: '仅支持个人账号桥模式', action: 'QQ / 微信只保留个人账号兼容桥，官方连接器已移除。' },
  official_connector_removed: { title: '官方连接器已移除', action: '请使用个人账号兼容桥，或改用内置桥。' },
  invalid_webhook_auth: { title: '回调鉴权失败', action: '检查桥的 access_token 或 Authorization 头是否与配置一致。' },
  connector_disabled: { title: '连接器未启用', action: '先在连接器面板启用它。' },
  not_allowlisted: { title: '发送者不在白名单内', action: '把该用户或群加入允许列表，或清空白名单。' },
  rate_limited: { title: '触发频率限制', action: '稍后再发；可在 QQ 连接器里调整 ratePerMinute。' },
  connector_event_in_progress: { title: '上一条消息仍在处理', action: '等它完成后再发送。' },

  // ---- workspace / settings ----
  workspace_mismatch: { title: '跨工作区请求被拒绝', action: '切换到消息所属的工作区后重试。' },
  context_revision_conflict: { title: '工作区上下文已被修改', action: '刷新后重新编辑，避免覆盖他人的改动。' },
  permission_required: { title: '该操作需要确认', action: '在弹出的权限提示里允许后重试。' },
  MEMORY_RECALL_FAILED: { title: '记忆检索失败', action: '重试；若持续失败，检查嵌入模型与索引状态。' },
  invalid_json: { title: '请求内容不是合法 JSON', action: '重新提交；如果是桥推送，检查桥的事件格式。' },
  payload_too_large: { title: '请求内容过大', action: '缩小消息或附件后重试。' },
  text_required: { title: '内容不能为空', action: '输入一些文字后重试。' },
  file_too_large: { title: '文件超出大小限制', action: '压缩或拆分后重试。' },

  // ---- tools / agent runtime ----
  tool_timeout: { title: '工具执行超时', action: '缩小任务范围后重试；超时任务可能仍有副作用。' },
  tool_not_exposed: { title: '该工具当前未开放', action: '在治理面板启用对应插件或 MCP 服务后重试。' },
  tool_executor_not_available: { title: '工具执行器不可用', action: '重启后端后再试。' },
  tool_executor_returned_none: { title: '工具没有返回结果', action: '重试；若持续失败，检查该工具的实现日志。' },
  permission_denied: { title: '权限不足', action: '在权限提示中允许该工具，或调整插件开关。' },
  user_denied: { title: '你拒绝了该操作', action: '如需继续，请在权限提示中允许后重试。' },
  untrusted_mcp_followup_requires_confirmation: { title: '该跟进操作需要确认', action: '在权限提示中确认后重试。' },
  generation_manager_unavailable: { title: '生成会话未就绪', action: '稍等片刻再发送，或重启后端。' },
  llm_unavailable: { title: '模型服务不可用', action: '检查「设置 → 模型」与网络连接后重试。' },
  chat_completion_failed: { title: '对话生成失败', action: '重试；若持续失败，检查模型配置与余额。' },
  chat_error: { title: '对话处理出错', action: '重试；必要时查看后端日志。' },
  companion_not_found: { title: '找不到伴侣配置', action: '在设置里重新选择伴侣后重试。' },
  dsh_io_error: { title: 'DSH 读写管道异常', action: '重试；任务可能已部分执行，请先核实文件。' },
  translate_error: { title: '翻译失败', action: '检查模型服务后重试。' },

  // ---- storage / index ----
  database_error: { title: '数据库操作失败', action: '稍后重试；若持续失败，检查磁盘空间与数据文件权限。' },
  database_not_initialized: { title: '数据库尚未初始化', action: '等待启动完成，或重启后端。' },
  memory_search_scan_limit_reached: { title: '记忆检索到扫描上限', action: '缩小查询范围，或重建索引。' },
  memory_index_rebuild_cancelled: { title: '索引重建已取消', action: '需要时可以重新发起重建。' },

  // ---- scheduler / recovery ----
  scheduler_not_available: { title: '计划任务服务未就绪', action: '重启后端后再试。' },
  scheduled_task_exception: { title: '计划任务执行异常', action: '查看任务详情与日志，修正后重试。' },
  unsupported_schedule_mode: { title: '不支持的调度方式', action: '改用支持的模式（间隔、每日或自定义）。' },
  recovery_not_available: { title: '当前没有可恢复的会话', action: '刷新后重新发起请求。' },
  recovery_resume_failed: { title: '会话恢复失败', action: '重新发起该轮对话。' },
  recovery_resume_invalid: { title: '会话恢复数据无效', action: '放弃恢复并重新发起请求。' },

  // ---- voice / bridge transport ----
  svc_error: { title: '变声服务出错', action: '检查 SVC 服务是否运行后重试。' },
  svc_not_initialized: { title: '变声服务未就绪', action: '在设置中启用 SVC，或改用默认语音。' },
  relationship_history_unavailable: { title: '关系历史暂不可用', action: '稍后重试；不影响当前对话。' },
  connection_closed: { title: '连接已断开', action: '等待自动重连；若未恢复，请刷新界面。' },
  server_reconnect: { title: '服务正在重连', action: '稍候再操作。' },
  unauthorized: { title: '未通过鉴权', action: '刷新控制页，或从 Electron 应用入口重新打开。' },
  auth_failed: { title: '鉴权失败', action: '检查控制令牌或后端令牌配置。' },
}

const STATUS_FALLBACK: Record<number, Entry> = {
  400: { title: '请求内容不被接受', action: '检查输入后重试。' },
  401: { title: '未通过身份验证', action: '检查 API Key 或控制令牌。' },
  403: { title: '没有权限执行该操作', action: '确认当前工作区与权限范围。' },
  404: { title: '目标不存在', action: '刷新后重试；它可能已被删除。' },
  409: { title: '当前状态不允许该操作', action: '刷新后按提示重试。' },
  422: { title: '参数校验未通过', action: '按提示修正输入。' },
  429: { title: '请求过于频繁', action: '稍后重试。' },
  502: { title: '上游服务异常', action: '稍后重试；若是桥，检查桥进程是否在运行。' },
  503: { title: '服务暂时不可用', action: '稍后重试；若刚启动，等待初始化完成。' },
  504: { title: '上游响应超时', action: '稍后重试或缩小任务范围。' },
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
  if (error == null) return { title: '操作失败', action: '请重试。' }

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
  if (known) return { title: known.title, action: known.action, code, status, requestId }

  const byStatus = status ? STATUS_FALLBACK[status] : undefined
  if (byStatus) {
    const detail = rawMessage && !looksLikeCode(rawMessage) && rawMessage !== byStatus.title ? rawMessage : undefined
    return {
      title: byStatus.title,
      action: detail ? `${byStatus.action}（后端说明：${detail}）` : byStatus.action,
      code,
      status,
      requestId,
    }
  }

  // Nothing machine-readable: keep whatever sentence the backend sent, but strip
  // a bare HTTP wrapper so the toast never reads "http_400".
  const readable = rawMessage && !looksLikeCode(rawMessage) ? rawMessage : ''
  return {
    title: readable || '操作失败',
    action: readable ? undefined : '请重试；若持续失败，请查看日志。',
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
  const body = action ? `${title}：${action}` : title
  return code && !body.includes(code) ? `${body}（${code}）` : body
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
