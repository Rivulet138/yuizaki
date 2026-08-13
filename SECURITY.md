# Local security boundary

Yuizaki is a local desktop application, not a hardened public service. The security model protects the local control plane and avoids accidental data disclosure without adding a production-style approval ceremony to ordinary companion interaction.

## Defaults

- Backend and Electron control services bind to loopback by default.
- The launcher creates one session control token and aligns it between renderer, Electron, and backend.
- API keys belong in `python/.env` or local settings and must never be committed or written to logs.
- Microphone capture requires an explicit voice mode and browser/Electron permission.
- Vision is off until enabled and requested by an Agent turn; frames are request-scoped.
- MCP is enabled by the normal launcher because this project targets a full local Agent startup. Use `--no-mcp` for a reduced or diagnostic run.

## Tool and provider risks

MCP servers, plugins, shell tools, and remote model providers can read or change data according to their configured capabilities. Review a server before enabling it, keep sensitive directories outside tool scope when practical, and do not send secrets in prompts. The local Agent may intentionally execute tools; this is a product capability, not a guarantee that every tool is harmless.

## Data handling

Chat, memory, settings, and caches are local files. Cloud providers receive the text, audio, or image payloads needed for the selected request. Vision frames are not persisted by default. Delete memory through the memory API or UI rather than manually editing database files while the service is running.

## Reporting

For a reproducible issue, include the commit, OS, runtime versions, launcher flags, and a redacted log. Never include API keys, control tokens, personal chat history, or captured screens. Report security-sensitive issues privately to the repository maintainers.
