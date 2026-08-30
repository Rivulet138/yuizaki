# Security and privacy boundary

Yuizaki is a local, single-user AI desktop pet Agent, not a hardened public service. The default policy favors usable loopback integration over per-request authentication while keeping boundaries around desktop data, native actions, external URLs, and managed files.

## Defaults

- Backend and Electron control services bind to loopback by default.
- The Electron control service accepts loopback API requests and rejects remote, `file:`, and `null` browser origins.
- Loopback Python, Socket.IO, and Electron control requests do not require per-request tokens. The launcher still creates one backend token for optional non-loopback Python and Socket.IO access.
- API keys belong in `python/.env` or local settings and must never be committed or logged.
- Microphone capture requires explicit voice mode and desktop permission.
- Vision is disabled until enabled and requested by an Agent turn.
- MCP starts by default for a full local Agent run; use `--no-mcp` for a reduced run.
- Enabling an MCP server or Agent plugin is the user authorization decision for its declared tools; enabled MCP/plugin tools do not prompt on every call. Disable the service or plugin to revoke that selection.

## Connector boundary

Telegram, Discord, and QQ/WeChat personal-account bridge adapters are experimental, local-first integrations. The governance panel is the user consent
point: enabling a connector authorizes its declared inbound message and outbound reply flow without a per-message
confirmation dialog. Credentials are stored in the local runtime data file and exposed only as configured/not configured
flags; connector API and renderer snapshots never return secret values.

Only these exact connector callback paths bypass the optional Yuizaki Backend API Token because an external bridge may not attach
that token:

- `/api/system/connectors/telegram/webhook`
- `/api/system/connectors/discord/webhook`
- `/api/system/connectors/qq/webhook`
- `/api/system/connectors/wechat/webhook` (`POST` callback from the selected local bridge)

All sibling connector routes (`GET`/`PUT .../config`, `POST .../disable`, `POST .../events/.../cancel`, webhook `GET`,
and additional path variants) remain inside the normal backend boundary. Telegram requires a Webhook Secret before enablement
and validates it on every inbound request. Discord requires a Public Key and verifies the raw body with Ed25519 headers,
including endpoint `PING`. QQ and WeChat require a Bridge Token before enablement and validate it on every bridge callback.
QQ and WeChat use a user-selected local personal-account bridge. This is not an official platform API; lockout,
 privacy, disconnect, and protocol-change risks are explicitly accepted by the local user.

Discord interactions are durably recorded before the deferred acknowledgement, then Agent work runs in the background; terminal delivery
edits the original response, uses the interaction token only within its local 15-minute deadline, and disables mention parsing.
An optional Bot Token may send one channel fallback for an expired persisted retry; there is no Discord Gateway ingress.
Connector turns use stable IDs with the local SQLite
TurnCommitStore claim/commit/replay layer. Agent commit state and external provider delivery state are separate: a failed
provider delivery can be retried from the persisted Agent result, while a confirmed delivery does not send a second
provider reply. Real public HTTPS delivery has not been completed in this repository. The production app fast-acknowledges
Telegram and personal bridge callbacks only after the inbound message is persisted in `connector_deliveries`; failed worker
states remain manually retryable. A process-local in-memory queue is never treated as durable.

## Capability risks

MCP servers, plugins, shell tools, browser automation, and remote model providers may read or change data according to their configuration. Treat every server as code with the permissions of its process. Review tool manifests, keep sensitive directories outside tool scope, and do not send secrets in prompts.

Prompt content, OCR output, screenshots, web pages, and MCP results are untrusted evidence. They must not be treated as authorization to bypass policy or reveal secrets.

The Electron perception bridge masks active-application metadata for common password-manager, finance/payment, and medical applications before renderer projection. Deployments may add a main-process matcher for organization-specific sensitive windows. This is a privacy filter, not an authorization grant; request consent, scope, expiry, interruption, and emergency-stop checks remain mandatory.

## Native desktop actions

Native desktop actions are limited to visible top-level window discovery,
foreground focus, and graceful close requests. They do not launch a shell,
terminate a process, inject keyboard or pointer input, or expose native window
identifiers to the renderer or model.

The feature starts disabled and uses a separate host-only token, explicit
application selection, short-lived target leases, revocation, and an emergency
stop. Windows and explicit Linux X11 sessions have adapters. Native Wayland and
macOS actions are not implemented. A timeout after a possible state change is
reported as an unknown effect and is not automatically retried as success.

## Data handling

Chat, memory, settings, and caches are local files. A cloud provider receives the text, audio, or image payload required by the selected feature. Vision frames are request-scoped and not persisted by default. Use the memory API or UI to correct or forget records; do not edit SQLite files while the service is running.

SQLite is the authority for memory. Qdrant, when configured, is a rebuildable
search projection. Workspace and session scope plus lifecycle filters are
applied before recall. Correction preserves history; soft-forgotten, expired,
superseded, rejected, and permanently deleted records must not be returned as
active memory. Use deletion previews before permanent removal so the UI can
show effects on chat references and the derived index.

## Public-release boundary

Do not expose the backend or Electron control proxy to the public internet without a separate deployment review covering authentication, origin policy, rate limiting, secrets, sandboxing, tool approval, tenant isolation, and audit logging.

## Issue reporting

Include the commit, OS, runtime versions, launcher flags, and a redacted log. Never include API keys, backend tokens, personal chat history, or captured screens. Report security-sensitive issues privately to the maintainers.

## 中文说明

Yuizaki 是面向本机单用户的 AI 桌宠 Agent，不是经过加固的公共服务。Electron 控制服务只绑定回环地址，接受本机浏览器来源并拒绝远程、`file:` 和 `null` 来源。本机回环的 Python、Socket.IO 和 Electron 控制请求均不要求逐请求令牌；启动器生成的 Backend API Token 仅作为可选非回环访问边界。API 密钥只能放在 `python/.env` 或本地设置中，禁止提交或写入日志。视觉、剪贴板、桌面操作、外部 URL 和托管文件仍保留各自的能力边界。

MCP、插件、Shell 工具、浏览器自动化和远程模型可能按配置读取或修改数据。请审查工具权限，将敏感目录置于工具作用域之外，并把提示、OCR、截图、网页和 MCP 结果视为不可信证据。聊天、记忆、设置和缓存默认保存在本地；服务运行时不要直接编辑 SQLite。

原生桌面动作仅限可见顶层窗口发现、聚焦和优雅关闭，默认关闭，并使用独立宿主令牌、短期租约、撤销和紧急停止边界。Windows 与明确的 Linux X11 会话具有适配器；Wayland 原生动作和 macOS 动作未实现。超时后可能已经产生现实影响的操作不会被自动重试为成功。

SQLite 是记忆权威数据源，Qdrant 仅是可重建的检索投影。召回前会应用工作区、会话和生命周期过滤；纠正保留历史，软遗忘、过期、被替代、被拒绝和永久删除的记录不得作为有效记忆返回。

 Telegram、Discord、QQ/微信个人账号兼容桥连接器默认关闭。用户在治理面板选择启用即完成授权，不会逐条确认。个人桥风险由用户自行承担。只有精确的 provider webhook 路径不要求 Yuizaki Backend API Token；配置、停用、取消和其他路径仍受原有后端边界保护。连接器 turn 使用本地 SQLite TurnCommitStore 的持久化 claim/commit/replay，Agent 结果和外部平台投递分开记录，投递失败可重试，已确认投递不会重复发送。

未经认证、来源策略、限流、密钥、沙箱、工具审批、租户隔离和审计日志审查，不得将后端或控制代理暴露到公网。报告安全问题时请提供 commit、系统、运行时版本、启动参数和脱敏日志，绝不要附带密钥、令牌、私人聊天记录或截图。
