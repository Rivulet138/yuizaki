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

## Capability risks

MCP servers, plugins, shell tools, browser automation, and remote model providers may read or change data according to their configuration. Treat every server as code with the permissions of its process. Review tool manifests, keep sensitive directories outside tool scope, and do not send secrets in prompts.

Prompt content, OCR output, screenshots, web pages, and MCP results are untrusted evidence. They must not be treated as authorization to bypass policy or reveal secrets.

## Data handling

Chat, memory, settings, and caches are local files. A cloud provider receives the text, audio, or image payload required by the selected feature. Vision frames are request-scoped and not persisted by default. Use the memory API or UI to correct or forget records; do not edit SQLite files while the service is running.

## Public-release boundary

Do not expose the backend or Electron control proxy to the public internet without a separate deployment review covering authentication, origin policy, rate limiting, secrets, sandboxing, tool approval, tenant isolation, and audit logging.

## Issue reporting

Include the commit, OS, runtime versions, launcher flags, and a redacted log. Never include API keys, backend tokens, personal chat history, or captured screens. Report security-sensitive issues privately to the maintainers.

## 中文说明

Yuizaki 是面向本机单用户的 AI 桌宠 Agent，不是经过加固的公共服务。Electron 控制服务只绑定回环地址，接受本机浏览器来源并拒绝远程、`file:` 和 `null` 来源。本机回环的 Python、Socket.IO 和 Electron 控制请求均不要求逐请求令牌；启动器生成的 Backend API Token 仅作为可选非回环访问边界。API 密钥只能放在 `python/.env` 或本地设置中，禁止提交或写入日志。视觉、剪贴板、桌面操作、外部 URL 和托管文件仍保留各自的能力边界。

MCP、插件、Shell 工具、浏览器自动化和远程模型可能按配置读取或修改数据。请审查工具权限，将敏感目录置于工具作用域之外，并把提示、OCR、截图、网页和 MCP 结果视为不可信证据。聊天、记忆、设置和缓存默认保存在本地；服务运行时不要直接编辑 SQLite。

未经认证、来源策略、限流、密钥、沙箱、工具审批、租户隔离和审计日志审查，不得将后端或控制代理暴露到公网。报告安全问题时请提供 commit、系统、运行时版本、启动参数和脱敏日志，绝不要附带密钥、令牌、私人聊天记录或截图。
