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
