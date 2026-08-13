# Security and privacy boundary

Yuizaki is a local desktop application, not a hardened public service. The default security model protects a loopback control plane and makes data boundaries visible; it does not provide multi-tenant isolation or a production approval workflow for every local action.

## Defaults

- Backend and Electron control services bind to loopback by default.
- The launcher creates and aligns a per-run control token.
- Protected API and Socket.IO routes require the configured token; `/api/ping` is a liveness probe.
- API keys belong in `python/.env` or local settings and must never be committed or logged.
- Microphone capture requires explicit voice mode and desktop permission.
- Vision is disabled until enabled and requested by an Agent turn.
- MCP starts by default for a full local Agent run; use `--no-mcp` for a reduced run.

## Capability risks

MCP servers, plugins, shell tools, browser automation, and remote model providers may read or change data according to their configuration. Treat every server as code with the permissions of its process. Review tool manifests, keep sensitive directories outside tool scope, and do not send secrets in prompts.

Prompt content, OCR output, screenshots, web pages, and MCP results are untrusted evidence. They must not be treated as authorization to bypass policy or reveal secrets.

## Data handling

Chat, memory, settings, and caches are local files. A cloud provider receives the text, audio, or image payload required by the selected feature. Vision frames are request-scoped and not persisted by default. Use the memory API or UI to correct or forget records; do not edit SQLite files while the service is running.

## Public-release boundary

Do not expose the backend or Electron control proxy to the public internet without a separate deployment review covering authentication, origin policy, rate limiting, secrets, sandboxing, tool approval, tenant isolation, and audit logging.

## Issue reporting

Include the commit, OS, runtime versions, launcher flags, and a redacted log. Never include API keys, control tokens, personal chat history, or captured screens. Report security-sensitive issues privately to the maintainers.

## 中文说明

Yuizaki 是本地桌面应用，不是经过加固的公共服务。默认服务绑定回环地址，启动器为每次运行创建控制令牌；API 密钥只能放在 `python/.env` 或本地设置中，禁止提交或写入日志。视觉按请求启用，麦克风需要显式语音模式和桌面权限。

MCP、插件、Shell 工具、浏览器自动化和远程模型可能按配置读取或修改数据。请审查工具权限，将敏感目录置于工具作用域之外，并把提示、OCR、截图、网页和 MCP 结果视为不可信证据。聊天、记忆、设置和缓存默认保存在本地；服务运行时不要直接编辑 SQLite。

未经认证、来源策略、限流、密钥、沙箱、工具审批、租户隔离和审计日志审查，不得将后端或控制代理暴露到公网。报告安全问题时请提供 commit、系统、运行时版本、启动参数和脱敏日志，绝不要附带密钥、令牌、私人聊天记录或截图。
