# 安全与隐私边界 / Security and privacy boundary

## 中文说明

Yuizaki 是面向本机单用户的 AI 桌宠 Agent，不是经过加固的公共服务。默认服务只绑定回环地址；API 密钥放在 `python/.env` 或本地设置中，禁止提交或写入日志。视觉、剪贴板、桌面操作、外部 URL 和托管文件各有独立能力边界。

MCP、插件、Shell 工具、浏览器自动化和远程模型按配置读取或修改数据；请审查工具权限，并把提示、OCR、截图、网页和 MCP 结果视为不可信证据。聊天、记忆、设置和缓存默认保存在本地，服务运行时不要直接编辑 SQLite。

原生桌面动作默认关闭，仅限可见窗口发现、聚焦和优雅关闭，并使用独立 `YUIZAKI_HOST_DESKTOP_ACTION_TOKEN`、短期租约、撤销和紧急停止。Windows 与明确的 Linux X11 会话支持适配器；Wayland 原生动作和 macOS 动作未实现。

SQLite 是记忆权威数据源，Qdrant 只是可重建检索投影。召回前会应用工作区、会话和生命周期过滤；纠正保留历史，软遗忘、过期、被替代、被拒绝和永久删除的记录不得作为有效记忆返回。

Telegram、Discord、QQ/微信个人账号桥接器默认关闭。用户在治理面板启用即完成授权；凭据只保存为本地配置状态，不通过 API 返回。未经认证、来源策略、限流、密钥、沙箱、工具审批、租户隔离和审计日志审查，不得将后端或控制代理暴露到公网。

Yuizaki is a local, single-user AI desktop pet Agent, not a hardened public service. The default policy favors usable loopback integration over per-request authentication while keeping boundaries around desktop data, native actions, external URLs, and managed files.

## Defaults

- Backend and Electron control services bind to loopback by default.
- The Electron control service rejects remote, `file:`, and `null` browser origins. Health and approved pet-asset GET paths are public; other routed control requests require the control token in a Bearer authorization header or `x-yuizaki-backend-token`.
- The control-token query bootstrap is accepted only for a loopback GET without an `Origin` header. It is not accepted for cross-origin or mutating requests. Python loopback and Socket.IO traffic retain their local trust model; optional non-loopback clients require the backend token.
- Native desktop-action control routes are the exception: they require a separate Electron-issued host token even on loopback.
- API keys belong in `python/.env` or local settings and must never be committed or logged.
- Microphone capture requires explicit voice mode and desktop permission.
- Vision is disabled until enabled and requested by an Agent turn.
- MCP is opt-in: the launcher leaves it stopped unless started with `--with-mcp` or `YUIZAKI_WITH_MCP=1`. `--no-mcp` forces it off.
- Enabling an MCP server or Agent plugin authorizes its ordinary declared tools. High/critical-risk tools, explicitly confirmation-required tools, and forced confirmation still use the policy approval flow; remembered grants remain scoped. Disable the service or plugin to revoke that selection.
- Plugin shutdown closes execution admission before closing the listener. Admitted executions are cancelled and awaited through request parsing, broker calls, sandbox workers, and process-tree cleanup; Windows `taskkill` completion is awaited before shutdown returns.

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
Personal-account protocols can lead to an account ban; use a secondary account for QQ testing.
The optional managed bridge downloads a third-party personal-account client from its upstream release
only after an explicit risk acknowledgement, verifies the archive against a pinned SHA256, and unpacks
only the executable. The upstream repository ships no LICENSE file, so this component carries unresolved
licensing and is never redistributed with this project; it runs with its own console window and the
generated OneBot token, not with Yuizaki credentials.
A configured sign server is a third-party service that participates in the login handshake, so the
bridge will only sign in through an endpoint you set yourself; Yuizaki stores the URL in the bridge
config, never ships a default, and refuses to pretend a login succeeded when signing fails. Capturing
the login QR (`qrText`) keeps the credential visible only inside the loopback UI and does not persist it.
Inline capture uses the optional `pywinpty` package; when it is absent the QR stays in the bridge window.
QQ ignores self/non-message events, requires group mentions by default, supports sender/group
allowlists, and bounds per-session admission and active turns. Rejected events return a 2xx
acknowledgement without creating a delivery; this is not an authentication substitute.

### DSH delegation boundary

`ask_dsh` starts an external coding agent with real filesystem permissions, not a sandboxed
read-only helper. It is high-risk and may edit files after approval. Only explicitly requested
coding/file/repository tasks should be delegated. It uses argv without a shell, a single-process
concurrency limit, bounded output, and timeout/cancellation cleanup. The child receives only the
MCP stdio inherited-environment whitelist plus explicitly allowed DSH provider keys, and no `YUIZAKI_*` variables. DSH uses its own profile
credentials; keep Yuizaki provider credentials in `YUIZAKI_PROVIDER_CREDENTIALS_JSON`, not in task
text or committed settings. Timeout or failed execution does not roll back file changes and must
not cause an automatic retry. DSH session data persists under `~/.dsh/sessions`.

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

When the Electron host is running, MCP configuration is stored as an encrypted `safeStorage` document and `mcp_servers.json` contains only a namespace/reference pointer. Legacy plaintext stores migrate only after the vault write succeeds; vault outage, corruption, or invalid schema fails closed without overwriting the previous pointer. Standalone Python mode without the host vault still supports environment references such as `{env:TOKEN}` or `Bearer {env:TOKEN}`, while rejecting new literal secrets. Public endpoint projections remove URL userinfo and mask query values. Real Windows/Linux encryption-backend coverage and multi-process compare-and-swap semantics remain release evidence items.

The built-in node-mcp browser tools accept only HTTP(S) URLs without embedded credentials and reject private, loopback, link-local, and metadata destinations. Before a browser starts, the hostname is resolved and every resolved address is checked; each request made by the browser is re-checked and blocked when it targets a blocked range. Concurrency, request size, SSE clients, and operation time are bounded (`MCP_MAX_CONCURRENT_BROWSERS`, `MCP_BROWSER_TIMEOUT_MS`); tool errors are sanitized and request IDs are validated. This is a request-target filter, not a general network sandbox or a proxy for untrusted content: an allowed public site can still be malicious, and DNS rebinding between resolution and connection is not fully mitigated.

The Electron perception bridge masks active-application metadata for common password-manager, finance/payment, and medical applications before renderer projection. Deployments may add a main-process matcher for organization-specific sensitive windows. This is a privacy filter, not an authorization grant; request consent, scope, expiry, interruption, and emergency-stop checks remain mandatory.

### Local file tools / 本地文件工具

The built-in `write_file` tool refuses sensitive filenames and suffixes (`.env*`, credentials, keys, databases) and sensitive directories such as `.ssh`, `.aws`, and `userdata`; it requires the resolved parent to stay inside `YUIZAKI_LOCAL_TOOL_ROOTS` (default: the repository root) and writes through a unique temporary file plus `os.replace` so a failed write cannot truncate the original. `YUIZAKI_LOCAL_TOOL_ROOTS` replaces the default rather than extending it, so set every root the Agent may use. This reduces accidental corruption and path escape risk; it is not a filesystem sandbox, so keep sensitive directories outside local-tool scope.

### Bounded inbound data / 入站数据上限

Realtime payloads are bounded before decoding: audio chunks may not exceed 2 MiB of PCM (base64 length checked first), SVC audio may not exceed 6 MiB, and invalid or oversized chunks end that request with an explicit error instead of being buffered. The node-mcp HTTP endpoint accepts JSON bodies up to 64 KiB and caps concurrent browsers and SSE clients.

### SoulX SVC service / SoulX 变声服务

The optional SoulX service binds to `127.0.0.1` by default. `/convert` requires `SOULX_AUTH_TOKEN` as a Bearer credential whenever `SOULX_HOST` is not loopback, and the process refuses to start non-loopback without one. `/health` stays unauthenticated on every bind and exposes only device/FP16 flags, so it is not a capability endpoint. Uploads are size-bounded, the audio filename suffix is validated, generated audio is capped by `SOULX_MAX_OUTPUT_BYTES`, and internal errors are logged rather than returned to the caller. Run it as a separate process with its own filesystem and GPU limits.

The settings "test connection" probe for the SVC base URL accepts only public hostnames or `localhost` resolving to loopback; it rejects literal loopback and private addresses, and follows at most three redirects, each re-validated. A default `SVC_BASE_URL` of `http://127.0.0.1:7861` therefore cannot be probed through that button; use `http://localhost:7861` for local probing, or treat the probe as a remote-endpoint check.

## Native desktop actions

Native desktop actions are limited to visible top-level window discovery,
foreground focus, and graceful close requests. They do not launch a shell,
terminate a process, inject keyboard or pointer input, or expose native window
identifiers to the renderer or model.

The feature starts disabled and uses explicit application selection,
short-lived target leases, revocation, and an emergency stop. Every
`/api/desktop-actions/*` request also requires the independent
`YUIZAKI_HOST_DESKTOP_ACTION_TOKEN` as a strict Bearer credential. Missing,
invalid, unconfigured, or backend-token-reused credentials fail closed. The
ordinary loopback API keeps its existing local trust model. Externally managed
Python must receive the same explicitly configured host token or desktop
actions remain unavailable. Windows and explicit Linux X11 sessions have
adapters. Native Wayland and macOS actions are not implemented. A timeout after
a possible state change is reported as an unknown effect and is not
automatically retried as success.

## Data handling

Chat, memory, settings, and caches are local files. A cloud provider receives the text, audio, or image payload required by the selected feature. Vision frames are request-scoped and not persisted by default. Use the memory API or UI to correct or forget records; do not edit SQLite files while the service is running.

Session and message operations resolve the requesting or active workspace before touching SQLite. A session that belongs to another workspace is rejected with `403 workspace_mismatch`, and realtime transcript deduplication keys are scoped by workspace and turn rather than being global. Exports and statistics use the same scope.

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
